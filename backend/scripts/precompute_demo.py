#!/usr/bin/env python3
"""Demo zones (concept §9) as GeoJSON presets + their reports.

Writes $UHD_DATA_DIR/places/demo.geojson (FeatureCollection; properties id, name, kind="demo", city, case,
note_uk) and $UHD_DATA_DIR/validation/demo_cases.json (full analyze() reports + GHSL built surface).
--repo-copy DIR also copies demo.geojson there (uhd/backend/data/places). Idempotent (--force).
Zones were picked from the 1.5 km cell scan of precompute_validation.py (METHOD.md §9).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys

import shapely.geometry as sg

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from uhd import science as S  # noqa: E402
from uhd.science import data as D  # noqa: E402
from uhd.science.geometry import to_3035, to_wgs84  # noqa: E402

log = logging.getLogger("precompute_demo")


def kyiv_box(r0: int, c0: int, n: int):
    g = D.grid("kyiv")
    return to_wgs84(sg.box(g.x0 + c0 * D.RES, g.y1 - (r0 + n) * D.RES, g.x0 + (c0 + n) * D.RES, g.y1 - r0 * D.RES))


def kyiv_circle(col: float, row: float, r_m: float):
    g = D.grid("kyiv")
    return to_wgs84(sg.Point(g.x0 + col * D.RES, g.y1 - row * D.RES).buffer(r_m, 64))


def square(lon: float, lat: float, half_m: float):
    return to_wgs84(to_3035(sg.Point(lon, lat)).buffer(half_m, cap_style="square"))


DEMOS = [
    dict(id="demo-nyzhni-sady", name="Нижні Сади (Осокорки)", case="densifying",
         geom=lambda: kyiv_box(750, 775, 50),
         note_uk="Колишні дачі забудовують щільніше — розрив із лісом росте."),
    dict(id="demo-desnianske", name="Котеджне містечко «Деснянське» (Троєщина)", case="greening",
         geom=lambda: kyiv_box(475, 675, 25),
         note_uk="Котеджі, де підросли сади: зелені більшає, розрив зменшується."),
    dict(id="demo-holosiivskyi-lis", name="Голосіївський ліс", case="control",
         geom=lambda: square(30.505, 50.375, 700),
         note_uk="Великий ліс у місті: поводиться як природа — розриву майже немає."),
    dict(id="demo-pozniaky", name="Позняки", case="hot_stable",
         geom=lambda: kyiv_circle(812.5, 712.9, 1000),
         note_uk="Щільні багатоповерхівки: найгарячіше місце, але розрив не росте."),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--repo-copy", default=None)
    a = ap.parse_args()
    (D.DATA / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(D.DATA / "logs" / "precompute_demo.log"),
                                  logging.StreamHandler()])
    pg = D.DATA / "places" / "demo.geojson"
    pr = D.DATA / "validation" / "demo_cases.json"
    if pg.exists() and pr.exists() and not a.force:
        log.info("exists, skip")
    else:
        pg.parent.mkdir(parents=True, exist_ok=True)
        pr.parent.mkdir(parents=True, exist_ok=True)
        feats, reports = [], {}
        for d in DEMOS:
            g = d["geom"]()
            geom = sg.mapping(g)
            rep = S.analyze(geom, name=d["name"])
            reports[d["id"]] = dict(report=rep, ghsl_built_surface_km2=S.ghsl_built(geom))
            feats.append(dict(type="Feature", geometry=geom, properties=dict(
                id=d["id"], name=d["name"], kind="demo", city="kyiv", case=d["case"], note_uk=d["note_uk"],
                area_km2=rep["zone"]["area_km2"])))
            t = rep["trend"]
            log.info("%s: gap %.2f, trend %s (p=%s, %s), ndvi %s (p=%s)", d["id"], rep["gap_summary"]["mean"],
                     t["slope_per_decade"], t["p"], t["verdict"], rep["ndvi_trend"]["slope_per_decade"],
                     rep["ndvi_trend"]["p"])
        json.dump(dict(type="FeatureCollection", features=feats), open(pg, "w"), ensure_ascii=False)
        json.dump(reports, open(pr, "w"), ensure_ascii=False)
    if a.repo_copy:
        os.makedirs(a.repo_copy, exist_ok=True)
        shutil.copy(pg, os.path.join(a.repo_copy, "demo.geojson"))


if __name__ == "__main__":
    main()
