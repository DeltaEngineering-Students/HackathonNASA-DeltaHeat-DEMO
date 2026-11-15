"""Display-only fill of year-specific LST holes on the map (PM item 9, Volyn/Rivne).

A pixel of summer Y is a *hole* if it had clear views (``ndvi_n >= 3``) but no LST (``lst_n == 0``) — mostly the
Landsat C2 L2 ASTER-GED emissivity gap, which in some summers covers extra patches. Holes that are **persistent**
(no LST in >= 7 of the 13 summers, the no-LST mask rule) are never filled: they stay transparent and the map hatches
them (overlay ``no_lst``). Other holes get, for display only, the median of the same pixel's value in the nearest valid
summers: Y±1, and if neither has a value, Y±2.

The fill is a separate tile layer (``gap_fill`` / ``lst_fill``: values only on filled pixels, NaN elsewhere), so the
regular ``gap`` / ``lst`` layers are unchanged and the renderer draws the fill with its own alpha and the legend note
«заповнено з сусідніх років». Reports, trends and every number in the analysis never read it.

Persistent counts come from ``$UHD_DATA_DIR/ukraine/nolst_years.tif`` (uint8, summers with a hole per pixel; built by
the CLI below) when present, otherwise they are counted on the fly (13 × 2 count reads per window)::

    nice -n 19 python -m uhd.science.gapfill [--out PATH] [--force]     # ~2 min, ~0.5 GB RAM, read-only on raw data
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import time
import warnings
from pathlib import Path

import numpy as np

from . import data as D

log = logging.getLogger("uhd.science.gapfill")
MIN_NDVI_N = 3                                  # = analysis.no_lst_product / nolst_mask
PERSISTENT_YEARS = math.ceil(0.5 * len(D.YEARS))  # 7 of 13 = nolst_mask.YEAR_SHARE
STEPS = ((1,), (2,))                             # Y±1 first, then Y±2
FILL_LAYERS = {"gap_fill": "gap", "lst_fill": "lst"}
STRIP = 1024


def counts_path() -> Path:
    return D.DATA / "ukraine" / "nolst_years.tif"


def holes(aoi: str, year: int, win: D.Win) -> np.ndarray:
    return (D.read_count(aoi, year, "lst_n", win) == 0) & (D.read_count(aoi, year, "ndvi_n", win) >= MIN_NDVI_N)


def hole_years(aoi: str, win: D.Win) -> np.ndarray:
    """Per pixel: number of summers with a hole (uint8)."""
    p = counts_path()
    if aoi == "ukraine" and p.exists():
        return D.read_tif(p, win, fill=0)
    if aoi != "ukraine" and p.exists():           # city grids are aligned sub-windows of the ukraine grid
        dr, dc = D.grid(aoi).offset_of(D.grid("ukraine"))
        r0, c0, h, w = win
        return D.read_tif(p, (r0 + dr, c0 + dc, h, w), fill=0)
    r0, c0, h, w = win
    n = np.zeros((h, w), np.uint8)
    for y in D.YEARS:
        n += holes(aoi, y, win)
    return n


def neighbour_years(year: int, step: int) -> list[int]:
    return [y for y in (year - step, year + step) if y in D.YEARS]


def fill_raster(aoi: str, layer: str, year: int, win: D.Win, base=None) -> np.ndarray:
    """Values only on filled pixels (NaN elsewhere). ``layer`` is ``gap`` or ``lst``; ``base`` = layer_raster(...)."""
    from .rasters import layer_raster

    def get(y):
        return np.asarray(layer_raster(aoi, layer, y, win)[0], np.float32)

    cur = get(year) if base is None else np.asarray(base, np.float32)
    out = np.full(cur.shape, np.nan, np.float32)
    todo = np.isnan(cur) & holes(aoi, year, win)
    if not todo.any():
        return out
    todo &= hole_years(aoi, win) < PERSISTENT_YEARS
    for (step,) in STEPS:
        if not todo.any():
            break
        ys = neighbour_years(year, step)
        if not ys:
            continue
        stack = np.stack([get(y) for y in ys])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)     # all-NaN columns
            med = np.nanmedian(stack, axis=0)
        ok = todo & np.isfinite(med)
        out[ok] = med[ok]
        todo &= ~ok
    return out


def build_counts(out: Path) -> None:
    import rasterio
    from affine import Affine
    from rasterio.windows import Window

    g = D.grid("ukraine")
    prof = dict(driver="GTiff", height=g.height, width=g.width, count=1, dtype="uint8", crs="EPSG:3035",
                transform=Affine(D.RES, 0, g.x0, 0, -D.RES, g.y1), compress="deflate", tiled=True,
                blockxsize=512, blockysize=512, nodata=None)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    with rasterio.open(tmp, "w", **prof) as o:
        for r0 in range(0, g.height, STRIP):
            h = min(STRIP, g.height - r0)
            n = np.zeros((h, g.width), np.uint8)
            for y in D.YEARS:
                n += holes("ukraine", y, (r0, 0, h, g.width))
            o.write(n, 1, window=Window(0, r0, g.width, h))
    os.replace(tmp, out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="per-pixel count of summers without LST (for the display fill)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    out = Path(a.out or counts_path())
    if out.exists() and not a.force:
        log.info("%s exists (use --force)", out)
        return
    t0 = time.time()
    build_counts(out)
    log.info("wrote %s (%d bytes) in %.0fs", out, out.stat().st_size, time.time() - t0)


if __name__ == "__main__":
    main()
