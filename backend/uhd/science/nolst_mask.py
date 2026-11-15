"""No-LST mask for the map hatch (MAP-TASKS #4, QA SCI-01): where Landsat C2 L2 gives no surface temperature.

Rule (the same as ``analysis.no_lst_product``: a product gap — missing ASTER GED emissivity — not clouds): on the
``ukraine`` grid a pixel qualifies in a summer if ``lst_n == 0`` and ``ndvi_n >= 3``; it is a no-LST pixel if it
qualifies in >= 50 % of the summers 2013–2025. Aggregated to ~1 km blocks (16 × 60 m): a block is no-LST if >= 50 % of
its land pixels (classes != water/none) are; morphological closing (1 block), vectorised, holes and polygons < 4 km²
dropped, clipped to Ukraine, simplified to ~500 m, written as WGS84 GeoJSON (coordinates 4 decimals, ≤ 300 kB).

Feature properties: ``years`` (summers in which >= 50 % of the feature's blocks are no-LST), ``share_years`` (mean
share of summers without LST over the feature's blocks), ``area_km2``, ``label_uk``.

CLI (read-only on /srv/landsat; strip-wise reads, ~75 s and ~0.6 GB peak RSS; run it nice'd)::

    nice -n 19 python -m uhd.science.nolst_mask [--out PATH] [--force]

Default output: $UHD_DATA_DIR/overlays/no_lst.geojson (served by the backend in GET /api/overlays).
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import time
from pathlib import Path

import numpy as np
import shapely.geometry as sg
from rasterio.features import shapes
from scipy import ndimage
from shapely.ops import unary_union

from . import classes as C
from . import data as D
from .geometry import to_wgs84

log = logging.getLogger("uhd.science.nolst_mask")

BLOCK = 16                 # 16 × 60 m = 960 m
STRIP_BLOCKS = 64          # rows of blocks read per strip (1024 px)
MIN_NDVI_N = 3             # = analysis.no_lst_product
YEAR_SHARE = 0.5           # pixel: no LST in >= 50 % of the summers
BLOCK_SHARE = 0.5          # block: >= 50 % of its land pixels
MIN_LAND_SHARE = 0.25      # blocks that are mostly sea / outside the data are ignored
MIN_KM2 = 4.0              # holes and polygons smaller than this are dropped
SIMPLIFY_M = 500.0
MAX_BYTES = 300_000
LABEL_UK = "немає супутникової температури поверхні"
CLASS_YEAR = 2021


def default_out() -> Path:
    return D.DATA / "overlays" / "no_lst.geojson"


def block_grids(years=D.YEARS) -> dict:
    """Per-block arrays on the ukraine grid: land px, no-LST px (multi-year rule) and per-year no-LST flags."""
    g = D.grid("ukraine")
    nby, nbx = math.ceil(g.height / BLOCK), math.ceil(g.width / BLOCK)
    H, W = nby * BLOCK, nbx * BLOCK
    land_px = np.zeros((nby, nbx), np.int32)
    nolst_px = np.zeros((nby, nbx), np.int32)
    per_year = np.zeros((len(years), nby, nbx), bool)
    year_frac = np.zeros((nby, nbx), np.float32)
    need = math.ceil(YEAR_SHARE * len(years))
    cls_band = CLASS_YEAR - D.YEARS[0] + 1

    def blocks(a):  # (h, W) -> (h/B, W/B) sums
        h = a.shape[0]
        return a.reshape(h // BLOCK, BLOCK, W // BLOCK, BLOCK).sum(axis=(1, 3))

    for br in range(0, nby, STRIP_BLOCKS):
        r0 = br * BLOCK
        h = min(STRIP_BLOCKS * BLOCK, H - r0)
        win = (r0, 0, h, W)
        cls = D.read_tif(D.derived_path("ukraine", "classes.tif"), win, band=cls_band, fill=0)
        land = (cls != C.WATER) & (cls != C.NONE)
        cnt = np.zeros((h, W), np.uint8)
        lb = blocks(land.astype(np.int32))
        land_px[br:br + h // BLOCK] = lb
        for k, y in enumerate(years):
            q = (D.read_count("ukraine", y, "lst_n", win) == 0) & (D.read_count("ukraine", y, "ndvi_n", win) >= MIN_NDVI_N)
            q &= land
            cnt += q
            qb = blocks(q.astype(np.int32))
            per_year[k, br:br + h // BLOCK] = qb >= BLOCK_SHARE * np.maximum(lb, 1)
        nolst_px[br:br + h // BLOCK] = blocks(((cnt >= need) & land).astype(np.int32))
        with np.errstate(invalid="ignore", divide="ignore"):
            year_frac[br:br + h // BLOCK] = blocks(cnt.astype(np.int32)) / np.maximum(lb, 1) / len(years)
        log.info("strip %d/%d", br // STRIP_BLOCKS + 1, math.ceil(nby / STRIP_BLOCKS))
    return dict(land_px=land_px, nolst_px=nolst_px, per_year=per_year, year_frac=year_frac, years=list(years))


def mask_from_blocks(b: dict) -> np.ndarray:
    land = b["land_px"]
    m = (land >= MIN_LAND_SHARE * BLOCK * BLOCK) & (b["nolst_px"] >= BLOCK_SHARE * np.maximum(land, 1))
    return ndimage.binary_closing(m, np.ones((3, 3), bool), iterations=1, border_value=0) | m


def _clean(poly, min_m2: float):
    """Drop holes < min_m2; None if the polygon itself is < min_m2."""
    if poly.area < min_m2:
        return None
    holes = [h for h in poly.interiors if sg.Polygon(h).area >= min_m2]
    return sg.Polygon(poly.exterior, holes)


def vectorise(mask: np.ndarray, b: dict) -> list[dict]:
    from affine import Affine

    g = D.grid("ukraine")
    T = Affine(D.RES * BLOCK, 0, g.x0, 0, -D.RES * BLOCK, g.y1)
    ua = D.aoi_polygon_3035("ukraine")
    min_m2 = MIN_KM2 * 1e6
    lab, n = ndimage.label(mask, np.ones((3, 3), bool))
    feats = []
    for k in range(1, n + 1):
        comp = lab == k
        polys = [sg.shape(geom) for geom, v in shapes(comp.astype(np.uint8), mask=comp, transform=T) if v == 1]
        geom = unary_union(polys).intersection(ua)
        parts = [_clean(p, min_m2) for p in getattr(geom, "geoms", [geom]) if p.geom_type == "Polygon"]
        parts = [p for p in parts if p is not None]
        if not parts:
            continue
        geom = unary_union(parts).simplify(SIMPLIFY_M, preserve_topology=True)
        if geom.is_empty or geom.area < min_m2:
            continue
        yrs = [y for i, y in enumerate(b["years"]) if b["per_year"][i][comp].mean() >= 0.5]
        share = float(b["year_frac"][comp].mean())
        feats.append((geom, dict(years=yrs, share_years=round(share, 2), area_km2=round(geom.area / 1e6, 1),
                                 label_uk=LABEL_UK)))
    return feats


def _round_coords(geom: dict, nd: int = 4) -> dict:
    def r(c):
        return [round(c[0], nd), round(c[1], nd)] if isinstance(c[0], (int, float)) else [r(x) for x in c]

    return dict(type=geom["type"], coordinates=r(geom["coordinates"]))


def build(out: Path | None = None) -> dict:
    t0 = time.time()
    b = block_grids()
    mask = mask_from_blocks(b)
    feats = vectorise(mask, b)
    fc = dict(type="FeatureCollection",
              properties=dict(rule="lst_n == 0 and ndvi_n >= 3 in >= 50 % of summers 2013–2025; ~1 km blocks with "
                                   ">= 50 % of land pixels; closed, < 4 km² dropped, simplified 500 m",
                              data_version=_data_version(), area_km2=round(sum(g.area for g, _ in feats) / 1e6, 0)),
              features=[dict(type="Feature", properties=p, geometry=_round_coords(sg.mapping(to_wgs84(g))))
                        for g, p in sorted(feats, key=lambda f: -f[0].area)])
    txt = json.dumps(fc, ensure_ascii=False, separators=(",", ":"))
    if len(txt.encode()) > MAX_BYTES:
        raise RuntimeError(f"no-LST mask too large: {len(txt.encode())} bytes")
    out = Path(out or default_out())
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(txt)
    os.replace(tmp, out)
    log.info("wrote %s: %d features, %.0f km², %d bytes in %.0fs", out, len(fc["features"]),
             fc["properties"]["area_km2"], len(txt.encode()), time.time() - t0)
    return fc


def _data_version() -> str:
    from .report import DATA_VERSION

    return DATA_VERSION


def contains(fc: dict, lon: float, lat: float) -> bool:
    p = sg.Point(lon, lat)
    return any(sg.shape(f["geometry"]).contains(p) for f in fc["features"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=None)
    ap.add_argument("--force", action="store_true", help="rebuild even if the output exists")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    out = Path(a.out or default_out())
    if out.exists() and not a.force:
        log.info("%s exists (use --force)", out)
        return
    fc = build(out)
    checks = {"Маріуполь (SCI-01)": (37.55, 47.10, True), "Київ": (30.52, 50.45, False),
              "Харків": (36.23, 49.99, False), "Львів": (24.03, 49.84, False)}
    for name, (lon, lat, want) in checks.items():
        got = contains(fc, lon, lat)
        log.info("check %s: inside=%s %s", name, got, "ok" if got == want else "UNEXPECTED")


if __name__ == "__main__":
    main()
