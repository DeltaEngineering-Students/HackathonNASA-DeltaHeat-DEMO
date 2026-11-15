"""GeoJSON validation, normalisation, hashing and area (EPSG:3035 equal-area)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import shapely
from pyproj import Transformer
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
import numpy as np

from uhd.config import get_settings
from uhd.errors import bad_request
from uhd.proj import transformer

_TO_3035 = transformer(4326, 3035)  # pipeline-built: cheap in every new threadpool thread (uhd.proj)
_TO_4326 = transformer(3035, 4326)

# Coarse coverage box (Ukraine + 20 km buffer grid of the "ukraine" AOI), WGS84.
UKRAINE_BBOX = (21.8, 43.9, 40.5, 52.6)


def _xf(t: Transformer):
    def f(c: np.ndarray) -> np.ndarray:
        x, y = t.transform(c[:, 0], c[:, 1])
        return np.column_stack([x, y])
    return f


def to_3035(g):
    return shapely.transform(g, _xf(_TO_3035))


def to_4326(g):
    return shapely.transform(g, _xf(_TO_4326))


MAX_WRAP_DEPTH = 3  # FeatureCollection → Feature → geometry; deeper nesting is rejected, never recursed into


def _unwrap(geojson: Any) -> dict:
    for _ in range(MAX_WRAP_DEPTH + 1):
        if not isinstance(geojson, dict):
            raise bad_request("invalid_geometry", "Межі мають бути об’єктом GeoJSON.")
        t = geojson.get("type")
        if t == "FeatureCollection":
            feats = geojson.get("features") or []
            if not isinstance(feats, list) or len(feats) != 1:
                raise bad_request("invalid_geometry", "FeatureCollection має містити рівно одну ділянку.")
            geojson = feats[0]
        elif t == "Feature":
            geojson = geojson.get("geometry")
        else:
            return geojson
    raise bad_request("invalid_geometry", "GeoJSON вкладено надто глибоко.")


def _check_coordinates(coords: Any, max_n: int) -> None:
    """Coordinates must be nested lists of real numbers (RB-09: strings/bools were coerced by shapely)."""
    stack, n = [coords], 0
    while stack:
        c = stack.pop()
        if not isinstance(c, list):
            raise bad_request("invalid_geometry", "Координати мають бути списками чисел.")
        if c and not isinstance(c[0], list):  # a position
            if len(c) < 2 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in c):
                raise bad_request("invalid_geometry", "Кожна точка — це [довгота, широта] числами.")
            n += 1
            if n > max_n * 2:
                raise bad_request("too_many_vertices", f"Забагато вершин (максимум {max_n}).")
        else:
            stack.extend(c)


def parse_geometry(geojson: Any) -> Polygon | MultiPolygon:
    """Validate a WGS84 GeoJSON Polygon/MultiPolygon (Feature wrappers accepted) and return a valid shapely geometry."""
    s = get_settings()
    gj = _unwrap(geojson)
    if gj.get("type") not in ("Polygon", "MultiPolygon"):
        raise bad_request("invalid_geometry", "Потрібен полігон (Polygon або MultiPolygon).", {"type": gj.get("type")})
    _check_coordinates(gj.get("coordinates"), s.max_vertices)
    try:
        g = shape(gj)
    except Exception as e:  # noqa: BLE001
        # RB-15: a fixed text, never the raw Python error (e.g. an empty MultiPolygon part → "list index out of range")
        raise bad_request("invalid_geometry", "Не вдалося прочитати межі: кожна частина полігону має бути замкненим "
                          "кільцем щонайменше з 4 точок [довгота, широта].") from e
    if g.is_empty:
        raise bad_request("invalid_geometry", "Межі порожні.")
    for p in getattr(g, "geoms", [g]):  # RB-09: a hole equal to its outline is an empty zone, not the whole square
        shell = Polygon(p.exterior).area
        if shell > 0 and any(Polygon(h).area >= 0.99 * shell for h in p.interiors):
            raise bad_request("invalid_geometry", "Отвір у полігоні збігається з його контуром — ділянка порожня.")
    n = shapely.get_num_coordinates(g)
    if n > s.max_vertices:
        raise bad_request("too_many_vertices", f"Забагато вершин: {n} (максимум {s.max_vertices}).")
    minx, miny, maxx, maxy = g.bounds
    if not (-180 <= minx <= 180 and -90 <= miny <= 90 and -180 <= maxx <= 180 and -90 <= maxy <= 90):
        raise bad_request("invalid_geometry", "Координати мають бути довготою/широтою WGS84.")
    if not g.is_valid:
        g = shapely.make_valid(g)
        polys = [p for p in getattr(g, "geoms", [g]) if isinstance(p, (Polygon, MultiPolygon))]
        g = shapely.unary_union(polys) if polys else Polygon()
        if g.is_empty:
            raise bad_request("invalid_geometry", "Межі не утворюють коректний полігон.")
    bx = UKRAINE_BBOX
    if maxx < bx[0] or minx > bx[2] or maxy < bx[1] or miny > bx[3]:
        raise bad_request("outside_coverage", "Територія поза межами даних (лише Україна).")
    check_bbox(g)
    return g


def check_bbox(g) -> None:
    """Raster windows follow the bbox, not the area: two tiny squares 800 km apart would allocate GBs (REVIEW H1).
    Same limits as science (SCI-09): 150 km inside the city AOIs, 72 km elsewhere (the derived reference reads the bbox
    plus a 30–60 km ring), and a bbox budget."""
    from uhd.services import rasters  # lazy: rasters imports this module

    s = get_settings()
    x0, y0, x1, y1 = to_3035(g).bounds
    w, h = (x1 - x0) / 1000, (y1 - y0) / 1000
    try:
        city = rasters.pick_aoi(g) in rasters.CITY_AOIS
    except Exception:  # noqa: BLE001 — no grids (tests without data): use the city limit
        city = True
    side = s.max_bbox_side_km if city else s.max_bbox_side_km_derived
    if w * h > s.max_bbox_km2 or max(w, h) > side:
        raise bad_request("bbox_too_large",
                          f"Територія надто розкидана: її межі займають {w:.0f} × {h:.0f} км (максимум {side:.0f} км "
                          f"по стороні{'' if city else ' поза Києвом, Харковом і Львовом'}). Оберіть компактнішу ділянку.",
                          {"bbox_km": [round(w, 1), round(h, 1)], "max_side_km": side,
                           "max_bbox_km2": s.max_bbox_km2})


def _uk(v: float, nd: int) -> str:
    return f"{v:.{nd}f}".replace(".", ",")


def area_km2(g) -> float:
    return to_3035(g).area / 1e6


def check_area(g) -> float:
    s = get_settings()
    a = area_km2(g)
    if a < s.min_area_km2:
        raise bad_request("area_too_small", f"Територія замала: {_uk(a, 2)} км² (мінімум {_uk(s.min_area_km2, 1)} км²).",
                          {"area_km2": round(a, 4), "min_km2": s.min_area_km2})
    if a > s.max_area_km2:
        raise bad_request("area_too_large", f"Територія завелика: {a:.0f} км² (максимум {s.max_area_km2:.0f} км²). Оберіть місто або район.",
                          {"area_km2": round(a, 1), "max_km2": s.max_area_km2})
    return a


def normalize(g) -> Polygon | MultiPolygon:
    """Canonical form for hashing: oriented rings, coordinates rounded to ~0.1 m."""
    g = shapely.set_precision(g, 1e-6)
    g = shapely.normalize(shapely.geometry.polygon.orient(g) if isinstance(g, Polygon) else g)
    return g


def geometry_hash(g) -> str:
    wkb = shapely.to_wkb(normalize(g), hex=True, output_dimension=2)
    return hashlib.sha256(wkb.encode()).hexdigest()[:16]


def to_geojson(g) -> dict:
    return json.loads(json.dumps(mapping(g)))


def circle(lon: float, lat: float, radius_km: float) -> Polygon:
    """Geodesically-correct-enough circle (built in EPSG:3035)."""
    x, y = _TO_3035.transform(lon, lat)
    return to_4326(shapely.Point(x, y).buffer(radius_km * 1000, quad_segs=16))
