#!/usr/bin/env python3
"""NASA NEX-GDDP-CMIP6 (0.25 deg, daily, bias-corrected) cut to Europe, May-Sep — extension of pipeline/cmip6.py.

Fills QUESTIONS #5: the existing set has only historical 2005-2014 and ssp245/585 2041-2050 + 2071-2080 (tasmax).
This job adds the PLAN periods (historical 1995-2014, 2041-2060, 2081-2100) and the variables tasmin
(tropical nights = night-time heat) and tas, first for the 5 existing models, then for 5 more models.

Output: ROOT/extra/cmip6/<var>/<model>_<scenario>_<year>.npz  (same layout as cmip6.py):
  <var>_mjjas  int16 0.01 degC (153 days May1-Sep30, lat, lon), -32768 = no data (ocean)   jja_mean float32 degC
  tasmax: hot30, hot35 (days > 30/35 C, May-Sep);  tasmin: trop20 (nights > 20 C);  lat, lon
Only the May-Sep daily chunks are fetched (HTTP ranges, ~42 % of each 240 MB file); full download as fallback.
Files already present in /root/landsat/extra/cmip6 (old tasmax set) are skipped, not duplicated.
"""
import os, sys, time, json, subprocess, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

import numpy as np

OLD = "/root/landsat/extra/cmip6"
MODELS_A = ["ACCESS-CM2", "MPI-ESM1-2-HR", "EC-Earth3", "MRI-ESM2-0", "CNRM-ESM2-1"]   # = existing models.json
MODELS_B = ["NorESM2-MM", "GFDL-ESM4", "INM-CM5-0", "MIROC6", "CanESM5", "UKESM1-0-LL", "IPSL-CM6A-LR"]
LAT, LON = (34.0, 72.0), (-25.0, 45.0)
YEARS = [("historical", y) for y in range(1995, 2015)] + \
        [(s, y) for s in ("ssp245", "ssp585") for y in list(range(2041, 2061)) + list(range(2081, 2101))]
log = None
CONN = int(os.environ.get("CMIP6_CONN", "6"))


_CACHE, _LOCK = {}, __import__("threading").Lock()


def find_item(model, scen, year):
    """One STAC search per (model, scenario) — the PC API rate-limits per IP (HTTP 429), so no per-file searches."""
    with _LOCK:
        if (model, scen) not in _CACHE:
            its = C.stac_search("nasa-nex-gddp-cmip6", query={
                "cmip6:model": {"eq": model}, "cmip6:scenario": {"eq": scen}})
            _CACHE[(model, scen)] = {i["properties"]["cmip6:year"]: i for i in its}
            time.sleep(2)
    return _CACHE[(model, scen)].get(year)


def _sel(nt, lat, lon):
    if nt not in (365, 366, 360):
        raise RuntimeError(f"unsupported calendar ({nt} days)")
    d0 = 120 if nt == 360 else 120 + (1 if nt == 366 else 0)   # May 1 (360-day: day 121)
    lon180 = np.where(lon > 180, lon - 360, lon)
    la = np.where((lat >= LAT[0]) & (lat <= LAT[1]))[0]
    lo = np.where((lon180 >= LON[0]) & (lon180 <= LON[1]))[0]
    return d0, lon180, la, lo[np.argsort(lon180[lo])]


def read_mjjas_ranges(href, var):
    """Read only the May-Sep daily chunks (file is chunked 1 day x whole globe, gzip+shuffle): ~42 % of the bytes.
    HDF5 metadata via fsspec/h5py, then each chunk by an HTTP range request (parallel), decoded with zlib."""
    import zlib, fsspec, h5py, requests
    from concurrent.futures import ThreadPoolExecutor
    with fsspec.filesystem("http").open(href, block_size=1 << 20) as fh, h5py.File(fh, "r") as f:
        v = f[var]
        nt, ny, nx = v.shape
        if v.chunks != (1, ny, nx) or v.compression != "gzip" or v.fletcher32 or v.dtype != np.float32:
            raise RuntimeError(f"unexpected layout chunks={v.chunks} comp={v.compression}")
        shuffle = v.shuffle
        lat, lon = f["lat"][:], f["lon"][:]
        d0, lon180, la, order = _sel(nt, lat, lon)
        info = [v.id.get_chunk_info_by_coord((d, 0, 0)) for d in range(d0, d0 + 153)]
        fill = v.fillvalue
    sess = requests.Session()

    def get(ci):
        for attempt in range(6):
            try:
                r = sess.get(href, headers={"Range": f"bytes={ci.byte_offset}-{ci.byte_offset + ci.size - 1}",
                                            "User-Agent": C.UA}, timeout=120)
                if r.status_code == 206 and len(r.content) == ci.size:
                    b = np.frombuffer(zlib.decompress(r.content), np.uint8)
                    if shuffle:
                        b = b.reshape(4, -1).T.copy()
                    g = b.view(np.float32).reshape(ny, nx)[la[0]:la[-1] + 1][:, order]
                    return np.where(g >= fill * 0.99, np.nan, g)
                raise RuntimeError(f"http {r.status_code} len {len(r.content)}")
            except Exception:  # noqa
                if attempt == 5:
                    raise
                time.sleep(10 * (attempt + 1))

    with ThreadPoolExecutor(CONN) as ex:
        a = np.stack(list(ex.map(get, info))) - 273.15
    return a, lat, lon180, la, order, nt


