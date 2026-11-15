#!/usr/bin/env python3
"""Per-scene-matched gap rasters for the preset cities (gap tiles that agree with the reports).

For city c and summer y (METHOD.md §4b):
  A_d(px)  = (LST_d(px) − clim(px)) − (ref_d − clim_ref)          date-matched anomaly, usable dates only
  gap_y    = (clim(px) − clim_ref) + G_σ[ median_d A_d ](px)       σ = 1.5 km normalised Gaussian
clim = per-pixel median of the 13 summer composites (seams of single years average out), ref_d = the
climatology-adjusted reference of date d (refstats.json). The pixel detail comes from the climatology, the yearly
change from same-date comparisons, so the Landsat path seam of the yearly composite disappears.
Also a blend weight for the Ukraine tiles: 1 within 15 km of the city boundary, linear to 0 at 20 km (grid edge).

Writes $UHD_DATA_DIR/<city>/gapmap.npz: gap (13, H, W) float16 °C (NaN = no data), weight (H, W) float16.
Needs precompute_cities.py. Idempotent (--force). Usage: precompute_gapmaps.py [kyiv kharkiv lviv]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import warnings

import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from uhd.science import analysis as A  # noqa: E402
from uhd.science import data as D  # noqa: E402
from uhd.science import reference as R  # noqa: E402
from uhd.science import scenes as SC  # noqa: E402

log = logging.getLogger("precompute_gapmaps")
SIGMA_PX = 25          # 1.5 km
BLEND_KM = (15.0, 20.0)


def smooth_nan(a: np.ndarray, sigma: float) -> np.ndarray:
    ok = np.isfinite(a)
    num = ndimage.gaussian_filter(np.where(ok, a, 0.0).astype(np.float32), sigma, mode="nearest")
    den = ndimage.gaussian_filter(ok.astype(np.float32), sigma, mode="nearest")
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0.05, num / den, np.nan)


def year_gap(city: str, year: int, clim: np.ndarray, clim_ref: float) -> np.ndarray:
    st = R.preset_stats(city)["dates"].get(str(year)) or []
    full = (0, 0) + clim.shape
    a = SC.window_lst(city, year, full) if SC.has_stack(city, year) else np.empty((0,) + clim.shape, np.float32)
    anoms = []
    for k, d in enumerate(st):
        if d["ref_valid_px"] < A.MIN_REF_PX_DATE or d["ref_lst_adj"] is None:
            continue
        anoms.append(a[k] - clim - np.float32(d["ref_lst_adj"] - clim_ref))
    if not anoms:  # no usable acquisition: composite anomaly vs the composite reference
        comp = D.read_lst(city, year, full)
        anoms = [comp - clim - np.float32(R.preset_stats(city)["composite"][str(year)]["ref_lst"] - clim_ref)]
    med = np.nanmedian(np.stack(anoms), axis=0)
    return (clim - clim_ref) + smooth_nan(med, SIGMA_PX)


def run(city: str, force: bool):
    p = D.derived_path(city, "gapmap.npz")
    if p.exists() and not force:
        log.info("[%s] exists, skip", city)
        return
    t0 = time.time()
    clim = np.asarray(SC.clim(city), np.float32)
    clim_ref = float(R.preset_stats(city)["clim"]["ref_lst"])
    gaps = np.stack([year_gap(city, y, clim, clim_ref) for y in D.YEARS]).astype(np.float16)
    urban = R.preset(city).urban
    dist_km = ndimage.distance_transform_edt(~urban) * D.RES / 1000.0
    w = np.clip((BLEND_KM[1] - dist_km) / (BLEND_KM[1] - BLEND_KM[0]), 0, 1).astype(np.float16)
    tmp = str(p) + ".tmp.npz"
    np.savez(tmp, gap=gaps, weight=w)
    os.replace(tmp, p)
    log.info("[%s] gapmap %s written in %.0fs", city, gaps.shape, time.time() - t0)


def main():
    warnings.simplefilter("ignore", RuntimeWarning)
    ap = argparse.ArgumentParser()
    ap.add_argument("cities", nargs="*", default=list(D.CITY_AOIS))
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    (D.DATA / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(D.DATA / "logs" / "precompute_gapmaps.log"),
                                  logging.StreamHandler()])
    for c in a.cities:
        run(c, a.force)


if __name__ == "__main__":
    main()
