"""Render one WebMercator tile from the EPSG:3035 grids.

Per tile: pixel centres (sampled on a 17×17 lattice, bilinearly densified) → EPSG:3035 → nearest source cell.
Source level: native 60 m raster (windowed read) when the tile pixel is ≤ 4×60 m, otherwise the cached ×4/×16/×64 pyramid.
"""

from __future__ import annotations

import io
import logging
import math
import os
import re
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from uhd.config import get_settings
from uhd.errors import bad_request
from uhd.proj import transformer
from uhd.services import rasters, science
from uhd.tiles import palettes, pyramid

log = logging.getLogger(__name__)
TILE = 256
LAYERS = ("gap", "lst", "ndvi", "dndvi", "gap_fill", "lst_fill", "nonbuilt")  # *_fill: display-only fill; nonbuilt: overlay
MIN_Z, MAX_Z = 3, 16
DNDVI_BASE = 2013
_W3857 = 20037508.342789244
_T = transformer(3857, 3035)  # pipeline-built: cheap in every new threadpool thread (uhd.proj)
_T_inv = transformer(3035, 3857)
_LATTICE = 17
TILE_FORMAT = "pal128"  # part of tiles_version: changing the encoding gives new URLs and a new cache dir


@lru_cache(maxsize=1)
def empty_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0)).save(buf, "PNG", optimize=True)
    return buf.getvalue()


def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    span = 2 * _W3857 / (1 << z)
    minx = -_W3857 + x * span
    maxy = _W3857 - y * span
    return minx, maxy - span, minx + span, maxy


@lru_cache(maxsize=8)
def grid_bounds_3857(aoi: str) -> tuple[float, float, float, float] | None:
    g = rasters.grid(aoi)
    if not g:
        return None
    x0, y0, x1, y1 = g["bounds_3035"]
    xs = np.concatenate([np.linspace(x0, x1, 50), np.full(50, x1), np.linspace(x1, x0, 50), np.full(50, x0)])
    ys = np.concatenate([np.full(50, y0), np.linspace(y0, y1, 50), np.full(50, y1), np.linspace(y1, y0, 50)])
    mx, my = _T_inv.transform(xs, ys)
    return float(np.min(mx)), float(np.min(my)), float(np.max(mx)), float(np.max(my))


def _sample_coords(z: int, x: int, y: int) -> tuple[np.ndarray, np.ndarray]:
    """EPSG:3035 coordinates of the 256×256 pixel centres."""
    minx, miny, maxx, maxy = tile_bounds(z, x, y)
    px = (maxx - minx) / TILE
    t = np.linspace(0.5, TILE - 0.5, _LATTICE)
    gx, gy = np.meshgrid(minx + t * px, maxy - t * px)
    ex, ey = _T.transform(gx.ravel(), gy.ravel())
    ex, ey = np.asarray(ex).reshape(gx.shape), np.asarray(ey).reshape(gx.shape)
    # densify lattice → full tile
    pos = (np.arange(TILE) + 0.5 - 0.5) / (TILE - 1) * (_LATTICE - 1)
    rr, cc = np.meshgrid(pos, pos, indexing="ij")
    X = ndimage.map_coordinates(ex, [rr, cc], order=1, mode="nearest")
    Y = ndimage.map_coordinates(ey, [rr, cc], order=1, mode="nearest")
    return X, Y


def _pixel_size_m(z: int, y: int) -> float:
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 0.5) / (1 << z)))))
    return 2 * _W3857 / (1 << z) / TILE * math.cos(math.radians(lat))


def _choose_factor(px_m: float, res: float) -> int:
    f = 1
    for cand in pyramid.FACTORS:
        if cand * res <= px_m * 1.01:
            f = cand
    return f


