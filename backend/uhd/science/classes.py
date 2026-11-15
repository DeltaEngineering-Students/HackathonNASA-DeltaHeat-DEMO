"""Land-cover classes per year: built / field / nature / water (+ other) and the stable masks.

Rules (documented in METHOD.md §3):
* 2017–2023: Esri/IO LULC of that year (majority at 60 m); missing Esri -> WorldCover 2021.
* 2013–2016: Esri 2017 as anchor; a pixel that is built in 2017 but was clearly greener in year y
  (ndvi_max_y − ndvi_max_2017 ≥ 0.20 and ndvi_max_y ≥ 0.60) was not built yet -> nature (field on farmland).
* 2024–2025: Esri 2023 as anchor; a non-built, non-water pixel that lost greenness and gained "concrete"
  (ndvi_max_y − ndvi_max_2023 ≤ −0.25, ndvi_max_y < 0.45, ndbi_y − ndbi_2023 ≥ 0.05) -> built;
  a built pixel that greened strongly (Δndvi_max ≥ 0.25 and ndvi_max_y ≥ 0.60) -> nature.
* OSM farmland (cities only): nature -> field in every year (fields are not the reference).
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

from . import data as D

NONE, BUILT, FIELD, NATURE, WATER, OTHER = 0, 1, 2, 3, 4, 5
CLASS_NAMES = {NONE: "none", BUILT: "built", FIELD: "field", NATURE: "nature", WATER: "water", OTHER: "other"}

ESRI_LUT = np.zeros(256, np.uint8)
ESRI_LUT[[D.ESRI_BUILT]] = BUILT
ESRI_LUT[[D.ESRI_CROPS]] = FIELD
ESRI_LUT[[D.ESRI_TREES, D.ESRI_FLOODED, D.ESRI_RANGE]] = NATURE
ESRI_LUT[[D.ESRI_WATER]] = WATER
ESRI_LUT[[D.ESRI_BARE]] = OTHER

WC_LUT = np.zeros(256, np.uint8)
WC_LUT[[D.WC_BUILT]] = BUILT
WC_LUT[[D.WC_CROP]] = FIELD
WC_LUT[[D.WC_TREES, D.WC_SHRUB, D.WC_GRASS, D.WC_WETLAND]] = NATURE
WC_LUT[[D.WC_WATER]] = WATER
WC_LUT[[D.WC_BARE]] = OTHER

# thresholds of the spectral extrapolation (NDVI/NDBI in [-1, 1])
PRE_GREENER_DNDVI = 0.20
PRE_GREEN_NDVI = 0.60
POST_LOSS_DNDVI = -0.25
POST_MAX_NDVI = 0.45
POST_DNDBI = 0.05
POST_REGREEN_DNDVI = 0.25


def esri_classes(esri: np.ndarray, wc: np.ndarray, farmland: np.ndarray | None) -> np.ndarray:
    c = ESRI_LUT[esri]
    miss = esri == 0
    c[miss] = WC_LUT[wc[miss]]
    if farmland is not None:
        c[(c == NATURE) & (farmland > 0)] = FIELD
    return c


def extrapolate_before(anchor: np.ndarray, ndvi_max_y, ndvi_max_a, farmland=None, wc=None) -> np.ndarray:
    """Classes for a year before the first Esri year, from the anchor (first Esri year) classes."""
    c = anchor.copy()
    with np.errstate(invalid="ignore"):
        greener = (anchor == BUILT) & (ndvi_max_y - ndvi_max_a >= PRE_GREENER_DNDVI) & (ndvi_max_y >= PRE_GREEN_NDVI)
    c[greener] = NATURE
    fieldish = np.zeros_like(greener)
    if farmland is not None:
        fieldish |= farmland > 0
    if wc is not None:
        fieldish |= wc == D.WC_CROP
    c[greener & fieldish] = FIELD
    return c


def extrapolate_after(anchor: np.ndarray, ndvi_max_y, ndvi_max_a, ndbi_y, ndbi_a) -> np.ndarray:
    """Classes for a year after the last Esri year, from the anchor (last Esri year) classes."""
    c = anchor.copy()
    with np.errstate(invalid="ignore"):
        dv = ndvi_max_y - ndvi_max_a
        new_built = ((anchor != BUILT) & (anchor != WATER) & (anchor != NONE) & (dv <= POST_LOSS_DNDVI)
                     & (ndvi_max_y < POST_MAX_NDVI) & (ndbi_y - ndbi_a >= POST_DNDBI))
        regreen = (anchor == BUILT) & (dv >= POST_REGREEN_DNDVI) & (ndvi_max_y >= PRE_GREEN_NDVI)
    c[new_built] = BUILT
    c[regreen] = NATURE
    return c


def classes_window(aoi: str, win: D.Win) -> np.ndarray:
    """(n_years, h, w) uint8 classes for 2013..2025 computed from the raw maps/composites."""
    wc = D.read_map(aoi, "worldcover2021", win)
    farm = D.read_map(aoi, "osm_farmland", win) if aoi in D.CITY_AOIS else None
    esri = {y: esri_classes(D.read_map(aoi, f"esri_{y}", win), wc, farm) for y in D.ESRI_YEARS}
    first, last = D.ESRI_YEARS[0], D.ESRI_YEARS[-1]
    nmax = {y: D.read_idx(aoi, y, "ndvi_max", win) for y in D.YEARS if y <= first or y >= last}
    out = np.zeros((len(D.YEARS),) + wc.shape, np.uint8)
    for i, y in enumerate(D.YEARS):
        if y in esri:
            out[i] = esri[y]
        elif y < first:
            out[i] = extrapolate_before(esri[first], nmax[y], nmax[first], farm, wc)
        else:
            out[i] = extrapolate_after(esri[last], nmax[y], nmax[last], D.read_idx(aoi, y, "ndbi_med", win),
                                       D.read_idx(aoi, last, "ndbi_med", win))
    return out


def stable_forest(wc: np.ndarray, esri_years: list[np.ndarray], farmland: np.ndarray | None,
                  ndvi_min: np.ndarray | None = None, erode: int = 1) -> np.ndarray:
    """Reference forest: WorldCover trees AND Esri trees in every Esri year AND not farmland
    AND (if given) min summer NDVI over the years ≥ 0.4 (drops later clear-cuts/burns), eroded by
    ``erode`` px so mixed edge pixels (thermal band is 100 m) are not used."""
    m = wc == D.WC_TREES
    for e in esri_years:
        m &= e == D.ESRI_TREES
    if farmland is not None:
        m &= farmland == 0
    if ndvi_min is not None:
        with np.errstate(invalid="ignore"):
            m &= ~(ndvi_min < 0.4)
    if erode:
        m = ndimage.binary_erosion(m, np.ones((3, 3), bool), iterations=erode)
    return m


def stable_nature(cls: np.ndarray, erode: int = 1) -> np.ndarray:
    """Nature (trees/grass/shrub/wetland, not farmland) in every year, eroded."""
    m = (cls == NATURE).all(0)
    if erode:
        m = ndimage.binary_erosion(m, np.ones((3, 3), bool), iterations=erode)
    return m


def land_change_masks(cls: np.ndarray) -> dict[str, np.ndarray]:
    """cls: (n_years, h, w) for the selected period.
    always_built: built every year; new_built: not built in the first two years, built in the last two;
    always_green: nature every year."""
    n = cls.shape[0]
    k = 2 if n >= 4 else 1
    built = cls == BUILT
    return dict(always_built=built.all(0),
                new_built=(~built[:k]).all(0) & built[-k:].all(0),
                always_green=(cls == NATURE).all(0))


PARK_MAX_KM2 = 5.0


def urban_parks(nature_in_urban: np.ndarray, max_km2: float = PARK_MAX_KM2) -> np.ndarray:
    """In-city green for the "do parks help?" comparison: connected patches (8-neighbour) of stable nature inside
    the urban area no larger than ``max_km2`` — parks, squares, green yards, small groves. Large forests inside the
    admin boundary (Holosiiv, Pushcha in Kyiv) are excluded: they behave like the forest reference itself."""
    lab, n = ndimage.label(nature_in_urban, np.ones((3, 3), bool))
    if n == 0:
        return nature_in_urban.copy()
    sizes = np.bincount(lab.ravel())[1:] * D.PX_KM2
    keep = np.zeros(n + 1, bool)
    keep[1:] = sizes <= max_km2
    return keep[lab]
