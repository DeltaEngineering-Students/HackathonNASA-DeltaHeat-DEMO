#!/usr/bin/env python3
"""Per-scene Landsat indices (same format as pipeline/ingest.py) for whole Ukraine or for city windows.

Fills the per-scene hole (QUESTIONS #6): ingest kept per-scene files for Ukraine only for 2013-2017.
Output (same as ingest.py, so the science code can read it unchanged):
  ROOT/<aoi>/scenes/<year>/<scene>.json          meta: id,date,summer,n_clear,row_off,col_off,h,w (+platform)
  ROOT/<aoi>/scenes/<year>/<scene>.idx.tif       int8 x100: NDVI[,NDBI,MNDWI] on the aoi grid window
  ROOT/<aoi>/scenes/<year>/<scene>.lst.tif       int16 degC x100 (summer scenes only)
  ROOT/<aoi>/items/<year>.json                   STAC items used
  ROOT/<aoi>/grid.json                           grid (x0,y1,W,H [+ parent offsets in the Ukraine grid])
row_off/col_off are relative to the aoi grid; aoi "ukraine" == the existing /root/landsat/ukraine grid.

Usage:
  landsat_scenes.py --aoi ukraine --platform landsat-8 --years 2018-2025 --summer-only [--items-dir DIR]
  landsat_scenes.py --aoi ukraine_l9 --platform landsat-9 --years 2021-2025 --summer-only
  landsat_scenes.py --cities dnipro,odesa --platform landsat-5 --years 1999-2011 --summer-only
Resumable (a scene with a .json is done). Stops cleanly (exit 75) when disk is low or ROOT/STOP exists.
"""
import os, sys, json, math, time, argparse, traceback
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402  (sets GDAL env first)

import numpy as np

LST_ND, IDX_ND = -32768, -128
SUMMER = (6, 7, 8)
CLOUD_MAX = 70
# Collection 2 L2 asset names on Planetary Computer; L5/L7 thermal band is "lwir", L8/L9 "lwir11"
THERMAL = {"landsat-8": "lwir11", "landsat-9": "lwir11", "landsat-5": "lwir", "landsat-7": "lwir"}

log = None


def _sas_token(href):
    """One SAS token per batch in the parent; workers append it (PC rate-limits the token API per IP)."""
    import planetary_computer as pc
    from urllib.parse import urlparse
    u = urlparse(href)
    return pc.sas.get_token(u.netloc.split(".")[0], u.path.split("/")[1]).token


def _read_bands(d, bands, dst_bounds, ovr, token=None):
    import pystac, rasterio
    import planetary_computer as pc
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, transform as win_transform
    item = pystac.Item.from_dict(d)
    if token:
        for a in bands:
            item.assets[a].href = item.assets[a].href.split("?")[0] + "?" + token
    else:
        pc.sign_inplace(item)
    kw = {"overview_level": ovr} if ovr is not None else {}
    with rasterio.open(item.assets["qa_pixel"].href, **kw) as s:
        crs, T, W, H = s.crs, s.transform, s.width, s.height
    sb = transform_bounds(C.DST_CRS, crs, *dst_bounds, densify_pts=21)
    pad = 2 * abs(T.a)
    c0 = max(0, math.floor((sb[0] - pad - T.c) / T.a)); c1 = min(W, math.ceil((sb[2] + pad - T.c) / T.a))
    r0 = max(0, math.floor((T.f - (sb[3] + pad)) / -T.e)); r1 = min(H, math.ceil((T.f - (sb[1] - pad)) / -T.e))
    if c1 <= c0 or r1 <= r0:
        return None, None, None
    win = Window(c0, r0, c1 - c0, r1 - r0)

    def rd(b):
        with rasterio.open(item.assets[b].href, **kw) as s:
            assert (s.width, s.height) == (W, H), f"{b} grid mismatch"
            return b, s.read(1, window=win)

    with ThreadPoolExecutor(len(bands)) as ex:
        arrs = dict(ex.map(rd, bands))
    return arrs, crs, win_transform(win, T)


