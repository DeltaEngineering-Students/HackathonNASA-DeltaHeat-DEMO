#!/usr/bin/env python3
"""City and city-district boundaries from OpenStreetMap (Overpass API) for all cities in common.CITIES.

Fills the "Lviv districts missing" hole and gives district presets for the other big cities.
For each city: every boundary=administrative relation with admin_level 6..10 intersecting a 60x60 km box
around the centre, assembled into (multi)polygons, written as
  ROOT/osm/districts/<city>_all.geojson   all assembled relations (tags: name, name:uk, name:en, admin_level, osm id)
  ROOT/osm/districts/<city>.geojson       suggested set: "city" = smallest polygon containing the centre with area
                                          >= 20 km2 whose level has >= 2 sub-units inside it; "district" features = the
                                          deepest level whose units cover >= 80 % of the city (empty if none)
Polite: one query at a time, generic User-Agent, waits between queries. WGS84 (EPSG:4326).
"""
import os, sys, json, time, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

import pyproj
import shapely.geometry as sg
from shapely.ops import polygonize, unary_union, transform as stransform

OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
log = None
to_m = pyproj.Transformer.from_crs(4326, 3035, always_xy=True).transform


def overpass(q):
    for attempt in range(8):
        url = OVERPASS[attempt % len(OVERPASS)]
        r = subprocess.run(["curl", "-s", "-A", C.UA, "--max-time", "400", "--data-urlencode", f"data={q}", url],
                           capture_output=True)
        try:
            return json.loads(r.stdout)
        except Exception:  # noqa
            log.warning("overpass retry %d (%s)", attempt, r.stdout[:120])
            time.sleep(60 * (attempt + 1))
    raise RuntimeError("overpass failed")


def assemble(el):
    outer = [sg.LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
             for m in el.get("members", []) if m.get("type") == "way" and m.get("role") in ("outer", "") and "geometry" in m]
    inner = [sg.LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
             for m in el.get("members", []) if m.get("type") == "way" and m.get("role") == "inner" and "geometry" in m]
    polys = list(polygonize(unary_union(outer))) if outer else []
    if not polys:
        return None
    g = unary_union(polys)
    if inner:
        holes = list(polygonize(unary_union(inner)))
        if holes:
            g = g.difference(unary_union(holes))
    return g if g.is_valid and not g.is_empty else g.buffer(0)


def city(name, lon, lat):
    out_dir = f"{C.ROOT}/osm/districts"
    os.makedirs(out_dir, exist_ok=True)
    if os.path.exists(f"{out_dir}/{name}.geojson"):
        return
    d = 0.3
    s, w, n, e = lat - d, lon - d / 0.65, lat + d, lon + d / 0.65
    q = (f'[out:json][timeout:360];rel["boundary"="administrative"]["admin_level"~"^(6|7|8|9|10)$"]'
         f'({s},{w},{n},{e});out geom;')
    data = overpass(q)
    feats = []
    for el in data.get("elements", []):
        g = assemble(el)
        if g is None:
            continue
        t = el.get("tags", {})
        feats.append(dict(type="Feature", geometry=sg.mapping(g), properties=dict(
            osm_id=el["id"], name=t.get("name"), name_uk=t.get("name:uk"), name_en=t.get("name:en"),
            admin_level=int(t.get("admin_level", 0)), area_km2=round(stransform(to_m, g).area / 1e6, 2))))
    C.atomic_json(dict(type="FeatureCollection", features=feats), f"{out_dir}/{name}_all.geojson", ensure_ascii=False)
    pt = sg.Point(lon, lat)
    shapes = [(f, sg.shape(f["geometry"])) for f in feats]
    sel, best = [], None
    for f, g in sorted(shapes, key=lambda x: x[0]["properties"]["area_km2"]):
        if f["properties"]["area_km2"] < 20 or not g.contains(pt):
            continue
        subs = [(ff, gg) for ff, gg in shapes if ff["properties"]["admin_level"] > f["properties"]["admin_level"]
                and g.contains(gg.representative_point()) and ff["properties"]["area_km2"] < f["properties"]["area_km2"]]
        if len(subs) >= 2:
            best = (f, g, subs)
            break
    if best is None:
        cands = [(f, g) for f, g in shapes if g.contains(pt) and f["properties"]["area_km2"] >= 20]
        if cands:
            f, g = min(cands, key=lambda x: x[0]["properties"]["area_km2"])
            best = (f, g, [])
    if best:
        f, g, subs = best
        sel.append(dict(f, properties=dict(f["properties"], role="city")))
        by_lvl = {}
        for ff, gg in subs:
            by_lvl.setdefault(ff["properties"]["admin_level"], []).append((ff, gg))
        for lvl in sorted(by_lvl, reverse=True):
            cov = unary_union([gg for _, gg in by_lvl[lvl]]).intersection(g).area / g.area
            if cov >= 0.8 or lvl == min(by_lvl):
                sel += [dict(ff, properties=dict(ff["properties"], role="district", coverage=round(cov, 3)))
                        for ff, _ in by_lvl[lvl]]
                break
    C.atomic_json(dict(type="FeatureCollection", features=sel), f"{out_dir}/{name}.geojson", ensure_ascii=False)
    nd = sum(1 for x in sel if x["properties"]["role"] == "district")
    log.info("%s: %d boundaries, city=%s, %d districts", name, len(feats),
             sel[0]["properties"]["name"] if sel else None, nd)
    C.manifest_update(f"osm/districts/{name}", relations=len(feats), districts=nd,
                      city=sel[0]["properties"]["name"] if sel else None, crs="EPSG:4326")


def main():
    global log
    log = C.setup_log("osm_districts")
    order = ["lviv"] + [c for c in C.CITIES if c != "lviv"]
    for c in order:
        try:
            city(c, *C.CITIES[c])
        except Exception as e:  # noqa
            log.warning("%s failed: %s", c, e)
        time.sleep(20)
    log.info("OSM DISTRICTS DONE")


if __name__ == "__main__":
    main()
