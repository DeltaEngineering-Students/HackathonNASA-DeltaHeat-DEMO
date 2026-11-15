#!/usr/bin/env python3
"""Temporarily occupied territory of Ukraine (PM 4b, QUESTIONS M1) for the «окупована територія» caveat and overlay.

Sources (see uhd/backend/data/places/README.md for terms and refresh steps):
* the official list — Наказ Мінрозвитку від 28.02.2025 № 376 «Про затвердження Переліку територій, на яких ведуться
  (велися) бойові дії або тимчасово окупованих Російською Федерацією», consolidated text (zakon.rada.gov.ua, z0380-25),
  annex tables (.docx) with one row per settlement: KATOTTH code, status, start and end date;
* OpenStreetMap hromada boundaries (admin_level=7, tag ``katotth``; ODbL), one Overpass query, cached;
* АР Крим and Севастополь: the oblast outlines from war_oblasts.geojson (every listed settlement is occupied).

A settlement is *currently occupied* if it has a row with status «Тимчасово окупована …» and no end date. A hromada is
drawn as occupied if >= 50 % of its listed settlements are and, when only part of them is (``partial``), its
administrative centre (KATOTTH settlement number 001) is among them — so Очаківська громада is not drawn for the three
occupied Кінбурн villages while Очаків itself is free.
This is a hromada-level outline (coarse by ~10 km at the front), labelled with the list's date, not a front line.

Writes uhd/backend/data/places/occupied.geojson (< 1 MB) and $UHD_DATA_DIR/places/occupied.geojson. Raw downloads are
cached in $UHD_DATA_DIR/places/raw/ and reused unless --force. Generic User-Agent, no personal data.
"""
from __future__ import annotations

import argparse
import collections
import json
import logging
import os
import re
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET

import shapely.geometry as sg
from shapely.ops import unary_union

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from uhd.science import data as D  # noqa: E402
from precompute_places import UA, element_polygon, overpass  # noqa: E402

log = logging.getLogger("precompute_occupied")
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..", "data", "places", "occupied.geojson")
WAR = os.path.join(HERE, "..", "data", "places", "war_oblasts.geojson")

SNAPSHOT_DATE = "2026-09-15"           # last amendment in the consolidated text (наказ № 1984 від 15.09.2026)
ORDER_URL = "https://zakon.rada.gov.ua/laws/show/z0380-25"
ANNEXES = ["https://zakon.rada.gov.ua/laws/file/text/141/f543637n58.docx",
           "https://zakon.rada.gov.ua/laws/file/text/141/f543637n59.docx",
           "https://zakon.rada.gov.ua/laws/file/text/141/f543637n63.docx"]
OCCUPIED = "Тимчасово окупована Російською Федерацією територія України"
MIN_SHARE = 0.5
WHOLE = {"UA01": "UA-43", "UA85": "UA-40"}   # KATOTTH prefix -> ISO code in war_oblasts.geojson (whole unit)
OBLAST_UK = {"UA01": "АР Крим", "UA85": "Севастополь", "UA14": "Донецька", "UA44": "Луганська",
             "UA23": "Запорізька", "UA65": "Херсонська", "UA63": "Харківська", "UA48": "Миколаївська"}
SOURCE_UK = "Перелік ТОТ (наказ Мінрозвитку № 376, ред. від 15.09.2026) + межі громад OpenStreetMap"
LICENCE = ("Перелік: офіційний документ, не є об’єктом авторського права (ст. 10 Закону України «Про авторське право "
           "і суміжні права» № 2811-IX); межі громад: © OpenStreetMap contributors, ODbL 1.0")
ATTRIBUTION = "Мінрозвитку України (наказ № 376 від 28.02.2025, zakon.rada.gov.ua); © OpenStreetMap contributors"
SIMPLIFY_DEG = 0.003                   # ~250 m
MAX_BYTES = 1_000_000
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_rows(path: str):
    """Table rows of a .docx as lists of cell texts (stdlib only)."""
    root = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    for tr in root.iter(_W + "tr"):
        cells = ["".join(t.text or "" for t in tc.iter(_W + "t")).strip() for tc in tr.findall(_W + "tc")]
        if len(cells) >= 8 and re.fullmatch(r"UA\d{17}", cells[4]):
            yield cells


def hromada_shares(rows) -> dict[str, tuple[int, int, bool]]:
    """KATOTTH hromada prefix (UA + oblast + raion + hromada = 9 chars) -> (currently occupied, listed settlements,
    centre occupied). The centre is settlement number 001 (characters 10–12 of the code)."""
    occ, listed = collections.defaultdict(set), collections.defaultdict(set)
    for r in rows:
        code, status, end = r[4], r[5], r[7]
        listed[code[:9]].add(code)
        if status == OCCUPIED and not end:
            occ[code[:9]].add(code)
    return {h: (len(occ[h]), len(listed[h]), any(c[9:12] == "001" for c in occ[h])) for h in occ}


def drawn(o: int, n: int, centre: bool) -> bool:
    return o >= MIN_SHARE * n and (o == n or centre)