def process_scene(d, sdir, grid, platform, ovr, token=None):
    """Same maths as pipeline/ingest.py process_scene (QA clear mask, x100 indices, LST degC x100)."""
    import rasterio
    from rasterio.warp import reproject, transform_bounds, Resampling
    from rasterio.windows import Window, transform as win_transform
    sid = d["id"]
    meta_path = f"{sdir}/{sid}.json"
    if os.path.exists(meta_path):
        return json.load(open(meta_path))
    date = d["properties"]["datetime"][:10]
    summer = int(date[5:7]) in SUMMER
    meta = dict(id=sid, date=date, summer=summer, n_clear=0, platform=platform,
                cloud=d["properties"].get("eo:cloud_cover"),
                path=d["properties"].get("landsat:wrs_path"), row=d["properties"].get("landsat:wrs_row"))
    gT = C.grid_transform(grid)
    bx = transform_bounds("EPSG:4326", C.DST_CRS, *d["bbox"], densify_pts=21)
    c0 = max(0, math.floor((bx[0] - grid["x0"]) / C.RES)); c1 = min(grid["W"], math.ceil((bx[2] - grid["x0"]) / C.RES))
    r0 = max(0, math.floor((grid["y1"] - bx[3]) / C.RES)); r1 = min(grid["H"], math.ceil((grid["y1"] - bx[1]) / C.RES))
    if c1 <= c0 or r1 <= r0:
        C.atomic_json(meta, meta_path); return meta
    dwin = Window(c0, r0, c1 - c0, r1 - r0)
    dT = win_transform(dwin, gT)
    dst_bounds = rasterio.windows.bounds(dwin, gT)
    th = THERMAL[platform]
    bands = ["qa_pixel", "red", "nir08"] + ([th, "swir16", "green"] if summer else [])
    err = None
    for attempt in range(5):
        try:
            arrs, scrs, sT = _read_bands(d, bands, dst_bounds, ovr, token if attempt < 3 else None)
            break
        except Exception as e:  # noqa
            err = e
            time.sleep(5 * (attempt + 1))
    else:
        # some source files are broken on Planetary Computer (e.g. 2022 SR_B3 blobs of 14 KB): retry without the
        # optional green band (MNDWI then = nodata, recorded in meta.missing_bands)
        if not summer or "green" not in bands:
            raise RuntimeError(f"{sid}: read failed: {err!r}")
        try:
            arrs, scrs, sT = _read_bands(d, [b for b in bands if b != "green"], dst_bounds, ovr, None)
            meta["missing_bands"] = ["green"]
        except Exception as e2:  # noqa
            raise RuntimeError(f"{sid}: read failed: {err!r} / without green: {e2!r}")
    if arrs is None:
        C.atomic_json(meta, meta_path); return meta
    qa = arrs["qa_pixel"]
    # bit0 fill, bit1 dilated cloud, bit2 cirrus (L8/9), bit3 cloud, bit4 shadow, bit5 snow, bit6 clear
    clear = ((qa & (1 << 6)) > 0) & ((qa & 0b111111) == 0)

    def refl(a):
        r = a.astype(np.float32) * 2.75e-5 - 0.2
        r[a == 0] = np.nan
        return r

    def nd(a, b):
        with np.errstate(divide="ignore", invalid="ignore"):
            v = (a - b) / (a + b)
        ok = clear & np.isfinite(v)
        out = np.full(v.shape, IDX_ND, np.int8)
        out[ok] = np.clip(np.round(v[ok] * 100), -100, 100).astype(np.int8)
        return out

    red, nir = refl(arrs["red"]), refl(arrs["nir08"])
    idx = [nd(nir, red)]
    lst = None
    if summer:
        sw = refl(arrs["swir16"])
        idx += [nd(sw, nir)]
        if "green" in arrs:
            idx += [nd(refl(arrs["green"]), sw)]
        else:
            idx += [np.full(sw.shape, IDX_ND, np.int8)]
        t = arrs[th]
        ok = clear & (t > 0)
        lst = np.full(t.shape, LST_ND, np.int16)
        lst[ok] = np.round((t[ok].astype(np.float32) * 0.00341802 + 149.0 - 273.15) * 100).astype(np.int16)

    def warp(a, nodata):
        out = np.full((dwin.height, dwin.width), nodata, a.dtype)
        reproject(a, out, src_transform=sT, src_crs=scrs, src_nodata=nodata, dst_transform=dT,
                  dst_crs=C.DST_CRS, dst_nodata=nodata, resampling=Resampling.nearest, num_threads=1)
        return out

    widx = [warp(a, IDX_ND) for a in idx]
    n_clear = int((widx[0] != IDX_ND).sum())
    meta.update(row_off=r0, col_off=c0, h=dwin.height, w=dwin.width, n_clear=n_clear)
    if n_clear:
        prof = dict(C.GT_OPTS, zstd_level=1, height=dwin.height, width=dwin.width, crs=C.DST_CRS, transform=dT)
        tmp = f"{sdir}/{sid}.idx.tif.tmp"
        with rasterio.open(tmp, "w", count=len(widx), dtype="int8", nodata=IDX_ND, **prof) as o:
            for i, a in enumerate(widx, 1):
                o.write(a, i)
        os.replace(tmp, f"{sdir}/{sid}.idx.tif")
        if summer:
            tmp = f"{sdir}/{sid}.lst.tif.tmp"
            with rasterio.open(tmp, "w", count=1, dtype="int16", nodata=LST_ND, **prof) as o:
                o.write(warp(lst, LST_ND), 1)
            os.replace(tmp, f"{sdir}/{sid}.lst.tif")
    C.atomic_json(meta, meta_path)
    return meta


