"""Access to the read-only Landsat composites/scenes layout under ``{landsat_dir}``."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds
from shapely.geometry import box, mapping

from uhd.config import get_settings
from uhd.services.geometry import to_3035, to_4326

CITY_AOIS = ("kyiv", "kharkiv", "lviv")
CITY_NAMES_UK = {"kyiv": "Київ", "kharkiv": "Харків", "lviv": "Львів", "ukraine": "Україна"}
LST_SCALE, IDX_SCALE = 0.01, 0.01  # int16 °C×100 ; int8 index×100
LST_ND, IDX_ND = -32768, -128


def root() -> Path:
    return get_settings().landsat_dir


@lru_cache(maxsize=None)
def years(aoi: str = "ukraine") -> list[int]:
    d = root() / aoi / "composites"
    if not d.is_dir():
        return []
    return sorted(int(p.name) for p in d.iterdir() if p.name.isdigit() and (p / "lst_med.tif").exists())


@lru_cache(maxsize=None)
def aois() -> list[str]:
    r = root()
    if not r.is_dir():
        return []
    return [a for a in ("ukraine", *CITY_AOIS) if (r / a / "composites").is_dir()]


@lru_cache(maxsize=None)
def grid(aoi: str) -> dict | None:
    ys = years(aoi)
    if not ys:
        return None
    info = json.loads((root() / aoi / "composites" / str(ys[-1]) / "info.json").read_text())
    g = info["grid"]
    res = float(info.get("res", 60.0))
    g = {"x0": g["x0"], "y1": g["y1"], "W": g["W"], "H": g["H"], "res": res, "crs": info.get("crs", "EPSG:3035")}
    g["bounds_3035"] = (g["x0"], g["y1"] - g["H"] * res, g["x0"] + g["W"] * res, g["y1"])
    return g


@lru_cache(maxsize=None)
def bbox_wgs84(aoi: str) -> list[float] | None:
    g = grid(aoi)
    if not g:
        return None
    return [round(v, 4) for v in to_4326(box(*g["bounds_3035"])).bounds]


def pick_aoi(geom_wgs84) -> str | None:
    """Prefer a city AOI that fully contains the geometry (complete per-scene data), else 'ukraine'."""
    g3 = to_3035(geom_wgs84)
    for a in CITY_AOIS:
        gr = grid(a)
        if gr and box(*gr["bounds_3035"]).contains(g3):
            return a
    gr = grid("ukraine")
    if gr and box(*gr["bounds_3035"]).intersects(g3):
        return "ukraine"
    return None


def composite_path(aoi: str, year: int, layer: str) -> Path:
    return root() / aoi / "composites" / str(year) / f"{layer}.tif"


def read_zone(path: Path, geom_wgs84, band: int = 1) -> tuple[np.ndarray, np.ndarray] | None:
    """Read the window covering the geometry; return (masked float array, inside-zone mask)."""
    g3 = to_3035(geom_wgs84)
    with rasterio.open(path) as src:
        win = from_bounds(*g3.bounds, transform=src.transform).round_offsets().round_lengths()
        win = win.intersection(Window(0, 0, src.width, src.height))
        if win.width <= 0 or win.height <= 0:
            return None
        a = src.read(band, window=win, masked=True)
        tr = src.window_transform(win)
    inside = ~geometry_mask([mapping(g3)], out_shape=a.shape, transform=tr, all_touched=False)
    return a, inside


def clear_caches() -> None:
    for f in (years, aois, grid, bbox_wgs84):
        f.cache_clear()