def fetch(url: str, out: str) -> None:
    tmp = out + ".tmp"
    subprocess.run(["curl", "-sfL", "-A", UA, "--max-time", "120", "-o", tmp, url], check=True)
    os.replace(tmp, out)


def build(shares: dict, osm: dict, war: dict) -> dict:
    by_obl = collections.defaultdict(list)
    partial = collections.defaultdict(list)
    seen = set()
    for el in osm.get("elements", []):
        k = el.get("tags", {}).get("katotth", "")[:9]
        if k in seen or k not in shares or k[:4] in WHOLE:
            continue
        o, n, centre = shares[k]
        if not drawn(o, n, centre):
            continue
        g = element_polygon(el)
        if g is None:
            log.warning("no polygon for %s %s", k, el.get("tags", {}).get("name"))
            continue
        seen.add(k)
        by_obl[k[:4]].append(g)
        if o < n:
            partial[k[:4]].append(el.get("tags", {}).get("name:uk") or el.get("tags", {}).get("name"))
    missing = [k for k, v in shares.items() if drawn(*v) and k[:4] not in WHOLE and k not in seen]
    if missing:
        log.warning("%d occupied hromadas without an OSM boundary: %s", len(missing), missing[:20])
    feats = []
    for pre, iso in WHOLE.items():
        by_obl[pre] = [sg.shape(war[iso]["geometry"])]
    for pre in sorted(by_obl):
        g = unary_union(by_obl[pre]).buffer(0.0005).buffer(-0.0005).simplify(SIMPLIFY_DEG, preserve_topology=True)
        n_h = sum(1 for k, v in shares.items() if k[:4] == pre and drawn(*v))
        feats.append(dict(type="Feature", geometry=_round(sg.mapping(g)),
                          properties=dict(oblast=OBLAST_UK.get(pre, pre), katotth_prefix=pre, n_hromadas=n_h,
                                          partial_hromadas=sorted(p for p in partial[pre] if p),
                                          whole_unit=pre in WHOLE)))
    props = dict(source=SOURCE_UK, source_url=ORDER_URL, annexes=ANNEXES, snapshot_date=SNAPSHOT_DATE,
                 licence=LICENCE, attribution=ATTRIBUTION,
                 rule=f"hromada drawn if >= {int(MIN_SHARE * 100)} % of its listed settlements are currently occupied "
                      f"(status «{OCCUPIED}», no end date) and, if only partly, its centre (settlement 001) is; "
                      f"АР Крим and Севастополь whole",
                 label_uk=label_uk(), missing_osm=missing)
    return dict(type="FeatureCollection", properties=props, features=feats)


def label_uk(snapshot: str = SNAPSHOT_DATE) -> str:
    y, m, d = snapshot.split("-")
    return f"окуповано (станом на {d}.{m}.{y}, джерело: Мінрозвитку, наказ № 376)"


def _round(geom: dict, nd: int = 4) -> dict:
    def r(c):
        return [round(c[0], nd), round(c[1], nd)] if isinstance(c[0], float) else [r(x) for x in c]
    return dict(type=geom["type"], coordinates=r(geom["coordinates"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-download the annexes and re-query Overpass")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raw = D.DATA / "places" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    rows = []
    for url in ANNEXES:
        p = str(raw / ("tot_" + url.rsplit("/", 1)[1]))
        if a.force or not os.path.exists(p):
            fetch(url, p)
        rows += list(docx_rows(p))
    shares = hromada_shares(rows)
    log.info("%d rows, %d hromadas with occupied settlements", len(rows), len(shares))
    osm_p = raw / "occupied_hromadas.json"
    if a.force or not osm_p.exists():
        pres = sorted({k[2:4] for k in shares} - {w[2:] for w in WHOLE})
        q = (f'[out:json][timeout:900];area["ISO3166-1"="UA"][admin_level=2]->.u;'
             f'rel(area.u)["boundary"="administrative"]["admin_level"="7"]["katotth"~"^UA({"|".join(pres)})"];out geom;')
        js = overpass(q)
        if not js.get("elements"):
            raise SystemExit("Overpass returned no hromadas; not overwriting (oblast fallback: war_oblasts.geojson)")
        osm_p.write_text(json.dumps(js))
    osm = json.loads(osm_p.read_text())
    war = {f["properties"]["iso"]: f for f in json.load(open(WAR))["features"]}
    fc = build(shares, osm, war)
    txt = json.dumps(fc, ensure_ascii=False, separators=(",", ":"))
    if len(txt.encode()) > MAX_BYTES:
        raise SystemExit(f"occupied.geojson too large: {len(txt.encode())} bytes")
    for p in (REPO, str(D.DATA / "places" / "occupied.geojson")):
        tmp = p + ".tmp"
        with open(tmp, "w") as f:
            f.write(txt)
        os.replace(tmp, p)
    log.info("wrote %d features, %d bytes", len(fc["features"]), len(txt.encode()))


if __name__ == "__main__":
    main()