def _sample(aoi: str, layer: str, year: int, X: np.ndarray, Y: np.ndarray, factor: int) -> np.ndarray:
    g = rasters.grid(aoi)
    res = g["res"]
    col = (X - g["x0"]) / (res * factor)
    row = (g["y1"] - Y) / (res * factor)
    ci, ri = np.floor(col).astype(np.int64), np.floor(row).astype(np.int64)
    out = np.full(X.shape, np.nan, np.float32)
    if factor == 1:
        inb = (ri >= 0) & (ri < g["H"]) & (ci >= 0) & (ci < g["W"])
        if not inb.any():
            return out
        r0, r1 = int(ri[inb].min()), int(ri[inb].max()) + 1
        c0, c1 = int(ci[inb].min()), int(ci[inb].max()) + 1
        a = pyramid.read_window(aoi, layer, year, r0, c0, r1 - r0, c1 - c0)
        out[inb] = a[ri[inb] - r0, ci[inb] - c0]
        return out
    lv = pyramid.level(aoi, layer, year, factor)
    inb = (ri >= 0) & (ri < lv.shape[0]) & (ci >= 0) & (ci < lv.shape[1])
    out[inb] = pyramid.decode(lv, lv[ri[inb], ci[inb]], layer)
    return out


def values(layer: str, year: int, z: int, x: int, y: int, base: int = DNDVI_BASE) -> np.ndarray:
    aoi = get_settings().tiles_aoi
    X, Y = _sample_coords(z, x, y)
    factor = _choose_factor(_pixel_size_m(z, y), rasters.grid(aoi)["res"])
    if layer in ("lst", "ndvi", "gap", "gap_fill", "lst_fill", "nonbuilt"):
        return _sample(aoi, layer, year, X, Y, factor)
    if layer == "dndvi":
        ny = _sample(aoi, "ndvi", year, X, Y, factor)
        v = ny - _sample(aoi, "ndvi", base, X, Y, factor)
        if dndvi_water_masked():  # NDVI change of a water surface is not a greenery change (Дніпро, reservoirs)
            with np.errstate(invalid="ignore"):
                water = _sample(aoi, pyramid.WATER, year, X, Y, factor) >= DNDVI_WATER_SHARE
                if base != year:  # water in BOTH years only: a drained bed (Kakhovka) or a new pond stays visible
                    water &= _sample(aoi, pyramid.WATER, base, X, Y, factor) >= DNDVI_WATER_SHARE
                if year >= KAKHOVKA_DRAINED_FROM and water.any():
                    water &= ~(_in_kakhovka(X, Y) & (ny >= KAKHOVKA_WATER_NDVI))
            v[water] = np.nan
        return v
    raise bad_request("invalid_layer", f"unknown layer {layer}")