def read_mjjas_full(href, var, tmp):
    import h5py
    pget = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pget.py")
    for attempt in range(6):   # the source gives ~1 MB/s per connection: ranged parallel download (pget.py)
        r = subprocess.run([sys.executable, pget, href, tmp, str(CONN)], capture_output=True)
        if r.returncode == 0:
            break
        time.sleep(30 * (attempt + 1))
    else:
        raise RuntimeError(f"download failed rc={r.returncode} {r.stderr[-200:]!r}")
    try:
        with h5py.File(tmp, "r") as f:
            v = f[var]
            nt = v.shape[0]
            lat, lon = f["lat"][:], f["lon"][:]
            d0, lon180, la, order = _sel(nt, lat, lon)
            a = v[d0:d0 + 153, la[0]:la[-1] + 1, :][:, :, order] - 273.15
    finally:
        os.remove(tmp)
    return a, lat, lon180, la, order, nt


def process(var, model, scen, year, out_dir, tmp_dir):
    import h5py
    import planetary_computer as pc
    out = f"{out_dir}/{model}_{scen}_{year}.npz"
    if os.path.exists(out) or (var == "tasmax" and os.path.exists(f"{OLD}/{model}_{scen}_{year}.npz")):
        return "skip"
    C.check_disk()
    it = find_item(model, scen, year)
    if it is None or var not in it["assets"]:
        return "missing"
    href = pc.sign(it["assets"][var]["href"])
    try:
        a, lat, lon180, la, order, nt = read_mjjas_ranges(href, var)
    except Exception as e:  # noqa
        log.warning("%s %s %s %d: ranged read failed (%s), full download", var, model, scen, year, str(e)[:150])
        a, lat, lon180, la, order, nt = read_mjjas_full(href, var, f"{tmp_dir}/{var}_{model}_{scen}_{year}.nc")
    a[np.abs(a) > 200] = np.nan                     # fill values (1e20 over the ocean) -> NaN
    ok = np.isfinite(a)
    q = np.full(a.shape, -32768, np.int16)
    q[ok] = np.round(a[ok] * 100).astype(np.int16)
    extra = {}
    if var == "tasmax":
        extra = dict(hot30=(a > 30).sum(0).astype(np.uint8), hot35=(a > 35).sum(0).astype(np.uint8))
    elif var == "tasmin":
        extra = dict(trop20=(a > 20).sum(0).astype(np.uint8))
    with np.errstate(all="ignore"):
        jja = np.nanmean(a[31:31 + 92], 0).astype(np.float32)
    np.savez_compressed(out + ".tmp.npz", **{f"{var}_mjjas": q}, nodata=np.int16(-32768),
                        jja_mean=jja, calendar_days=np.int16(nt),
                        lat=lat[la].astype(np.float32), lon=lon180[order].astype(np.float32), **extra)
    os.replace(out + ".tmp.npz", out)
    return "ok"


def main():
    global log
    ap = argparse.ArgumentParser()
    ap.add_argument("--par", type=int, default=8)
    ap.add_argument("--stages", default="0,1,2,3,4", help="indices into the stage list below")
    a = ap.parse_args()
    log = C.setup_log("cmip6_ext")
    base = f"{C.ROOT}/extra/cmip6"
    tmp_dir = f"{C.ROOT}/extra/tmp_cmip6"
    os.makedirs(tmp_dir, exist_ok=True)
    import shutil
    for f in os.listdir(tmp_dir):
        shutil.rmtree(f"{tmp_dir}/{f}") if os.path.isdir(f"{tmp_dir}/{f}") else os.remove(f"{tmp_dir}/{f}")
    # priority order: tasmax for the 5 models (PLAN periods) -> tasmin -> tas -> tasmax/tasmin for more models
    stages = [("tasmax", MODELS_A), ("tasmin", MODELS_A), ("tas", MODELS_A), ("tasmax", MODELS_B), ("tasmin", MODELS_B)]
    stages = [stages[int(i)] for i in a.stages.split(",")]
    try:
        for var, models in stages:
            out_dir = f"{base}/{var}"
            os.makedirs(out_dir, exist_ok=True)
            tasks = [(var, m, s, y) for m in models for s, y in YEARS]
            t0, done, res = time.time(), 0, {}
            log.info("stage %s %s: %d files", var, models, len(tasks))
            with ThreadPoolExecutor(a.par) as ex:
                futs = {ex.submit(process, *t, out_dir, tmp_dir): t for t in tasks}
                for f in as_completed(futs):
                    done += 1
                    try:
                        r = f.result()
                    except C.DiskFull:
                        raise
                    except Exception as e:  # noqa
                        r = "fail"
                        log.warning("%s failed: %s", futs[f], str(e)[:200])
                    res[r] = res.get(r, 0) + 1
                    if r == "missing":
                        log.info("missing on source: %s", futs[f])
                    if done % 20 == 0 or done == len(tasks):
                        log.info("[%s] %d/%d %s %.0fs", var, done, len(tasks), res, time.time() - t0)
            n = len([x for x in os.listdir(out_dir) if x.endswith(".npz")])
            C.manifest_update(f"cmip6/{var}", path=out_dir, files=n, models_stage=models, result=res,
                              grid="0.25 deg lat/lon, Europe 34-72N 25W-45E, May-Sep daily")
        log.info("CMIP6 EXT DONE")
    except C.DiskFull as e:
        log.warning("stopping: %s", e)
        sys.exit(75)


if __name__ == "__main__":
    main()
