"""Elevation-matched reference forest (sci-v3.6, INVESTIGATION-REGIONAL-GAP fix 3 «C»).

The stable-forest reference keeps only the forest pixels whose elevation is within ±MATCH_M (100 m) of the median
elevation of the zone's built basis (always-built pixels, else built in the last year, else the whole zone — the same
pixels as the ``ref_higher`` caveat). Mountain forest is cooler than the valley a city sits in (Ужгород, Сімферополь,
Севастополь, Чернівці, Івано-Франківськ), so an unmatched reference overstates the gap.

* ``matched``    — some forest was dropped and ≥ MIN_MATCH_PX remain: the report uses the matched reference.
* ``all_within`` — every forest pixel is already within the band: nothing changes (flat places: Київ, Одеса, …).
* ``fallback``   — fewer than MIN_MATCH_PX matched pixels: the whole forest is kept (``ref_higher`` may still warn).
* ``unavailable`` — no 60 m DEM (or no refbins for a preset city) or no elevation for the zone: not evaluated, the
  whole forest is kept.

DEM: ``$UHD_DATA_DIR/ukraine/dem60.tif`` (``python -m uhd.science.refquality --dem60``): Copernicus DEM GLO-90,
bilinear on the 60 m ukraine grid, int16 m. Preset cities (per-scene method) read their matched per-date reference from
``<city>/refbins.npz`` (``scripts/precompute_refbins.py``): per-metre-of-elevation sums of the same quantities as
``refstats.json``, so any ±100 m band is summed exactly without reading the scene stacks.
"""
from __future__ import annotations

import dataclasses
import logging
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import classes as C
from . import data as D
from ._lru import LRU

log = logging.getLogger("uhd.science.elevmatch")
MATCH_M = 100.0
MIN_MATCH_PX = 200
MIN_BASIS_PX = 50
DEM_ND = -32768


def dem60_path() -> Path:
    return D.DATA / "ukraine" / "dem60.tif"


def refbins_path(city: str) -> Path:
    return D.derived_path(city, "refbins.npz")


_DEM_CACHE = LRU(16, maxbytes=48 * 2**20, sizeof=lambda a: a.nbytes)


def dem_window(aoi: str, win: D.Win) -> np.ndarray | None:
    """int16 elevation (m, DEM_ND = none) on an aoi window (city grids are aligned with the ukraine grid); None
    without the DEM file."""
    p = dem60_path()
    if not p.exists():
        return None
    k = (aoi, tuple(int(v) for v in win))
    a = _DEM_CACHE.get(k)
    if a is None:
        dr, dc = (0, 0) if aoi == "ukraine" else D.grid(aoi).offset_of(D.grid("ukraine"))
        r0, c0, h, w = win
        a = D.read_tif(p, (r0 + dr, c0 + dc, h, w), fill=DEM_ND).astype(np.int16)
        _DEM_CACHE.put(k, a)
    return a


def basis_pixels(ctx) -> np.ndarray:
    """The zone's built basis: always-built pixels, else built in the last year, else the whole zone."""
    basis = ctx.basis_mask("always_built")
    if basis is None or basis.sum() < MIN_BASIS_PX:
        basis = ctx.zone.mask & (ctx.cls[-1] == C.BUILT)
    if basis.sum() < MIN_BASIS_PX:
        basis = ctx.zone.mask
    return basis


@dataclass
class Match:
    status: str                              # matched | all_within | fallback | unavailable
    zone_elev_m: float | None = None
    band_m: tuple[int, int] | None = None    # inclusive integer-metre band [lo, hi]
    dz_before_m: float | None = None         # median forest − median basis elevation, whole forest
    dz_after_m: float | None = None          # the same for the reference actually used
    px_kept: int | None = None               # forest pixels inside the band
    px_total: int | None = None              # forest pixels of the unmatched reference
    mask: np.ndarray | None = None           # matched reference mask (ref window), only for ``matched``

    @property
    def applied(self) -> bool:
        return self.status == "matched"

    def info(self) -> dict:
        r = lambda v: None if v is None else round(float(v), 1)  # noqa: E731
        return dict(applied=self.applied, status=self.status, tolerance_m=int(MATCH_M), min_px=MIN_MATCH_PX,
                    zone_elev_m=r(self.zone_elev_m), dz_before_m=r(self.dz_before_m), dz_after_m=r(self.dz_after_m),
                    px_kept=self.px_kept, px_total=self.px_total)


