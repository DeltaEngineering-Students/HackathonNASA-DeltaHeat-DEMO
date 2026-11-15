#!/usr/bin/env python3
"""CMIP6 summary for climate_projection(): $UHD_DATA_DIR/climate/cmip6_summary.npz (idempotent, --force)."""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from uhd.science import climate as CL  # noqa: E402
from uhd.science import data as D  # noqa: E402

log = logging.getLogger("precompute_climate")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--v2", default=None, metavar="RAW_DIR",
                    help="CMIP6 v2 proposal: build from the yearly tasmax files in RAW_DIR (20-year windows); "
                         "needs --out (activation = copying it over cmip6_summary.npz, after the user's decision)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    (D.DATA / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(D.DATA / "logs" / "precompute_climate.log"),
                                  logging.StreamHandler()])
    from pathlib import Path
    if a.v2 and not a.out:
        raise SystemExit("--v2 needs --out (the live summary is replaced only after the user's decision)")
    p = Path(a.out) if a.out else CL.summary_path()
    if p.exists() and not a.force:
        log.info("exists, skip: %s", p)
        return
    t0 = time.time()
    s = CL.build_summary_v2(a.v2) if a.v2 else CL.build_summary()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(p) + ".tmp.npz"
    np.savez_compressed(tmp, **s)
    os.replace(tmp, p)
    log.info("written %s (%d arrays) in %.0fs", p, len(s), time.time() - t0)


if __name__ == "__main__":
    main()
