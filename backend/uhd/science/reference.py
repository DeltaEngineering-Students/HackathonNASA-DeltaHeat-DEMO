"""Reference ("nature around the city") and in-city green masks.

Preset cities (Kyiv, Kharkiv, Lviv): urban area = OSM admin boundary (/srv/landsat/aoi/<city>.geojson).
Any other place (Ukraine grid): urban area = the connected built-up patch(es) touching the zone, from the
2021 class map closed with a 300 m dilation (so blocks separated by streets/parks merge) — see METHOD.md §4.
Reference = stable forest (classes.stable_forest) in the ring 2–15 km outside the urban area, inside Ukraine
(sci-v3.6: the ring is clipped to the state border before the minimum-forest check, INVESTIGATION-FOREIGN-REFERENCE).
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
from scipy import ndimage

from . import classes as C
from . import data as D
from ._lru import LRU
from .geometry import Zone, rasterize, to_wgs84

RING_KM = (2.0, 15.0)
RING_KM_WIDE = (2.0, 30.0)
MIN_REF_PX = 500           # 1.8 km² of forest
URBAN_CLOSE_PX = 5         # 300 m
URBAN_MIN_PX = 28          # ~0.1 km²: smaller built patches are villages/noise -> urban area = zone itself
CLASS_YEAR_FOR_URBAN = 2021
MARGINS_PX = (500, 1000)   # 30 km, 60 km around the zone bbox
BORDER_NOTE_SHARE = 0.10   # caveat ref_border_clipped when ≥ 10 % of the ring forest lies abroad


@dataclass
class Reference:
    city: str                    # preset id or "derived"
    name_uk: str
    kind: str                    # preset | derived
    aoi: str
    win: D.Win                   # window on the aoi grid the masks refer to
    ref: np.ndarray              # bool reference forest pixels
    green: np.ndarray            # bool urban parks: stable-nature patches ≤ 5 km² inside the urban area
    urban: np.ndarray            # bool urban area
    ring_km: tuple[float, float] = RING_KM
    key: str = ""                # cache key (city id or hash of the derived reference)
    notes: list[str] = field(default_factory=list)
    elev_band: tuple[int, int] | None = None   # sci-v3.6: forest restricted to this elevation band (elevmatch)
    abroad_px: int = 0           # sci-v3.6: ring forest px dropped because they lie outside Ukraine

    @property
    def nbytes(self) -> int:
        return int(self.ref.nbytes + self.green.nbytes + self.urban.nbytes)

    @property
    def forest_px(self) -> int:
        return int(self.ref.sum())

    def info(self, with_geometry: bool = False) -> dict:
        out = dict(city=self.city, name_uk=self.name_uk, kind=self.kind, ring_km=list(self.ring_km),
                   area_km2=round(self.forest_px * D.PX_KM2, 1), forest_px=self.forest_px,
                   urban_area_km2=round(float(self.urban.sum()) * D.PX_KM2, 1), notes=list(self.notes))
        if with_geometry:
            out["ring_geometry"] = mask_to_geojson(self.ref, self.aoi, self.win, simplify_m=300)
        return out


def mask_to_geojson(mask: np.ndarray, aoi: str, win: D.Win, simplify_m: float = 120) -> dict:
    import shapely.geometry as sg
    from rasterio.features import shapes
    from shapely.ops import unary_union

    T = D.grid(aoi).window_transform(win)
    # coarsen to 4x4 px blocks to keep polygons small
    polys = [sg.shape(s) for s, v in shapes(mask.astype(np.uint8), mask=mask, transform=T) if v == 1]
    if not polys:
        return sg.mapping(sg.GeometryCollection())
    g = unary_union(polys).buffer(simplify_m / 2).buffer(-simplify_m / 2).simplify(simplify_m / 2)
    return sg.mapping(to_wgs84(g))


def ring_mask(urban: np.ndarray, ring_km=RING_KM) -> np.ndarray:
    d = ndimage.distance_transform_edt(~urban) * D.RES / 1000.0
    return (d > ring_km[0]) & (d <= ring_km[1])


def read_classes(aoi: str, win: D.Win, years=None) -> np.ndarray:
    """(n, h, w) uint8 classes from the precomputed classes.tif (bands = years)."""
    bands = [y - D.YEARS[0] + 1 for y in (years or D.YEARS)]
    return D.read_tif(D.derived_path(aoi, "classes.tif"), win, band=bands, fill=0)


def read_forest(aoi: str, win: D.Win) -> np.ndarray:
    return D.read_tif(D.derived_path(aoi, "forest.tif"), win, fill=0) > 0


@lru_cache(maxsize=1)
def _ukraine_polygon():
    return D.aoi_polygon_3035("ukraine")


_UA_CACHE = LRU(8, maxbytes=64 * 2**20, sizeof=lambda a: a.nbytes)


def ukraine_mask(aoi: str, win: D.Win) -> np.ndarray:
    """True inside Ukraine's border (the same polygon the zones are clipped to; it includes coastal waters).
    Without the polygon file (synthetic test layouts) everything counts as Ukraine."""
    k = (aoi, tuple(int(v) for v in win))
    m = _UA_CACHE.get(k)
    if m is None:
        try:
            poly = _ukraine_polygon()
        except FileNotFoundError:
            return np.ones((win[2], win[3]), bool)
        _, m = rasterize(poly, aoi, win)
        _UA_CACHE.put(k, m)
    return m


# ------------------------------------------------------------------ preset cities
def build_city_masks(city: str) -> dict[str, np.ndarray]:
    """Full-grid masks for a preset city (used by the precompute script). Reference clipped to Ukraine (sci-v3.6; a
    no-op for Kyiv, Kharkiv and Lviv, whose rings have no forest abroad)."""
    g = D.grid(city)
    win = (0, 0, g.height, g.width)
    _, urban = rasterize(D.aoi_polygon_3035(city), city, win)
    forest = read_forest(city, win) & ukraine_mask(city, win)
    ring = ring_mask(urban, RING_KM)
    cls = read_classes(city, win)
    green = C.urban_parks(urban & C.stable_nature(cls, erode=1))
    return dict(urban=urban, ring=ring, ref=ring & forest, green=green)


@lru_cache(maxsize=4)
def preset(city: str) -> Reference:
    p = D.derived_path(city, "ref_masks.npz")
    z = np.load(p)
    g = D.grid(city)
    return Reference(city=city, name_uk=D.CITY_NAMES_UK[city], kind="preset", aoi=city,
                     win=(0, 0, g.height, g.width), ref=z["ref"], green=z["green"], urban=z["urban"], key=city)


@lru_cache(maxsize=4)
def preset_stats(city: str) -> dict:
    return json.load(open(D.derived_path(city, "refstats.json")))


# ------------------------------------------------------------------ derived (any place)
def _expand(win: D.Win, m: int) -> D.Win:
    r0, c0, h, w = win
    return r0 - m, c0 - m, h + 2 * m, w + 2 * m


def derive(zone: Zone) -> Reference:
    """Reference for a zone outside the preset cities (Ukraine grid)."""
    notes = []
    aoi = zone.aoi
    for margin in MARGINS_PX:
        win = _expand(zone.win, margin)
        cls = read_classes(aoi, win, [CLASS_YEAR_FOR_URBAN])[0]
        zm = np.zeros(cls.shape, bool)
        zm[margin:margin + zone.mask.shape[0], margin:margin + zone.mask.shape[1]] = zone.mask
        built = cls == C.BUILT
        closed = ndimage.binary_closing(built, np.ones((3, 3), bool), iterations=URBAN_CLOSE_PX)
        lab, _ = ndimage.label(closed)
        ids = np.unique(lab[zm & closed])
        ids = ids[ids > 0]
        urban = np.isin(lab, ids) if ids.size else np.zeros_like(zm)
        if urban.sum() < URBAN_MIN_PX:
            urban = zm.copy()
            notes.append("urban_area_is_zone")
        urban |= zm
        touches = urban[0].any() or urban[-1].any() or urban[:, 0].any() or urban[:, -1].any()
        if not touches:
            break
    else:
        notes.append("urban_area_clipped")
    ring_km = RING_KM
    forest_all = read_forest(aoi, win)
    forest = forest_all & ukraine_mask(aoi, win)     # sci-v3.6: border clip before the minimum-forest check
    ring = ring_mask(urban, ring_km)
    ref = ring & forest
    if ref.sum() < MIN_REF_PX:
        ring_km = RING_KM_WIDE
        ring = ring_mask(urban, ring_km)
        ref = ring & forest
        notes.append("ring_widened")
    n_all = int((ring & forest_all).sum())
    abroad = n_all - int(ref.sum())
    if n_all and abroad >= BORDER_NOTE_SHARE * n_all:
        notes.append("ref_border_clipped")
    cls_all = read_classes(aoi, win)
    green = C.urban_parks(urban & C.stable_nature(cls_all, erode=1))
    win, (ref, green, urban) = _crop(win, ref, green, urban)
    key = hashlib.sha1(repr((aoi, win, ring_km)).encode() + np.packbits(ref).tobytes()
                       + np.packbits(green).tobytes()).hexdigest()[:16]
    return Reference(city="derived", name_uk="", kind="derived", aoi=aoi, win=win, ref=ref, green=green,
                     urban=urban, ring_km=ring_km, key=key, notes=notes, abroad_px=abroad)


def _crop(win: D.Win, *masks: np.ndarray) -> tuple[D.Win, list[np.ndarray]]:
    """Crop aligned masks to the bbox of their union (drops the empty 30–60 km read margin; QA RB-01 memory).
    Consumers only use sums, ``composite_mean(win, mask)`` and the outline, so the window moves with the crop."""
    u = np.logical_or.reduce(masks)
    if not u.any():
        return win, [np.ascontiguousarray(m) for m in masks]
    rows, cols = np.flatnonzero(u.any(1)), np.flatnonzero(u.any(0))
    a, b, c, d = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    r0, c0, _, _ = win
    return (r0 + int(a), c0 + int(c), int(b - a), int(d - c)), [np.ascontiguousarray(m[a:b, c:d]) for m in masks]


# per worker: ≤ 64 references and ≤ 160 MB of masks (a 1200 px zone + 60 km margin is ~3200² px ≈ 30 MB uncropped)
DERIVE_CACHE_BYTES = 160 * 2**20
_DERIVE_CACHE = LRU(64, maxbytes=DERIVE_CACHE_BYTES, sizeof=lambda r: r.nbytes)


def derive_cached(zone: Zone) -> Reference:
    k = (zone.aoi, zone.win, hashlib.sha1(np.packbits(zone.mask).tobytes()).hexdigest())
    r = _DERIVE_CACHE.get(k)
    if r is None:
        r = derive(zone)
        _DERIVE_CACHE.put(k, r)
    return r


def composite_mean(aoi: str, year: int, win: D.Win, mask: np.ndarray) -> tuple[float | None, int]:
    """Mean summer-composite LST over mask (reads only the mask's bbox)."""
    if not mask.any():
        return None, 0
    rows, cols = np.where(mask.any(1))[0], np.where(mask.any(0))[0]
    a0, a1, b0, b1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    sub = (win[0] + a0, win[1] + b0, a1 - a0, b1 - b0)
    lst = D.read_lst(aoi, year, sub)
    v = lst[mask[a0:a1, b0:b1]]
    v = v[np.isfinite(v)]
    return (float(v.mean()) if v.size else None), int(v.size)


def ensure_masks_written(city: str, force: bool = False) -> None:
    p = D.derived_path(city, "ref_masks.npz")
    if p.exists() and not force:
        return
    m = build_city_masks(city)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(p) + ".tmp.npz"
    np.savez_compressed(tmp, **m)
    os.replace(tmp, p)

