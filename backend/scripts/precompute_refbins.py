#!/usr/bin/env python3
"""sci-v3.6 elevation-matched reference for the preset cities: $UHD_DATA_DIR/<city>/refbins.npz.

Per metre of elevation (60 m DEM, $UHD_DATA_DIR/ukraine/dem60.tif) over the preset reference forest: pixel counts and
sums of the climatology, of the yearly composite LST and of every acquisition's LST and LST − climatology — the same
quantities as refstats.json, so `elevmatch.matched_stats` sums any ±100 m band exactly (uhd/docs/METHOD.md §4.1).
Needs precompute_cities.py (ref_masks, clim, scene stacks, refstats) and `python -m uhd.science.refquality --dem60`.
A few MB per city. Idempotent (--force). Usage: precompute_refbins.py [--force] [kyiv kharkiv lviv]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from uhd.science import data as D  # noqa: E402
from uhd.science import elevmatch as EM  # noqa: E402

log = logging.getLogger("precompute_refbins")


def run(city: str, force: bool) -> None:
    p = EM.refbins_path(city)
    if p.exists() and not force:
        log.info("[%s] %s exists (use --force)", city, p)
        return
    t0 = time.time()
    b = EM.build_refbins(city)
    tmp = str(p) + ".tmp.npz"
    np.savez_compressed(tmp, **b)
    os.replace(tmp, p)
    log.info("[%s] refbins: %d m of elevation bins from %d m, %d px; %d bytes in %.0fs", city, b["px"].size,
             int(b["emin"]), int(b["px"].sum()), p.stat().st_size, time.time() - t0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cities", nargs="*", default=list(D.CITY_AOIS))
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for c in a.cities:
        run(c, a.force)


if __name__ == "__main__":
    main()
