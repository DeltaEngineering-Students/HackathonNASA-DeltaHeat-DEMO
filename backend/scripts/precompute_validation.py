#!/usr/bin/env python3
"""Validation + demo-case scan (numbers quoted in uhd/docs/METHOD.md §8–9).

1. Legacy reproduction: Kyiv WorldCover-built vs WorldCover-trees ring (old composite method) and Pozniaky.
2. Seam effect: per-scene vs composite gap for the Pozniaky demo circle and for every 1.5 km cell of a city
   (difference per year, inter-annual SD of the gap).
3. Demo scan: cells ranked by gap trend / new built-up / NDVI trend -> candidates for the 3 demo cases.
Writes $UHD_DATA_DIR/validation/<city>.json. Idempotent (--force to recompute). Usage: precompute_validation.py kyiv
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import warnings

import numpy as np
import shapely.geometry as sg

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from uhd.science import analysis as A  # noqa: E402
from uhd.science import data as D  # noqa: E402
from uhd.science import reference as R  # noqa: E402
from uhd.science import stats as ST  # noqa: E402
from uhd.science.geometry import rasterize, to_wgs84  # noqa: E402

log = logging.getLogger("precompute_validation")
CELL = 25  # px = 1.5 km
POZNIAKY_PX = (812.5, 712.9)  # (col, row) in the kyiv grid, ~1 km radius demo zone


def px_circle(city: str, col: float, row: float, r_m: float) -> dict:
    g = D.grid(city)
    p = sg.Point(g.x0 + col * D.RES, g.y1 - row * D.RES).buffer(r_m, 64)
    return sg.mapping(to_wgs84(p))


def px_box(city: str, r0: int, c0: int, n: int) -> dict:
    g = D.grid(city)
    b = sg.box(g.x0 + c0 * D.RES, g.y1 - (r0 + n) * D.RES, g.x0 + (c0 + n) * D.RES, g.y1 - r0 * D.RES)
    return sg.mapping(to_wgs84(b))


def legacy(city: str, zone_mask_full: np.ndarray | None = None) -> dict:
    """Old composite method: WorldCover 2021 built inside the boundary minus WorldCover trees in the ring."""
    g = D.grid(city)
    full = (0, 0, g.height, g.width)
    _, urban = rasterize(D.aoi_polygon_3035(city), city, full)
    wc = D.read_map(city, "worldcover2021", full)
    ring = R.ring_mask(urban)
    zone = (zone_mask_full if zone_mask_full is not None else urban) & (wc == D.WC_BUILT)
    out = {}
    for name, ref in {"wc_trees_ring": ring & (wc == D.WC_TREES),
                      "wc_nature_ring": ring & np.isin(wc, [10, 20, 30, 90]),
                      "stable_forest_ring": R.preset(city).ref}.items():
        gaps = []
        for y in D.YEARS:
            lst = D.read_lst(city, y, full)
            gaps.append(float(np.nanmean(lst[zone]) - np.nanmean(lst[ref])))
        out[name] = dict(mean=round(float(np.mean(gaps)), 2), series=[round(v, 2) for v in gaps])
    return out


def series_pair(geom: dict) -> dict:
    ctx = A.build_context(geom)
    s1 = A.series(ctx)
    s2 = A.composite_series(ctx)
    ys = [r["year"] for r in s1]
    g1 = [r["gap"] for r in s1]
    g2 = [r["gap"] for r in s2]
    diffs = [a - b for a, b, r in zip(g1, g2, s1) if a is not None and b is not None and r["method"] == "per_scene"]
    v1 = [v for v in g1 if v is not None]
    v2 = [v for v in g2 if v is not None]
    lc = A.land_change(ctx)
    return dict(
        mode=ctx.mode, n_px=int(ctx.zone.mask.sum()), land_change=lc,
        per_scene=dict(series=g1, mean=float(np.mean(v1)) if v1 else None, sd=float(np.std(v1, ddof=1)) if len(v1) > 2 else None,
                       trend=ST.trend(ys, g1)),
        composite=dict(series=g2, mean=float(np.mean(v2)) if v2 else None, sd=float(np.std(v2, ddof=1)) if len(v2) > 2 else None,
                       trend=ST.trend(ys, g2)),
        diff_mean=float(np.mean(diffs)) if diffs else None, diff_absmean=float(np.mean(np.abs(diffs))) if diffs else None,
        ndvi_trend=ST.trend(ys, [r["ndvi"] for r in s1], nd=3),
        ndvi=[r["ndvi"] for r in s1], built_share=[r["built_share"] for r in s1],
        scenes=[r["scenes"] for r in s1], methods=[r["method"] for r in s1])


def scan(city: str) -> list[dict]:
    g = D.grid(city)
    ref = R.preset(city)
    out = []
    t0 = time.time()
    for r0 in range(0, g.height - CELL, CELL):
        for c0 in range(0, g.width - CELL, CELL):
            if ref.urban[r0:r0 + CELL, c0:c0 + CELL].mean() < 0.9:
                continue
            try:
                s = series_pair(px_box(city, r0, c0, CELL))
            except Exception as e:  # noqa: BLE001
                log.warning("cell %d,%d failed: %s", r0, c0, e)
                continue
            cx, cy = g.x0 + (c0 + CELL / 2) * D.RES, g.y1 - (r0 + CELL / 2) * D.RES
            ll = to_wgs84(sg.Point(cx, cy))
            out.append(dict(r0=r0, c0=c0, lon=round(ll.x, 5), lat=round(ll.y, 5), **s))
        log.info("[%s] scan row %d/%d, %d cells, %.0fs", city, r0, g.height, len(out), time.time() - t0)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cities", nargs="*", default=["kyiv"])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    warnings.simplefilter("ignore", RuntimeWarning)
    (D.DATA / "logs").mkdir(parents=True, exist_ok=True)
    (D.DATA / "validation").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(D.DATA / "logs" / "precompute_validation.log"),
                                  logging.StreamHandler()])
    for city in a.cities:
        p = D.DATA / "validation" / f"{city}.json"
        if p.exists() and not a.force:
            log.info("exists, skip %s", p)
            continue
        res = dict(city=city, data_version=__import__("uhd.science", fromlist=["DATA_VERSION"]).DATA_VERSION)
        res["legacy_city"] = legacy(city)
        res["city_series"] = series_pair(sg.mapping(to_wgs84(D.aoi_polygon_3035(city))))
        if city == "kyiv":
            g = D.grid(city)
            rr, cc = np.mgrid[0:g.height, 0:g.width]
            col, row = POZNIAKY_PX
            circ = ((cc + 0.5 - col) ** 2 + (rr + 0.5 - row) ** 2) <= (1000 / D.RES) ** 2
            res["legacy_pozniaky"] = legacy(city, circ)
            res["pozniaky"] = series_pair(px_circle(city, col, row, 1000))
        res["cells"] = scan(city)
        json.dump(res, open(str(p) + ".tmp", "w"), default=float)
        os.replace(str(p) + ".tmp", p)
        log.info("written %s", p)


if __name__ == "__main__":
    main()
