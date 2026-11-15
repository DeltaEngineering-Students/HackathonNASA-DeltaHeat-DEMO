"""Tool registry for the AI analyst. Each tool calls the SAME service function as the REST API, so the site
and the chat cannot disagree on numbers. Schemas are JSON Schema (Anthropic ``input_schema``)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

import jsonschema
from shapely.geometry import shape

from uhd.errors import APIError, bad_request
from uhd.services import analysis, climate, places, reports, scenes, weather
from uhd.services.geometry import parse_geometry

log = logging.getLogger(__name__)
SERIES_VARS = ["zone_lst", "ref_lst", "gap", "ndvi", "ndbi", "built_share", "scenes", "valid_share", "method",
               "excluded"]
LAYERS = ["gap", "lst", "ndvi", "dndvi"]
METRICS = ["gap_last", "gap_mean", "slope_per_decade", "ndvi_slope_per_decade", "new_built_km2", "all"]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[..., Any]
    public: bool = True
    rest: str = ""  # the REST endpoint backed by the same function

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


_ZONE = {
    "report_id": {"type": "string", "pattern": "^[0-9a-f]{16}$", "description": "id of an existing report"},
    "place_id": {"type": "string", "description": "preset id (e.g. kyiv-pozniaky) or osm:R123 from search"},
}
_YEARS = {"type": "array", "items": {"type": "integer", "minimum": 2013, "maximum": 2025}, "minItems": 2, "maxItems": 2,
          "description": "[from, to]"}


def _zone_geom(report_id: str | None = None, place_id: str | None = None, geometry: dict | None = None):
    if report_id:
        return parse_geometry(reports.require(report_id)["params"]["geometry"])
    if place_id:
        return parse_geometry(places.get_place(place_id)["geometry"])
    if geometry:
        return parse_geometry(geometry)
    raise bad_request("missing_zone", "give report_id or place_id")


def _compact_report(rep: dict) -> dict:
    out = {k: v for k, v in rep.items() if k != "params"}
    p = rep.get("params") or {}
    g = shape(p["geometry"]) if p.get("geometry") else None
    out["params"] = {k: v for k, v in p.items() if k != "geometry"}
    if g is not None:
        out["params"]["bbox"] = [round(v, 5) for v in g.bounds]
        c = g.centroid
        out["params"]["centroid"] = [round(c.x, 5), round(c.y, 5)]
    return out


# ------------------------------------------------------------------ handlers
def t_list_reports(limit: int = 20) -> dict:
    return {"reports": reports.list_reports(limit)}


def t_get_report(report_id: str) -> dict:
    return _compact_report(analysis.stored_report(report_id))


def t_list_scenes(year: int | None = None, report_id: str | None = None, place_id: str | None = None,
                  summer_only: bool = True) -> dict:
    return scenes.list_scenes(_zone_geom(report_id, place_id), year=year, summer_only=summer_only)


def t_get_scene_stats(scene_id: str, report_id: str | None = None, place_id: str | None = None) -> dict:
    return scenes.scene_stats(scene_id, _zone_geom(report_id, place_id))


def t_zone_timeseries(report_id: str, variables: list[str] | None = None) -> dict:
    rep = reports.require(report_id)
    vs = list(variables or ["zone_lst", "ref_lst", "gap", "ndvi"])
    if "excluded" not in vs:  # always say why a year has no gap (SCI-06)
        vs.append("excluded")
    return {"report_id": report_id, "series": [{"year": s.get("year"), **{v: s.get(v) for v in vs}}
                                               for s in rep.get("series", [])]}


def t_land_change(report_id: str) -> dict:
    rep = reports.require(report_id)
    return {"report_id": report_id, "land_change": rep.get("land_change"), "ndvi_trend": rep.get("ndvi_trend"),
            "units": "km²"}


def _metric(rep: dict, metric: str) -> float | None:
    if metric == "gap_last":
        return (rep.get("gap_summary") or {}).get("last")
    if metric == "gap_mean":
        return (rep.get("gap_summary") or {}).get("mean")
    if metric == "slope_per_decade":
        return (rep.get("trend") or {}).get("slope_per_decade")
    if metric == "ndvi_slope_per_decade":
        return (rep.get("ndvi_trend") or {}).get("slope_per_decade")
    if metric == "new_built_km2":
        return (rep.get("land_change") or {}).get("new_built")
    raise bad_request("invalid_metric", f"metric must be one of {METRICS}")


def _r(x: Any, nd: int = 2) -> Any:
    return round(x, nd) if isinstance(x, float) else x


def _summary_rows(reps: list[dict], descending: bool = True) -> list[dict]:
    """One row per zone with every comparison criterion (one call instead of one per metric)."""
    rows = []
    for r in reps:
        gs, t, nt = r.get("gap_summary") or {}, r.get("trend") or {}, r.get("ndvi_trend") or {}
        lc, gg = r.get("land_change") or {}, r.get("green_gap") or {}
        series = r.get("series") or []
        last = next((x for x in reversed(series) if x.get("gap") is not None), {})
        rows.append({
            "name": (r.get("zone") or {}).get("name"), "report_id": r.get("report_id"),
            "place_id": (r.get("params") or {}).get("place_id"), "years": r.get("years"),
            "gap_mean": _r(gs.get("mean")), "gap_last": _r(gs.get("last")), "gap_last_year": last.get("year"),
            "gap_min": _r(gs.get("min")), "gap_max": _r(gs.get("max")),
            "trend_per_decade": _r(t.get("slope_per_decade")), "trend_p": _r(t.get("p"), 3),
            "trend_verdict": t.get("verdict"),
            "ndvi_trend_per_decade": _r(nt.get("slope_per_decade"), 3), "ndvi_verdict": nt.get("verdict"),
            "built_km2": _r(lc.get("always_built"), 3), "new_built_km2": _r(lc.get("new_built"), 3),
            "parks_gap_mean": _r(gg.get("mean")),
            "excluded_years": [x.get("year") for x in series if x.get("excluded")],
        })
    rows.sort(key=lambda x: (x["gap_mean"] is None, -(x["gap_mean"] or 0) if descending else (x["gap_mean"] or 0)))
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows


def t_rank_zones(metric: str, place_ids: list[str] | None = None, report_ids: list[str] | None = None,
                 years: list[int] | None = None, descending: bool = True) -> dict:
    reps = [reports.require(r) for r in (report_ids or [])]
    for pid in place_ids or []:
        p = places.get_place(pid)
        reps.append(analysis.analyze(p["geometry"], years, name=p["name"], place_id=pid))
    if not reps:
        raise bad_request("missing_zones", "give place_ids and/or report_ids")
    if metric == "all":
        return {"metric": "all", "sorted_by": "gap_mean", "zones": _summary_rows(reps, descending)}
    rows = []
    for r in reps:
        t = r.get("trend") or {}
        rows.append({"report_id": r["report_id"], "name": (r.get("zone") or {}).get("name"),
                     "value": _metric(r, metric), "verdict": t.get("verdict"), "p": t.get("p")})
    rows.sort(key=lambda x: (x["value"] is None, -(x["value"] or 0) if descending else (x["value"] or 0)))
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return {"metric": metric, "ranking": rows}


def _point(lat: float | None, lon: float | None, report_id: str | None, place_id: str | None) -> tuple[float, float]:
    if lat is not None and lon is not None:
        return lat, lon
    c = _zone_geom(report_id, place_id).centroid
    return round(c.y, 5), round(c.x, 5)


def t_climate_projection(lat: float | None = None, lon: float | None = None, report_id: str | None = None,
                         place_id: str | None = None) -> dict:
    return climate.projection(*_point(lat, lon, report_id, place_id))


def t_get_weather(date: str, lat: float | None = None, lon: float | None = None, report_id: str | None = None,
                  place_id: str | None = None) -> dict:
    la, lo = _point(lat, lon, report_id, place_id)
    out = weather.get_weather(date, la, lo)
    if out.get("available") is False:  # item 34: quota / upstream down — the answer goes on without weather
        out = {**out, "agent_note": "Weather is unavailable right now. Do not call get_weather again in this "
                                    "conversation. Answer from the other tools and add at most one short sentence "
                                    "that weather context is temporarily unavailable; no apology."}
    return out


def t_create_report(place_id: str | None = None, geometry: dict | None = None, years: list[int] | None = None,
                    name: str | None = None, report_id: str | None = None) -> dict:
    name = name[:120] if name else name
    if report_id and not geometry and not place_id:  # re-run an existing report (e.g. other years)
        old = reports.require(report_id)
        geometry = old["params"]["geometry"]
        place_id = (old.get("params") or {}).get("place_id")
        name = name or (old.get("zone") or {}).get("name")
    if place_id and not geometry:
        p = places.get_place(place_id)
        geometry, name = p["geometry"], name or p["name"]
    if not geometry:
        raise bad_request("missing_zone", "give place_id or geometry")
    rep = analysis.analyze(geometry, years, name=name, place_id=place_id)
    return {"report_id": rep["report_id"], "summary": reports.summary(rep), "trend": rep.get("trend"),
            "gap_summary": rep.get("gap_summary"), "caveats": rep.get("caveats")}


def _overview_doc() -> dict:
    import json as _json

    from uhd.services import overview

    got = overview.load()
    if got is None:
        raise APIError(503, "overview_not_built", "the overview is not built yet")
    return _json.loads(got[0])


# Oblast name stem (matches the start of our Ukrainian oblast name, lower case) → Latin / English / Russian aliases.
REGION_ALIASES: dict[str, list[str]] = {
    "вінниц": ["vinnytsia", "vinnitsa", "vinnytska", "винниц"],
    "волин": ["volyn", "volynska", "volinska", "волын"],
    "дніпропетров": ["dnipropetrovsk", "dnipropetrovska", "dnipro", "днепропетров"],
    "донецьк": ["donetsk", "donetska", "донецк"],
    "житомир": ["zhytomyr", "zhytomyrska", "житомир"],
    "закарпат": ["zakarpattia", "zakarpatska", "transcarpathia", "zakarpatye", "закарпат"],
    "запоріз": ["zaporizhzhia", "zaporizhia", "zaporozhye", "zaporizka", "запорож"],
    "івано-франків": ["ivano-frankivsk", "ivano-frankivska", "ivano frankivsk", "frankivsk", "ивано-франк"],
    "київська": ["kyiv oblast", "kyivska", "kiev oblast", "киевская"],
    "київ": ["kyiv", "kiev", "kyiv city", "киев"],
    "кіровоград": ["kirovohrad", "kirovohradska", "kropyvnytskyi", "кировоград"],
    "луганськ": ["luhansk", "luhanska", "lugansk", "луганск"],
    "львів": ["lviv", "lvivska", "lvov", "львов"],
    "миколаїв": ["mykolaiv", "mykolaivska", "nikolaev", "николаев"],
    "одес": ["odesa", "odessa", "odeska", "одесс"],
    "полтав": ["poltava", "poltavska", "полтав"],
    "рівнен": ["rivne", "rivnenska", "rovno", "ровен", "ровн"],
    "сум": ["sumy", "sumska", "сумск"],
    "тернопіл": ["ternopil", "ternopilska", "тернопол"],
    "харків": ["kharkiv", "kharkov", "kharkivska", "харьков"],
    "херсон": ["kherson", "khersonska", "херсон"],
    "хмельни": ["khmelnytskyi", "khmelnytskyy", "khmelnytska", "хмельниц"],
    "черкас": ["cherkasy", "cherkaska", "cherkassy", "черкасс"],
    "чернівец": ["chernivtsi", "chernivetska", "черновц"],
    "чернігів": ["chernihiv", "chernihivska", "chernigov", "чернигов"],
    "крим": ["crimea", "crimean", "krym", "autonomous republic of crimea", "ar krym", "республіка крим", "крым"],
    "севастопол": ["sevastopol", "sevastopil", "севастополь"],
}
CRIMEA_STEMS = ("крим", "севастопол")
_REGION_NOISE = ("oblast", "region", "province", "область", "обл.", "обл", "області", "регіон", "oblasti")


def _norm_region(x: str) -> str:
    x = x.lower().replace("’", "'").replace("ʼ", "'").strip()
    for w in _REGION_NOISE:
        x = x.replace(w, " ")
    return " ".join(x.replace(".", " ").split())


def resolve_region(q: str) -> list[str]:
    """Stems matching a user-given region name (Ukrainian, English, Latin transliteration, Russian)."""
    n = _norm_region(q)
    if not n:
        return []
    if n in ("kyiv", "kiev", "київ", "киев"):  # the city, unless «oblast» was said
        return ["київська"] if _norm_region(q) != q.lower().strip() else ["київ"]
    hits = [st for st, al in REGION_ALIASES.items()
            if n.startswith(st) or any(n == a or (len(n) >= 4 and (n in a or a in n)) for a in al)]
    if "київська" in hits and "київ" in hits:
        hits.remove("київ")
    if n == "крим" or "crimea" in n:
        return ["крим", "севастопол"]
    return hits[:2]


def _oblast_stem(oblast: str | None) -> str | None:
    o = (oblast or "").lower()
    if o.startswith("київська"):
        return "київська"
    for st in REGION_ALIASES:
        if st != "київська" and (o.startswith(st) or (st == "крим" and "крим" in o)):
            return st
    return None


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


LOW_COVERAGE = 3


def t_compare_regions(oblasts: list[str]) -> dict:
    d = _overview_doc()
    by_stem: dict[str, list[dict]] = {}
    for r in d.get("places", []):
        st = _oblast_stem(r.get("oblast"))
        if st:
            by_stem.setdefault(st, []).append(r)
    regions, unresolved = [], []
    seen: set[tuple] = set()
    for q in oblasts:
        stems = resolve_region(q)
        if not stems:
            unresolved.append(q)
            continue
        key = tuple(sorted(stems))
        if key in seen:
            continue
        seen.add(key)
        rows = [r for st in stems for r in by_stem.get(st, [])]
        label = "АР Крим (з Севастополем)" if set(stems) == set(CRIMEA_STEMS) else next(
            (r["oblast"] for r in rows if r.get("oblast")), stems[0])
        occupied = any(st in CRIMEA_STEMS for st in stems) or any(r.get("occupied") for r in rows)
        wars = sorted({(r.get("war_region") or {}).get("name") for r in rows if r.get("war_region")} - {None})
        ok = [r for r in rows if isinstance(r.get("gap_mean"), (int, float))]
        gaps = [r["gap_mean"] for r in ok]
        with_tr = [r for r in ok if (r.get("trend") or {}).get("verdict") not in (None, "insufficient_data")]
        sig = [r for r in with_tr if r["trend"]["verdict"] == "significant"]
        hot = sorted(ok, key=lambda r: -r["gap_mean"])[:3]
        reg: dict[str, Any] = {
            "query": q, "oblast": label, "n_places": len(rows), "places_covered": len(ok), "n_with_gap": len(ok),
            "gap_mean_median": _r(_median(gaps)) if gaps else None,
            "gap_mean_mean": _r(sum(gaps) / len(gaps)) if gaps else None,
            "n_trend_evaluated": len(with_tr), "n_significant_trend": len(sig),
            "share_significant_trend_pct": round(100 * len(sig) / len(with_tr)) if with_tr else None,
            "hottest_places": [{"name": r.get("name"), "place_id": r.get("place_id"), "gap_mean": _r(r["gap_mean"]),
                                "verdict": (r.get("trend") or {}).get("verdict"), "report_id": r.get("report_id")}
                               for r in hot],
            "occupied": occupied, "war_regions": wars,
        }
        if occupied or wars:
            reg["caveats"] = [{"code": "occupied" if occupied else "war_zone"}]
            reg["agent_note"] = ("Occupied / war region: say so in the answer and that 2022–2025 changes may be "
                                 "destruction; the data exist but are not comparable like peacetime data.")
        if rows and len(ok) < LOW_COVERAGE:
            reg["coverage_note"] = (f"Only {len(ok)} place(s) of this region are on our map: say so plainly "
                                    "(e.g. «on our map this oblast is represented by N place(s)») and do not present "
                                    "the figures as representative of the whole region.")
        if not rows:
            reg["agent_note"] = "No places of this region are in our overview; say so, give no numbers for it."
        regions.append(reg)
    return {"version": d.get("version"), "method_version": d.get("method_version"), "years": d.get("years"),
            "regions": regions, "unresolved": unresolved,
            "note": "aggregates over the places in our overview (districts / cities we analysed), NOT the whole "
                    "oblast; gap = surface, not air. Say how many places each figure covers."}


OVERVIEW_SORT = ["gap_mean", "gap_last", "slope_per_decade", "lst_mean"]


def t_get_overview(city: str | None = None, kind: str | None = None, sort_by: str = "gap_mean",
                   limit: int = 15) -> dict:
    d = _overview_doc()
    rows = []
    for r in d.get("places", []):
        if city and city != "all" and r.get("city") != city and not (r.get("kind") == "city" and
                                                                    r.get("place_id", "").endswith(city)):
            continue
        if kind and r.get("kind") != kind:
            continue
        gby = r.get("gap_by_year") or {}
        last = next(((int(y), v) for y, v in sorted(gby.items(), reverse=True) if v is not None), None)
        tr = r.get("trend") or {}
        rows.append({"place_id": r.get("place_id"), "name": r.get("name"), "kind": r.get("kind"),
                     "city": r.get("city"), "oblast": r.get("oblast"), "status": r.get("status"),
                     "gap_mean": r.get("gap_mean"), "gap_last": last[1] if last else None,
                     "gap_last_year": last[0] if last else None, "lst_mean": r.get("lst_mean"),
                     "slope_per_decade": tr.get("slope_per_decade"), "p": tr.get("p"), "verdict": tr.get("verdict"),
                     "occupied": bool(r.get("occupied")), "war_region": (r.get("war_region") or {}).get("name"),
                     "caveats": [{"code": c} for c in r.get("caveats") or [] if c in ("occupied", "war_zone")],
                     "report_id": r.get("report_id")})
    key = sort_by if sort_by in OVERVIEW_SORT else "gap_mean"
    rows.sort(key=lambda x: (x[key] is None, -(x[key] or 0)))
    rows = rows[: max(1, min(limit, 30))]
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return {"version": d.get("version"), "method_version": d.get("method_version"), "years": d.get("years"),
            "sorted_by": key, "n": len(rows), "places": rows,
            "note": "precomputed with the same code as POST /api/analyze {place_id}; gap = surface, not air"}


def t_search_places(query: str) -> dict:
    return places.search(query, limit=8)


def t_set_map_view(layer: str | None = None, year: int | None = None, place_ids: list[str] | None = None,
                   report_ids: list[str] | None = None, bbox: list[float] | None = None) -> dict:
    for r in report_ids or []:
        reports.require(r)
    for p in place_ids or []:
        places.get_place(p)
    view = {"layer": layer, "year": year, "place_ids": place_ids or [], "report_ids": report_ids or [], "bbox": bbox}
    return {"ok": True, "map_view": view}


def t_run_analysis(code: str, report_ids: list[str] | None = None) -> dict:
    from uhd.agent import sandbox

    return sandbox.run(code, [reports.require(r) for r in (report_ids or [])])


TOOLS: list[Tool] = [
    Tool("search_places", "Find preset zones (districts, demo zones, whole cities) or geocode a place name in Ukraine. "
         "Returns ids usable as place_id.", _obj({"query": {"type": "string", "minLength": 1}}, ["query"]),
         t_search_places, rest="GET /api/places"),
    Tool("list_reports", "List stored reports (most recent first) with their headline numbers and verdicts.",
         _obj({"limit": {"type": "integer", "minimum": 1, "maximum": 100}}), t_list_reports, public=False,
         rest="GET /api/reports (team)"),
    Tool("get_report", "Full stored report: per-year series, gap summary, trends with p-values and the backend verdict, "
         "land change, caveats, parameters and data version.", _obj({"report_id": _ZONE["report_id"]}, ["report_id"]),
         t_get_report, rest="GET /api/reports/{id}"),
    Tool("list_scenes", "Landsat 8 scenes over a zone (date, WRS path/row, cloud cover). Landsat passes every 8–16 days "
         "at ~10:30 local solar time.", _obj({**_ZONE, "year": {"type": "integer", "minimum": 2013, "maximum": 2025},
                                              "summer_only": {"type": "boolean"}}), t_list_scenes, rest="GET /api/scenes"),
    Tool("get_scene_stats", "Zone (and, when available, reference) surface temperature on one Landsat acquisition.",
         _obj({"scene_id": {"type": "string"}, **_ZONE}, ["scene_id"]), t_get_scene_stats,
         rest="GET /api/scenes/{scene_id}"),
    Tool("zone_timeseries", "Per-year values from a report (zone LST, reference LST, gap, NDVI, NDBI, built share, "
         "scene counts, valid share).", _obj({"report_id": _ZONE["report_id"], "variables": {
             "type": "array", "items": {"type": "string", "enum": SERIES_VARS}}}, ["report_id"]),
         t_zone_timeseries, rest="GET /api/reports/{id} → series"),
    Tool("land_change", "Land-cover change inside the zone (always built, new built, always green; km²) and the NDVI trend.",
         _obj({"report_id": _ZONE["report_id"]}, ["report_id"]), t_land_change, rest="GET /api/reports/{id} → land_change"),
    Tool("rank_zones", "Compare several zones (runs/reuses analyses; max 15 zones, e.g. all districts of a city in ONE "
         "call). metric=\"all\" returns every criterion per zone in one call (mean and last-summer gap, min/max, gap "
         "trend °C/decade with p and verdict, NDVI trend, built and new-built km², parks gap, excluded years, "
         "report_id) — use it for tables and multi-criteria comparisons instead of one call per metric.",
         _obj({"metric": {"type": "string", "enum": METRICS},
               "place_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 15},
               "report_ids": {"type": "array", "items": _ZONE["report_id"], "maxItems": 15},
               "years": _YEARS, "descending": {"type": "boolean"}}, ["metric"]), t_rank_zones,
         rest="POST /api/analyze × N"),
    Tool("climate_projection", "CMIP6 projected summer daily-max AIR temperature change at a location (NEX-GDDP-CMIP6, "
         "ssp245/ssp585, 2041–2060 and 2081–2100 vs 1995–2014, median of 12 models with the 10–90% range). "
         "Not surface temperature.",
         _obj({"lat": {"type": "number"}, "lon": {"type": "number"}, **_ZONE}), t_climate_projection,
         rest="GET /api/climate"),
    Tool("get_weather", "Reanalysis weather for a date and place (Open-Meteo/ERA5): daily max/min air temperature, rain "
         "on the preceding 3 days, wind, cloud, hourly values around the Landsat overpass.",
         _obj({"date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}, "lat": {"type": "number"},
               "lon": {"type": "number"}, **_ZONE}, ["date"]), t_get_weather, rest="GET /api/weather"),
    Tool("get_overview", "Precomputed headline numbers for every preset district / demo zone / city (same code as "
         "POST /api/analyze {place_id}): mean gap, last gap, gap trend per decade with p and the backend verdict, "
         "occupied / war flags, report_id. Use it for rankings across districts or cities instead of rank_zones.",
         _obj({"city": {"type": "string", "description": "preset city id (kyiv, kharkiv, lviv) or all"},
               "kind": {"type": "string", "enum": ["district", "demo_zone", "city"]},
               "sort_by": {"type": "string", "enum": OVERVIEW_SORT},
               "limit": {"type": "integer", "minimum": 1, "maximum": 30}}), t_get_overview, rest="GET /api/overview"),
    Tool("compare_regions", "Compare oblasts / regions (e.g. Crimea vs Rivne oblast) in ONE call from the precomputed "
         "overview: per region number of places covered, median and mean gap, the hottest places, how many places have "
         "a significant gap trend, occupied / war flags. Accepts Ukrainian, English or Latin names (\"Crimea\", "
         "\"rivnenska\", \"Rivne oblast\"). Covers only the places in our overview, not the whole oblast. Use it "
         "instead of search_places + rank_zones for region comparisons.",
         _obj({"oblasts": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 80},
                           "minItems": 1, "maxItems": 6}}, ["oblasts"]), t_compare_regions, rest="GET /api/overview"),
    Tool("create_report", "Run (or reuse) the analysis for a zone and store it as a reproducible report; returns its id "
         "and headline numbers. Give place_id (preset), or report_id to re-run an existing report (e.g. other years).",
         _obj({"place_id": _ZONE["place_id"], "report_id": _ZONE["report_id"], "geometry": {"type": "object"},
               "years": _YEARS, "name": {"type": "string", "maxLength": 120}}), t_create_report,
         rest="POST /api/analyze"),
    Tool("set_map_view", "Show something on the user's map: zones, a layer (gap/lst/ndvi/dndvi) and a year.",
         _obj({"layer": {"type": "string", "enum": LAYERS}, "year": {"type": "integer", "minimum": 2013, "maximum": 2025},
               "place_ids": {"type": "array", "items": {"type": "string"}},
               "report_ids": {"type": "array", "items": _ZONE["report_id"]},
               "bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}}),
         t_set_map_view, rest="(UI action)"),
    Tool("run_analysis", "Run a short Python snippet (numpy available) in a read-only sandbox without network for "
         "questions no other tool covers. Variables: REPORTS (list of the given reports), LANDSAT_DIR. Print results.",
         _obj({"code": {"type": "string", "maxLength": 20000},
               "report_ids": {"type": "array", "items": _ZONE["report_id"], "maxItems": 30}}, ["code"]),
         t_run_analysis, public=False, rest="(sandbox)"),
]
BY_NAME = {t.name: t for t in TOOLS}


def available_tools(team: bool, sandbox_enabled: bool) -> list[Tool]:
    out = []
    for t in TOOLS:
        if t.name == "run_analysis" and not (team and sandbox_enabled):
            continue
        if not t.public and not team:
            continue
        out.append(t)
    return out


def execute(name: str, args: Any, allowed: set[str] | frozenset[str] | None = None) -> tuple[Any, bool]:
    """Run a tool; returns (result, is_error). Inputs are validated against the schema first.

    ``allowed`` is the caller's tool set (``available_tools(team, …)``); a tool outside it is refused even if the model
    names it. ``None`` means "no restriction" and is only for internal callers (eval, tests)."""
    tool = BY_NAME.get(name)
    if tool is None:
        return {"error": "unknown_tool", "message": name}, True
    if allowed is not None and name not in allowed:
        return {"error": "tool_not_allowed", "message": name}, True
    try:
        jsonschema.validate(args, tool.input_schema)
    except jsonschema.ValidationError as e:
        return {"error": "invalid_input", "message": e.message}, True
    try:
        return tool.handler(**args), False
    except APIError as e:
        return e.body(), True
    except Exception as e:  # noqa: BLE001
        log.exception("tool failed", extra={"tool": name})
        return {"error": "tool_failed", "message": str(e)[:500]}, True
