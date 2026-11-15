"""Per-year "too few clear scenes" mask for the map (QA chat-review re-test, 2022 swath Знам'янка–Олександрія).

Some summers lack whole Landsat strips: in 2022 the Planetary Computer Landsat 8 catalogue has a single, 48 %-cloudy
path-179 scene over rows 26/27 (Landsat 9 has four clear ones, not merged — QUESTIONS A3). Such pixels have no LST
*and* fewer than 3 clear NDVI observations, so they are not the ASTER-GED product gap (``no_lst``) and the display fill
(``gapfill``, which only fills clear-but-no-LST pixels) leaves them transparent. This overlay hatches them per year.

Rule (ukraine grid): a pixel qualifies in year Y if ``lst_n == 0`` and ``ndvi_n < 3`` and it is land (2021 classes);
~1 km blocks (16 × 60 m) with >= 50 % of their land qualifying and >= 25 % land; one-block closing; clipped to
Ukraine; polygons < 25 km² dropped; simplified 500 m. One feature group per year with ``year``, ``area_km2``,
``label_uk`` «{Y}: замало безхмарних знімків цієї смуги».

CLI (read-only on raw data, ~1–2 min, < 1 GB)::

    nice -n 19 python -m uhd.science.noscene_mask [--out PATH] [--force]

Default output: $UHD_DATA_DIR/overlays/no_scenes.geojson. Display only: analysis already excludes such years
(``too_few_scenes`` / ``low_coverage``).
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
from pathlib import Path

import numpy as np
import shapely.geometry as sg
from rasterio.features import shapes
from scipy import ndimage
from shapely.ops import unary_union

from . import classes as C
from . import data as D
from .geometry import to_wgs84
from .nolst_mask import BLOCK, CLASS_YEAR, MIN_LAND_SHARE, SIMPLIFY_M, STRIP_BLOCKS, _clean, _round_coords

log = logging.getLogger("uhd.science.noscene_mask")
MIN_NDVI_N = 3
BLOCK_SHARE = 0.5
MIN_KM2 = 25.0
MAX_BYTES = 400_000


def label_uk(year: int) -> str:
    return f"{year}: замало безхмарних знімків цієї смуги"


def default_out() -> Path:
    return D.DATA / "overlays" / "no_scenes.geojson"


def block_grids(years=D.YEARS) -> tuple[np.ndarray, np.ndarray]:
    """(land px per block, qualifying px per block per year)."""
    g = D.grid("ukraine")
    nby, nbx = math.ceil(g.height / BLOCK), math.ceil(g.width / BLOCK)
    H, W = nby * BLOCK, nbx * BLOCK
    land_px = np.zeros((nby, nbx), np.int32)
    q_px = np.zeros((len(years), nby, nbx), np.int32)

    def blocks(a):
        h = a.shape[0]
        return a.reshape(h // BLOCK, BLOCK, W // BLOCK, BLOCK).sum(axis=(1, 3))

    for br in range(0, nby, STRIP_BLOCKS):
        r0 = br * BLOCK
        h = min(STRIP_BLOCKS * BLOCK, H - r0)
        win = (r0, 0, h, W)
        cls = D.read_tif(D.derived_path("ukraine", "classes.tif"), win, band=CLASS_YEAR - D.YEARS[0] + 1, fill=0)
        land = (cls != C.WATER) & (cls != C.NONE)
        land_px[br:br + h // BLOCK] = blocks(land.astype(np.int32))
        for k, y in enumerate(years):
            q = land & (D.read_count("ukraine", y, "lst_n", win) == 0) & (D.read_count("ukraine", y, "ndvi_n", win) < MIN_NDVI_N)
            q_px[k, br:br + h // BLOCK] = blocks(q.astype(np.int32))
    return land_px, q_px


def year_mask(land_px: np.ndarray, q: np.ndarray) -> np.ndarray:
    m = (land_px >= MIN_LAND_SHARE * BLOCK * BLOCK) & (q >= BLOCK_SHARE * np.maximum(land_px, 1))
    return ndimage.binary_closing(m, np.ones((3, 3), bool), iterations=1, border_value=0) | m


def vectorise(mask: np.ndarray):
    from affine import Affine

    g = D.grid("ukraine")
    T = Affine(D.RES * BLOCK, 0, g.x0, 0, -D.RES * BLOCK, g.y1)
    if not mask.any():
        return None
    polys = [sg.shape(geom) for geom, v in shapes(mask.astype(np.uint8), mask=mask, transform=T) if v == 1]
    geom = unary_union(polys).intersection(D.aoi_polygon_3035("ukraine"))
    parts = [_clean(p, MIN_KM2 * 1e6) for p in getattr(geom, "geoms", [geom]) if p.geom_type == "Polygon"]
    parts = [p for p in parts if p is not None]
    if not parts:
        return None
    geom = unary_union(parts).simplify(SIMPLIFY_M, preserve_topology=True)
    return None if geom.is_empty else geom


def build(out: Path | None = None) -> dict:
    land_px, q_px = block_grids()
    feats = []
    for k, y in enumerate(D.YEARS):
        geom = vectorise(year_mask(land_px, q_px[k]))
        if geom is None:
            continue
        feats.append(dict(type="Feature", geometry=_round_coords(sg.mapping(to_wgs84(geom))),
                          properties=dict(year=y, area_km2=round(geom.area / 1e6, 0), label_uk=label_uk(y))))
        log.info("%d: %.0f km²", y, geom.area / 1e6)
    fc = dict(type="FeatureCollection",
              properties=dict(rule="lst_n == 0 and ndvi_n < 3 on land; ~1 km blocks with >= 50 % of land; closed, "
                                   "< 25 km² dropped, simplified 500 m; one feature per year",
                              label_uk="замало безхмарних знімків цієї смуги в цьому році"),
              features=feats)
    txt = json.dumps(fc, ensure_ascii=False, separators=(",", ":"))
    if len(txt.encode()) > MAX_BYTES:
        raise RuntimeError(f"no-scenes mask too large: {len(txt.encode())} bytes")
    out = Path(out or default_out())
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(txt)
    os.replace(tmp, out)
    log.info("wrote %s: %d features, %d bytes", out, len(feats), len(txt.encode()))
    return fc


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
    build(out)


if __name__ == "__main__":
    main()
