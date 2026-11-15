"""Report context that makes a «not significant» card still say something (frontend card v2):

* ``context.rank`` — the zone's mean gap ranked among its city's preset districts (computed at response time from
  the stored district reports; the per-city table is cached in memory and on disk, keyed by method version);
* ``context.climate`` — CMIP6 ssp245 air-temperature change at the zone centre (the nearest available period);
* ``hotspots`` — up to 3 hottest clusters inside the zone from the mean per-pixel gap of the last 3 summers with data
  (60 m, smoothed σ≈300 m, peaks ≥ 500 m apart). Geometry-only → stored with the (name-free) report.

    python -m uhd.services.context        # precompute the district tables (deploy), prints them
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from functools import lru_cache
from typing import Any

import numpy as np
from rasterio import features
from scipy import ndimage

from uhd.config import get_settings
from uhd.errors import APIError
from uhd.services import places, rasters, science
from uhd.services.num import rnd
from uhd.services.geometry import parse_geometry, to_3035, to_4326

log = logging.getLogger(__name__)
RANK_KIND = "district"
RANK_TABLE_SCHEMA = "t2"  # rows carry basis + analysed area
RANK_SMALL_RATIO = 0.25  # zone's analysed built-up area < 25 % of the smallest district's → «not like-for-like» note
_CITY_GEN = {"kyiv": "Києва", "kharkiv": "Харкова", "lviv": "Львова"}
HOTSPOTS_VERSION = "hs4"  # hs4: search inside the zone clipped at Ukraine's border (24/28) + zone_outline; stored with
#                            the report; a report with another version is recomputed (hotspots only, never its numbers)
CLIP_MIN_SHARE = 0.01     # same rule as science make_zone: a cut ≤ 1 % of the zone (border slivers) is ignored
HOTSPOT_YEARS = 3
HOTSPOT_MIN_SEP_M = 500.0
HOTSPOT_MAX = 3
HOTSPOT_TOP_SHARE = 0.10      # candidates: built pixels in the zone's top 10 % of the smoothed 3-summer mean gap
HOTSPOT_MIN_DELTA_C = 1.0     # a hotspot must be ≥ 1 °C hotter than the zone's built-up mean (same years, same raster)
HOTSPOT_MIN_PX = 3
HOTSPOT_LARGE_KM2 = 30.0      # zones above this (districts, cities) use the district scale
# (sigma m, cap km²): local scale — σ 120 m (2 px, ≈ the 100 m thermal footprint), ≤ 0.25 km² and ≤ 10 % of the zone;
# district scale — σ 300 m, ≤ 1 km²
HOTSPOT_SCALES = {"local": (120.0, 0.25), "district": (300.0, 1.0)}
HOTSPOT_MAX_PX = 4_000_000    # skip (null) for windows bigger than this (≈14 400 km²)
_tables: dict[tuple[str, str], dict] = {}
_tables_lock = threading.Lock()
_building: set[str] = set()


# ------------------------------------------------------------------ rank among the city's districts

def _table_path(city: str):
    mv = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{science.data_version()}_{science.method_version()}_{RANK_TABLE_SCHEMA}")
    return get_settings().cache_dir / "rank" / mv / f"{city}.json"


def _districts(city: str) -> list[dict]:
    return sorted((p for p in places.presets().values() if p["kind"] == RANK_KIND and p.get("city") == city),
                  key=lambda p: p["id"])


def build_table(city: str) -> dict:
    """Mean gap of every preset district of ``city`` (stored reports; computed once if missing)."""
    from uhd.services import analysis

    rows = []
    for p in _districts(city):
        try:
            rep = analysis.analyze(p["geometry"], None, name=p["name"], place_id=p["id"], enrich=False)
        except APIError as e:
            log.warning("rank: district failed", extra={"place_id": p["id"], "err": e.code})
            continue
        m = (rep.get("gap_summary") or {}).get("mean")
        z = rep.get("zone") or {}
        if m is not None:
            rows.append({"place_id": p["id"], "name": p["name"], "gap_mean": m, "basis": z.get("basis"),
                         "analysed_area_km2": z.get("analysed_area_km2")})
    t = {"city": city, "method_version": science.method_version(), "data_version": science.data_version(),
         "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "districts": rows}
    path = _table_path(city)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(t, ensure_ascii=False))
        os.replace(tmp, path)
    except OSError:
        pass
    return t


def table(city: str, build_if_missing: bool = True) -> dict | None:
    key = (city, science.method_version(), RANK_TABLE_SCHEMA)
    t = _tables.get(key)
    if t is not None:
        return t
    try:
        t = json.loads(_table_path(city).read_text())
    except (FileNotFoundError, ValueError):
        t = None
    if t is None and build_if_missing:
        # never make a visitor wait for ~10 district computations: build in the background, rank appears next time
        with _tables_lock:
            if city not in _building:
                _building.add(city)
                threading.Thread(target=_build_bg, args=(city,), daemon=True, name=f"rank-{city}").start()
        return None
    if t is not None:
        _tables[key] = t
    return t


def _build_bg(city: str) -> None:
    try:
        _tables[(city, science.method_version(), RANK_TABLE_SCHEMA)] = build_table(city)
    except Exception:  # noqa: BLE001
        log.exception("rank table build failed", extra={"city": city})
    finally:
        _building.discard(city)


def rank(rep: dict, place_id: str | None) -> dict | None:
    city = (rep.get("zone") or {}).get("city") or (rep.get("reference") or {}).get("city")
    if city not in rasters.CITY_AOIS:
        return None
    if place_id and (places.presets().get(place_id) or {}).get("kind") == "city":
        return None  # a whole city is not ranked against its own districts
    mean = (rep.get("gap_summary") or {}).get("mean")
    if not city or mean is None or (rep.get("zone") or {}).get("analysed") == "all_land":
        return None
    t = table(city)
    if not t:
        return None
    basis = (rep.get("zone") or {}).get("basis")
    # like-for-like: the same basis (always_built: built-up pixels only, vs the same city reference) for zone and districts
    rows = [d for d in t["districts"] if d.get("basis") == basis]
    if len(rows) < 3:
        return None
    if place_id not in {d["place_id"] for d in rows}:
        place_id = _same_district(rep, city) or place_id  # R4-2: a drawn/shared copy of a district is that district
    others = [d for d in rows if d["place_id"] != place_id]
    is_district = len(others) < len(rows)
    n = len(others) + 1  # the zone itself is one of the compared areas
    hotter = sum(1 for d in others if d["gap_mean"] > mean)
    cooler = sum(1 for d in others if d["gap_mean"] < mean)
    za = (rep.get("zone") or {}).get("analysed_area_km2")
    areas = [d["analysed_area_km2"] for d in rows if d.get("analysed_area_km2")]
    small = bool(za and areas and za < RANK_SMALL_RATIO * min(areas))
    nd = len(others)
    what = "забудовою" if basis == "always_built" else "територією"
    text = f"порівняно із {what} {nd} {_districts_word(nd)} {_CITY_GEN.get(city, city)}"
    return {"rank": hotter + 1, "of": n, "percentile": round(100 * cooler / (n - 1)) if n > 1 else None,
            "city": city, "metric": "gap_mean", "compared_with": "districts", "is_district": is_district,
            "basis": basis, "compared_to_uk": text,
            "district_gap_range": [min(d["gap_mean"] for d in rows), max(d["gap_mean"] for d in rows)],
            "district_extremes": {"hottest": _ext(max(rows, key=lambda d: d["gap_mean"])),
                                  "coolest": _ext(min(rows, key=lambda d: d["gap_mean"]))},
            "zone_analysed_km2": za, "district_analysed_km2_range": [min(areas), max(areas)] if areas else None,
            "like_for_like": not small,
            "note_uk": (f"Ділянка невелика ({_km2(za)} км² забудови), а в районах — {_km2(min(areas))}–{_km2(max(areas))} км²: "
                        "щільний квартал зазвичай гарячіший за середнє по цілому району.") if small else None}


def _ext(d: dict) -> dict:
    return {"id": d["place_id"], "name": d["name"], "short_name": d["name"].split(" (")[0], "gap": d["gap_mean"]}


DISTRICT_IOU = 0.98


@lru_cache(maxsize=8)
def _district_shapes(city: str) -> tuple:
    from uhd.services.geometry import area_km2

    out = []
    for p in _districts(city):
        g = parse_geometry(p["geometry"])
        out.append((p["id"], g, area_km2(g)))
    return tuple(out)


def _same_district(rep: dict, city: str) -> str | None:
    """Preset district whose boundary equals the zone's (IoU ≥ 0.98), for a geometry sent without place_id."""
    try:
        from uhd.services.geometry import area_km2

        g = parse_geometry(rep["params"]["geometry"])
        a = area_km2(g)
        for pid, dg, da in _district_shapes(city):
            if not (0.97 * da <= a <= da / 0.97) or not g.intersects(dg):
                continue  # IoU ≥ 0.98 needs areas within ~2 % — skip the polygon maths otherwise
            u = g.union(dg).area
            if u > 0 and g.intersection(dg).area / u >= DISTRICT_IOU:
                return pid
    except Exception:  # noqa: BLE001 — optional
        log.exception("district match failed")
    return None


