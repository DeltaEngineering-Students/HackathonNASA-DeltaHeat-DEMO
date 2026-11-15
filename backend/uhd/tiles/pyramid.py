"""Raster sources for tiles + downsampled pyramids (×4, ×16, ×64; NaN-aware mean) cached as .npy memmaps.

Values come from ``uhd.science.layer_raster`` / ``gap_raster`` (same numbers as the reports: the gap reference is
the city constant near preset cities and the smooth regional forest field elsewhere — see METHOD.md). If the science
package is not deployed, ``lst``/``ndvi`` fall back to reading the composites directly; ``gap``/``dndvi`` need science
(``dndvi`` is computed here as ndvi(year) − ndvi(base), identical to science for base = first year).

Layout: ``{cache_dir}/pyramid/{data_version}/{aoi}/{layer}/{year}/f{factor}.npy`` (float32, NaN = no data).
"""

from __future__ import annotations

import logging
import os
import re
import threading
import warnings
from functools import lru_cache
from collections import defaultdict
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window

from uhd.config import get_settings
from uhd.errors import APIError
from uhd.services import rasters, science

log = logging.getLogger(__name__)
FACTORS = (4, 16, 64)
STRIP = 1024  # rows per read; multiple of max(FACTORS)
BASE_LAYERS = ("lst", "ndvi", "gap")  # pyramids are built for these; dndvi is derived from ndvi
_DIRECT = {"lst": ("lst_med", rasters.LST_SCALE, rasters.LST_ND), "ndvi": ("ndvi_med", rasters.IDX_SCALE, rasters.IDX_ND)}
_locks: defaultdict[tuple, threading.Lock] = defaultdict(threading.Lock)
_mm: dict[Path, np.ndarray] = {}


def scaled(a: np.ndarray, scale: float, nodata: int) -> np.ndarray:
    out = a.astype(np.float32) * np.float32(scale)
    out[a == nodata] = np.nan
    return out


NONBUILT = "nonbuilt"  # item 13: built share of classified pixels (science classes.tif, class 1 = built that year)
WATER = "water"        # water share (classes.tif class 4 that year): masks inland water in the dndvi tiles
SHARE_LAYERS = {NONBUILT: 1, WATER: 4}  # uint8 share pyramids from classes.tif → class counted
_SHARE_NODATA = 255     # uint8 pyramid: 0…250 = share × 250, 255 = no classified pixel (open sea / none)


def classes_path() -> Path:
    return get_settings().data_dir / "ukraine" / "classes.tif"


@lru_cache(maxsize=1)
def classes_tag() -> str:
    return _file_tag([classes_path()])


def nonbuilt_available() -> bool:
    return classes_path().exists()


def _read_share(year: int, r0: int, c0: int, h: int, w: int, klass: int = 1) -> np.ndarray:
    """1 = class ``klass`` (built / water), 0 = another class, NaN = class 0 (sea/none)."""
    with rasterio.open(classes_path()) as src:
        band = [d for d in src.descriptions].index(str(year)) + 1 if str(year) in src.descriptions else year - 2012
        c = src.read(band, window=Window(c0, r0, w, h), boundless=True, fill_value=0)
    out = np.where(c == klass, 1.0, 0.0).astype(np.float32)
    out[c == 0] = np.nan
    return out


def read_window(aoi: str, layer: str, year: int, r0: int, c0: int, h: int, w: int) -> np.ndarray:
    """float32 [h, w], NaN = no data; boundless (outside the grid → NaN)."""
    if layer in SHARE_LAYERS:
        return _read_share(year, r0, c0, h, w, SHARE_LAYERS[layer])
    if science.has_helper("layer_raster"):
        a, _, _ = science.helper("layer_raster", aoi, layer, year, (r0, c0, h, w))
        return np.asarray(a, np.float32)
    return _read_direct(aoi, layer, year, r0, c0, h, w)


def _read_direct(aoi: str, layer: str, year: int, r0: int, c0: int, h: int, w: int) -> np.ndarray:
    if layer not in _DIRECT:
        raise APIError(503, "science_not_ready", f"the {layer} layer needs the science package")
    name, scale, nd = _DIRECT[layer]
    with rasterio.open(rasters.composite_path(aoi, year, name)) as src:
        a = src.read(1, window=Window(c0, r0, w, h), boundless=True, fill_value=nd)
    return scaled(a, scale, nd)


