"""Reference-quality caveats (INVESTIGATION-REGIONAL-GAP; text only, no number changes).

* ``ref_higher`` — the reference forest lies >= 100 m higher than the zone's built surface (median elevations from a
  600 m Copernicus DEM GLO-90 on the ukraine grid): mountain forest is cooler, the gap may be overstated.
* ``ref_weak`` — the reference is small or fragmented (< 20 km² of forest, or median patch < 1 km², or > 10 % of it
  within 300 m of water): steppe shelterbelts and riverside groves are warm, the gap may be understated.

DEM: ``python -m uhd.science.refquality [--force]`` → ``$UHD_DATA_DIR/ukraine/dem600.tif`` (int16 m, 600 m cells
aligned with the 60 m ukraine grid; built once from the public Copernicus GLO-90 COGs, coarse overviews only).
Without the file ``ref_higher`` is simply not evaluated.
sci-v3.6: ``python -m uhd.science.refquality --dem60`` → ``ukraine/dem60.tif`` (full-resolution GLO-90, bilinear on the
60 m grid) for the elevation-matched reference (``elevmatch``); ``ref_higher`` then uses it via ``elevmatch``.
"""
from __future__ import annotations

import argparse
import logging
import math
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy import ndimage

from . import classes as C
from . import data as D

log = logging.getLogger("uhd.science.refquality")
F = 10                          # DEM cell = 10 × 60 m
HIGHER_M = 100.0
WEAK_KM2 = 20.0
WEAK_PATCH_KM2 = 1.0
WEAK_NEAR_WATER = 0.10
WATER_PX = 5                    # 300 m
CLASS_YEAR = 2021
DEM_URL = ("https://copernicus-dem-90m.s3.amazonaws.com/Copernicus_DSM_COG_30_N{lat:02d}_00_E{lon:03d}_00_DEM/"
           "Copernicus_DSM_COG_30_N{lat:02d}_00_E{lon:03d}_00_DEM.tif")
UA = "uhd-hackathon-prototype/0.1"


def dem_path() -> Path:
    return D.DATA / "ukraine" / "dem600.tif"


def dem60_path() -> Path:
    return D.DATA / "ukraine" / "dem60.tif"


@lru_cache(maxsize=1)
def _dem() -> np.ndarray | None:
    p = dem_path()
    if not p.exists():
        return None
    a = D.read_tif(p, None).astype(np.float32)
    a[a == -32768] = np.nan
    return a


