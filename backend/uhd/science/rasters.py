"""Rasters for map tiles: gap (LST − reference), lst, ndvi, ndbi, dndvi, classes.

gap:
* preset cities (aoi kyiv/kharkiv/lviv, and inside them on the ukraine aoi): per-scene-matched gap map
  (scripts/precompute_gapmaps.py) = pixel climatology gap + smoothed median of date-matched anomalies; agrees with
  the per-scene reports within ~1.5 °C per year (composite tiles: up to 3.8 °C) and has no path seam.
  On the ukraine aoi it is blended into the composite gap between 15 and 20 km from the city boundary.
* elsewhere (ukraine aoi): summer composite LST minus a smooth "nearby stable forest" field
  (scripts/precompute_reffield.py: forest LST on a 1.2 km grid, Gaussian σ = 10 km; the city reference within
  15 km of the preset cities, blended into the field over 15–25 km). Composite → path seams possible (1–3 °C).
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from . import data as D
from . import reference as R

COARSE = 20  # reference field cell = 20 px = 1.2 km


def reffield_path():
    return D.DATA / "ukraine" / "reffield.npz"


@lru_cache(maxsize=1)
def _reffield() -> dict[int, np.ndarray]:
    z = D.npz_mmap(reffield_path())   # shared memmaps (RB-01)
    return {int(k.split("_")[1]): v for k, v in z.items() if k.startswith("y_")}


def _win(aoi: str, window) -> D.Win:
    w = D.as_win(window)
    if w is None:
        g = D.grid(aoi)
        w = (0, 0, g.height, g.width)
    return w


def reference_window(aoi: str, year: int, win: D.Win) -> np.ndarray | float:
    if aoi in D.CITY_AOIS:
        v = R.preset_stats(aoi)["composite"][str(year)]["ref_lst"]
        return np.nan if v is None else float(v)
    f = _reffield()[year]
    r0, c0, h, w = win
    rr = np.clip((np.arange(r0, r0 + h) // COARSE), 0, f.shape[0] - 1)
    cc = np.clip((np.arange(c0, c0 + w) // COARSE), 0, f.shape[1] - 1)
    return f[np.ix_(rr, cc)]


@lru_cache(maxsize=3)
def _gapmap(city: str) -> dict[str, np.ndarray] | None:
    p = D.derived_path(city, "gapmap.npz")
    if not p.exists():
        return None
    z = D.npz_mmap(p)                 # shared memmaps (RB-01): ~25–53 MB per city no longer copied per worker
    return dict(gap=z["gap"], weight=z["weight"])


def _city_window(city: str, aoi: str, win: D.Win):
    """Intersection of an aoi window with a city grid: (slice in window, slice in city grid) or None."""
    cg, ag = D.grid(city), D.grid(aoi)
    dr, dc = cg.offset_of(ag)           # city origin in aoi pixels
    r0, c0, h, w = win
    a0, a1 = max(r0, dr), min(r0 + h, dr + cg.height)
    b0, b1 = max(c0, dc), min(c0 + w, dc + cg.width)
    if a1 <= a0 or b1 <= b0:
        return None
    return ((slice(a0 - r0, a1 - r0), slice(b0 - c0, b1 - c0)),
            (slice(a0 - dr, a1 - dr), slice(b0 - dc, b1 - dc)))


def gap_raster(aoi: str, year: int, window=None, per_scene: bool = True):
    """LST − reference [°C]. per_scene=False forces the plain composite gap (for comparison)."""
    win = _win(aoi, window)
    T = D.grid(aoi).window_transform(win)
    out = (D.read_lst(aoi, year, win) - reference_window(aoi, year, win)).astype(np.float32)
    if not per_scene:
        return out, T, D.CRS
    i = year - D.YEARS[0]
    for city in ([aoi] if aoi in D.CITY_AOIS else D.CITY_AOIS):
        gm = _gapmap(city)
        cw = _city_window(city, aoi, win) if gm is not None else None
        if cw is None:
            continue
        sw, sc = cw
        g = gm["gap"][i][sc].astype(np.float32)
        wt = np.ones_like(g) if aoi == city else gm["weight"][sc].astype(np.float32)
        cur = out[sw]
        ok = np.isfinite(g) & (wt > 0)
        blend = np.where(np.isfinite(cur), wt * g + (1 - wt) * cur, g)
        cur[ok] = blend[ok]
    return out, T, D.CRS


def layer_raster(aoi: str, layer: str, year: int, window=None):
    win = _win(aoi, window)
    T = D.grid(aoi).window_transform(win)
    if layer == "gap":
        return gap_raster(aoi, year, win)
    if layer in ("gap_fill", "lst_fill"):           # display-only fill of year-specific holes (gapfill.py)
        from .gapfill import FILL_LAYERS, fill_raster
        return fill_raster(aoi, FILL_LAYERS[layer], year, win), T, D.CRS
    if layer == "lst":
        return D.read_lst(aoi, year, win), T, D.CRS
    if layer in ("ndvi", "ndbi", "mndwi"):
        return D.read_idx(aoi, year, f"{layer}_med", win), T, D.CRS
    if layer == "ndvi_max":
        return D.read_idx(aoi, year, "ndvi_max", win), T, D.CRS
    if layer == "dndvi":
        base = D.read_idx(aoi, D.YEARS[0], "ndvi_med", win)
        return (D.read_idx(aoi, year, "ndvi_med", win) - base).astype(np.float32), T, D.CRS
    raise ValueError(f"unknown layer {layer}")


def classes_raster(aoi: str, year: int, window=None):
    win = _win(aoi, window)
    return R.read_classes(aoi, win, [year])[0], D.grid(aoi).window_transform(win), D.CRS