def search_geom(grid):
    """Ukraine boundary + 20 km (as ingest.make_grid) when the aoi is the whole Ukraine grid, else the grid box."""
    import pyproj
    import shapely.geometry as sg
    from shapely.ops import transform as stransform
    gj = f"{C.ROOT}/aoi/Ukraine.geojson"
    if grid.get("W") == C.UKRAINE_GRID["W"] and os.path.exists(gj):
        to_m = pyproj.Transformer.from_crs(4326, 3035, always_xy=True).transform
        to_ll = pyproj.Transformer.from_crs(3035, 4326, always_xy=True).transform
        g = stransform(to_m, sg.shape(json.load(open(gj))["features"][0]["geometry"])).buffer(20_000).simplify(2000)
        return sg.mapping(stransform(to_ll, g).simplify(0.01))
    return sg.mapping(sg.box(*C.grid_bounds_ll(grid)))


def search_items(aoi_dir, year, grid, platform, summer_only, items_dir):
    path = f"{aoi_dir}/items/{year}.json"
    if os.path.exists(path):
        return json.load(open(path))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    src = f"{items_dir}/{year}.json" if items_dir else None
    if src and os.path.exists(src):          # reuse the exact scene list of the original ingest
        ds = [d for d in json.load(open(src)) if d["properties"].get("platform") == platform]
    else:
        months = ("06-01", "08-31") if summer_only else ("04-01", "10-31")
        ds = C.stac_search("landsat-c2-l2", intersects=search_geom(grid),
                           datetime=f"{year}-{months[0]}/{year}-{months[1]}",
                           query={"platform": {"in": [platform]}, "eo:cloud_cover": {"lt": CLOUD_MAX}})
    if summer_only:
        ds = [d for d in ds if int(d["properties"]["datetime"][5:7]) in SUMMER]
    C.atomic_json(ds, path)
    return ds


