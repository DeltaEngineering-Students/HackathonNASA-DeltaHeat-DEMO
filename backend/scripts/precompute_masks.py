#!/usr/bin/env python3
"""Precompute per-AOI land-cover classes (13 bands, 2013..2025) and the stable-forest mask.

Writes (idempotent: existing outputs are skipped unless --force):
  $UHD_DATA_DIR/<aoi>/classes.tif   uint8, band i = year 2013+i, 0 none 1 built 2 field 3 nature 4 water 5 other
  $UHD_DATA_DIR/<aoi>/forest.tif    uint8 0/1 stable forest (reference candidate pixels)
Usage: precompute_masks.py [--force] kyiv kharkiv lviv ukraine
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import rasterio
from rasterio.windows import Window

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from uhd.science import classes as C  # noqa: E402
from uhd.science import data as D  # noqa: E402

log = logging.getLogger("precompute_masks")
BLOCK = 2048
HALO = 2
PROFILE = dict(driver="GTiff", tiled=True, blockxsize=256, blockysize=256, compress="zstd", zstd_level=3,
               interleave="pixel", bigtiff="IF_SAFER", crs=D.CRS)


def block(aoi: str, r0: int, c0: int, h: int, w: int):
    win = (r0 - HALO, c0 - HALO, h + 2 * HALO, w + 2 * HALO)
    cls = C.classes_window(aoi, win)
    wc = D.read_map(aoi, "worldcover2021", win)
    farm = D.read_map(aoi, "osm_farmland", win) if aoi in D.CITY_AOIS else None
    esri = [D.read_map(aoi, f"esri_{y}", win) for y in D.ESRI_YEARS]
    nd = np.stack([D.read_idx(aoi, y, "ndvi_med", win) for y in D.YEARS])
    with np.errstate(all="ignore"):
        import warnings
        warnings.simplefilter("ignore")
        ndmin = np.nanmin(nd, axis=0)
    forest = C.stable_forest(wc, esri, farm, ndmin, erode=1)
    s = (slice(HALO, HALO + h), slice(HALO, HALO + w))
    return r0, c0, h, w, cls[(slice(None),) + s], forest[s].astype(np.uint8)


def run(aoi: str, force: bool, workers: int):
    g = D.grid(aoi)
    out_dir = D.DATA / aoi
    out_dir.mkdir(parents=True, exist_ok=True)
    pc, pf = out_dir / "classes.tif", out_dir / "forest.tif"
    if pc.exists() and pf.exists() and not force:
        log.info("[%s] classes/forest exist, skip", aoi)
        return
    t0 = time.time()
    prof = dict(PROFILE, width=g.width, height=g.height, transform=g.transform)
    jobs = [(r0, c0, min(BLOCK, g.height - r0), min(BLOCK, g.width - c0))
            for r0 in range(0, g.height, BLOCK) for c0 in range(0, g.width, BLOCK)]
    log.info("[%s] %dx%d px, %d blocks", aoi, g.width, g.height, len(jobs))
    tmp_c, tmp_f = str(pc) + ".tmp", str(pf) + ".tmp"
    with rasterio.open(tmp_c, "w", count=len(D.YEARS), dtype="uint8", nodata=0, **prof) as oc, \
            rasterio.open(tmp_f, "w", count=1, dtype="uint8", nodata=None, **prof) as of, \
            ProcessPoolExecutor(workers) as ex:
        oc.descriptions = tuple(str(y) for y in D.YEARS)
        futs = [ex.submit(block, aoi, *j) for j in jobs]
        for i, f in enumerate(as_completed(futs), 1):
            r0, c0, h, w, cls, forest = f.result()
            oc.write(cls, window=Window(c0, r0, w, h))
            of.write(forest, 1, window=Window(c0, r0, w, h))
            if i % 10 == 0 or i == len(jobs):
                log.info("[%s] %d/%d blocks %.0fs", aoi, i, len(jobs), time.time() - t0)
    os.replace(tmp_c, pc)
    os.replace(tmp_f, pf)
    log.info("[%s] done in %.0fs", aoi, time.time() - t0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("aois", nargs="*", default=list(D.AOIS))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    (D.DATA / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(D.DATA / "logs" / "precompute_masks.log"),
                                  logging.StreamHandler()])
    for aoi in a.aois:
        run(aoi, a.force, a.workers)


if __name__ == "__main__":
    main()
