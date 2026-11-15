#!/usr/bin/env python3
"""SCI-01: Landsat 8 radiance-level thermal inputs where C2 L2 has no surface temperature (ASTER GED gap,
~11 300 km2, mostly east incl. Mariupol), so the science code can compute LST itself (METHOD.md §5,
NDVI-based emissivity).

Scenes: every summer (Jun-Aug) Landsat 8 scene 2013-2025 from the original ingest lists (src_items/ukraine/<y>.json,
cloud < 70 %) whose footprint touches the SCI-01 mask (ROOT/aoi/sci01_mask.tif from sci01_mask.py).
Patch clusters (sci01_clusters.json) >= 10 km2 (98 % of the area). Per scene and cluster the window = cluster window
(+2 km) ∩ scene footprint, on the Ukraine EPSG:3035 60 m grid (offsets in the meta JSON, like ingest.py).
Reads the 60 m overview (as ingest.py).

Output ROOT/sci01/scenes/<year>/:
  <scene>.json      {id, date, windows: [{cluster, platform, cloud, path, row, row_off, col_off, h, w (Ukraine grid),
                    n_clear, n_mask, scale}]};  files per window are <scene>.<cluster>.*.tif
  <scene>.<c>.rad.tif   int16, 4 bands RAW C2 L2 DN: trad, urad, drad, atran (nodata -9999; non-clear pixels = nodata)
                    scale: trad/urad/drad x0.001 W/(m2 sr um), atran x0.0001 (tags + band descriptions)
  <scene>.ndvi.tif  int8 NDVI x100 (clear pixels; nodata -128)
  <scene>.qa.tif    uint16 qa_pixel (unmasked, for alternative cloud masks)
usage: sci01_radiance.py --years 2013-2025 [--workers 4]
"""
import os, sys, json, math, time, argparse, traceback
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import landsat_scenes as L  # noqa: E402

import numpy as np

BANDS = ["trad", "urad", "drad", "atran"]
SCALE = {"trad": 0.001, "urad": 0.001, "drad": 0.001, "atran": 0.0001}
log = None


def scene_windows(d, mask, clusters):
    """Per cluster (>= MIN_KM2) touching the scene footprint: window = cluster window ∩ scene bbox (Ukraine grid)."""
    from rasterio.warp import transform_bounds
    G = C.UKRAINE_GRID
    bx = transform_bounds("EPSG:4326", C.DST_CRS, *d["bbox"], densify_pts=21)
    s0 = max(0, math.floor((bx[0] - G["x0"]) / C.RES)); s1 = min(G["W"], math.ceil((bx[2] - G["x0"]) / C.RES))
    t0 = max(0, math.floor((G["y1"] - bx[3]) / C.RES)); t1 = min(G["H"], math.ceil((G["y1"] - bx[1]) / C.RES))
    import pyproj
    import shapely.geometry as sg
    from shapely.ops import transform as stransform
    foot = stransform(pyproj.Transformer.from_crs(4326, 3035, always_xy=True).transform, sg.shape(d["geometry"]))
    out = []
    for c in clusters:
        g = c["grid"]
        r0, r1 = max(t0, g["parent_row_off"]), min(t1, g["parent_row_off"] + g["H"])
        c0, c1 = max(s0, g["parent_col_off"]), min(s1, g["parent_col_off"] + g["W"])
        if r1 <= r0 or c1 <= c0:
            continue
        sub = mask[r0:r1, c0:c1]
        if not sub.any():
            continue
        # count only mask pixels inside the real (tilted) scene footprint, not its bbox
        from rasterio.features import geometry_mask
        from rasterio.windows import Window, transform as win_transform
        inside = ~geometry_mask([foot], out_shape=sub.shape, transform=win_transform(Window(c0, r0, c1 - c0, r1 - r0),
                                C.grid_transform(G)))
        n = int((sub & inside).sum())
        if n >= 100:
            out.append((c["id"], int(r0), int(c0), int(r1 - r0), int(c1 - c0), n))
    return out