def _districts_word(n: int) -> str:
    # genitive after «із … »: 1 району, 2+ районів (21 району)
    return "району" if n % 10 == 1 and n % 100 != 11 else "районів"


def _km2(v: float) -> str:
    return (f"{rnd(v, 1):.1f}" if v < 10 else f"{rnd(v, 0):.0f}").replace(".", ",")


# ------------------------------------------------------------------ CMIP6 at the zone centre

def climate(rep: dict) -> dict | None:
    try:
        g = parse_geometry(rep["params"]["geometry"])
        c = g.representative_point()
        from uhd.services import climate as cl

        pr = cl.projection(round(c.y, 3), round(c.x, 3))
    except Exception:  # noqa: BLE001 — optional context
        return None
    sc = pr.get("ssp245") or {}
    if not sc:
        return None
    period = sorted(sc)[0]  # the nearest future period in the subset (2041–2060, CMIP6 v2)
    p = sc[period]
    return {"scenario": "ssp245", "period": period, "variable": pr.get("variable", "tasmax"), "unit": "°C",
            "delta": p.get("delta"), "delta_range": p.get("delta_range"),
            "baseline_period": (pr.get("baseline") or {}).get("period"),
            "note_uk": "Прогноз приземної температури повітря (на висоті 2 м; CMIP6, комірка сітки ≈25 км), а не поверхні. "
                       "Медіана 12 моделей, діапазон 10–90 %; 20-річні вікна, база 1995–2014.",
            "source": f"/api/climate?lat={round(c.y, 4)}&lon={round(c.x, 4)}"}


