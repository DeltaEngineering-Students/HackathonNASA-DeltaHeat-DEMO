"""Per-scene (per-acquisition-date) LST stacks for the preset cities.

Raw per-scene files (/srv/landsat/<city>/scenes/<year>/<id>.lst.tif + .json) are windows on the city grid.
Scenes of the same date (adjacent WRS rows of one path) are mosaicked into one "acquisition".
Precomputed: $UHD_DATA_DIR/<city>/scenes/<year>.npy  int16 (n_dates, H, W), 0.01 °C, -32768 = no data
             $UHD_DATA_DIR/<city>/scenes/<year>.json [{date, ids, path, rows, cloud}]
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

import numpy as np
import rasterio

from . import data as D


def _items_cloud(aoi: str, year: int) -> dict[str, float]:
    p = D.RAW / aoi / "items" / f"{year}.json"
    if not p.exists():
        return {}
    return {d["id"]: d["properties"].get("eo:cloud_cover") for d in json.load(open(p))}


def raw_summer_metas(aoi: str, year: int) -> list[dict]:
    sdir = D.RAW / aoi / "scenes" / str(year)
    if not sdir.exists():
        return []
    out = []
    for f in sorted(os.listdir(sdir)):
        if not f.endswith(".json"):
            continue
        m = json.load(open(sdir / f))
        if m.get("summer") and m.get("n_clear", 0) > 0 and (sdir / f"{m['id']}.lst.tif").exists():
            out.append(m)
    return out


def path_row(scene_id: str) -> tuple[int, int]:
    pr = scene_id.split("_")[2]
    return int(pr[:3]), int(pr[3:])


def build_stack(city: str, year: int, force: bool = False) -> int:
    out_dir = D.derived_path(city, "scenes")
    out_dir.mkdir(parents=True, exist_ok=True)
    pn, pj = out_dir / f"{year}.npy", out_dir / f"{year}.json"
    if pn.exists() and pj.exists() and not force:
        return -1
    g = D.grid(city)
    metas = raw_summer_metas(city, year)
    cloud = _items_cloud(city, year)
    by_date: dict[str, list[dict]] = {}
    for m in metas:
        by_date.setdefault(m["date"], []).append(m)
    dates = sorted(by_date)
    arr = np.full((len(dates), g.height, g.width), D.LST_ND, np.int16)
    info = []
    sdir = D.RAW / city / "scenes" / str(year)
    for i, dt in enumerate(dates):
        ms = by_date[dt]
        for m in ms:
            with rasterio.open(sdir / f"{m['id']}.lst.tif") as s:
                a = s.read(1)
            r0, c0 = m["row_off"], m["col_off"]
            sub = arr[i, r0:r0 + a.shape[0], c0:c0 + a.shape[1]]
            fill = (sub == D.LST_ND) & (a != D.LST_ND)
            sub[fill] = a[fill]
        prs = [path_row(m["id"]) for m in ms]
        cl = [cloud.get(m["id"]) for m in ms if cloud.get(m["id"]) is not None]
        info.append(dict(date=dt, ids=[m["id"] for m in ms], path=prs[0][0], rows=sorted(r for _, r in prs),
                         cloud=round(float(np.mean(cl)), 1) if cl else None,
                         valid_px=int((arr[i] != D.LST_ND).sum())))
    tmp = str(pn) + ".tmp.npy"
    np.save(tmp, arr)
    os.replace(tmp, pn)
    json.dump(info, open(str(pj) + ".tmp", "w"))
    os.replace(str(pj) + ".tmp", pj)
    return len(dates)


def has_stack(city: str, year: int) -> bool:
    return (D.derived_path(city, "scenes") / f"{year}.npy").exists()


@lru_cache(maxsize=64)
def stack(city: str, year: int) -> np.ndarray:
    return np.load(D.derived_path(city, "scenes") / f"{year}.npy", mmap_mode="r")


@lru_cache(maxsize=64)
def dates(city: str, year: int) -> list[dict]:
    return json.load(open(D.derived_path(city, "scenes") / f"{year}.json"))


def window_lst(city: str, year: int, win: D.Win) -> np.ndarray:
    """(n_dates, h, w) float32 °C with NaN for a window fully inside the city grid."""
    r0, c0, h, w = win
    a = np.asarray(stack(city, year)[:, r0:r0 + h, c0:c0 + w])
    out = a.astype(np.float32) / 100.0
    out[a == D.LST_ND] = np.nan
    return out


def masked_means(a: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-date mean over mask pixels and valid share. a: (n, h, w) float with NaN."""
    n_mask = int(mask.sum())
    if n_mask == 0 or a.shape[0] == 0:
        return np.full(a.shape[0], np.nan), np.zeros(a.shape[0])
    v = a[:, mask]                       # (n, k)
    ok = np.isfinite(v)
    cnt = ok.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(cnt > 0, np.nansum(v, 1) / np.maximum(cnt, 1), np.nan)
    return mean, cnt / n_mask


@lru_cache(maxsize=4)
def clim(city: str) -> np.ndarray:
    """Per-pixel LST climatology (median of the 13 summer composites), float32 °C, city grid."""
    return np.load(D.derived_path(city, "clim.npy"), mmap_mode="r")


def masked_means_adjusted(a: np.ndarray, mask: np.ndarray, clim_win: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-date zone mean made independent of which part of the zone is visible:
    mean_zone(clim) + mean_visible(LST_d − clim). Pixels without climatology are dropped from the mask."""
    m = mask & np.isfinite(clim_win)
    anom, share = masked_means(a - clim_win, m)
    base = float(clim_win[m].mean()) if m.any() else np.nan
    return base + anom, share