def run_aoi(aoi, grid, platform, years, summer_only, items_dir, workers, ovr):
    aoi_dir = f"{C.ROOT}/{aoi}"
    os.makedirs(aoi_dir, exist_ok=True)
    C.atomic_json(dict(grid, crs=C.DST_CRS, res=C.RES, platform=platform), f"{aoi_dir}/grid.json")
    ctx = mp.get_context("spawn")
    for y in years:
        if os.path.exists(f"{aoi_dir}/scenes/{y}/DONE"):
            continue
        C.check_disk()
        items = search_items(aoi_dir, y, grid, platform, summer_only, items_dir)
        sdir = f"{aoi_dir}/scenes/{y}"
        os.makedirs(sdir, exist_ok=True)
        todo = [d for d in items if not os.path.exists(f"{sdir}/{d['id']}.json")]
        log.info("[%s %s %d] %d scenes, %d to fetch, free %.0f GB", aoi, platform, y, len(items), len(todo), C.free_gb())
        t0, failed = time.time(), []
        for attempt in range(3):
            failed, done = [], 0
            batch = workers * 6          # fresh pool per batch (workers leak memory, see ingest.py)
            for b0 in range(0, len(todo), batch):
                C.check_disk()
                try:
                    token = _sas_token(todo[b0]["assets"]["qa_pixel"]["href"])
                except Exception as e:  # noqa
                    log.warning("token fetch failed (%s), workers sign themselves", str(e)[:100]); token = None
                with ProcessPoolExecutor(workers, mp_context=ctx) as ex:
                    futs = {ex.submit(process_scene, d, sdir, grid, platform, ovr, token): d
                            for d in todo[b0:b0 + batch]}
                    for f in as_completed(futs):
                        try:
                            f.result()
                        except Exception as e:  # noqa
                            failed.append(futs[f])
                            log.warning("[%s %d] %s failed: %s", aoi, y, futs[f]["id"], str(e)[:300])
                        done += 1
                log.info("[%s %s %d] %d/%d failed=%d %.1fs/scene", aoi, platform, y, done, len(todo), len(failed),
                         (time.time() - t0) / max(done, 1))
            if not failed:
                break
            todo = failed
            time.sleep(60)
        n_ok = sum(1 for f in os.listdir(sdir) if f.endswith(".json"))
        if failed:
            log.error("[%s %d] %d scenes still failing", aoi, y, len(failed))
            C.atomic_json([d["id"] for d in failed], f"{sdir}/FAILED.json")
        open(f"{sdir}/DONE", "w").write(time.strftime("%F %T"))
        C.manifest_update(f"landsat/{aoi}", platform=platform, crs=C.DST_CRS, res_m=C.RES,
                          **{f"y{y}": dict(items=len(items), metas=n_ok, failed=len(failed),
                                           seconds=round(time.time() - t0))})
    log.info("[%s %s] ALL YEARS DONE", aoi, platform)


def parse_years(s):
    out = []
    for p in s.split(","):
        a, _, b = p.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


def main():
    global log
    ap = argparse.ArgumentParser()
    ap.add_argument("--aoi", help="aoi name; 'ukraine*' = whole Ukraine grid")
    ap.add_argument("--cities", help="comma list of common.CITIES (50x50 km windows of the Ukraine grid)")
    ap.add_argument("--platform", default="landsat-8")
    ap.add_argument("--years", required=True)
    ap.add_argument("--summer-only", action="store_true")
    ap.add_argument("--items-dir")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--half-km", type=float, default=25)
    ap.add_argument("--full-res", action="store_true", help="read 30 m level instead of the 60 m overview")
    ap.add_argument("--log", default="landsat_scenes")
    a = ap.parse_args()
    log = C.setup_log(a.log)
    ovr = None if a.full_res else 0
    years = parse_years(a.years)
    try:
        if a.aoi:
            run_aoi(a.aoi, C.UKRAINE_GRID, a.platform, years, a.summer_only, a.items_dir, a.workers, ovr)
        for c in (a.cities.split(",") if a.cities else []):
            g = C.subgrid(*C.CITIES[c], half_km=a.half_km)
            run_aoi(f"cities_{a.platform.replace('landsat-', 'l')}/{c}", g, a.platform, years, a.summer_only,
                    None, a.workers, ovr)
    except C.DiskFull as e:
        log.warning("stopping: %s", e)
        sys.exit(75)
    except Exception:  # noqa
        log.error(traceback.format_exc())
        sys.exit(1)
    log.info("FINISHED %s", " ".join(sys.argv[1:]))


if __name__ == "__main__":
    main()
