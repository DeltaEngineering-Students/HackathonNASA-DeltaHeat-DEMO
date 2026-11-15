#!/usr/bin/env python3
"""Fetch real district (raion) and named-locality polygons for Kyiv/Kharkiv/Lviv from OpenStreetMap.

Overpass API (public data, ODbL; generic User-Agent, no personal data), mirrors with exponential backoff.
Writes $UHD_DATA_DIR/places/<city>.geojson (FeatureCollection; properties: id, name, kind, city, osm_id,
admin_level/place, area_km2) and copies to uhd/backend/data/places/ when --repo-copy is given.
Idempotent: cached raw responses in places/raw/ are reused unless --force.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time

import shapely.geometry as sg
from shapely.ops import linemerge, polygonize, unary_union

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from uhd.science import data as D  # noqa: E402
from uhd.science.geometry import to_3035  # noqa: E402

log = logging.getLogger("precompute_places")
ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
UA = "uhd-hackathon-prototype/0.1"
CITY_OSM_NAME = {"kyiv": "Київ", "kharkiv": "Харків", "lviv": "Львів"}
SLUG = str.maketrans({"'": "", "ʼ": "", " ": "-"})
MIN_PRESET_KM2 = 0.5   # = the backend's min_area_km2 and science MIN_ZONE_KM2: smaller presets can never get a report
# adjacent OSM neighbourhoods too small on their own, merged into one meaningful preset: (city, slug, name, members)
MERGES = [("kyiv", "виноградар", "Виноградар (1-й і 2-й мікрорайони)",
           ("1-й мікрорайон Виноградаря", "2-й мікрорайон Виноградаря"))]


def overpass(q: str) -> dict:
    for attempt in range(8):
        url = ENDPOINTS[attempt % len(ENDPOINTS)]
        r = subprocess.run(["curl", "-s", "-A", UA, "--max-time", "300", "--data-urlencode", f"data={q}", url],
                           capture_output=True)
        try:
            return json.loads(r.stdout)
        except Exception:  # noqa: BLE001
            wait = 5 * 2 ** min(attempt, 4)
            log.warning("overpass %s failed (%s), retry in %ds", url, r.stdout[:80], wait)
            time.sleep(wait)
    raise RuntimeError("overpass failed")


def element_polygon(el: dict):
    if el["type"] == "way":
        g = el.get("geometry") or []
        if len(g) >= 4 and g[0] == g[-1]:
            return sg.Polygon([(p["lon"], p["lat"]) for p in g])
        return None
    outer, inner = [], []
    for m in el.get("members", []):
        if m.get("type") != "way" or "geometry" not in m:
            continue
        line = sg.LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
        (inner if m.get("role") == "inner" else outer).append(line)
    if not outer:
        return None
    polys = list(polygonize(linemerge(outer)))
    if not polys:
        return None
    g = unary_union(polys)
    if inner:
        holes = list(polygonize(linemerge(inner)))
        if holes:
            g = g.difference(unary_union(holes))
    return g if not g.is_empty else None


def fetch(city: str, raw_dir, force: bool) -> list[dict]:
    name = CITY_OSM_NAME[city]
    poly_ll = sg.shape(json.load(open(D.RAW / "aoi" / f"{city}.geojson"))["features"][0]["geometry"])
    w, s, e, n = poly_ll.bounds
    queries = {
        "districts": f'[out:json][timeout:240];area["boundary"="administrative"]["name"="{name}"]->.a;'
                     f'rel(area.a)["boundary"="administrative"]["admin_level"~"^(6|7|8|9|10)$"];out geom;',
        "localities": f'[out:json][timeout:240];(way["place"~"^(suburb|quarter|neighbourhood)$"]({s},{w},{n},{e});'
                      f'rel["place"~"^(suburb|quarter|neighbourhood)$"]({s},{w},{n},{e}););out geom;',
    }
    feats = []
    city_m = to_3035(poly_ll)
    for kind, q in queries.items():
        p = raw_dir / f"{city}_{kind}.json"
        if force or not p.exists():
            data = overpass(q)
            json.dump(data, open(p, "w"))
            time.sleep(3)
        data = json.load(open(p))
        for el in data.get("elements", []):
            tags = el.get("tags", {})
            nm = tags.get("name:uk") or tags.get("name")
            if not nm:
                continue
            g = element_polygon(el)
            if g is None or not g.is_valid:
                g = g.buffer(0) if g is not None else None
            if g is None or g.is_empty:
                continue
            gm = to_3035(g)
            if gm.area < 0.05e6 or gm.intersection(city_m).area < 0.5 * gm.area:
                continue
            k = "district" if kind == "districts" else "locality"
            if k == "district" and "район" not in nm.lower():
                continue
            feats.append(dict(type="Feature", geometry=sg.mapping(g.simplify(0.0002)), properties=dict(
                id=f"{city}-{nm.lower().translate(SLUG)}", name=nm, kind=k, city=city, osm_id=f"{el['type']}/{el['id']}",
                admin_level=tags.get("admin_level"), place=tags.get("place"), area_km2=round(gm.area / 1e6, 2))))
    for c, slug, new, members in MERGES:
        parts = [f for f in feats if c == city and f["properties"]["name"] in members]
        if c != city or len(parts) != len(members):
            continue
        g = unary_union([sg.shape(f["geometry"]) for f in parts]).buffer(0.0003).buffer(-0.0003)
        if g.geom_type != "Polygon":
            log.warning("merge %s is not one polygon, skipped", new)
            continue
        feats.append(dict(type="Feature", geometry=sg.mapping(g.simplify(0.0002)), properties=dict(
            id=f"{city}-{slug}", name=new, kind="locality", city=city,
            osm_id=",".join(f["properties"]["osm_id"] for f in parts), admin_level=None, place="neighbourhood",
            area_km2=round(to_3035(g).area / 1e6, 2))))
    feats = [f for f in feats if f["properties"]["area_km2"] >= MIN_PRESET_KM2]
    # de-duplicate by id (keep the larger polygon)
    best = {}
    for f in feats:
        i = f["properties"]["id"]
        if i not in best or f["properties"]["area_km2"] > best[i]["properties"]["area_km2"]:
            best[i] = f
    return sorted(best.values(), key=lambda f: (f["properties"]["kind"], f["properties"]["name"]))


def _analysable(f: dict) -> bool:
    from uhd import science as S

    try:
        r = S.analyze(f["geometry"], name=f["properties"]["name"])
    except S.ScienceError as e:
        log.warning("drop %s: %s", f["properties"]["id"], e)
        return False
    if r["gap_summary"]["mean"] is None:
        log.warning("drop %s: no gap in any year", f["properties"]["id"])
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cities", nargs="*", default=list(D.CITY_AOIS))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--repo-copy", default=None, help="directory to copy the geojson files to")
    ap.add_argument("--check", action="store_true", help="drop presets for which uhd.science.analyze() fails")
    a = ap.parse_args()
    out_dir = D.DATA / "places"
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (D.DATA / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(D.DATA / "logs" / "precompute_places.log"),
                                  logging.StreamHandler()])
    for c in a.cities:
        feats = fetch(c, raw_dir, a.force)
        if a.check:
            feats = [f for f in feats if _analysable(f)]
        p = out_dir / f"{c}.geojson"
        json.dump(dict(type="FeatureCollection", features=feats,
                       attribution="© OpenStreetMap contributors, ODbL 1.0"), open(p, "w"), ensure_ascii=False)
        log.info("[%s] %d districts, %d localities -> %s", c,
                 sum(f["properties"]["kind"] == "district" for f in feats),
                 sum(f["properties"]["kind"] == "locality" for f in feats), p)
        if a.repo_copy:
            os.makedirs(a.repo_copy, exist_ok=True)
            shutil.copy(p, os.path.join(a.repo_copy, f"{c}.geojson"))


if __name__ == "__main__":
    main()