SHOW_DROP_SHARE = 0.05         # caveat ref_elev_matched only when ≥ 5 % of the ring forest is dropped
SHOW_DZ_CHANGE_M = 20.0        # … or the median elevation difference moves by ≥ 20 m


def shown(m: "Match") -> bool:
    """Whether the applied match changes the forest enough to say so in the report (the fields are always there)."""
    if not m.applied or not m.px_total:
        return False
    dropped = 1 - m.px_kept / m.px_total
    ddz = abs((m.dz_before_m or 0.0) - (m.dz_after_m or 0.0))
    return dropped >= SHOW_DROP_SHARE or ddz >= SHOW_DZ_CHANGE_M


def band(zone_elev: float) -> tuple[int, int]:
    """Integer elevations e with |e − zone_elev| ≤ MATCH_M."""
    return int(math.ceil(zone_elev - MATCH_M)), int(math.floor(zone_elev + MATCH_M))


def match(ref_mask: np.ndarray, ref_dem: np.ndarray | None, basis_dem: np.ndarray | None) -> Match:
    """Pure core: ``ref_dem`` on the reference window, ``basis_dem`` = elevations of the basis pixels (DEM_ND = none)."""
    total = int(ref_mask.sum())
    if ref_dem is None or basis_dem is None:
        return Match("unavailable", px_total=total)
    zb = basis_dem[basis_dem != DEM_ND]
    if zb.size < 5:
        return Match("unavailable", px_total=total)
    ze = float(np.median(zb))
    lo, hi = band(ze)
    fe_all = ref_dem[ref_mask]
    fe_all = fe_all[fe_all != DEM_ND]
    dz0 = float(np.median(fe_all)) - ze if fe_all.size else None
    keep = ref_mask & (ref_dem >= lo) & (ref_dem <= hi)
    kept = int(keep.sum())
    m = Match("matched", zone_elev_m=ze, band_m=(lo, hi), dz_before_m=dz0, dz_after_m=dz0, px_kept=kept,
              px_total=total)
    if kept == total:
        m.status = "all_within"
    elif kept < MIN_MATCH_PX:
        m.status = "fallback"
    else:
        m.mask = keep
        m.dz_after_m = float(np.median(ref_dem[keep])) - ze
    return m


def for_context(ctx) -> Match:
    """Evaluate the match for a context (zone + its unmatched reference)."""
    ref = ctx.ref
    try:
        rd = dem_window(ref.aoi, ref.win)
        zd = dem_window(ctx.zone.aoi, ctx.zone.win)
    except Exception:  # noqa: BLE001 — a broken DEM read never breaks a report: no match
        log.exception("DEM read failed")
        rd = zd = None
    if rd is None or zd is None:
        return Match("unavailable", px_total=ref.forest_px)
    m = match(ref.ref, rd, zd[basis_pixels(ctx)])
    if m.applied and ref.kind == "preset" and not refbins_path(ref.city).exists():
        log.warning("no refbins for %s: elevation match not applied", ref.city)
        m.status, m.mask, m.dz_after_m = "unavailable", None, m.dz_before_m
    return m


def matched_reference(ref, m: Match):
    """A copy of the reference restricted to the band (new cache key, ``elev_band`` set)."""
    return dataclasses.replace(ref, ref=m.mask, key=f"{ref.key}:e{m.band_m[0]}_{m.band_m[1]}", elev_band=m.band_m,
                               notes=list(ref.notes))


# ------------------------------------------------------------------ preset cities: matched refstats from refbins
def _r(v, nd=3):
    return None if v is None or not np.isfinite(v) else round(float(v), nd)


@lru_cache(maxsize=4)
def _bins(city: str) -> dict:
    z = np.load(refbins_path(city))
    return {k: z[k] for k in z.files}


def _div(s, n):
    return float(s) / float(n) if n else float("nan")


