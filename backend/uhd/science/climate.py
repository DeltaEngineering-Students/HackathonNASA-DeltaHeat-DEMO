"""CMIP6 (NASA NEX-GDDP-CMIP6, 0.25°) summer daily-max AIR temperature projections for a point.

Active since 15.11 (user's decision after the mentor review): **v2** — 12 models, 20-year windows 1995–2014 →
2041–2060 / 2081–2100, median across models with the P10–P90 range (``build_summary_v2``, ``_projection_v2``; the
summary file is stamped ``version=v2``). v1 below (5 models, 10-year windows, ensemble mean, min–max) is kept for
reproducing old numbers: $UHD_DATA_DIR/climate/cmip6_summary_v1.npz.

v1 raw: /srv/landsat/extra/cmip6/<model>_<scenario>_<year>.npz (jja_mean, hot30, hot35, lat, lon; Europe cut),
     models.json. Periods on disk: historical 2005–2014, ssp245/ssp585 2041–2050 and 2071–2080.
Precomputed by scripts/precompute_climate.py: $UHD_DATA_DIR/climate/cmip6_summary.npz with, per model and
period, the mean of jja_mean / hot30 / hot35 over the 10 years, cut to Ukraine (+1°).
"""
from __future__ import annotations

import json
from functools import lru_cache

import numpy as np

from . import data as D
from .stats import rnd

PERIODS = {"historical": (2005, 2014), "2041-2050": (2041, 2050), "2071-2080": (2071, 2080)}
SCENARIOS = ("ssp245", "ssp585")
BBOX = (43.0, 54.0, 21.0, 42.0)  # lat0, lat1, lon0, lon1
LABEL_UK = ("Прогноз кліматичних моделей CMIP6 (NASA NEX-GDDP): середня денна максимальна приземна "
            "температура повітря (на висоті 2 м) влітку (червень–серпень), комірка сітки ≈25 км. Це не температура поверхні (LST) і не прогноз "
            "для окремого району.")


def raw_dir():
    return D.RAW / "extra" / "cmip6"


def summary_path():
    return D.DATA / "climate" / "cmip6_summary.npz"


def models() -> list[str]:
    return json.load(open(raw_dir() / "models.json"))


def build_summary() -> dict[str, np.ndarray]:
    """Average the yearly npz files per model/scenario/period (used by the precompute script)."""
    out: dict[str, np.ndarray] = {}
    lat = lon = None
    for m in models():
        for scen, per in [("historical", "historical")] + [(s, p) for s in SCENARIOS for p in PERIODS if
                                                            p != "historical"]:
            y0, y1 = PERIODS[per]
            acc = {k: [] for k in ("jja_mean", "hot30", "hot35")}
            for y in range(y0, y1 + 1):
                p = raw_dir() / f"{m}_{scen}_{y}.npz"
                if not p.exists():
                    continue
                z = np.load(p)
                if lat is None:
                    la, lo = z["lat"], z["lon"]
                    iy = np.where((la >= BBOX[0]) & (la <= BBOX[1]))[0]
                    ix = np.where((lo >= BBOX[2]) & (lo <= BBOX[3]))[0]
                    lat, lon = la[iy], lo[ix]
                sl = (slice(iy[0], iy[-1] + 1), slice(ix[0], ix[-1] + 1))
                for k in acc:
                    acc[k].append(z[k][sl].astype(np.float32))
            if not acc["jja_mean"]:
                continue
            for k, v in acc.items():
                out[f"{m}|{scen}|{per}|{k}"] = np.mean(v, axis=0).astype(np.float32)
            out[f"{m}|{scen}|{per}|n_years"] = np.array(len(acc["jja_mean"]))
    out["lat"], out["lon"] = lat, lon
    return out


# ------------------------------------------------------------------ CMIP6 v2 (active, METHOD.md §9b)
# Mentor review 15.11: 20-year windows, more models, median and P10–P90 across models. Built from the yearly files of
# the homelab job cmip6_ext.py (<dir>/<model>_<scen>_<year>.npz, tasmax_mjjas + jja_mean + hot30/hot35). Activated by
# putting the v2 file in place of cmip6_summary.npz (done 15.11, user's decision); the code reads both.
PERIODS_V2 = {"historical": (1995, 2014), "2041-2060": (2041, 2060), "2081-2100": (2081, 2100)}
CLIMATE_VERSION_V2 = "cmip6-v2"   # in every v2 answer: 20-year windows, median + P10–P90 (v1 answers have none)
MIN_YEAR_SHARE = 0.8          # a model counts for a window only with >= 80 % of its years


