#!/usr/bin/env python3
"""Boundaries of the regions occupied or on the front line since 2014/2022 (for the `war_zone` caveat, QA SCI-03).

No offline front-line dataset is available, so we use whole first-level units (OSM admin_level=4, ISO 3166-2):
АР Крим (UA-43) and Севастополь (UA-40), occupied since 2014; Донецька (UA-14) and Луганська (UA-09), partly
occupied since 2014 and front line since 2022; Запорізька (UA-23) and Херсонська (UA-65), partly occupied since 2022.
This is coarse on purpose: the caveat says "the region", never "this place is occupied".

Overpass API (public data, ODbL; generic User-Agent, no personal data). Writes a simplified (~200 m) copy to
uhd/backend/data/places/war_oblasts.geojson (read at runtime) and $UHD_DATA_DIR/places/war_oblasts.geojson.
Idempotent: the raw response in $UHD_DATA_DIR/places/raw/ is reused unless --force.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

import shapely.geometry as sg
from shapely.ops import unary_union

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from uhd.science import data as D  # noqa: E402
from precompute_places import element_polygon, overpass  # noqa: E402

log = logging.getLogger("precompute_war_areas")
REGIONS = {  # ISO 3166-2 -> (name, since)
    "UA-43": ("Автономна Республіка Крим", 2014), "UA-40": ("Севастополь", 2014),
    "UA-14": ("Донецька область", 2014), "UA-09": ("Луганська область", 2014),
    "UA-23": ("Запорізька область", 2022), "UA-65": ("Херсонська область", 2022),
}
REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "places", "war_oblasts.geojson")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raw = D.DATA / "places" / "raw" / "war_oblasts.json"
    raw.parent.mkdir(parents=True, exist_ok=True)
    if a.force or not raw.exists():
        codes = "|".join(c.split("-")[1] for c in REGIONS)
        q = f'[out:json][timeout:600];rel["boundary"="administrative"]["ISO3166-2"~"^UA-({codes})$"];out geom;'
        js = overpass(q)
        raw.write_text(json.dumps(js))
    js = json.loads(raw.read_text())
    feats, seen = [], set()
    for el in js.get("elements", []):
        code = el.get("tags", {}).get("ISO3166-2")
        if code not in REGIONS or code in seen:
            continue
        g = element_polygon(el)
        if g is None:
            log.warning("no polygon for %s", code)
            continue
        seen.add(code)
        g = unary_union([g]).simplify(0.002, preserve_topology=True)
        name, since = REGIONS[code]
        feats.append(dict(type="Feature", geometry=sg.mapping(g),
                          properties=dict(iso=code, name=name, since=since, osm_id=el["id"])))
        log.info("%s %s: %.0f km² (approx)", code, name, g.area * 111 * 72)
    missing = set(REGIONS) - seen
    if missing:
        raise SystemExit(f"missing regions: {sorted(missing)}")
    fc = json.dumps(dict(type="FeatureCollection", features=feats), ensure_ascii=False)
    for p in (REPO, D.DATA / "places" / "war_oblasts.geojson"):
        with open(p, "w") as f:
            f.write(fc)
    log.info("wrote %d regions", len(feats))


if __name__ == "__main__":
    main()
