import numpy as np
import pytest
from scipy import stats as sps

from uhd.science import stats as ST

YEARS = list(range(2013, 2026))


def test_theil_sen_exact_line():
    y = [2.0 + 0.1 * (x - 2013) for x in YEARS]
    slope, intercept, lo, hi = ST.theil_sen(YEARS, y)
    assert slope == pytest.approx(0.1)
    assert lo == pytest.approx(0.1) and hi == pytest.approx(0.1)


def test_theil_sen_robust_to_outlier():
    y = [5.0 + 0.2 * (x - 2013) for x in YEARS]
    y[5] = 50.0  # one crazy summer
    slope, *_ = ST.theil_sen(YEARS, y)
    assert slope == pytest.approx(0.2, abs=0.02)


def test_mann_kendall_monotonic_and_matches_kendall_tau_without_ties():
    y = np.arange(13, dtype=float)
    s, p = ST.mann_kendall(y)
    assert s == 13 * 12 / 2
    assert p < 0.001
    rng = np.random.default_rng(0)
    y = rng.normal(size=13)
    s, p = ST.mann_kendall(y)
    tau, _ = sps.kendalltau(np.arange(13), y)
    assert s == pytest.approx(tau * 13 * 12 / 2)


def test_mann_kendall_ties_and_constant():
    s, p = ST.mann_kendall([1, 1, 1, 1, 1, 1, 1, 1])
    assert s == 0 and p == 1.0
    s, p = ST.mann_kendall([1, 1, 2, 2, 3, 3, 4, 4, 5, 5])
    assert s > 0 and p < 0.01


def test_mann_kendall_short_series():
    assert ST.mann_kendall([1.0, 2.0]) == (0.0, 1.0)


def test_mk_false_positive_rate_close_to_alpha():
    rng = np.random.default_rng(42)
    ps = [ST.mann_kendall(rng.normal(size=13))[1] for _ in range(2000)]
    rate = np.mean(np.array(ps) < 0.05)
    assert 0.02 < rate < 0.08


@pytest.mark.parametrize("p,n,expected", [
    (0.01, 13, "significant"), (0.049, 8, "significant"), (0.05, 13, "not_significant"),
    (0.6, 13, "not_significant"), (0.001, 7, "insufficient_data"), (None, 13, "insufficient_data")])
def test_verdict_rule(p, n, expected):
    assert ST.verdict(p, n) == expected


def test_trend_block_per_decade_and_missing_values():
    y = [1.0 + 0.3 * (x - 2013) for x in YEARS]
    y[3] = None
    y[7] = float("nan")
    t = ST.trend(YEARS, y)
    assert t["n_years"] == 11
    assert t["slope_per_decade"] == pytest.approx(3.0)
    assert t["verdict"] == "significant"
    assert t["ci95"][0] <= t["slope_per_decade"] <= t["ci95"][1]


def test_trend_insufficient():
    t = ST.trend(YEARS[:7], [1, 2, 3, 4, 5, 6, 7])
    assert t["verdict"] == "insufficient_data" and t["p"] is not None
    t = ST.trend(YEARS[:2], [1, 2])
    assert t["slope_per_decade"] is None and t["verdict"] == "insufficient_data"


def test_summary():
    s = ST.summary([1.0, None, 3.0, float("nan"), 2.0, None])
    assert s == dict(mean=2.0, last=2.0, min=1.0, max=3.0)
    assert ST.summary([None, None])["mean"] is None


def test_half_up_rounding_and_text_agree():
    from uhd.science.report import _uk_num

    assert ST.rnd(11.25, 1) == 11.3
    assert ST.rnd(2.675, 2) == 2.68          # binary float would give 2.67
    assert ST.rnd(-0.05, 1) == -0.1
    assert ST.rnd(float("nan")) is None and ST.rnd(None) is None
    assert _uk_num(11.25) == "11,3"
    assert _uk_num(-1.25) == "−1,3"
    s = ST.summary([11.0, 11.5])
    assert s["mean"] == 11.25 and _uk_num(s["mean"]) == "11,3"


def test_verdict_decided_on_shown_p(monkeypatch):
    monkeypatch.setattr(ST, "mann_kendall", lambda y: (10.0, 0.04996))
    t = ST.trend(YEARS, [float(i) for i in range(13)])
    assert t["p"] == 0.05 and t["verdict"] == "not_significant"
