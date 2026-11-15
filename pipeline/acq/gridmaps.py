#!/usr/bin/env python3
"""Static rasters on the Ukraine EPSG:3035 60 m grid (same grid/blocks as pipeline/maps.py).

  dem_cop30.tif          Copernicus DEM GLO-30, mean elevation in the 60 m cell, int16 decimetres (nodata -32768)
                         -> elevation / lapse-rate correction of LST (−0.65 °C per 100 m as a first guess)
  worldcover2020.tif     ESA WorldCover v100 (2020), majority class (same codes as worldcover2021.tif)
  gsw_occurrence.tif     JRC Global Surface Water occurrence 1984-2021, % (uint8, 255 = no data), mean
  gsw_seasonality.tif    JRC GSW months of water per year (uint8 0-12), max
  cci_lc_<year>.tif      ESA CCI Land Cover 300 m 1992/2000/2005/2010/2015/2020 (uint8 LCCS class, mode)
Output: ROOT/ukraine/maps/<name>.tif.  Resumable per map.
"""
import os, sys, time, math, argparse
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

import numpy as np

BLOCK = 1024
log = None


def block(items, asset, r0, c0, h, w, grid, ovr, resampling, dtype, src_nd, out_nd, scale):
    import rasterio, pystac
    import planetary_computer as pc
    from rasterio.warp import reproject, Resampling
    from rasterio.windows import Window, transform as win_transform
    rs = getattr(Resampling, resampling)
    dT = win_transform(Window(c0, r0, w, h), C.grid_transform(grid))
    out = np.full((h, w), np.nan, np.float32)
    for d in items:
        it = pystac.Item.from_dict(d)
        for attempt in range(5):
            try:
                pc.sign_inplace(it)
                kw = {"overview_level": ovr} if ovr is not None else {}
                with rasterio.open(it.assets[asset].href, **kw) as s:
                    tmp = np.full((h, w), np.nan, np.float32)
                    nd = src_nd if src_nd is not None else s.nodata
                    reproject(rasterio.band(s, 1), tmp, dst_transform=dT, dst_crs=C.DST_CRS, src_nodata=nd,
                              dst_nodata=np.nan, resampling=rs, num_threads=2)
                break
            except Exception as e:  # noqa
                if attempt == 4:
                    raise RuntimeError(f"{d['id']}: {e!r}")
                time.sleep(5 * (attempt + 1))
        fill = np.isnan(out) & np.isfinite(tmp)
        out[fill] = tmp[fill]
    o = np.full((h, w), out_nd, dtype)
    ok = np.isfinite(out)
    o[ok] = np.round(out[ok] * scale).astype(dtype)
    return o


def build(name, collection, asset, search_kw=None, item_filter=None, ovr=None, resampling="mode",
          dtype="uint8", src_nd=None, out_nd=0, scale=1.0, par=4):
    import rasterio, pyproj
    import shapely.geometry as sg
    from shapely.ops import transform as stransform
    from rasterio.windows import Window
    grid = C.UKRAINE_GRID
    path = f"{C.ROOT}/ukraine/maps/{name}.tif"
    if os.path.exists(path):
        log.info("%s exists, skip", name); return
    C.check_disk()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    t0 = time.time()
    w, s, e, n = C.grid_bounds_ll(grid)
    items = C.stac_search(collection, bbox=[w, s, e, n], **(search_kw or {}))
    if item_filter:
        items = [d for d in items if item_filter(d)]
    to_ll = pyproj.Transformer.from_crs(3035, 4326, always_xy=True).transform
    gT = C.grid_transform(grid)
    jobs = []
    for r0 in range(0, grid["H"], BLOCK):
        for c0 in range(0, grid["W"], BLOCK):
            h, w_ = min(BLOCK, grid["H"] - r0), min(BLOCK, grid["W"] - c0)
            bll = stransform(to_ll, sg.box(*rasterio.windows.bounds(Window(c0, r0, w_, h), gT)))
            its = [d for d in items if sg.shape(d["geometry"]).intersects(bll)]
            if its:
                jobs.append((r0, c0, h, w_, its))
    log.info("%s: %d source items, %d blocks", name, len(items), len(jobs))
    prof = dict(C.GT_OPTS, height=grid["H"], width=grid["W"], crs=C.DST_CRS, transform=gT, count=1,
                dtype=dtype, nodata=out_nd)
    with rasterio.open(path + ".tmp", "w", **prof) as o, \
            ProcessPoolExecutor(par, mp_context=mp.get_context("spawn")) as ex:
        futs = {ex.submit(block, its, asset, r0, c0, h, w_, grid, ovr, resampling, dtype, src_nd, out_nd, scale):
                (r0, c0, h, w_) for r0, c0, h, w_, its in jobs}
        for i, f in enumerate(as_completed(futs), 1):
            r0, c0, h, w_ = futs[f]
            o.write(f.result(), 1, window=Window(c0, r0, w_, h))
            if i % 50 == 0:
                log.info("%s %d/%d blocks", name, i, len(jobs))
    os.replace(path + ".tmp", path)
    C.manifest_update(f"maps/{name}", path=path, crs=C.DST_CRS, res_m=C.RES, source=f"PC {collection}:{asset}",
                      items=len(items), bytes=os.path.getsize(path), seconds=round(time.time() - t0))
    log.info("%s done in %.0fs", name, time.time() - t0)


def main():
    global log
    ap = argparse.ArgumentParser()
    ap.add_argument("--par", type=int, default=4)
    a = ap.parse_args()
    log = C.setup_log("gridmaps")
    p = a.par
    try:
        build("dem_cop30", "cop-dem-glo-30", "data", resampling="average", dtype="int16", out_nd=-32768,
              scale=10.0, par=p)
        build("worldcover2020", "esa-worldcover", "map", ovr=0, par=p,
              item_filter=lambda d: d["properties"].get("esa_worldcover:product_version") == "1.0.0")
        build("gsw_occurrence", "jrc-gsw", "occurrence", resampling="average", out_nd=255, src_nd=255, par=p)
        build("gsw_seasonality", "jrc-gsw", "seasonality", resampling="max", out_nd=255, src_nd=255, par=p)
        for y in (1995, 2000, 2005, 2010, 2015, 2020):
            build(f"cci_lc_{y}", "esa-cci-lc", "lccs_class", search_kw=dict(datetime=f"{y}-01-01/{y}-12-31"),
                  par=p, src_nd=0)
        log.info("GRIDMAPS DONE")
    except C.DiskFull as e:
        log.warning("stopping: %s", e)
        sys.exit(75)


if __name__ == "__main__":
    main()