# ------------------------------------------------------------------ hotspots

_CLASS_UK = {"built": "забудова", "field": "поле", "nature": "зелень", "water": "вода", "other": "голий ґрунт / інше",
             "none": "немає даних"}


def _classes(aoi: str, win: tuple[int, int, int, int], years: list[int]) -> np.ndarray | None:
    """(len(years), h, w) uint8 land classes (science: Esri LULC + spectral extrapolation), None without science."""
    if science.module().__name__ != "uhd.science":
        return None
    from uhd.science import classes as SC, data as D

    cls = SC.classes_window(aoi, win)
    return np.stack([cls[D.YEARS.index(y)] for y in years])


def _class_names() -> dict[int, str]:
    try:
        from uhd.science.classes import CLASS_NAMES

        return CLASS_NAMES
    except ImportError:
        return {0: "none", 1: "built", 2: "field", 3: "nature", 4: "water", 5: "other"}


@lru_cache(maxsize=1)
def _ukraine_3035():
    """Ukraine outline (the one science clips zones with: {landsat_dir}/aoi/Ukraine.geojson) in EPSG:3035, prepared."""
    from shapely.geometry import shape as _shape
    from shapely.ops import unary_union
    from shapely.prepared import prep

    p = get_settings().landsat_dir / "aoi" / "Ukraine.geojson"
    try:
        fc = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    feats = fc.get("features") if fc.get("type") == "FeatureCollection" else [fc]
    g = to_3035(unary_union([_shape(f.get("geometry", f)) for f in feats]))
    return g, prep(g)


def clipped_zone(g):
    """(geometry WGS84, clipped?) — the zone as the analysis sees it: cut at Ukraine's border when > 1 % lies
    outside (science make_zone), else unchanged."""
    from shapely.ops import unary_union

    ua = _ukraine_3035()
    if ua is None:
        return g, False
    full, prepared = ua
    g3 = to_3035(g)
    if prepared.contains(g3):
        return g, False
    inter = g3.intersection(full)
    inter = unary_union([p for p in getattr(inter, "geoms", [inter]) if p.geom_type in ("Polygon", "MultiPolygon")]) \
        if not inter.is_empty else inter
    if inter.is_empty or (g3.area - inter.area) <= CLIP_MIN_SHARE * g3.area:
        return g, False
    return to_4326(inter), True


def zone_outline(rep: dict) -> dict | None:
    """GeoJSON (WGS84, ~1 m) of the analysed zone when it was cut at the border; null = draw params.geometry."""
    g, clipped = clipped_zone(parse_geometry(rep["params"]["geometry"]))
    if not clipped:
        return None
    gj = json.loads(json.dumps(g.__geo_interface__))
    gj["coordinates"] = _round_coords(gj["coordinates"])
    return gj


