"""Country-level map data (MAP-TASKS.md, «API contract»): ``/api/overview`` (one result per city / district for the
markers below z9) and ``/api/overlays`` (Ukraine outline, war regions, no-LST mask).

The overview is precomputed at deploy with the same code and data as ``POST /api/analyze {place_id}`` (so a marker
equals the card headline) and served from memory; the overlays are small static geometry built on first request.

    python -m uhd.services.overview --build [--jobs 4]      # writes {data_dir}/overview.json
    python -m uhd.services.overview --print-overlays         # writes nothing; prints sizes
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from shapely.geometry import mapping, shape

from uhd.config import get_settings
from uhd.errors import APIError
from uhd.services import places, rasters, science
from uhd.services.geometry import parse_geometry
from uhd.services.num import rnd

log = logging.getLogger(__name__)

# label priority (1 = most important): cities by population (2021 estimates, order only)
CITY_ORDER = ["Київ", "Харків", "Одеса", "Дніпро", "Донецьк", "Запоріжжя", "Львів", "Кривий Ріг", "Миколаїв",
              "Маріуполь", "Луганськ", "Севастополь", "Вінниця", "Сімферополь", "Херсон", "Полтава", "Чернігів",
              "Черкаси", "Хмельницький", "Чернівці", "Житомир", "Суми", "Рівне", "Івано-Франківськ", "Кам’янське",
              "Кропивницький", "Тернопіль", "Луцьк", "Біла Церква", "Краматорськ", "Мелітополь", "Ужгород",
              "Бровари", "Нікополь", "Слов’янськ", "Бердянськ", "Павлоград", "Ірпінь", "Умань", "Буча"]
AOI_OBLAST = {"kyiv": "Київ", "kharkiv": "Харківська область", "lviv": "Львівська область"}
REASON_UK = {
    "no_lst": "немає супутникової температури поверхні (прогалина в продукті USGS)",
    "no_data": "немає даних про температуру поверхні за ці роки",
    "insufficient_data": "замало літніх сезонів із даними, щоб оцінити тренд",
    "error": "не вдалося порахувати",
}
NO_LST_FILE = "overlays/no_lst.geojson"
NO_SCENES_FILE = "overlays/no_scenes.geojson"  # science: per-year swaths without enough clear scenes (2022 …)  # under data_dir; written by science (scripts/precompute_*)


def _path() -> Path:
    return get_settings().data_dir / "overview.json"


# ------------------------------------------------------------------ build

def _targets() -> list[dict]:
    pre = places.presets()
    out = [p for p in pre.values() if p["kind"] == "city" and p["id"] in rasters.CITY_AOIS]
    out += list(places.city_shortcuts().values())
    out += sorted((p for p in pre.values() if p["kind"] == "district" and p.get("city") in rasters.CITY_AOIS),
                  key=lambda p: p["id"])
    return out


def _clean_name(p: dict) -> str:
    return p["name"].removeprefix("Увесь ").strip()


def _rank(p: dict, area: float) -> int:
    if p["kind"] == "city":
        n = _clean_name(p)
        return CITY_ORDER.index(n) + 1 if n in CITY_ORDER else len(CITY_ORDER) + 1
    return 100 + int(1000 / max(area, 1))  # districts after every city; bigger first


def _get_place(pid: str) -> dict:
    for attempt in range(20):  # osm cities: the boundary comes from Nominatim (1 req/s across processes, cached)
        try:
            return places.get_place(pid)
        except APIError as e:
            if e.code != "geocoder_busy" or attempt == 19:
                raise
            time.sleep(1.5)
    raise AssertionError("unreachable")


def place_entry(p: dict) -> dict:
    """One overview row; numbers from the same ``analysis.analyze`` call as POST /api/analyze {place_id}."""
    from uhd.services import analysis

    base: dict[str, Any] = {"place_id": p["id"], "name": _clean_name(p) if p["kind"] == "city" else p["name"],
                            "kind": p["kind"], "city": p.get("city"), "oblast": p.get("oblast")}
    if p.get("city") in AOI_OBLAST and not base["oblast"]:
        base["oblast"] = AOI_OBLAST[p["city"]]
    if p["kind"] == "city" and not base["oblast"]:  # cities with special status (Севастополь)
        base["oblast"] = base["name"]
    try:
        full = _get_place(p["id"])
        g = parse_geometry(full["geometry"])
        lp = g.representative_point()
        base.update(lon=round(lp.x, 4), lat=round(lp.y, 4), bbox=[round(v, 4) for v in g.bounds],
                    rank=_rank(p, full.get("area_km2") or 0))
        rep = analysis.analyze(full["geometry"], None, name=full["name"], place_id=full["id"], enrich=False)
    except Exception as e:  # noqa: BLE001 — one failing place never breaks the overview
        log.warning("overview: place failed", extra={"place_id": p["id"], "err": getattr(e, "code", str(e))})
        base.setdefault("rank", _rank(p, 0))
        return {**base, "lon": base.get("lon", (p.get("center") or [None, None])[0]),
                "lat": base.get("lat", (p.get("center") or [None, None])[1]), "bbox": base.get("bbox", p.get("bbox")),
                "status": "error", "gap_mean": None, "gap_by_year": {}, "lst_mean": None, "lst_last": None, "trend": None, "method": None, "caveats": [],
                "war_region": None, "occupied": None, "reason_uk": REASON_UK["error"]}
    gs = rep.get("gap_summary") or {}
    tr = rep.get("trend") or {}
    codes = [c.get("code") for c in rep.get("caveats") or []]
    mean = gs.get("mean")
    if mean is None:
        status, reason = "no_data", REASON_UK["no_lst" if "no_lst_product" in codes else "no_data"]
    elif tr.get("verdict") in (None, "insufficient_data"):
        status, reason = "insufficient_data", REASON_UK["insufficient_data"]
    else:
        status, reason = "ok", None
    trend = None
    if status == "ok":
        trend = {"slope_per_decade": tr.get("slope_per_decade"), "p": tr.get("p"), "verdict": tr.get("verdict")}
    # item 21 H: the zone's own summer surface temperature (°C) for the marker tooltip «сама поверхня ≈ 36 °C»:
    # mean of zone_lst over the years that have a gap (the same years as gap_mean), and the latest such year
    lst = [(s["year"], s["zone_lst"]) for s in rep.get("series") or []
           if s.get("gap") is not None and s.get("zone_lst") is not None]
    lst_mean = rnd(sum(v for _, v in lst) / len(lst), 1) if lst else None
    lst_last = {"year": lst[-1][0], "value": rnd(lst[-1][1], 1)} if lst else None
    return {**base, "status": status, "gap_mean": mean, "lst_mean": lst_mean, "lst_last": lst_last,
            "gap_by_year": {str(s["year"]): s.get("gap") for s in rep.get("series") or []},
            "trend": trend, "method": rep.get("method"), "caveats": codes,
            "war_region": (rep.get("zone") or {}).get("war_region"),
            "occupied": (rep.get("zone") or {}).get("occupied"), "reason_uk": reason,
            "report_id": rep.get("report_id")}


def build(jobs: int = 4) -> dict:
    from uhd.services import analysis

    t0 = time.time()
    targets = _targets()
    with ThreadPoolExecutor(max_workers=max(1, min(jobs, 4))) as ex:
        rows = list(ex.map(place_entry, targets))
    rows.sort(key=lambda r: (r["rank"], r["name"]))
    out = {"version": science.data_version(), "method_version": science.method_version(),
           "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "years": list(analysis.YEARS),
           "places": rows}
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    os.replace(tmp, path)
    log.info("overview built", extra={"places": len(rows), "s": round(time.time() - t0, 1),
                                      "bytes": path.stat().st_size})
    return out


# ------------------------------------------------------------------ serve

_cache: dict[str, Any] = {}
_lock = threading.Lock()


def load() -> tuple[bytes, str] | None:
    """(body, etag) of the stored overview, re-read when the file changes; None when not built yet."""
    p = _path()
    try:
        st = p.stat()
    except FileNotFoundError:
        return None
    key = (str(p), st.st_mtime_ns, st.st_size)
    with _lock:
        if _cache.get("ov_key") != key:
            body = p.read_bytes()
            d = json.loads(body)
            _cache["ov_key"] = key
            _cache["ov"] = (body, f'"{d.get("version")}|{d.get("method_version")}|{d.get("generated_at")}"')
        return _cache["ov"]


def _simplify(g, tol: float):
    s = g.simplify(tol, preserve_topology=True)
    return s if not s.is_empty else g


def _round(c, nd=4):
    if c and isinstance(c[0], (int, float)):
        return [round(c[0], nd), round(c[1], nd)]
    return [_round(x, nd) for x in c]


def _geo(g) -> dict:
    m = mapping(g)
    return {"type": m["type"], "coordinates": _round(json.loads(json.dumps(m["coordinates"])))}


def _war_text(name: str, since: int) -> str:
    try:
        from uhd.science.report import CAVEATS_UK

        return CAVEATS_UK["war_zone"].format(since=since, region=name)
    except Exception:  # noqa: BLE001
        return f"Територія в регіоні, де з {since} р. тривають окупація або бойові дії ({name})."


def build_overlays() -> dict:
    s = get_settings()
    ukraine = None
    up = s.landsat_dir / "aoi" / "Ukraine.geojson"
    try:
        fc = json.loads(up.read_text())
        geoms = [shape(f["geometry"]) for f in fc.get("features", [])] if fc.get("type") == "FeatureCollection" \
            else [shape(fc.get("geometry", fc))]
        from shapely.ops import unary_union

        g = _simplify(unary_union(geoms), 0.005)
        ukraine = {"bbox": [round(v, 4) for v in g.bounds], "geometry": _geo(g)}
    except (OSError, ValueError, KeyError) as e:
        log.warning("overlays: no Ukraine outline", extra={"err": str(e)})
    war = {"type": "FeatureCollection", "features": []}
    wp = places.REPO_PLACES / "war_oblasts.geojson"
    try:
        for f in json.loads(wp.read_text())["features"]:
            pr = f["properties"]
            war["features"].append({"type": "Feature", "properties": {
                "name": pr["name"], "since": int(pr["since"]), "text_uk": _war_text(pr["name"], int(pr["since"]))},
                "geometry": _geo(_simplify(shape(f["geometry"]), 0.005))})
    except (OSError, ValueError, KeyError) as e:
        log.warning("overlays: no war regions", extra={"err": str(e)})
    occ = {"type": "FeatureCollection", "properties": None, "features": []}
    try:  # PM 4b: official occupied list (science, sci-v3.5); war_regions stays «зона бойових дій»
        d = json.loads((places.REPO_PLACES / "occupied.geojson").read_text())
        pr = d.get("properties") or {}
        occ["properties"] = {k: pr.get(k) for k in
                             ("label_uk", "attribution", "source", "source_url", "snapshot_date", "licence")}
        for f in d["features"]:
            fp = f.get("properties") or {}
            occ["features"].append({"type": "Feature", "properties": {
                "oblast": fp.get("oblast"), "whole_unit": bool(fp.get("whole_unit")), "label_uk": pr.get("label_uk")},
                "geometry": _geo(_simplify(shape(f["geometry"]), 0.005))})
    except (OSError, ValueError, KeyError) as e:
        log.warning("overlays: no occupied list", extra={"err": str(e)})
    no_lst = _science_fc(s.data_dir / NO_LST_FILE, "no_lst")
    no_scenes = _science_fc(s.data_dir / NO_SCENES_FILE, "no_scenes")
    return {"version": science.data_version(), "ukraine": ukraine, "war_regions": war, "occupied": occ,
            "no_lst": no_lst, "no_scenes": no_scenes}


def _science_fc(path: Path, what: str) -> dict:
    """A science-written FeatureCollection served as-is (already simplified by science); empty until it exists."""
    try:
        d = json.loads(path.read_text())
        if d.get("type") == "FeatureCollection":
            return d
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        log.warning("overlays: bad science file", extra={"what": what, "err": str(e)})
    return {"type": "FeatureCollection", "features": []}


def _file_key(p: Path):
    try:
        st = p.stat()
        return (st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
        return None


def overlays() -> tuple[bytes, str]:
    """Built once per worker; rebuilt when a science overlay file (no-LST, no-scenes) appears or changes."""
    dd = get_settings().data_dir
    key = (_file_key(dd / NO_LST_FILE), _file_key(dd / NO_SCENES_FILE))
    with _lock:
        if _cache.get("ol_key", "∅") != key or "ol" not in _cache:
            d = build_overlays()
            body = json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode()
            import hashlib

            _cache["ol"] = (body, '"%s"' % hashlib.sha256(body).hexdigest()[:16])
            _cache["ol_key"] = key
        return _cache["ol"]


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def main() -> None:
    from uhd.logging_setup import setup_logging

    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--print-overlays", action="store_true")
    a = ap.parse_args()
    setup_logging("INFO", True)
    if a.build:
        d = build(a.jobs)
        st: dict[str, int] = {}
        for r in d["places"]:
            st[r["status"]] = st.get(r["status"], 0) + 1
        print("overview:", len(d["places"]), "places", st, _path(), _path().stat().st_size, "bytes")
    if a.print_overlays:
        body, _ = overlays()
        d = json.loads(body)
        print("overlays:", len(body), "bytes; war", len(d["war_regions"]["features"]), "occupied",
              len(d["occupied"]["features"]), "no_scenes", len(d["no_scenes"]["features"]), "no_lst",
              len(d["no_lst"]["features"]), "ukraine", bool(d["ukraine"]))


if __name__ == "__main__":
    main()
