#!/usr/bin/env python3
"""Precompute everything the preset cities need for fast analysis (run after precompute_masks.py).

  $UHD_DATA_DIR/<city>/ref_masks.npz     urban / ring / ref (stable forest in the 2–15 km ring) / green masks
  $UHD_DATA_DIR/<city>/scenes/<year>.npy per-date LST stacks (see uhd.science.scenes)
  $UHD_DATA_DIR/<city>/refstats.json     reference + in-city green LST per year (composite) and per date
Idempotent: existing files are kept unless --force. Usage: precompute_cities.py [--force] kyiv kharkiv lviv
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

import warnings

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from uhd.science import data as D  # noqa: E402
from uhd.science import reference as R  # noqa: E402
from uhd.science import scenes as SC  # noqa: E402

log = logging.getLogger("precompute_cities")


def _r(v, nd=3):
    return None if v is None or not np.isfinite(v) else round(float(v), nd)


def refstats(city: str) -> dict:
    ref = R.preset(city)
    g = D.grid(city)
    full = (0, 0, g.height, g.width)
    out = {"composite": {}, "dates": {}, "ref_px": ref.forest_px, "green_px": int(ref.green.sum())}
    # per-pixel climatology (median of the 13 summer composites): spatial pattern used to make the
    # per-date reference independent of which part of the ring a given acquisition sees
    clim = np.nanmedian(np.stack([D.read_lst(city, y, full) for y in D.YEARS]), axis=0).astype(np.float32)
    cp = D.derived_path(city, "clim.npy")
    np.save(str(cp) + ".tmp.npy", clim)
    os.replace(str(cp) + ".tmp.npy", cp)
    clim_ref, clim_green = float(np.nanmean(clim[ref.ref])), float(np.nanmean(clim[ref.green]))
    out["clim"] = dict(ref_lst=_r(clim_ref), green_lst=_r(clim_green))
    for y in D.YEARS:
        lst = D.read_lst(city, y, full)
        rv, gv = lst[ref.ref], lst[ref.green]
        out["composite"][str(y)] = dict(
            ref_lst=_r(np.nanmean(rv)), ref_valid_share=_r(np.isfinite(rv).mean()),
            green_lst=_r(np.nanmean(gv)) if ref.green.any() else None,
            green_valid_share=_r(np.isfinite(gv).mean()) if ref.green.any() else None)
        if not SC.has_stack(city, y):
            continue
        a = SC.window_lst(city, y, full)
        rm, rs = SC.masked_means(a, ref.ref)
        gm, gs = SC.masked_means(a, ref.green)
        ra, _ = SC.masked_means(a - clim, ref.ref)      # mean anomaly vs climatology on visible pixels
        ga, _ = SC.masked_means(a - clim, ref.green)
        out["dates"][str(y)] = [dict(date=d["date"], ref_lst=_r(rm[i]), ref_lst_adj=_r(clim_ref + ra[i]),
                                     ref_valid_share=_r(rs[i]), ref_valid_px=int(round(rs[i] * ref.forest_px)),
                                     green_lst=_r(gm[i]), green_lst_adj=_r(clim_green + ga[i]),
                                     green_valid_share=_r(gs[i]))
                                for i, d in enumerate(SC.dates(city, y))]
        del a
    return out


def run(city: str, force: bool):
    t0 = time.time()
    R.ensure_masks_written(city, force)
    R.preset.cache_clear()
    ref = R.preset(city)
    log.info("[%s] masks: urban %d px, ref forest %d px (%.0f km²), green %d px", city, ref.urban.sum(),
             ref.forest_px, ref.forest_px * D.PX_KM2, ref.green.sum())
    for y in D.YEARS:
        n = SC.build_stack(city, y, force)
        if n >= 0:
            log.info("[%s %d] stack: %d acquisition dates", city, y, n)
    SC.stack.cache_clear()
    SC.dates.cache_clear()
    p = D.derived_path(city, "refstats.json")
    if force or not p.exists():
        st = refstats(city)
        json.dump(st, open(str(p) + ".tmp", "w"), indent=1)
        os.replace(str(p) + ".tmp", p)
        log.info("[%s] refstats written", city)
    log.info("[%s] done in %.0fs", city, time.time() - t0)


def main():
    warnings.simplefilter("ignore", RuntimeWarning)
    ap = argparse.ArgumentParser()
    ap.add_argument("cities", nargs="*", default=list(D.CITY_AOIS))
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    (D.DATA / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(D.DATA / "logs" / "precompute_cities.log"),
                                  logging.StreamHandler()])
    for c in a.cities:
        run(c, a.force)


if __name__ == "__main__":
    main()