def encode_png(rgba: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG", compress_level=6)
    return buf.getvalue()


NONBUILT_ALPHA = 1.0  # baked full strength; the frontend scales raster-opacity with the slider (default 0.7)
NONBUILT_LEVELS = 16
NONBUILT_COLOR = {"dark": (0x1C, 0x24, 0x38), "light": (0xF6, 0xF6, 0xF3)}  # the map's ground colour per theme


def encode_overlay(share: np.ndarray, theme: str) -> bytes:
    """Item 13: ground colour at alpha (1 − built share), 16 levels; index 0 = transparent (sea / no class)."""
    valid = np.isfinite(share)
    lvl = np.round((1 - np.clip(np.where(valid, share, 1), 0, 1)) * (NONBUILT_LEVELS - 1)).astype(np.uint8) + 1
    lvl[~valid] = 0
    im = Image.fromarray(lvl, "P")
    im.putpalette(bytes(3) + bytes(NONBUILT_COLOR[theme]) * NONBUILT_LEVELS)
    alphas = [0] + [round(255 * NONBUILT_ALPHA * i / (NONBUILT_LEVELS - 1)) for i in range(NONBUILT_LEVELS)]
    buf = io.BytesIO()
    im.save(buf, "PNG", transparency=bytes(alphas), compress_level=6)
    return buf.getvalue()


def encode_indexed(values: np.ndarray, layer: str, theme: str) -> bytes:
    if layer == "nonbuilt":
        return encode_overlay(values, theme)
    """Palette PNG (128 colours, index 0 transparent): same look, ~15–25 KB instead of ~100 KB (RB-03)."""
    idx, pal = palettes.indexed(values, pyramid.FILL_LAYERS.get(layer, layer), theme)  # fill = base palette
    im = Image.fromarray(idx, "P")
    im.putpalette(pal)
    buf = io.BytesIO()
    im.save(buf, "PNG", transparency=0, compress_level=6)
    return buf.getvalue()


CLIP_BUFFER_M = 1500.0  # Ukraine outline + 1.5 km (task 2a): nothing is drawn over Moldova, Russia or the sea
CLIP_TAG = "ua1500"


@lru_cache(maxsize=1)
def ukraine_clip():
    """(polygon in EPSG:3857, prepared) of the Ukraine outline (/srv/landsat/aoi/Ukraine.geojson, Crimea included)
    buffered by 1.5 km, or None when the outline is missing (then tiles are not clipped)."""
    import json

    from shapely.geometry import shape
    from shapely.ops import transform as stransform, unary_union
    from shapely.prepared import prep

    p = get_settings().landsat_dir / "aoi" / "Ukraine.geojson"
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        log.warning("tiles: no Ukraine outline, tiles are not clipped", extra={"path": str(p)})
        return None
    fs = d["features"] if d.get("type") == "FeatureCollection" else [d]
    g = unary_union([shape(f.get("geometry", f)) for f in fs])
    to3035 = transformer(4326, 3035).transform
    g = stransform(to3035, g).buffer(CLIP_BUFFER_M, 8).simplify(60)
    g = stransform(_T_inv.transform, g)
    return g, prep(g)


def _tile_box(z: int, x: int, y: int):
    from shapely.geometry import box

    return box(*tile_bounds(z, x, y))


def outside_ukraine(z: int, x: int, y: int) -> bool:
    c = ukraine_clip()
    return c is not None and not c[1].intersects(_tile_box(z, x, y))


def clip_mask(z: int, x: int, y: int) -> np.ndarray | None:
    """256×256 bool, True = inside Ukraine (+1.5 km); None = the whole tile is inside (or no outline)."""
    c = ukraine_clip()
    if c is None:
        return None
    tb = _tile_box(z, x, y)
    if c[1].contains(tb):
        return None
    from rasterio import features
    from rasterio.transform import Affine

    minx, miny, maxx, maxy = tile_bounds(z, x, y)
    px = (maxx - minx) / TILE
    part = c[0].intersection(tb.buffer(2 * px))
    if part.is_empty:
        return np.zeros((TILE, TILE), bool)
    return features.rasterize([(part, 1)], out_shape=(TILE, TILE), transform=Affine(px, 0, minx, 0, -px, maxy),
                              fill=0, dtype="uint8").astype(bool)


SEA_TAG = "sea1"
_SEA_COARSE = 16  # in-memory sea mask level for low zooms (×16 = 960 m cells, ~1 MB); finer zooms read windows


def _sea_path() -> Path:
    return get_settings().data_dir / "ukraine" / "sea_mask.tif"


@lru_cache(maxsize=1)
def sea_info() -> dict | None:
    """Science's open-sea mask on the ukraine grid (uint8, 1 = sea; lagoons joined to the sea count, lakes and
    reservoirs do not), or None. Sea pixels are transparent in every layer (task 2a, with the outline clip)."""
    p = _sea_path()
    if not p.exists():
        return None
    import rasterio
    from rasterio.enums import Resampling

    try:
        with rasterio.open(p) as ds:
            t = ds.transform
            H, W = ds.height, ds.width
            f = _SEA_COARSE
            coarse = ds.read(1, out_shape=(-(-H // f), -(-W // f)), resampling=Resampling.mode) == 1
    except Exception:  # noqa: BLE001
        log.exception("tiles: unreadable sea mask", extra={"path": str(p)})
        return None
    rr, cc = np.nonzero(coarse)
    if not len(rr):
        return None
    res = t.a
    x0, y1 = t.c, t.f
    sb = (x0 + cc.min() * f * res, y1 - (rr.max() + 1) * f * res, x0 + (cc.max() + 1) * f * res, y1 - rr.min() * f * res)
    return {"path": str(p), "x0": x0, "y1": y1, "res": res, "H": H, "W": W, "coarse": coarse, "bounds": sb}


def _sea_sample(X: np.ndarray, Y: np.ndarray, px_m: float) -> np.ndarray | None:
    """bool sea mask at the tile's pixel centres (EPSG:3035), None when the tile is away from the sea."""
    si = sea_info()
    if si is None:
        return None
    b = si["bounds"]
    if X.max() < b[0] or X.min() > b[2] or Y.max() < b[1] or Y.min() > b[3]:
        return None
    res = si["res"]
    if px_m >= _SEA_COARSE * res / 2:
        f, arr, r0, c0 = _SEA_COARSE, si["coarse"], 0, 0
    else:
        import rasterio
        from rasterio.windows import Window

        f = 4 if px_m >= 2 * res else 1
        col = (X - si["x0"]) / res
        row = (si["y1"] - Y) / res
        c0, c1 = int(np.floor(col.min())), int(np.floor(col.max())) + 1
        r0, r1 = int(np.floor(row.min())), int(np.floor(row.max())) + 1
        c0, r0 = max(c0, 0), max(r0, 0)
        c1, r1 = min(c1, si["W"]), min(r1, si["H"])
        if c1 <= c0 or r1 <= r0:
            return None
        c0, r0 = c0 - c0 % f, r0 - r0 % f
        with rasterio.open(si["path"]) as ds:
            arr = ds.read(1, window=Window(c0, r0, c1 - c0, r1 - r0),
                          out_shape=(-(-(r1 - r0) // f), -(-(c1 - c0) // f))) == 1
        r0, c0 = r0 // f, c0 // f
    ci = np.floor((X - si["x0"]) / (res * f)).astype(np.int64) - c0
    ri = np.floor((si["y1"] - Y) / (res * f)).astype(np.int64) - r0
    inb = (ri >= 0) & (ri < arr.shape[0]) & (ci >= 0) & (ci < arr.shape[1])
    out = np.zeros(X.shape, bool)
    out[inb] = arr[ri[inb], ci[inb]]
    return out


@lru_cache(maxsize=1)
def _inputs_tag() -> str:
    """Short hash of the derived inputs that change tile values without a DATA/METHOD version bump (science's
    reffield.npz — the gap reference outside the preset cities — and the sea mask): size + mtime, read once per
    worker (deploy reloads the workers). A rebuilt file → new tiles_version → new browser and server caches."""
    paths = [_sea_path()]
    rp = pyramid.reffield_path()
    if rp is not None:
        paths.append(rp)
    paths.append(pyramid.classes_path())  # nonbuilt overlay (item 13)
    return pyramid._file_tag(paths)


FILL_TAG = "fill1"
# served fill layers: gap only for now (PM: thin pool tight — lst_fill would add ~1.15 GB of pyramids)
FILL_SERVED = ("gap_fill",)


def fill_enabled() -> bool:
    return pyramid.fill_available()


# dndvi only: inland water (classes.tif class 4 in BOTH the year and the base year; ≥ half of the cell at coarse zooms
# in both) is transparent; water in only one of the two (drained Kakhovka bed, new ponds) is a real change and shown. The tag names the dndvi cache dir and is appended to tiles_version (new browser URLs), but it is NOT
# part of the server cache dir tag, so the gap/lst/ndvi/… tiles already rendered stay valid.
DNDVI_WATER_TAG = "w2"  # w1: water in either year (hid the Kakhovka bed); w2: both years + Kakhovka exemption
DNDVI_WATER_SHARE = 0.5


# Kakhovka exemption: the dam was destroyed in June 2023 and the bed greened, but classes.tif for 2024–2025 inherits
# Esri 2023, which still maps much of the bed as water. Inside this lon/lat box, from 2023 on, a "water" pixel counts as
# water only if it still looks like water that year (NDVI < 0.2); the vegetated bed (NDVI ≈ 0.6–0.7) is shown.
KAKHOVKA_BOX = (33.30, 46.72, 35.15, 47.80)  # Нова Каховка … below Запоріжжя (DniproHES upstream end)
KAKHOVKA_DRAINED_FROM = 2023
KAKHOVKA_WATER_NDVI = 0.2
_T_ll = transformer(3035, 4326)


@lru_cache(maxsize=1)
def _kakhovka_env_3035() -> tuple[float, float, float, float]:
    w, s, e, n = KAKHOVKA_BOX
    t = np.linspace(0, 1, 9)
    lon = np.concatenate([w + (e - w) * t, np.full(9, e), w + (e - w) * t, np.full(9, w)])
    lat = np.concatenate([np.full(9, s), s + (n - s) * t, np.full(9, n), s + (n - s) * t])
    xs, ys = transformer(4326, 3035).transform(lon, lat)
    return float(np.min(xs)), float(np.min(ys)), float(np.max(xs)), float(np.max(ys))


def _in_kakhovka(X: np.ndarray, Y: np.ndarray) -> np.ndarray:
    x0, y0, x1, y1 = _kakhovka_env_3035()
    if X.max() < x0 or X.min() > x1 or Y.max() < y0 or Y.min() > y1:
        return np.zeros(X.shape, bool)
    lon, lat = _T_ll.transform(X, Y)
    w, s, e, n = KAKHOVKA_BOX
    return (lon >= w) & (lon <= e) & (lat >= s) & (lat <= n)


def dndvi_water_masked() -> bool:
    return pyramid.nonbuilt_available()  # same classes.tif as the nonbuilt overlay


def dndvi_dir_prefix() -> str:
    return f"dndvi-{DNDVI_WATER_TAG}-b" if dndvi_water_masked() else "dndvi-b"


def _base_version() -> str:
    clip = f"+{CLIP_TAG}" if ukraine_clip() is not None else ""
    clip += f"+{SEA_TAG}" if sea_info() is not None else ""
    clip += f"+i{_inputs_tag()}"
    clip += f"+{FILL_TAG}" if fill_enabled() else ""
    return f"{science.data_version()}+{science.tiles_method_version()}+p{palettes.version()}+{TILE_FORMAT}{clip}"


def tiles_version() -> str:
    """Changes whenever tile pixels can change: data, science tile method, palettes, the clip or the derived inputs
    (reffield, sea mask), and per-layer tags (dndvi water mask). Use as ``&v=``."""
    return _base_version() + (f"+dndvi{DNDVI_WATER_TAG}" if dndvi_water_masked() else "")


def cache_tag() -> str:
    """Server tile cache dir: tiles_version without the per-layer tags (those live in the layer dir names)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", _base_version())


def _cache_path(layer: str, theme: str, year: int, z: int, x: int, y: int, base: int) -> Path:
    s = get_settings()
    tag = cache_tag()
    lay = f"{dndvi_dir_prefix()}{base}" if layer == "dndvi" else layer
    return s.cache_dir / "tiles" / tag / lay / theme / str(year) / str(z) / str(x) / f"{y}.png"


_render_sem = threading.BoundedSemaphore(max(2, (os.cpu_count() or 4) // 2))


def validate(layer: str, year: int, z: int, x: int, y: int, theme: str, base: int) -> None:
    if layer not in LAYERS or (layer in pyramid.FILL_LAYERS and not (fill_enabled() and layer in FILL_SERVED)) \
            or (layer == "nonbuilt" and not pyramid.nonbuilt_available()):
        raise bad_request("invalid_layer", f"layer must be one of {', '.join(LAYERS)}")
    if theme not in palettes.THEMES:
        raise bad_request("invalid_theme", "theme must be light or dark")
    ys = rasters.years(get_settings().tiles_aoi)
    if year not in ys or (layer == "dndvi" and base not in ys):
        raise bad_request("invalid_year", f"year must be one of {ys[0] if ys else '?'}–{ys[-1] if ys else '?'}")
    if not (MIN_Z <= z <= MAX_Z and 0 <= x < (1 << z) and 0 <= y < (1 << z)):
        raise bad_request("invalid_tile", f"z must be {MIN_Z}–{MAX_Z} and x/y inside the zoom level")


def tile_png(layer: str, year: int, z: int, x: int, y: int, theme: str = "light", base: int = DNDVI_BASE) -> bytes:
    validate(layer, year, z, x, y, theme, base)
    gb = grid_bounds_3857(get_settings().tiles_aoi)
    tb = tile_bounds(z, x, y)
    if gb is None or tb[2] < gb[0] or tb[0] > gb[2] or tb[3] < gb[1] or tb[1] > gb[3] or outside_ukraine(z, x, y):
        return empty_png()
    cp = _cache_path(layer, theme, year, z, x, y, base)
    try:
        return cp.read_bytes()
    except FileNotFoundError:
        pass
    with _render_sem:
        v = values(layer, year, z, x, y, base)
        m = clip_mask(z, x, y)
        if m is not None:
            v = np.where(m, v, np.nan)
        if sea_info() is not None and np.isfinite(v).any():
            X, Y = _sample_coords(z, x, y)
            sea = _sea_sample(X, Y, _pixel_size_m(z, y))
            if sea is not None:
                v = np.where(sea, np.nan, v)
    png = empty_png() if not np.isfinite(v).any() else encode_indexed(v, layer, theme)
    _store(cp, png)
    return png


def cached(layer: str, year: int, z: int, x: int, y: int, theme: str = "light", base: int = DNDVI_BASE) -> bytes | None:
    """Fast path for the async route (no thread pool): a cached tile or the shared empty tile, else None."""
    validate(layer, year, z, x, y, theme, base)
    gb = grid_bounds_3857(get_settings().tiles_aoi)
    tb = tile_bounds(z, x, y)
    if gb is None or tb[2] < gb[0] or tb[0] > gb[2] or tb[3] < gb[1] or tb[1] > gb[3] or outside_ukraine(z, x, y):
        return empty_png()
    try:
        return _cache_path(layer, theme, year, z, x, y, base).read_bytes()
    except FileNotFoundError:
        return None


_disk_check = {"t": 0.0, "ok": True}


def _disk_ok() -> bool:
    """Persist tiles only while the disk keeps ``tile_cache_min_free_gb`` free (RB-04: shared disk, a download job
    writes there too); checked at most every 30 s."""
    import shutil
    import time as _t

    now = _t.monotonic()
    if now - _disk_check["t"] > 30:
        s = get_settings()
        d = s.cache_dir
        while not d.exists() and d.parent != d:
            d = d.parent
        try:
            _disk_check["ok"] = shutil.disk_usage(d).free / 2**30 >= s.tile_cache_min_free_gb
        except OSError:
            _disk_check["ok"] = False
        _disk_check["t"] = now
    return _disk_check["ok"]


def _store(cp: Path, png: bytes) -> None:
    if not _disk_ok():
        return
    try:
        cp.parent.mkdir(parents=True, exist_ok=True)
        tmp = cp.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_bytes(png)
        os.replace(tmp, cp)
    except OSError as e:  # ENOSPC etc.: serve the rendered tile anyway
        log.warning("tile cache write failed", extra={"err": str(e)})