def elevations(aoi: str, win: D.Win, mask: np.ndarray) -> np.ndarray:
    """DEM values (m) at the True pixels of a mask on an aoi window (city grids are aligned with the ukraine grid)."""
    dem = _dem()
    if dem is None or not mask.any():
        return np.array([], np.float32)
    dr, dc = (0, 0) if aoi == "ukraine" else D.grid(aoi).offset_of(D.grid("ukraine"))
    rr, cc = np.nonzero(mask)
    r = np.clip((rr + win[0] + dr) // F, 0, dem.shape[0] - 1)
    c = np.clip((cc + win[1] + dc) // F, 0, dem.shape[1] - 1)
    v = dem[r, c]
    return v[np.isfinite(v)]


def elevation_diff(ref, zone_aoi: str, zone_win: D.Win, basis: np.ndarray) -> float | None:
    """Median elevation of the reference forest minus that of the zone's basis pixels (m), or None."""
    fe, ze = elevations(ref.aoi, ref.win, ref.ref), elevations(zone_aoi, zone_win, basis)
    if fe.size < 50 or ze.size < 5:
        return None
    return float(np.median(fe) - np.median(ze))


_QUAL: dict[str, dict] = {}


def quality(ref) -> dict:
    """Forest area, median patch size (pixel-weighted) and share near water of a reference (cached by its key)."""
    key = ref.key or f"{ref.aoi}:{ref.win}:{ref.forest_px}"
    if key in _QUAL:
        return _QUAL[key]
    m = ref.ref
    lab, n = ndimage.label(m)
    if n:
        sizes = np.bincount(lab.ravel())[1:]
        patch = float(np.median(np.repeat(sizes, sizes))) * D.PX_KM2
    else:
        patch = 0.0
    cls = D.read_tif(D.derived_path(ref.aoi, "classes.tif"), ref.win, band=CLASS_YEAR - D.YEARS[0] + 1, fill=0)
    water = ndimage.binary_dilation(cls == C.WATER, iterations=WATER_PX)
    near = float((m & water).sum() / max(m.sum(), 1))
    q = dict(forest_km2=round(m.sum() * D.PX_KM2, 1), patch_km2=round(patch, 2), near_water=round(near, 3))
    if len(_QUAL) > 256:
        _QUAL.clear()
    _QUAL[key] = q
    return q


def is_weak(q: dict) -> bool:
    return q["forest_km2"] < WEAK_KM2 or q["patch_km2"] < WEAK_PATCH_KM2 or q["near_water"] > WEAK_NEAR_WATER


# ------------------------------------------------------------------ DEM build (CLI)
def build_dem(out: Path) -> None:
    import rasterio
    from affine import Affine
    from rasterio.warp import Resampling, reproject, transform_bounds

    g = D.grid("ukraine")
    H, W = math.ceil(g.height / F), math.ceil(g.width / F)
    T = Affine(D.RES * F, 0, g.x0, 0, -D.RES * F, g.y1)
    acc = np.full((H, W), np.nan, np.float32)
    b = transform_bounds("EPSG:3035", "EPSG:4326", g.x0, g.y1 - H * D.RES * F, g.x0 + W * D.RES * F, g.y1)
    n = 0
    with rasterio.Env(GDAL_HTTP_USERAGENT=UA, GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="4",
                      GDAL_HTTP_RETRY_DELAY="2"):
        for lat in range(math.floor(b[1]), math.floor(b[3]) + 1):
            for lon in range(math.floor(b[0]), math.floor(b[2]) + 1):
                try:
                    s = rasterio.open("/vsicurl/" + DEM_URL.format(lat=lat, lon=lon), overview_level=1)
                except Exception:  # noqa: BLE001 — sea / missing tiles
                    continue
                with s:
                    tmp = np.full((H, W), np.nan, np.float32)
                    reproject(rasterio.band(s, 1), tmp, src_nodata=s.nodata, dst_transform=T, dst_crs="EPSG:3035",
                              dst_nodata=np.nan, resampling=Resampling.average)
                ok = np.isfinite(tmp) & np.isnan(acc)
                acc[ok] = tmp[ok]
                n += 1
    log.info("%d DEM tiles", n)
    data = np.where(np.isfinite(acc), np.round(acc), -32768).astype(np.int16)
    prof = dict(driver="GTiff", height=H, width=W, count=1, dtype="int16", crs="EPSG:3035", transform=T,
                nodata=-32768, compress="deflate", tiled=True, blockxsize=256, blockysize=256)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmpf = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    with rasterio.open(tmpf, "w", **prof) as o:
        o.write(data, 1)
    os.replace(tmpf, out)


def _dem60_tile(lat: int, lon: int, g) -> tuple[tuple[int, int], np.ndarray] | None:
    """One GLO-90 tile reprojected (bilinear) onto the 60 m ukraine grid: ((row0, col0), int16 block) or None."""
    import rasterio
    from rasterio.warp import Resampling, reproject, transform_bounds

    try:
        s = rasterio.open("/vsicurl/" + DEM_URL.format(lat=lat, lon=lon))
    except Exception:  # noqa: BLE001 — sea / missing tiles
        return None
    with s:
        x0, y0, x1, y1 = transform_bounds(s.crs, "EPSG:3035", *s.bounds, densify_pts=21)
        r0 = max(int(math.floor((g.y1 - y1) / D.RES)) - 2, 0)
        r1 = min(int(math.ceil((g.y1 - y0) / D.RES)) + 2, g.height)
        c0 = max(int(math.floor((x0 - g.x0) / D.RES)) - 2, 0)
        c1 = min(int(math.ceil((x1 - g.x0) / D.RES)) + 2, g.width)
        if r1 <= r0 or c1 <= c0:
            return None
        tmp = np.full((r1 - r0, c1 - c0), np.nan, np.float32)
        reproject(rasterio.band(s, 1), tmp, src_nodata=s.nodata, dst_transform=g.window_transform((r0, c0, 0, 0)),
                  dst_crs="EPSG:3035", dst_nodata=np.nan, resampling=Resampling.bilinear)
    return (r0, c0), tmp


def build_dem60(out: Path, threads: int = 6) -> None:
    """60 m DEM on the ukraine grid (int16 m, -32768 = none): GLO-90 full resolution, bilinear — the elevation-matched
    reference (sci-v3.6, ``elevation_match``). ~1 GB downloaded once; the file is a few hundred MB at most."""
    import rasterio
    from concurrent.futures import ThreadPoolExecutor
    from rasterio.warp import transform_bounds

    g = D.grid("ukraine")
    acc = np.full((g.height, g.width), -32768, np.int16)
    b = transform_bounds("EPSG:3035", "EPSG:4326", g.x0, g.y1 - g.height * D.RES, g.x0 + g.width * D.RES, g.y1)
    tiles = [(la, lo) for la in range(math.floor(b[1]), math.floor(b[3]) + 1)
             for lo in range(math.floor(b[0]), math.floor(b[2]) + 1)]
    n = 0
    with rasterio.Env(GDAL_HTTP_USERAGENT=UA, GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="4",
                      GDAL_HTTP_RETRY_DELAY="2"), ThreadPoolExecutor(threads) as ex:
        for res in ex.map(lambda t: _dem60_tile(t[0], t[1], g), tiles):
            if res is None:
                continue
            (r0, c0), tmp = res
            sub = acc[r0:r0 + tmp.shape[0], c0:c0 + tmp.shape[1]]
            ok = np.isfinite(tmp) & (sub == -32768)
            sub[ok] = np.round(tmp[ok]).astype(np.int16)
            n += 1
            if n % 20 == 0:
                log.info("%d / %d tiles", n, len(tiles))
    log.info("%d DEM tiles", n)
    prof = dict(driver="GTiff", height=g.height, width=g.width, count=1, dtype="int16", crs="EPSG:3035",
                transform=g.transform, nodata=-32768, compress="deflate", predictor=2, zlevel=9, tiled=True,
                blockxsize=512, blockysize=512)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmpf = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    with rasterio.open(tmpf, "w", **prof) as o:
        o.write(acc, 1)
    os.replace(tmpf, out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="DEMs on the ukraine grid: 600 m (ref_higher caveat) and, with --dem60, "
                                             "60 m (elevation-matched reference, sci-v3.6)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--dem60", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    out = Path(a.out or (dem60_path() if a.dem60 else dem_path()))
    if out.exists() and not a.force:
        log.info("%s exists (use --force)", out)
        return
    (build_dem60 if a.dem60 else build_dem)(out)
    log.info("wrote %s (%d bytes)", out, out.stat().st_size)


if __name__ == "__main__":
    main()
