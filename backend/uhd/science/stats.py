"""Trend statistics: Theil–Sen slope with 95 % CI, Mann–Kendall test, verdict rule."""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from collections.abc import Sequence

import numpy as np
from scipy import stats as sps

MIN_YEARS = 8
ALPHA = 0.05


def mann_kendall(y: Sequence[float]) -> tuple[float, float]:
    """Two-sided Mann–Kendall test with tie correction. Returns (S, p). n < 3 -> p = 1."""
    y = np.asarray(y, float)
    n = y.size
    if n < 3:
        return 0.0, 1.0
    s = 0.0
    for k in range(n - 1):
        s += np.sign(y[k + 1:] - y[k]).sum()
    _, counts = np.unique(y, return_counts=True)
    var = (n * (n - 1) * (2 * n + 5) - (counts * (counts - 1) * (2 * counts + 5)).sum()) / 18.0
    if var <= 0:
        return float(s), 1.0
    if s > 0:
        z = (s - 1) / math.sqrt(var)
    elif s < 0:
        z = (s + 1) / math.sqrt(var)
    else:
        z = 0.0
    p = 2 * (1 - sps.norm.cdf(abs(z)))
    return float(s), float(min(1.0, p))


def theil_sen(x: Sequence[float], y: Sequence[float]) -> tuple[float, float, float, float]:
    """Theil–Sen slope, intercept and 95 % CI of the slope (Sen 1968, as in scipy.stats.theilslopes)."""
    res = sps.theilslopes(np.asarray(y, float), np.asarray(x, float), alpha=0.95)
    return float(res[0]), float(res[1]), float(res[2]), float(res[3])


def verdict(p: float | None, n_years: int) -> str:
    if n_years < MIN_YEARS or p is None:
        return "insufficient_data"
    return "significant" if p < ALPHA else "not_significant"


def rnd(v, nd: int = 2) -> float | None:
    """Round half-up on the decimal representation (11.25 -> 11.3), None for missing — the same rule for stored
    numbers and for numbers in the Ukrainian texts, so they always agree."""
    if v is None or not np.isfinite(v):
        return None
    q = Decimal(1).scaleb(-nd)
    return float(Decimal(repr(float(v))).quantize(q, rounding=ROUND_HALF_UP))


_r = rnd


def trend(years: Sequence[int], values: Sequence[float | None], per: float = 10.0, nd: int = 2) -> dict:
    """Trend block for the report. Missing values (None/NaN) are dropped.

    slope_per_decade and ci95 are in value units per ``per`` years (default per decade).
    """
    pairs = [(int(x), float(v)) for x, v in zip(years, values) if v is not None and np.isfinite(v)]
    n = len(pairs)
    out = dict(slope_per_decade=None, ci95=[None, None], p=None, n_years=n, verdict="insufficient_data")
    if n < 3:
        return out
    x = np.array([p[0] for p in pairs], float)
    y = np.array([p[1] for p in pairs], float)
    slope, _, lo, hi = theil_sen(x, y)
    _, p = mann_kendall(y)
    p3 = _r(p, 3)  # the verdict is decided on the p that is shown (backend and texts use it too)
    out.update(slope_per_decade=_r(slope * per, nd), ci95=[_r(lo * per, nd), _r(hi * per, nd)],
               p=p3, verdict=verdict(p3, n))
    return out


def summary(values: Sequence[float | None], nd: int = 2) -> dict:
    v = [float(x) for x in values if x is not None and np.isfinite(x)]
    if not v:
        return dict(mean=None, last=None, min=None, max=None)
    last = next(x for x in reversed(list(values)) if x is not None and np.isfinite(x))
    return dict(mean=_r(np.mean(v), nd), last=_r(last, nd), min=_r(min(v), nd), max=_r(max(v), nd))
