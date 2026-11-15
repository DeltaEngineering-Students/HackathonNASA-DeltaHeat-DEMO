#!/usr/bin/env python3
"""NASA NEX-GDDP-CMIP6 daily max air temperature (tasmax, 0.25 deg) cut to Europe.

Minimal set: 5 models x (historical 2005-2014, ssp245 + ssp585 for 2041-2050 and 2071-2080).
Files on the source are global daily maps (one chunk per day), so each file is downloaded whole,
cut to Europe May-Sep, and the global file is deleted.

Output per (model, scenario, year): extra/cmip6/<model>_<scenario>_<year>.npz
  tasmax_mjjas  int16, 0.01 degC, (153 days May1-Sep30, lat, lon)   -- raw daily, Europe
  jja_mean      float32 degC   (summer mean of daily max)
  hot30, hot35  uint8          (days with tasmax > 30 / > 35 degC, May-Sep)
  lat, lon      grid (lon in -180..180)
"""
import os, sys, time, json, logging, subprocess, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import h5py
import pystac_client
import planetary_computer as pc

OUT = "/root/landsat/extra/cmip6"
TMP = "/root/landsat/extra/tmp"
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
CANDIDATES = ["ACCESS-CM2", "MPI-ESM1-2-HR", "EC-Earth3", "MRI-ESM2-0", "CNRM-ESM2-1",
              "NorESM2-MM", "GFDL-ESM4", "INM-CM5-0", "MIROC6", "CanESM5"]
N_MODELS = 5
LAT = (34.0, 72.0)
LON = (-25.0, 45.0)
JOBS = [("historical", y) for y in range(2005, 2015)] + \
       [(s, y) for s in ("ssp245", "ssp585") for y in list(range(2041, 2051)) + list(range(2071, 2081))]
N_PAR = 16

log = logging.getLogger("cmip6")


def item(cat, model, scen, year):
    its = list(cat.search(collections=["nasa-nex-gddp-cmip6"], query={
        "cmip6:model": {"eq": model}, "cmip6:scenario": {"eq": scen}, "cmip6:year": {"eq": year}}).items())
    return its[0] if its else None


def pick_models(cat):
    models = []
    for m in CANDIDATES:
        ok = all(item(cat, m, s, y) is not None for s, y in (("historical", 2010), ("ssp245", 2045), ("ssp585", 2075)))
        log.info("model %s available=%s", m, ok)
        if ok:
            models.append(m)
        if len(models) == N_MODELS:
            break
    return models


def process(model, scen, year):
    out = f"{OUT}/{model}_{scen}_{year}.npz"
    if os.path.exists(out):
        return "skip"
    cat = pystac_client.Client.open(STAC)
    it = item(cat, model, scen, year)
    if it is None:
        raise RuntimeError("no item")
    tmp = f"{TMP}/{model}_{scen}_{year}.nc"
    for attempt in range(6):
        href = pc.sign(it.assets["tasmax"].href)
        r = subprocess.run(["curl", "-sf", "--retry", "5", "--max-time", "3600", "-o", tmp, href])
        if r.returncode == 0:
            break
        time.sleep(30 * (attempt + 1))
    else:
        raise RuntimeError(f"download failed rc={r.returncode}")
    try:
        with h5py.File(tmp, "r") as f:
            v = f["tasmax"]
            nt = v.shape[0]
            if nt not in (365, 366):
                raise RuntimeError(f"unsupported calendar ({nt} days)")
            d0 = 120 + (1 if nt == 366 else 0)          # May 1
            lat = f["lat"][:]
            lon = f["lon"][:]
            lon180 = np.where(lon > 180, lon - 360, lon)
            la = np.where((lat >= LAT[0]) & (lat <= LAT[1]))[0]
            lo = np.where((lon180 >= LON[0]) & (lon180 <= LON[1]))[0]
            order = lo[np.argsort(lon180[lo])]
            a = v[d0:d0 + 153, la[0]:la[-1] + 1, :][:, :, order] - 273.15   # May-Sep, Europe
    finally:
        os.remove(tmp)
    jja = a[31:31 + 92]
    np.savez_compressed(out + ".tmp.npz",
                        tasmax_mjjas=np.round(a * 100).astype(np.int16),
                        jja_mean=jja.mean(0).astype(np.float32),
                        hot30=(a > 30).sum(0).astype(np.uint8), hot35=(a > 35).sum(0).astype(np.uint8),
                        lat=lat[la].astype(np.float32), lon=lon180[order].astype(np.float32))
    os.replace(out + ".tmp.npz", out)
    return "ok"


def main():
    os.makedirs(OUT, exist_ok=True); os.makedirs(TMP, exist_ok=True)
    for f in os.listdir(TMP):
        os.remove(f"{TMP}/{f}")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler("/root/landsat/logs/cmip6.log"), logging.StreamHandler()])
    cat = pystac_client.Client.open(STAC)
    mpath = f"{OUT}/models.json"
    models = json.load(open(mpath)) if os.path.exists(mpath) else pick_models(cat)
    json.dump(models, open(mpath, "w"))
    log.info("models: %s", models)
    tasks = [(m, s, y) for m in models for s, y in JOBS]
    done = fails = 0
    t0 = time.time()
    with ThreadPoolExecutor(N_PAR) as ex:
        futs = {ex.submit(process, *t): t for t in tasks}
        for f in as_completed(futs):
            done += 1
            try:
                f.result()
            except Exception as e:  # noqa
                fails += 1
                log.warning("%s failed: %s", futs[f], e)
            if done % 5 == 0 or done == len(tasks):
                log.info("%d/%d files, failed=%d, %.0fs", done, len(tasks), fails, time.time() - t0)
    if fails:
        raise SystemExit(f"{fails} files failed")
    log.info("CMIP6 DONE")


if __name__ == "__main__":
    main()
