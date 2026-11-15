"""Zone geometry: GeoJSON (WGS84) -> EPSG:3035 shape -> pixel mask on an AOI grid."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import numpy as np
from shapely.ops import unary_union
import shapely.geometry as sg
from pyproj import Transformer
from rasterio.features import geometry_mask
import shapely

from uhd.proj import transformer

from . import data as D

_TO_M = transformer(4326, 3035)  # same operation as from_crs, cheap in every new API thread (uhd.proj)
_TO_LL = transformer(3035, 4326)


def _apply(t: Transformer, g):
    return shapely.transform(g, lambda xy: np.column_stack(t.transform(xy[:, 0], xy[:, 1])))
MAX_AREA_KM2 = 5000.0
MAX_SIDE_PX = 2500             # 150 km: bbox side of any zone (multi-part zones far apart are refused)
MAX_SIDE_PX_DERIVED = 1200     # 72 km: zones outside preset cities (derived reference reads bbox + 30–60 km)
MAX_BBOX_PX = 4_000_000        # bbox pixel budget (~14 400 km²)


class ScienceError(Exception):
    """Input problem the API should map to HTTP 422."""

    def __init__(self, code: str, message_uk: str):
        super().__init__(f"{code}: {message_uk}")
        self.code = code
        self.message_uk = message_uk


def to_shape(geometry: dict):
    if not isinstance(geometry, dict):
        raise ScienceError("bad_geometry", "Геометрія має бути об'єктом GeoJSON.")
    if geometry.get("type") == "Feature":
        geometry = geometry.get("geometry") or {}
    if geometry.get("type") == "FeatureCollection":
        geoms = [sg.shape(f["geometry"]) for f in geometry.get("features", [])]
        g = sg.MultiPolygon([p for x in geoms for p in getattr(x, "geoms", [x])])
    else:
        try:
            g = sg.shape(geometry)
        except Exception as e:  # noqa: BLE001
            raise ScienceError("bad_geometry", "Не вдалося прочитати геометрію GeoJSON.") from e
    if g.geom_type not in ("Polygon", "MultiPolygon"):
        raise ScienceError("bad_geometry", "Потрібен полігон (Polygon або MultiPolygon).")
    if not g.is_valid:
        g = g.buffer(0)
    if g.is_empty:
        raise ScienceError("bad_geometry", "Порожній полігон.")
    return g


def to_3035(g_ll):
    return _apply(_TO_M, g_ll)


def to_wgs84(g_m):
    return _apply(_TO_LL, g_m)


def geometry_hash(geometry: dict, years=None) -> str:
    g = to_shape(geometry)
    s = json.dumps([sg.mapping(g.normalize()), list(years) if years else None], sort_keys=True, default=str)
    return hashlib.sha1(s.encode()).hexdigest()[:16]


@dataclass
class Zone:
    shape_ll: object
    shape_m: object
    aoi: str           # grid used for pixels
    win: D.Win         # window on that grid (tight bbox + 1 px)
    mask: np.ndarray   # bool (h, w), True inside the zone
    suburb: bool = False  # outside the preset city's boundary but within its 15 km ring
    clipped_km2: float = 0.0  # area cut off because it lies outside Ukraine's border (or at sea)
    war_region: dict | None = None  # occupied / front-line region the zone lies in (SCI-03), see data.war_region
    occupied: dict | None = None    # most of the zone in occupied territory (PM 4b), see data.occupied

    @property
    def area_km2(self) -> float:
        return self.shape_m.area / 1e6

    @property
    def n_px(self) -> int:
        return int(self.mask.sum())


def rasterize(shape_m, aoi: str, win: D.Win | None = None) -> tuple[D.Win, np.ndarray]:
    g = D.grid(aoi)
    if win is None:
        win = g.window_for_bounds(*shape_m.bounds, pad=1)
    r0, c0, h, w = win
    m = ~geometry_mask([sg.mapping(shape_m)], out_shape=(h, w), transform=g.window_transform(win), invert=False)
    if not m.any():  # tiny polygon: take touched pixels
        m = ~geometry_mask([sg.mapping(shape_m)], out_shape=(h, w), transform=g.window_transform(win),
                           all_touched=True)
    return win, m


SUBURB_KM = 15.0


def city_of(shape_m) -> tuple[str | None, bool]:
    """(preset city, is_suburb). Inside: the admin boundary contains the zone's representative point or > 50 % of
    it. Suburb: the representative point is within 15 km of the boundary (the city's own reference ring) — such
    zones (Гатне, Бровари, Ірпінь …) use the city's reference so they can be compared with the city's districts."""
    pt = shape_m.representative_point()
    for c in D.CITY_AOIS:
        poly = D.aoi_polygon_3035(c)
        if poly.contains(pt) or poly.intersection(shape_m).area > 0.5 * shape_m.area:
            return c, False
    for c in D.CITY_AOIS:
        if D.aoi_polygon_3035(c).distance(pt) <= SUBURB_KM * 1000:
            return c, True
    return None, False


def make_zone(geometry: dict) -> tuple[Zone, str | None]:
    g_ll = to_shape(geometry)
    g_m = to_3035(g_ll)
    if g_m.area / 1e6 > MAX_AREA_KM2:
        raise ScienceError("too_large", f"Територія завелика (> {MAX_AREA_KM2:.0f} км²). Оберіть місто або район.")
    clipped_km2 = 0.0
    ua = D.aoi_polygon_3035("ukraine")
    if not ua.contains(g_m):
        inter = g_m.intersection(ua)
        inter = unary_union([p for p in getattr(inter, "geoms", [inter]) if p.geom_type in ("Polygon", "MultiPolygon")]) \
            if not inter.is_empty else inter
        if inter.is_empty or inter.area < 1e4:
            raise ScienceError("outside_coverage", "Територія поза межами даних (лише Україна).")
        cut = (g_m.area - inter.area) / 1e6
        if cut > 0.01 * g_m.area / 1e6:  # ignore sliver differences along the border line
            clipped_km2, g_m = cut, inter
            g_ll = to_wgs84(g_m)
    city, suburb = city_of(g_m)
    aoi = "ukraine"
    if city is not None:
        win = D.grid(city).window_for_bounds(*g_m.bounds, pad=1)
        if D.grid(city).contains_window(win):
            aoi = city
        else:
            city = None
    ug = D.grid("ukraine")
    if aoi == "ukraine":
        win = ug.window_for_bounds(*g_m.bounds, pad=1)
        if not ug.contains_window(win) or not D.aoi_polygon_3035("ukraine").buffer(5000).intersects(g_m):
            raise ScienceError("outside_coverage", "Територія поза межами даних (лише Україна).")
    _check_budget(win, aoi)
    win, mask = rasterize(g_m, aoi)
    return Zone(g_ll, g_m, aoi, win, mask, suburb=suburb and city is not None, clipped_km2=clipped_km2,
                war_region=D.war_region(g_m), occupied=D.occupied(g_m)), city


def _check_budget(win: D.Win, aoi: str) -> None:
    """Refuse zones whose bounding box would make us allocate huge rasters (e.g. two small squares 800 km apart)."""
    _, _, h, w = win
    side = MAX_SIDE_PX if aoi in D.CITY_AOIS else MAX_SIDE_PX_DERIVED
    if h > side or w > side or h * w > MAX_BBOX_PX:
        raise ScienceError("too_large", f"Територія надто розкидана: її межі займають {w * D.RES / 1000:.0f} × "
                                        f"{h * D.RES / 1000:.0f} км (максимум {side * D.RES / 1000:.0f} км). "
                                        "Аналізуйте частини окремо.")