def hotspots(rep: dict) -> list[dict] | None:
    """Compact hot places inside the zone (v2, after the user's «а шо це за точки»): built pixels in the top 10 % of the
    zone's smoothed 3-summer mean gap → connected clusters, capped in size around their peak, ≥ 1 °C above the zone's
    built-up mean; marker at the cluster's hottest smoothed pixel inside the zone (≥ 1 px from its edge).
    The zone is the analysed one: cut at Ukraine's border like the report (24/28), so nothing lands abroad."""
    g, _ = clipped_zone(parse_geometry(rep["params"]["geometry"]))
    aoi = rasters.pick_aoi(g)
    gr = rasters.grid(aoi) if aoi else None
    if not gr:
        return None
    have = set(rasters.years(aoi))
    years = [s["year"] for s in rep.get("series") or [] if s.get("gap") is not None and s["year"] in have]
    years = years[-HOTSPOT_YEARS:]
    if not years:
        return []
    res = gr["res"]
    g3 = to_3035(g)
    zone_km2 = g3.area / 1e6
    scale = "district" if zone_km2 > HOTSPOT_LARGE_KM2 else "local"
    sigma_m, cap_km2 = HOTSPOT_SCALES[scale]
    x0, y0, x1, y1 = g3.bounds
    c0, r0 = int((x0 - gr["x0"]) // res), int((gr["y1"] - y1) // res)
    c1, r1 = int((x1 - gr["x0"]) // res) + 1, int((gr["y1"] - y0) // res) + 1
    pad = int(3 * sigma_m / res) + 1
    r0, c0, r1, c1 = r0 - pad, c0 - pad, r1 + pad, c1 + pad
    h, w = r1 - r0, c1 - c0
    if h * w > HOTSPOT_MAX_PX:
        return None
    from rasterio.transform import Affine
    from shapely.geometry import Point, shape as _shape
    from shapely.ops import unary_union
    from uhd.tiles import pyramid

    stack = [pyramid.read_window(aoi, "gap", y, r0, c0, h, w) for y in years]
    import warnings

    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN pixels → NaN, expected
        mean = np.nanmean(np.stack(stack), axis=0) if len(stack) > 1 else stack[0]
    T = Affine(res, 0, gr["x0"] + c0 * res, 0, -res, gr["y1"] - r0 * res)
    inside = features.rasterize([(g3, 1)], out_shape=(h, w), transform=T, fill=0, dtype="uint8").astype(bool)
    if not inside.any():  # zone smaller than a pixel centre
        inside = features.rasterize([(g3, 1)], out_shape=(h, w), transform=T, fill=0, dtype="uint8",
                                    all_touched=True).astype(bool)
    try:
        cls = _classes(aoi, (r0, c0, h, w), years)
    except Exception:  # noqa: BLE001 — classes are optional (no maps for this aoi, …)
        log.exception("hotspots: classes failed")
        cls = None
    built = (cls == 1).any(0) if cls is not None else np.ones((h, w), bool)
    ok = np.isfinite(mean) & inside & built
    if ok.sum() < HOTSPOT_MIN_PX:
        return []
    sig = sigma_m / res
    val = np.where(ok, mean, 0.0)
    num = ndimage.gaussian_filter(val, sig, mode="constant")
    den = ndimage.gaussian_filter(ok.astype(np.float64), sig, mode="constant")
    with np.errstate(all="ignore"):
        sm = np.where(ok & (den > 0.05), num / den, np.nan)
    zone_mean = float(np.nanmean(mean[ok]))
    thr = float(np.nanpercentile(sm[np.isfinite(sm)], 100 * (1 - HOTSPOT_TOP_SHARE)))
    hot = np.isfinite(sm) & (sm >= max(thr, zone_mean + HOTSPOT_MIN_DELTA_C))  # top 10 % AND distinctly hotter
    cap_px = max(HOTSPOT_MIN_PX, int(min(cap_km2, HOTSPOT_TOP_SHARE * ok.sum() * (res / 1000) ** 2 if scale == "local"
                                         else cap_km2) / (res / 1000) ** 2))
    interior = ndimage.binary_erosion(inside, np.ones((3, 3), bool))
    lab, n = ndimage.label(hot, np.ones((3, 3), bool))
    cands = []
    for k in range(1, n + 1):
        comp = lab == k
        if comp.sum() > cap_px:  # keep the cap_px hottest pixels of the component, connected to its peak
            v = np.where(comp, sm, -np.inf)
            kth = np.partition(v[comp], -cap_px)[-cap_px]
            sub, _ = ndimage.label(comp & (sm >= kth), np.ones((3, 3), bool))
            pk = np.unravel_index(int(np.argmax(v)), v.shape)
            comp = sub == sub[pk]
        if comp.sum() < HOTSPOT_MIN_PX:
            continue
        gap = float(np.nanmean(mean[comp]))
        if gap - zone_mean < HOTSPOT_MIN_DELTA_C:
            continue
        sel = comp & interior if (comp & interior).any() else comp
        pk = np.unravel_index(int(np.nanargmax(np.where(sel, sm, np.nan))), sm.shape)
        cands.append((gap, comp, pk))
    cands.sort(key=lambda t: -t[0])
    names = _class_names()
    out: list[dict] = []
    picked: list[tuple[int, int]] = []
    sep_px = HOTSPOT_MIN_SEP_M / res
    for gap, comp, (r, c) in cands:
        if any((r - a) ** 2 + (c - b) ** 2 < sep_px ** 2 for a, b in picked):
            continue
        picked.append((r, c))
        px, py = gr["x0"] + (c0 + c + 0.5) * res, gr["y1"] - (r0 + r + 0.5) * res
        p = to_4326(Point(px, py))
        poly = unary_union([_shape(sh) for sh, v in features.shapes(comp.astype(np.uint8), mask=comp, transform=T)
                            if v == 1]).simplify(res / 2).intersection(g3)  # clip AFTER simplifying (QA R6)
        if poly.geom_type == "GeometryCollection":
            poly = unary_union([p_ for p_ in poly.geoms if p_.geom_type in ("Polygon", "MultiPolygon")])
        pg = to_4326(poly).intersection(g)  # and again in WGS84 against the zone as drawn (no reprojection slack)
        if pg.geom_type == "GeometryCollection":
            pg = unary_union([p_ for p_ in pg.geoms if p_.geom_type in ("Polygon", "MultiPolygon")])
        pj = json.loads(json.dumps(pg.__geo_interface__))
        pj["coordinates"] = _round_coords(pj["coordinates"])
        land = None
        if cls is not None:
            cc = cls[:, comp].ravel()
            vals, cnt = np.unique(cc, return_counts=True)
            top = int(vals[np.argmax(cnt)])
            land = {"class": names.get(top, "other"), "label_uk": _CLASS_UK.get(names.get(top, "other"), "інше"),
                    "share": rnd(float(cnt.max()) / cc.size, 2), "source": "Esri/IO LULC (+ Landsat extrapolation)"}
        out.append({"lon": rnd(p.x, 5), "lat": rnd(p.y, 5), "gap": rnd(gap, 1),
                    "gap_peak_px": rnd(np.nanmax(mean[comp]), 1), "delta_vs_zone": rnd(gap - zone_mean, 1),
                    "zone_built_mean_gap": rnd(zone_mean, 1), "area_km2": rnd(float(comp.sum()) * (res / 1000) ** 2, 3),
                    "land_class": land, "years": years, "scale": scale, "polygon": pj})
        if len(out) >= HOTSPOT_MAX:
            break
    return out


def _round_coords(c):
    if c and isinstance(c[0], (int, float)):
        return [rnd(c[0], 5), rnd(c[1], 5)]
    return [_round_coords(x) for x in c]


# ------------------------------------------------------------------ CLI (deploy)

def main() -> None:
    from uhd.logging_setup import setup_logging

    setup_logging("INFO", True)
    for city in rasters.CITY_AOIS:
        if _districts(city):
            t = build_table(city)
            print(city, len(t["districts"]), [(d["place_id"], d["gap_mean"]) for d in t["districts"]])
    precompute_hotspots()


def precompute_hotspots() -> None:
    """Store hotspots with every preset report at deploy, so no visitor pays the cold computation (~0.5 s)."""
    from uhd.services import analysis

    t0, n = time.time(), 0
    for p in sorted(places.presets().values(), key=lambda p: p["id"]):
        try:
            rep = analysis.analyze(p["geometry"], None, name=p["name"], place_id=p["id"])
            n += rep.get("hotspots") is not None
        except APIError as e:
            log.warning("hotspots: preset failed", extra={"place_id": p["id"], "err": e.code})
    print("hotspots stored for", n, "presets in", round(time.time() - t0, 1), "s")


if __name__ == "__main__":
    main()
