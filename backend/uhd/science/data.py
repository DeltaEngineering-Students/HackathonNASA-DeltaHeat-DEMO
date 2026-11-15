"""Raster data access: grids, paths, windowed reads (no analysis logic here).

All grids are EPSG:3035, 60 m, aligned: a city grid is a sub-window of the Ukraine grid.
Windows are ``(row_off, col_off, height, width)`` tuples on a given AOI grid; reads are boundless
(outside the file -> nodata), so callers never have to clip.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from rasterio.windows import Window

RAW = Path(os.environ.get("UHD_LANDSAT_DIR") or os.environ.get("UHD_RAW") or "/srv/landsat")
DATA = Path(os.environ.get("UHD_DATA_DIR") or os.environ.get("UHD_DATA") or "/root/uhd/data")

CRS = "EPSG:3035"
RES = 60.0
PX_KM2 = RES * RES / 1e6
YEARS = tuple(range(2013, 2026))
ESRI_YEARS = tuple(range(2017, 2024))
CITY_AOIS = ("kyiv", "kharkiv", "lviv")
AOIS = CITY_AOIS + ("ukraine",)
CITY_NAMES_UK = {"kyiv": "Київ", "kharkiv": "Харків", "lviv": "Львів"}
CITY_GEN_UK = {"kyiv": "Києва", "kharkiv": "Харкова", "lviv": "Львова"}

LST_ND, IDX_ND = -32768, -128

# ESA WorldCover v200 and Esri/IO LULC v02 class codes (as written by pipeline/maps.py)
WC_TREES, WC_SHRUB, WC_GRASS, WC_CROP, WC_BUILT, WC_BARE, WC_WATER, WC_WETLAND = 10, 20, 30, 40, 50, 60, 80, 90
ESRI_WATER, ESRI_TREES, ESRI_FLOODED, ESRI_CROPS, ESRI_BUILT, ESRI_BARE, ESRI_RANGE = 1, 2, 4, 5, 7, 8, 11

Win = tuple[int, int, int, int]


@dataclass(frozen=True)
class Grid:
    aoi: str
    x0: float
    y1: float
    width: int
    height: int

    @property
    def transform(self) -> Affine:
        return Affine(RES, 0.0, self.x0, 0.0, -RES, self.y1)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self.x0, self.y1 - self.height * RES, self.x0 + self.width * RES, self.y1

    def window_transform(self, win: Win) -> Affine:
        r0, c0, _, _ = win
        return Affine(RES, 0.0, self.x0 + c0 * RES, 0.0, -RES, self.y1 - r0 * RES)

    def offset_of(self, other: "Grid") -> tuple[int, int]:
        """(row, col) of this grid's origin in ``other``'s pixel coordinates (grids are aligned)."""
        return int(round((other.y1 - self.y1) / RES)), int(round((self.x0 - other.x0) / RES))

    def window_for_bounds(self, xmin: float, ymin: float, xmax: float, ymax: float, pad: int = 0) -> Win:
        c0 = int(np.floor((xmin - self.x0) / RES)) - pad
        c1 = int(np.ceil((xmax - self.x0) / RES)) + pad
        r0 = int(np.floor((self.y1 - ymax) / RES)) - pad
        r1 = int(np.ceil((self.y1 - ymin) / RES)) + pad
        return r0, c0, r1 - r0, c1 - c0

    def contains_window(self, win: Win) -> bool:
        r0, c0, h, w = win
        return r0 >= 0 and c0 >= 0 and r0 + h <= self.height and c0 + w <= self.width

    def info(self) -> dict:
        from pyproj import Transformer

        t = Transformer.from_crs(CRS, 4326, always_xy=True)
        xmin, ymin, xmax, ymax = self.bounds
        lon, lat = t.transform([xmin, xmin, xmax, xmax], [ymin, ymax, ymin, ymax])
        return dict(aoi=self.aoi, crs=CRS, res=RES, x0=self.x0, y1=self.y1, width=self.width, height=self.height,
                    transform=list(self.transform)[:6],
                    bbox_wgs84=[round(min(lon), 5), round(min(lat), 5), round(max(lon), 5), round(max(lat), 5)])


@lru_cache(maxsize=None)
def grid(aoi: str) -> Grid:
    if aoi not in AOIS:
        raise ValueError(f"unknown aoi {aoi}")
    g = json.load(open(RAW / aoi / "composites" / "2013" / "info.json"))["grid"]
    return Grid(aoi, float(g["x0"]), float(g["y1"]), int(g["W"]), int(g["H"]))


def as_win(window) -> Win:
    if window is None:
        return None
    if isinstance(window, Window):
        return int(window.row_off), int(window.col_off), int(window.height), int(window.width)
    return tuple(int(v) for v in window)


def read_tif(path: Path | str, win: Win | None, band: int | list[int] = 1, fill=None) -> np.ndarray:
    """Boundless windowed read; missing file -> filled array (fill or file nodata)."""
    with rasterio.open(path) as s:
        nd = s.nodata if fill is None else fill
        if win is None:
            return s.read(band)
        r0, c0, h, w = win
        return s.read(band, window=Window(c0, r0, w, h), boundless=True,
                      fill_value=0 if nd is None else nd)


def composite_path(aoi: str, year: int, layer: str) -> Path:
    return RAW / aoi / "composites" / str(year) / f"{layer}.tif"


def map_path(aoi: str, name: str) -> Path:
    return RAW / aoi / "maps" / f"{name}.tif"


def derived_path(aoi: str, name: str) -> Path:
    return DATA / aoi / name


def read_lst(aoi: str, year: int, win: Win) -> np.ndarray:
    """Summer median LST composite, °C float32 with NaN."""
    a = read_tif(composite_path(aoi, year, "lst_med"), win)
    out = a.astype(np.float32) / 100.0
    out[a == LST_ND] = np.nan
    return out


def read_idx(aoi: str, year: int, layer: str, win: Win) -> np.ndarray:
    """Index composite (ndvi_med, ndbi_med, mndwi_med, ndvi_max) as float32 in [-1, 1] with NaN."""
    a = read_tif(composite_path(aoi, year, layer), win)
    out = a.astype(np.float32) / 100.0
    out[a == IDX_ND] = np.nan
    return out


def read_count(aoi: str, year: int, layer: str, win: Win) -> np.ndarray:
    return read_tif(composite_path(aoi, year, layer), win, fill=0)


def read_map(aoi: str, name: str, win: Win) -> np.ndarray:
    p = map_path(aoi, name)
    if not p.exists():
        r0, c0, h, w = win
        return np.zeros((h, w), np.uint8)
    return read_tif(p, win, fill=0)


def npz_mmap(path) -> dict[str, np.ndarray]:
    """Members of an .npz as read-only memmaps (shared page cache across API workers instead of a private copy each;
    QA RB-01). Each member is extracted once to ``<path>.d/<name>.npy`` (atomic, refreshed when the .npz is newer)."""
    path = Path(path)
    try:
        return _npz_mmap(path)
    except OSError:                      # read-only data dir: fall back to a private in-memory copy
        with np.load(path) as z:
            return {n: z[n] for n in z.files}


def _npz_mmap(path: Path) -> dict[str, np.ndarray]:
    d = path.with_name(path.name + ".d")
    out = {}
    with np.load(path) as z:
        names = list(z.files)
        for n in names:
            f = d / f"{n}.npy"
            if not f.exists() or f.stat().st_mtime < path.stat().st_mtime:
                d.mkdir(exist_ok=True)
                tmp = d / f".{n}.{os.getpid()}.tmp.npy"
                np.save(tmp, z[n])
                os.replace(tmp, f)
    for n in names:
        out[n] = np.load(d / f"{n}.npy", mmap_mode="r")
    return out


PLACES_REPO = Path(__file__).resolve().parents[2] / "data" / "places"


@lru_cache(maxsize=1)
def _war_regions() -> list:
    """Occupied / front-line regions (scripts/precompute_war_areas.py), as (name, since, prepared 3035 geometry)."""
    import shapely.geometry as sg
    from shapely.prepared import prep

    from .geometry import to_3035

    p = PLACES_REPO / "war_oblasts.geojson"
    if not p.exists():
        return []
    out = []
    for f in json.load(open(p))["features"]:
        g = to_3035(sg.shape(f["geometry"]))
        out.append((f["properties"]["name"], int(f["properties"]["since"]), g, prep(g)))
    return out


def war_region(shape_m) -> dict | None:
    """The occupied / front-line region containing (most of) the zone, or None."""
    pt = shape_m.representative_point()
    for name, since, g, pg in _war_regions():
        if pg.contains(pt) or (pg.intersects(shape_m) and g.intersection(shape_m).area > 0.5 * shape_m.area):
            return dict(name=name, since=since)
    return None


@lru_cache(maxsize=1)
def _occupied():
    """Temporarily occupied territory (scripts/precompute_occupied.py, PM 4b): (collection props, 3035 geom, prep)."""
    import shapely.geometry as sg
    from shapely.ops import unary_union
    from shapely.prepared import prep

    from .geometry import to_3035

    p = PLACES_REPO / "occupied.geojson"
    if not p.exists():
        return None
    fc = json.load(open(p))
    g = to_3035(unary_union([sg.shape(f["geometry"]) for f in fc["features"]]))
    return fc.get("properties", {}), g, prep(g)


def occupied(shape_m) -> dict | None:
    """{snapshot_date, source, source_url} if most (> 50 %) of the zone lies in occupied territory, else None."""
    occ = _occupied()
    if occ is None:
        return None
    props, g, pg = occ
    if not pg.intersects(shape_m):
        return None
    if not pg.contains(shape_m) and g.intersection(shape_m).area <= 0.5 * shape_m.area:
        return None
    return dict(snapshot_date=props.get("snapshot_date"), source=props.get("source"),
                source_url=props.get("source_url"))


@lru_cache(maxsize=8)
def aoi_polygon_3035(aoi: str):
    """City boundary (OSM admin polygon from /srv/landsat/aoi) in EPSG:3035."""
    import shapely.geometry as sg

    from .geometry import to_3035

    name = "Ukraine" if aoi == "ukraine" else aoi
    gj = json.load(open(RAW / "aoi" / f"{name}.geojson"))
    geom = sg.shape(gj["features"][0]["geometry"])
    return to_3035(geom)