def build_summary_v2(raw: str, keys=("jja_mean", "hot30", "hot35")) -> dict[str, np.ndarray]:
    """Per model and window: mean over the years of each key, cut to Ukraine (+1°). Models = those with files."""
    import glob
    import os

    files = glob.glob(os.path.join(raw, "*.npz"))
    ms = sorted({os.path.basename(f).split("_")[0] for f in files})
    out: dict[str, np.ndarray] = {}
    sl = lat = lon = None
    for m in ms:
        for scen, per in [("historical", "historical")] + [(sc, p) for sc in SCENARIOS for p in PERIODS_V2
                                                           if p != "historical"]:
            y0, y1 = PERIODS_V2[per]
            acc = {k: [] for k in keys}
            for y in range(y0, y1 + 1):
                p = os.path.join(raw, f"{m}_{scen}_{y}.npz")
                if not os.path.exists(p):
                    continue
                z = np.load(p)
                if sl is None:
                    la, lo = z["lat"], z["lon"]
                    iy = np.where((la >= BBOX[0]) & (la <= BBOX[1]))[0]
                    ix = np.where((lo >= BBOX[2]) & (lo <= BBOX[3]))[0]
                    sl = (slice(iy[0], iy[-1] + 1), slice(ix[0], ix[-1] + 1))
                    lat, lon = la[iy], lo[ix]
                for k in keys:
                    if k in z.files:
                        acc[k].append(z[k][sl].astype(np.float32))
            n = len(acc["jja_mean"])
            if n < MIN_YEAR_SHARE * (y1 - y0 + 1):
                continue
            for k, v in acc.items():
                if v:
                    out[f"{m}|{scen}|{per}|{k}"] = np.mean(v, axis=0).astype(np.float32)
            out[f"{m}|{scen}|{per}|n_years"] = np.array(n)
    out["lat"], out["lon"] = lat, lon
    out["version"] = np.array("v2")
    return out


def _projection_v2(s: dict, lat: float, lon: float, iy: int, ix: int) -> dict:
    """Median across models with the P10–P90 range (no ensemble mean as the headline)."""
    la, lo = s["lat"], s["lon"]
    ms = sorted({k.split("|")[0] for k in s if "|" in k})

    def val(m, scen, per, k):
        key = f"{m}|{scen}|{per}|{k}"
        return float(s[key][iy, ix]) if key in s else np.nan

    def stats(v):
        v = np.asarray([x for x in v if np.isfinite(x)])
        if not v.size:
            return None, [None, None], 0
        return _r(float(np.median(v))), [_r(float(np.percentile(v, 10))), _r(float(np.percentile(v, 90)))], int(v.size)

    base = {m: val(m, "historical", "historical", "jja_mean") for m in ms}
    base_hot = {m: val(m, "historical", "historical", "hot30") for m in ms}
    bm, _, _ = stats(base.values())
    bh, _, _ = stats(base_hot.values())
    out = dict(lat=lat, lon=lon, cell=[_r(float(la[iy]), 3), _r(float(lo[ix]), 3)], variable="tasmax", unit="°C",
               label_uk=LABEL_UK, models=[m for m in ms if np.isfinite(base[m])], statistic="median_p10_p90",
               climate_version=CLIMATE_VERSION_V2,
               baseline=dict(period=list(PERIODS_V2["historical"]), jja_mean=bm, hot30_days=None if bh is None else _r(bh, 1)))
    for scen in SCENARIOS:
        blk = {}
        for per in ("2041-2060", "2081-2100"):
            d = [val(m, scen, per, "jja_mean") - base[m] for m in ms]
            med, rng, n = stats(d)
            hm, _, _ = stats([val(m, scen, per, "hot30") for m in ms])
            fm, _, _ = stats([val(m, scen, per, "jja_mean") for m in ms])
            blk[per] = dict(delta=med, delta_range=rng, delta_stat="median_p10_p90", jja_mean=fm,
                            hot30_days=None if hm is None else _r(hm, 1), n_models=n)
        out[scen] = blk
    return out


@lru_cache(maxsize=1)
def _summary() -> dict[str, np.ndarray]:
    z = np.load(summary_path())
    return {k: z[k] for k in z.files}


def _r(v, nd=2):
    return rnd(v, nd)


def climate_projection(lat: float, lon: float) -> dict:
    s = _summary()
    la, lo = s["lat"], s["lon"]
    if not (la.min() - 0.5 <= lat <= la.max() + 0.5 and lo.min() - 0.5 <= lon <= lo.max() + 0.5):
        from .geometry import ScienceError
        raise ScienceError("outside_coverage", "Точка поза межами кліматичних даних (Україна).")
    iy, ix = int(np.abs(la - lat).argmin()), int(np.abs(lo - lon).argmin())
    if "version" in s and str(s["version"]) == "v2":
        return _projection_v2(s, lat, lon, iy, ix)
    ms = sorted({k.split("|")[0] for k in s if "|" in k})

    def val(m, scen, per, k):
        key = f"{m}|{scen}|{per}|{k}"
        return float(s[key][iy, ix]) if key in s else np.nan

    base = {m: val(m, "historical", "historical", "jja_mean") for m in ms}
    base_hot = {m: val(m, "historical", "historical", "hot30") for m in ms}
    out = dict(lat=lat, lon=lon, cell=[_r(float(la[iy]), 3), _r(float(lo[ix]), 3)], variable="tasmax", unit="°C",
               label_uk=LABEL_UK, models=ms,
               baseline=dict(period=list(PERIODS["historical"]), jja_mean=_r(np.nanmean(list(base.values()))),
                             hot30_days=_r(np.nanmean(list(base_hot.values())), 1)))
    for scen in SCENARIOS:
        blk = {}
        for per in ("2041-2050", "2071-2080"):
            d = np.array([val(m, scen, per, "jja_mean") - base[m] for m in ms])
            h = np.array([val(m, scen, per, "hot30") for m in ms])
            d = d[np.isfinite(d)]
            blk[per] = dict(delta=_r(d.mean()) if d.size else None,
                            delta_range=[_r(d.min()), _r(d.max())] if d.size else [None, None],
                            jja_mean=_r(np.nanmean([val(m, scen, per, "jja_mean") for m in ms])),
                            hot30_days=_r(np.nanmean(h), 1), n_models=int(d.size))
        out[scen] = blk
    return out