@lru_cache(maxsize=128)
def matched_stats(city: str, band_m: tuple[int, int]) -> dict:
    """refstats.json of a preset city for the forest pixels in an elevation band (same keys and rounding)."""
    from . import reference as R

    base = R.preset_stats(city)
    b = _bins(city)
    e0 = int(b["emin"])
    K = b["px"].shape[0]
    i0, i1 = max(band_m[0] - e0, 0), min(band_m[1] - e0 + 1, K)
    sl = slice(i0, max(i1, i0))
    px = int(b["px"][sl].sum())
    clim_ref = _div(b["clim_sum"][sl].sum(), b["clim_n"][sl].sum())
    out = {"composite": {}, "dates": {}, "ref_px": px, "green_px": base["green_px"],
           "clim": dict(ref_lst=_r(clim_ref), green_lst=base["clim"]["green_lst"]), "elev_band_m": list(band_m)}
    years = [int(y) for y in b["years"]]
    for j, y in enumerate(years):
        c = dict(base["composite"][str(y)])
        n = b["comp_n"][j, sl].sum()
        c.update(ref_lst=_r(_div(b["comp_sum"][j, sl].sum(), n)), ref_valid_share=_r(_div(n, px)))
        out["composite"][str(y)] = c
        rows = base["dates"].get(str(y))
        if rows is None:
            continue
        vis, rsum = b[f"d{y}_vis"][:, sl].sum(1), b[f"d{y}_rsum"][:, sl].sum(1)
        an, asum = b[f"d{y}_an"][:, sl].sum(1), b[f"d{y}_asum"][:, sl].sum(1)
        new = []
        for i, d in enumerate(rows):
            share = _div(vis[i], px)
            new.append(d | dict(ref_lst=_r(_div(rsum[i], vis[i])), ref_lst_adj=_r(clim_ref + _div(asum[i], an[i])),
                                ref_valid_share=_r(share), ref_valid_px=int(round(share * px)) if px else 0))
        out["dates"][str(y)] = new
    return out


def build_refbins(city: str) -> dict[str, np.ndarray]:
    """Per-elevation-metre sums over the preset reference forest (precompute; see module docstring)."""
    import warnings

    from . import reference as R
    from . import scenes as SC

    ref = R.preset(city)
    g = D.grid(city)
    full = (0, 0, g.height, g.width)
    dem = dem_window(city, full)
    if dem is None:
        raise FileNotFoundError(dem60_path())
    m = ref.ref & (dem != DEM_ND)
    e = dem[m].astype(np.int64)
    e0 = int(e.min())
    K = int(e.max()) - e0 + 1
    idx = e - e0

    def bsum(v):
        ok = np.isfinite(v)
        return (np.bincount(idx[ok], weights=v[ok], minlength=K) if v.ndim == 1 else None,
                np.bincount(idx[ok], minlength=K))

    out: dict[str, np.ndarray] = dict(emin=np.array(e0), years=np.array(D.YEARS),
                                      px=np.bincount(idx, minlength=K).astype(np.int32))
    clim = np.asarray(SC.clim(city))[m].astype(np.float64)
    out["clim_sum"], out["clim_n"] = bsum(clim)
    cs, cn = [], []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for y in D.YEARS:
            s, n = bsum(D.read_lst(city, y, full)[m].astype(np.float64))
            cs.append(s)
            cn.append(n)
            if not SC.has_stack(city, y):
                continue
            a = SC.window_lst(city, y, full)[:, m].astype(np.float64)      # (dates, k)
            an_ = a - clim[None, :]
            rows = [bsum(a[i]) for i in range(a.shape[0])]
            arows = [bsum(an_[i]) for i in range(a.shape[0])]
            shape = (a.shape[0], K)
            out[f"d{y}_rsum"] = np.array([r[0] for r in rows]).reshape(shape)
            out[f"d{y}_vis"] = np.array([r[1] for r in rows]).reshape(shape).astype(np.int32)
            out[f"d{y}_asum"] = np.array([r[0] for r in arows]).reshape(shape)
            out[f"d{y}_an"] = np.array([r[1] for r in arows]).reshape(shape).astype(np.int32)
    out["comp_sum"], out["comp_n"] = np.array(cs), np.array(cn).astype(np.int32)
    return out
