"""Sea mask on the ukraine grid (60 m, EPSG:3035) for clipping map tiles: 1 = sea, 0 = land / inland water.

The Ukraine outline includes the 12-nm territorial sea, so tiles clipped to it still drew "heat" over the sea.
Sea = pixels of the 2021 class map that are open sea (class 0: no land-cover product, i.e. beyond the coastal water
of Esri/WorldCover, ~30 km offshore) or water (class 4), connected to seed points in the Black and Azov seas through
water at least ~2.4 km wide — so bays and wide estuaries (Дніпровсько-Бузький лиман) count as sea, but the flood does
not run up the Dnipro into the reservoirs. Lakes, rivers and lagoons behind narrow inlets stay "land" for the tiles.

CLI (read-only on raw data; ~1.5 GB RAM, < 1 min; run it nice'd)::

    nice -n 19 python -m uhd.science.sea_mask [--out PATH] [--force]

Default output: $UHD_DATA_DIR/ukraine/sea_mask.tif (uint8, deflate; written to a temp file, then renamed).
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path

import numpy as np
import rasterio
from scipy import ndimage

from . import classes as C
from . import data as D

log = logging.getLogger("uhd.science.sea_mask")
CLASS_YEAR = 2021
NECK_PX = 20                         # erosion 1.2 km: water narrower than ~2.4 km does not connect to the sea
SEEDS = [(31.5, 45.5), (35.0, 44.3), (36.5, 46.0), (33.5, 44.0)]   # NW Black Sea, S of Crimea, Azov, S Black Sea


def default_out() -> Path:
    return D.DATA / "ukraine" / "sea_mask.tif"


def build_mask() -> np.ndarray:
    """Sea = water (class 4) or no-product (class 0, open sea) pixels connected to the sea seeds through water at
    least ~2.4 km wide: the water is eroded by NECK_PX, the components holding a seed are kept and grown back inside
    the water. Narrow rivers break the connection, so the Dnipro, its reservoirs and inland lakes stay land."""
    from rasterio.warp import transform

    g = D.grid("ukraine")
    cls = D.read_tif(D.derived_path("ukraine", "classes.tif"), None, band=CLASS_YEAR - D.YEARS[0] + 1)
    water = (cls == C.NONE) | (cls == C.WATER)
    del cls
    H, W = water.shape
    st = np.ones((3, 3), bool)
    core = ndimage.binary_erosion(water, st, iterations=NECK_PX, border_value=1)
    lab, _ = ndimage.label(core)
    keep = set()
    for lon, lat in SEEDS:
        x, y = transform("EPSG:4326", "EPSG:3035", [lon], [lat])
        r, c = int((g.y1 - y[0]) / D.RES), int((x[0] - g.x0) / D.RES)
        if 0 <= r < H and 0 <= c < W and lab[r, c] > 0:
            keep.add(int(lab[r, c]))
    if not keep:
        raise RuntimeError("no sea seed inside the grid")
    sea = np.isin(lab, sorted(keep))
    del lab, core
    sea = ndimage.binary_dilation(sea, st, iterations=NECK_PX + 2, mask=water)
    # water pixels that touch the grown sea and belong to the same connected water body near the coast
    return sea


def write(mask: np.ndarray, out: Path) -> None:
    g = D.grid("ukraine")
    from affine import Affine

    prof = dict(driver="GTiff", height=mask.shape[0], width=mask.shape[1], count=1, dtype="uint8", crs="EPSG:3035",
                transform=Affine(D.RES, 0, g.x0, 0, -D.RES, g.y1), compress="deflate", tiled=True,
                blockxsize=512, blockysize=512)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    with rasterio.open(tmp, "w", **prof) as o:
        o.write(mask.astype(np.uint8), 1)
    os.replace(tmp, out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=None)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    out = Path(a.out or default_out())
    if out.exists() and not a.force:
        log.info("%s exists (use --force)", out)
        return
    t0 = time.time()
    m = build_mask()
    write(m, out)
    log.info("wrote %s: sea %.0f km², %.0fs", out, m.sum() * D.PX_KM2, time.time() - t0)


if __name__ == "__main__":
    main()
