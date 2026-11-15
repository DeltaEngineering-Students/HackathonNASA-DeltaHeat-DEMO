#!/usr/bin/env python3
"""Ukraine-wide smooth reference field for gap tiles: $UHD_DATA_DIR/ukraine/reffield.npz (y_<year> arrays).

Per year: mean stable-forest LST on a 1.2 km grid (20x20 px), normalised Gaussian smoothing (σ = 10 km, then
σ = 30 km, then σ = 100 km to fill gaps, then the nearest value — so every cell has a reference; without the last two
steps steppe areas > ~60 km from stable forest (northern Crimea, Kerch, Syvash) had no field and their gap tiles were
transparent "lenses" around the Crimean mountain forests, PM 4c), and the preset-city constant within 15 km of each city's boundary, blended linearly
into the regional field between 15 and 25 km.
sci-v3.6: only stable forest inside Ukraine's border enters the sums (INVESTIGATION-FOREIGN-REFERENCE; the grid
extends ≥ 20 km abroad and foreign forest used to leak into the field near the border).
Needs precompute_masks.py (forest.tif) and precompute_cities.py (refstats). Idempotent (--force; --out to write
elsewhere, e.g. to swap the file in at deploy time).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from uhd.science import data as D  # noqa: E402
from uhd.science import rasters as RA  # noqa: E402
from uhd.science import reference as R  # noqa: E402
from uhd.science.geometry import rasterize  # noqa: E402

log = logging.getLogger("precompute_reffield")
STRIP = 2000  # rows per read (multiple of COARSE)
_UA: dict = {}  # strip window -> packed Ukraine mask (rasterised once, reused for every year)
BLEND_KM = 10.0  # city value -> regional field over 15..25 km from the boundary


def coarse_sums(year: int, forest_path) -> tuple[np.ndarray, np.ndarray]:
    g = D.grid("ukraine")
    k = RA.COARSE
    H, W = -(-g.height // k), -(-g.width // k)
    s = np.zeros((H, W), np.float64)
    n = np.zeros((H, W), np.float64)
    for r0 in range(0, g.height, STRIP):
        h = min(STRIP, g.height - r0)
        win = (r0, 0, -(-h // k) * k, W * k)
        lst = D.read_lst("ukraine", year, win)
        if win not in _UA:
            _UA[win] = np.packbits(R.ukraine_mask("ukraine", win), axis=1)
        ua = np.unpackbits(_UA[win], axis=1, count=win[3]).astype(bool)
        f = (D.read_tif(forest_path, win, fill=0) > 0) & ua
        ok = f & np.isfinite(lst)
        v = np.where(ok, lst, 0.0)
        hh = win[2] // k
        s[r0 // k:r0 // k + hh] = v.reshape(hh, k, W, k).sum((1, 3))
        n[r0 // k:r0 // k + hh] = ok.reshape(hh, k, W, k).sum((1, 3))
    return s, n


def smooth(s, n, sigma_cells):
    ss = ndimage.gaussian_filter(s, sigma_cells, mode="constant")
    nn = ndimage.gaussian_filter(n, sigma_cells, mode="constant")
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(nn > 1.0, ss / nn, np.nan)


def fill_nearest(f: np.ndarray) -> np.ndarray:
    bad = ~np.isfinite(f)
    if not bad.any() or bad.all():
        return f
    idx = ndimage.distance_transform_edt(bad, return_distances=False, return_indices=True)
    return f[tuple(idx)]


def city_zones() -> dict[str, np.ndarray]:
    """Coarse-cell masks within 15 km of each preset city's boundary."""
    g = D.grid("ukraine")
    k = RA.COARSE
    H, W = -(-g.height // k), -(-g.width // k)
    out = {}
    for c in D.CITY_AOIS:
        poly = D.aoi_polygon_3035(c).buffer(15000)
        win = g.window_for_bounds(*poly.bounds, pad=k)
        win = (win[0] // k * k, win[1] // k * k, -(-(win[2] + k) // k) * k, -(-(win[3] + k) // k) * k)
        _, m = rasterize(poly, "ukraine", win)
        mc = m.reshape(win[2] // k, k, win[3] // k, k).mean((1, 3)) > 0.5
        full = np.zeros((H, W), bool)
        r, cc = win[0] // k, win[1] // k
        full[r:r + mc.shape[0], cc:cc + mc.shape[1]] = mc[:H - r, :W - cc]
        out[c] = full
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    (D.DATA / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(D.DATA / "logs" / "precompute_reffield.log"),
                                  logging.StreamHandler()])
    from pathlib import Path
    p = Path(a.out) if a.out else RA.reffield_path()
    if p.exists() and not a.force:
        log.info("exists, skip: %s", p)
        return
    forest_path = D.derived_path("ukraine", "forest.tif")
    zones = city_zones()
    weights = {c: np.clip(1 - ndimage.distance_transform_edt(~m) * D.RES * RA.COARSE / 1000.0 / BLEND_KM, 0, 1)
               for c, m in zones.items()}
    sig = 10_000 / (D.RES * RA.COARSE)
    out = {}
    for y in D.YEARS:
        t0 = time.time()
        s, n = coarse_sums(y, forest_path)
        f = smooth(s, n, sig)
        f2 = smooth(s, n, 3 * sig)
        f = np.where(np.isfinite(f), f, f2)
        f = np.where(np.isfinite(f), f, smooth(s, n, 10 * sig))
        f = fill_nearest(f)
        for c, m in zones.items():
            v = R.preset_stats(c)["composite"][str(y)]["ref_lst"]
            if v is not None:  # city value within 15 km, linear blend to the regional field at 25 km (no step)
                w = weights[c]
                f = np.where(w > 0, w * v + (1 - w) * np.where(np.isfinite(f), f, v), f)
        out[f"y_{y}"] = f.astype(np.float32)
        log.info("%d: field %s, finite %.1f%%, %.0fs", y, f.shape, 100 * np.isfinite(f).mean(), time.time() - t0)
    tmp = str(p) + ".tmp.npz"
    np.savez_compressed(tmp, **out)
    os.replace(tmp, p)
    log.info("written %s", p)


if __name__ == "__main__":
    main()
