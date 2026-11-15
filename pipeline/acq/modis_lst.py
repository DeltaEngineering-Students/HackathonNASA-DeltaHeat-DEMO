#!/usr/bin/env python3
"""MODIS LST (Collection 6.1) day + NIGHT, Terra (~10:30/22:30) and Aqua (~13:30/01:30), over Ukraine.

Night-time LST is what Landsat cannot give us: the night urban heat island. 1 km, so it is for city-scale
UHI and context, not districts.

Source: Planetary Computer modis-11A2-061 (8-day) and modis-11A1-061 (daily), sinusoidal tiles
h19v03 h19v04 h20v03 h20v04, reprojected (nearest) onto a 960 m EPSG:3035 grid that nests exactly in the
60 m Ukraine grid (same origin x0=5195100, y1=3534420; 1 px = 16 x 16 px of the 60 m grid; 1362 x 952 px).

Output: ROOT/modis/<MOD11A2|MYD11A2|MOD11A1|MYD11A1>/<year>/<YYYY-MM-DD>.tif, int16, nodata -32768, 6 bands:
  1 LST_Day degC x100   2 LST_Night degC x100   3 QC_Day   4 QC_Night   5 Day_view_time h x10   6 Night_view_time h x10
(QC bits 0-1: 00 good, 01 other quality; bits 6-7 LST error: 00 <=1K, 01 <=2K, ...)

Usage: modis_lst.py  (runs the stages below in order; resumable per file)
"""
import os, sys, time, math, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

import numpy as np

F = 16
GRID = dict(x0=C.UKRAINE_GRID["x0"], y1=C.UKRAINE_GRID["y1"],
            W=math.ceil(C.UKRAINE_GRID["W"] / F), H=math.ceil(C.UKRAINE_GRID["H"] / F))
RES = C.RES * F
ASSETS = ["LST_Day_1km", "LST_Night_1km", "QC_Day", "QC_Night", "Day_view_time", "Night_view_time"]
log = None


def build(prod, date, items, out):
    import rasterio, pystac
    import planetary_computer as pc
    from rasterio.warp import reproject, Resampling
    T = C.grid_transform(GRID, RES)
    acc = {a: np.zeros((GRID["H"], GRID["W"]), np.float32) for a in ASSETS}
    have = {a: np.zeros((GRID["H"], GRID["W"]), bool) for a in ASSETS}
    for d in items:
        it = pystac.Item.from_dict(d)
        for attempt in range(5):
            try:
                pc.sign_inplace(it)
                for a in ASSETS:
                    if a not in it.assets:
                        continue
                    with rasterio.open(it.assets[a].href) as s:
                        src = s.read(1)
                        nd = s.nodata
                        dst = np.zeros((GRID["H"], GRID["W"]), np.float32)
                        ok = np.zeros((GRID["H"], GRID["W"]), np.uint8)
                        if a.startswith("LST"):
                            valid = src > 0                      # 0 = fill
                        elif a.endswith("view_time"):
                            valid = src < 255                    # 255 = fill
                        else:
                            valid = np.ones(src.shape, bool)     # QC: 0 means "good quality", not fill
                        reproject(src.astype(np.float32), dst, src_transform=s.transform, src_crs=s.crs,
                                  dst_transform=T, dst_crs=C.DST_CRS, resampling=Resampling.nearest)
                        reproject(valid.astype(np.uint8), ok, src_transform=s.transform, src_crs=s.crs,
                                  dst_transform=T, dst_crs=C.DST_CRS, resampling=Resampling.nearest)
                    m = (ok == 1) & ~have[a]
                    acc[a][m] = dst[m]
                    have[a] |= m
                break
            except Exception as e:  # noqa
                if attempt == 4:
                    raise RuntimeError(f"{d['id']}: {e!r}")
                time.sleep(5 * (attempt + 1))
    out_arr = np.full((6, GRID["H"], GRID["W"]), -32768, np.int16)
    for i, a in enumerate(ASSETS):
        v, h = acc[a], have[a]
        if a.startswith("LST"):
            out_arr[i][h] = np.round(v[h] * 2 - 27315).astype(np.int16)      # 0.02 K -> degC x100
        elif a.endswith("view_time"):
            h &= v < 255
            out_arr[i][h] = v[h].astype(np.int16)                          # 0.1 h local solar time
        else:
            out_arr[i][h] = v[h].astype(np.int16)
    prof = dict(C.GT_OPTS, blockxsize=256, blockysize=256, predictor=2, zstd_level=9, height=GRID["H"], width=GRID["W"], count=6,
                dtype="int16", nodata=-32768, crs=C.DST_CRS, transform=T)
    with rasterio.open(out + ".tmp", "w", **prof) as o:
        o.write(out_arr)
        o.descriptions = tuple(ASSETS)
        o.update_tags(product=prod, date=date, tiles=",".join(d["id"].split(".")[2] for d in items))
    os.replace(out + ".tmp", out)
    return int(have["LST_Day_1km"].sum()), int(have["LST_Night_1km"].sum())