def process_win(d, sdir, win, token):
    import rasterio
    from rasterio.warp import reproject, Resampling
    from rasterio.windows import Window, transform as win_transform
    cid, r0, c0, h, w, n_mask = win
    sid = f'{d["id"]}.{cid}' 
    dwin = Window(c0, r0, w, h)
    gT = C.grid_transform(C.UKRAINE_GRID)
    dT = win_transform(dwin, gT)
    meta = dict(id=d["id"], cluster=cid, date=d["properties"]["datetime"][:10], platform="landsat-8",
                cloud=d["properties"].get("eo:cloud_cover"), path=d["properties"].get("landsat:wrs_path"),
                row=d["properties"].get("landsat:wrs_row"), row_off=r0, col_off=c0, h=h, w=w, n_mask=n_mask, n_clear=0,
                scale=SCALE, note="raw C2 L2 DN; LST to be derived by science (METHOD.md §5)")
    bands = ["qa_pixel", "red", "nir08"] + BANDS
    err = None
    for attempt in range(5):
        try:
            arrs, scrs, sT = L._read_bands(d, bands, rasterio.windows.bounds(dwin, gT), 0, token if attempt < 3 else None)
            break
        except Exception as e:  # noqa
            err = e; time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError(f"{sid}: read failed {err!r}")
    if arrs is None:
        return meta

    def warp(a, nodata, dtype):
        out = np.full((h, w), nodata, dtype)
        reproject(a.astype(dtype), out, src_transform=sT, src_crs=scrs, src_nodata=nodata, dst_transform=dT,
                  dst_crs=C.DST_CRS, dst_nodata=nodata, resampling=Resampling.nearest, num_threads=1)
        return out

    qa = arrs["qa_pixel"]
    clear = ((qa & (1 << 6)) > 0) & ((qa & 0b111111) == 0)
    rad = []
    for b in BANDS:
        a = arrs[b].astype(np.int16)
        a[~clear | (a == -9999)] = -9999
        rad.append(warp(a, -9999, np.int16))
    red = arrs["red"].astype(np.float32) * 2.75e-5 - 0.2
    nir = arrs["nir08"].astype(np.float32) * 2.75e-5 - 0.2
    with np.errstate(divide="ignore", invalid="ignore"):
        v = (nir - red) / (nir + red)
    ok = clear & np.isfinite(v) & (arrs["red"] > 0)
    ndvi = np.full(v.shape, -128, np.int8)
    ndvi[ok] = np.clip(np.round(v[ok] * 100), -100, 100).astype(np.int8)
    wndvi = warp(ndvi, -128, np.int8)
    wqa = np.zeros((h, w), np.uint16)
    reproject(qa, wqa, src_transform=sT, src_crs=scrs, src_nodata=1, dst_transform=dT, dst_crs=C.DST_CRS,
              dst_nodata=1, resampling=Resampling.nearest, num_threads=1)
    meta["n_clear"] = int((rad[0] != -9999).sum())
    if meta["n_clear"]:
        prof = dict(C.GT_OPTS, zstd_level=1, height=h, width=w, crs=C.DST_CRS, transform=dT)
        for name, arrs_, dt, nd, desc in [("rad", rad, "int16", -9999, BANDS), ("ndvi", [wndvi], "int8", -128, ["ndvi_x100"]),
                                          ("qa", [wqa], "uint16", 1, ["qa_pixel"])]:
            tmp = f"{sdir}/{sid}.{name}.tif.tmp"
            with rasterio.open(tmp, "w", count=len(arrs_), dtype=dt, nodata=nd, **prof) as o:
                for i, a in enumerate(arrs_, 1):
                    o.write(a, i)
                o.descriptions = tuple(desc)
                if name == "rad":
                    o.update_tags(**{f"scale_{b}": str(SCALE[b]) for b in BANDS})
            os.replace(tmp, f"{sdir}/{sid}.{name}.tif")
    return meta


def process(d, sdir, wins, token):
    mp_ = f"{sdir}/{d['id']}.json"
    if os.path.exists(mp_):
        return "skip"
    metas = [process_win(d, sdir, w, token) for w in wins]
    C.atomic_json(dict(id=d["id"], date=d["properties"]["datetime"][:10], windows=metas), mp_)
    return "ok"


def main():
    global log
    import rasterio
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2013-2025")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--min-km2", type=float, default=10, help="skip patch clusters smaller than this (98 %% of area kept)")
    a = ap.parse_args()
    log = C.setup_log("sci01_radiance")
    with rasterio.open(f"{C.ROOT}/aoi/sci01_mask.tif") as s:
        mask = s.read(1).astype(bool)
    clusters = [c for c in json.load(open(f"{C.ROOT}/aoi/sci01_clusters.json"))["clusters"] if c["patch_km2"] >= a.min_km2]
    log.info("%d clusters >= %s km2", len(clusters), a.min_km2)
    ctx = mp.get_context("spawn")
    try:
        for y in L.parse_years(a.years):
            sdir = f"{C.ROOT}/sci01/scenes/{y}"
            if os.path.exists(f"{sdir}/DONE"):
                continue
            C.check_disk()
            os.makedirs(sdir, exist_ok=True)
            items = [d for d in json.load(open(f"{C.ROOT}/src_items/ukraine/{y}.json"))
                     if int(d["properties"]["datetime"][5:7]) in (6, 7, 8) and d["properties"].get("platform") == "landsat-8"]
            jobs = [(d, w) for d in items for w in [scene_windows(d, mask, clusters)] if w]
            todo = [(d, w) for d, w in jobs if not os.path.exists(f"{sdir}/{d['id']}.json")]
            log.info("[sci01 %d] %d summer scenes, %d touch the mask, %d to fetch", y, len(items), len(jobs), len(todo))
            t0, fails, failed_ids = time.time(), 0, []
            B = a.workers * 6
            for b0 in range(0, len(todo), B):
                C.check_disk()
                try:
                    token = L._sas_token(todo[b0][0]["assets"]["qa_pixel"]["href"])
                except Exception:  # noqa
                    token = None
                with ProcessPoolExecutor(a.workers, mp_context=ctx) as ex:
                    futs = {ex.submit(process, d, sdir, w, token): d for d, w in todo[b0:b0 + B]}
                    for f in as_completed(futs):
                        try:
                            f.result()
                        except Exception as e:  # noqa
                            fails += 1
                            failed_ids.append([futs[f]["id"], str(e)[:300]])
                            log.warning("%s failed: %s", futs[f]["id"], str(e)[:200])
                log.info("[sci01 %d] %d/%d failed=%d %.1fs/scene", y, min(b0 + B, len(todo)), len(todo), fails,
                         (time.time() - t0) / max(1, min(b0 + B, len(todo))))
            if failed_ids:   # e.g. truncated source blobs on Planetary Computer (nir08 / trad of a few 2022 scenes)
                C.atomic_json(failed_ids, f"{sdir}/FAILED.json", indent=1)
            open(f"{sdir}/DONE", "w").write(time.strftime("%F %T"))
            C.manifest_update("sci01/radiance", **{f"y{y}": dict(scenes=len(jobs), failed=fails)},
                              path=f"{C.ROOT}/sci01", crs=C.DST_CRS, res_m=C.RES)
        log.info("SCI01 DONE")
    except C.DiskFull as e:
        log.warning("stopping: %s", e); sys.exit(75)
    except Exception:  # noqa
        log.error(traceback.format_exc()); sys.exit(1)


if __name__ == "__main__":
    main()
