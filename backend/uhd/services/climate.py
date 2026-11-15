"""CMIP6 (NASA NEX-GDDP-CMIP6, tasmax) summer projection at a point.

Inputs: ``{landsat_dir}/extra/cmip6/<model>_<scenario>_<year>.npz`` with ``jja_mean`` (°C, mean daily max Jun–Aug),
``hot30``/``hot35`` (days May–Sep with tasmax > 30/35 °C), ``lat``/``lon`` (0.25°).
Fallback only: ``/api/climate`` serves science's summary (CMIP6 v2: median of 12 models with the 10–90 % range,
2041–2060 and 2081–2100 vs 1995–2014). This path is used only when that summary is missing; it computes from the raw
per-year files that exist on disk (historical 2005–2014, ssp245/ssp585 2041–2050 and 2071–2080).
A compact summary cube is built once and cached in ``{cache_dir}/climate/``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np

from uhd.config import get_settings
from uhd.errors import APIError, bad_request
from uhd.services.num import rnd

log = logging.getLogger(__name__)
PERIODS = {"baseline": ("historical", 2005, 2014), "mid": (None, 2041, 2050), "late": (None, 2071, 2080)}
SCENARIOS = ("ssp245", "ssp585")
_lock = threading.Lock()
_FNAME = re.compile(r"^(?P<model>.+)_(?P<scen>historical|ssp\d{3})_(?P<year>\d{4})\.npz$")


def _src() -> Path:
    return get_settings().landsat_dir / "extra" / "cmip6"


def _cube_path() -> Path:
    p = get_settings().cache_dir / "climate"
    p.mkdir(parents=True, exist_ok=True)
    return p / "cmip6_summary_v1.npz"


def _build_cube() -> dict:
    src = _src()
    files = sorted(f for f in os.listdir(src) if _FNAME.match(f))
    if not files:
        raise APIError(503, "climate_data_missing", "CMIP6 files not found")
    models = sorted({_FNAME.match(f)["model"] for f in files})
    keys = sorted({(m["scen"], int(m["year"])) for f in files if (m := _FNAME.match(f))})
    lat = lon = None
    jja = hot30 = hot35 = None
    for f in files:
        m = _FNAME.match(f)
        z = np.load(src / f)
        if lat is None:
            lat, lon = z["lat"], z["lon"]
            shp = (len(models), len(keys), len(lat), len(lon))
            jja = np.full(shp, np.nan, np.float32)
            hot30 = np.zeros(shp, np.uint8)
            hot35 = np.zeros(shp, np.uint8)
        i, j = models.index(m["model"]), keys.index((m["scen"], int(m["year"])))
        jja[i, j] = z["jja_mean"]
        hot30[i, j] = z["hot30"]
        hot35[i, j] = z["hot35"]
    out = {"models": np.array(models), "scen": np.array([k[0] for k in keys]), "year": np.array([k[1] for k in keys]),
           "lat": lat, "lon": lon, "jja": jja, "hot30": hot30, "hot35": hot35}
    tmp = str(_cube_path()) + ".tmp.npz"
    np.savez(tmp, **out)
    os.replace(tmp, _cube_path())
    return out


@lru_cache(maxsize=1)
def cube() -> dict:
    with _lock:
        p = _cube_path()
        if p.exists():
            with np.load(p) as z:
                return {k: z[k] for k in z.files}
        log.info("building CMIP6 summary cube")
        return _build_cube()


def _stats(vals: np.ndarray) -> dict:
    v = vals[np.isfinite(vals)]
    if not len(v):
        return {"median": None, "min": None, "max": None, "n_models": 0}
    return {"median": rnd(np.median(v), 2), "min": rnd(v.min(), 2), "max": rnd(v.max(), 2),
            "n_models": int(len(v))}


def projection(lat: float, lon: float) -> dict:
    """Prefer the science package (METHOD.md §0.2); this module's own summary is the fallback."""
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise bad_request("invalid_coordinates", "lat/lon out of range")
    from uhd.services import science

    if science.has_helper("climate_projection"):
        try:
            out = science.helper("climate_projection", lat, lon)
            out.setdefault("caveats", [{"code": "air_not_surface",
                                        "text_uk": "Це прогноз приземної температури повітря (на висоті 2 м), а не температури поверхні з Landsat."}])
            out["source_impl"] = "science"
            return out
        except APIError:
            raise
        except FileNotFoundError:
            log.warning("science climate summary missing; using backend fallback")
    return _projection_fallback(lat, lon)


def _projection_fallback(lat: float, lon: float) -> dict:
    c = cube()
    if not (c["lat"].min() - 0.2 <= lat <= c["lat"].max() + 0.2 and c["lon"].min() - 0.2 <= lon <= c["lon"].max() + 0.2):
        raise bad_request("outside_coverage", "CMIP6 subset covers Europe only")
    iy, ix = int(np.abs(c["lat"] - lat).argmin()), int(np.abs(c["lon"] - lon).argmin())
    models = [str(m) for m in c["models"]]

    def per_model(scen: str, y0: int, y1: int, var: str) -> np.ndarray:
        sel = (c["scen"] == scen) & (c["year"] >= y0) & (c["year"] <= y1)
        if not sel.any():
            return np.full(len(models), np.nan)
        a = c[var][:, sel, iy, ix].astype(np.float64)
        if var == "jja":
            return np.nanmean(a, axis=1)
        return a.mean(axis=1)

    _, b0, b1 = PERIODS["baseline"]
    base_t = per_model("historical", b0, b1, "jja")
    base_h30 = per_model("historical", b0, b1, "hot30")
    base_h35 = per_model("historical", b0, b1, "hot35")
    out = {
        "lat": lat, "lon": lon, "grid_lat": round(float(c["lat"][iy]), 3), "grid_lon": round(float(c["lon"][ix]), 3),
        "variable": "tasmax", "variable_uk": "денний максимум приземної температури повітря (на висоті 2 м), не температура поверхні",
        "baseline": {"period": [b0, b1], "jja_tasmax": _stats(base_t), "hot30_days": _stats(base_h30),
                     "hot35_days": _stats(base_h35)},
        "scenarios": {}, "models": models,
        "source": "NASA NEX-GDDP-CMIP6 (0.25°, bias-corrected, downscaled), 5 models",
        "caveats": [{"code": "air_not_surface", "text_uk": "Це прогноз приземної температури повітря (на висоті 2 м), а не температури поверхні з Landsat."}],
    }
    for scen in SCENARIOS:
        out["scenarios"][scen] = {}
        for pname in ("mid", "late"):
            _, y0, y1 = PERIODS[pname]
            t = per_model(scen, y0, y1, "jja")
            out["scenarios"][scen][pname] = {
                "period": [y0, y1], "jja_tasmax": _stats(t), "delta_jja_tasmax": _stats(t - base_t),
                "hot30_days": _stats(per_model(scen, y0, y1, "hot30")),
                "delta_hot30_days": _stats(per_model(scen, y0, y1, "hot30") - base_h30),
                "hot35_days": _stats(per_model(scen, y0, y1, "hot35")),
                "delta_hot35_days": _stats(per_model(scen, y0, y1, "hot35") - base_h35),
            }
    return json.loads(json.dumps(out))