def stage(coll, years, months, par):
    w, s, e, n = C.grid_bounds_ll(GRID, RES)
    for y in years:
        C.check_disk()
        m0, m1 = months
        last = {2: 28, 4: 30, 6: 30, 9: 30, 11: 30}.get(m1, 31)
        items = C.stac_search(coll, bbox=[w, s, e, n], datetime=f"{y}-{m0:02d}-01/{y}-{m1:02d}-{last}")
        groups = {}
        for d in items:
            prod = d["id"].split(".")[0]
            date = d["properties"].get("start_datetime", d["properties"].get("datetime"))[:10]
            groups.setdefault((prod, date), []).append(d)
        todo = []
        for (prod, date), its in sorted(groups.items()):
            out = f"{C.ROOT}/modis/{prod}/{y}/{date}.tif"
            if not os.path.exists(out):
                os.makedirs(os.path.dirname(out), exist_ok=True)
                todo.append((prod, date, its, out))
        t0 = time.time()
        log.info("[%s %d] %d items, %d dates, %d to build", coll, y, len(items), len(groups), len(todo))
        fails = 0
        with ThreadPoolExecutor(par) as ex:
            futs = {ex.submit(build, *t): t for t in todo}
            for f in as_completed(futs):
                try:
                    f.result()
                except Exception as e:  # noqa
                    fails += 1
                    log.warning("%s %s failed: %s", futs[f][0], futs[f][1], str(e)[:200])
        log.info("[%s %d] done %d (%d failed) in %.0fs", coll, y, len(todo), fails, time.time() - t0)
        C.manifest_update(f"modis/{coll}", path=f"{C.ROOT}/modis", crs=C.DST_CRS, res_m=RES,
                          grid=GRID, **{f"y{y}_months{m0}-{m1}": dict(dates=len(groups), failed=fails)})


def main():
    global log
    ap = argparse.ArgumentParser()
    ap.add_argument("--par", type=int, default=6)
    ap.add_argument("--stages", default="1,2,3,4,5,6")
    ap.add_argument("--years", help="restrict every stage to these years, e.g. 2021-2025")
    a = ap.parse_args()
    log = C.setup_log("modis_lst")
    stages = {
        1: ("modis-11A2-061", range(2013, 2026), (1, 12)),   # 8-day, full year, Terra+Aqua
        2: ("modis-11A1-061", range(2013, 2026), (6, 8)),    # daily, summer
        3: ("modis-11A2-061", range(2003, 2013), (1, 12)),   # 8-day back to Aqua start (Jul 2002)
        4: ("modis-11A1-061", range(2003, 2013), (6, 8)),    # daily summers back to 2003
        5: ("modis-11A1-061", range(2013, 2026), (5, 5)),    # shoulder months
        6: ("modis-11A1-061", range(2013, 2026), (9, 9)),
    }
    try:
        keep = None
        if a.years:
            y0, _, y1 = a.years.partition("-")
            keep = set(range(int(y0), int(y1 or y0) + 1))
        for k in [int(x) for x in a.stages.split(",")]:
            coll, yrs, months = stages[k]
            stage(coll, [y for y in yrs if keep is None or y in keep], months, a.par)
        log.info("MODIS DONE stages %s", a.stages)
    except C.DiskFull as e:
        log.warning("stopping: %s", e)
        sys.exit(75)


if __name__ == "__main__":
    main()