def _block_mean(a: np.ndarray, f: int) -> np.ndarray:
    h, w = a.shape
    H, W = -(-h // f) * f, -(-w // f) * f
    if (H, W) != (h, w):
        p = np.full((H, W), np.nan, np.float32)
        p[:h, :w] = a
        a = p
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(a.reshape(H // f, f, W // f, f), axis=(1, 3)).astype(np.float32)


REFFIELD_LAYERS = ("gap", "gap_fill")  # values depend on science's reffield.npz (gap reference outside the cities)
FILL_LAYERS = {"gap_fill": "gap", "lst_fill": "lst"}  # display-only fill (science gapfill.py) → palette of the base


def _file_tag(paths: list[Path]) -> str:
    import hashlib

    parts = []
    for p in paths:
        try:
            st = p.stat()
            parts.append(f"{p.name}:{st.st_size}:{st.st_mtime_ns}")
        except OSError:
            parts.append(f"{p.name}:-")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:6]


def reffield_path() -> Path | None:
    try:
        if science.module().__name__ == "uhd.science":
            from uhd.science.rasters import reffield_path as rp

            return Path(rp())
    except Exception:  # noqa: BLE001
        pass
    return None


@lru_cache(maxsize=1)
def reffield_tag() -> str:
    """Identity (size + mtime) of reffield.npz, read once per process (deploy reloads the workers): a rebuilt field
    gives new gap pyramids instead of stale low zooms (the 2a Crimea fix kept the old ×4…×64 levels)."""
    p = reffield_path()
    return _file_tag([p]) if p else "none"


def layer_dirname(layer: str) -> str:
    if layer in SHARE_LAYERS:
        return f"{layer}@{classes_tag()}"
    return f"{layer}@{reffield_tag()}" if layer in REFFIELD_LAYERS else layer


def _encode_share(a: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        q = np.where(np.isfinite(a), np.round(np.clip(a, 0, 1) * 250), _SHARE_NODATA)
    return q.astype(np.uint8)


def decode(arr: np.ndarray, values: np.ndarray, layer: str) -> np.ndarray:
    """Pyramid cell values → float (share pyramids are stored as uint8 to keep them ≈ 22 MB per year)."""
    if layer not in SHARE_LAYERS:
        return values
    v = values.astype(np.float32) / 250.0
    v[values == _SHARE_NODATA] = np.nan
    return v


def _dir(aoi: str, layer: str, year: int) -> Path:
    dv = re.sub(r"[^A-Za-z0-9._-]+", "_", science.data_version())
    return get_settings().cache_dir / "pyramid" / dv / aoi / layer_dirname(layer) / str(year)


def fill_available() -> bool:
    """Display-only fill layers exist only with the real science package (gapfill.py)."""
    try:
        if science.module().__name__ != "uhd.science":
            return False
        import importlib.util

        return importlib.util.find_spec("uhd.science.gapfill") is not None
    except Exception:  # noqa: BLE001
        return False


def _save(path: Path, arr: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp.npy")
    np.save(tmp, arr)
    os.replace(tmp, path)


def build(aoi: str, layer: str, year: int) -> None:
    """One streaming pass over the 60 m raster → ×4, then ×16 and ×64 from the ×4 level."""
    g = rasters.grid(aoi)
    H, W = g["H"], g["W"]
    f0 = FACTORS[0]
    lvl0 = np.full((-(-H // f0), -(-W // f0)), np.nan, np.float32)
    for r0 in range(0, H, STRIP):
        h = min(STRIP, H - r0)
        lvl0[r0 // f0: r0 // f0 + -(-h // f0)] = _block_mean(read_window(aoi, layer, year, r0, 0, h, W), f0)
    d = _dir(aoi, layer, year)
    enc = _encode_share if layer in SHARE_LAYERS else (lambda x: x)
    _save(d / f"f{f0}.npy", enc(lvl0))
    prev, pf = lvl0, f0
    for f in FACTORS[1:]:
        prev = _block_mean(prev, f // pf)
        pf = f
        _save(d / f"f{f}.npy", enc(prev))
    log.info("pyramid built", extra={"aoi": aoi, "layer": layer, "year": year})


def level(aoi: str, layer: str, year: int, factor: int) -> np.ndarray:
    p = _dir(aoi, layer, year) / f"f{factor}.npy"
    arr = _mm.get(p)
    if arr is not None:
        return arr
    with _locks[(aoi, layer, year)]:
        if not p.exists():
            build(aoi, layer, year)
        arr = np.load(p, mmap_mode="r")
        _mm[p] = arr
        return arr


def status(aoi: str) -> dict[str, list[int]]:
    out = {}
    for layer in BASE_LAYERS:
        out[layer] = [y for y in rasters.years(aoi) if (_dir(aoi, layer, y) / f"f{FACTORS[-1]}.npy").exists()]
    return out
