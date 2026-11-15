"""sci-v3.6 elevation-matched reference (uhd.science.elevmatch): filter, fallback, no-op, preset bins, texts."""
import numpy as np
import pytest

from uhd.science import elevmatch as EM
from uhd.science import i18n_en as EN
from uhd.science import reference as R
from uhd.science.report import CAVEATS_UK, METHOD_VERSION


def _ref(n=40):
    """n×n forest everywhere; elevation rises 10 m per row from 100 m (rows 0..n-1 → 100..100+10(n-1) m)."""
    mask = np.ones((n, n), bool)
    dem = (100 + 10 * np.arange(n))[:, None].repeat(n, 1).astype(np.int16)
    return mask, dem


def test_filter_keeps_only_forest_within_100_m_of_the_built_median():
    mask, dem = _ref()                                   # forest 100..490 m, median 295 m
    basis = np.array([140, 150, 150, 160, 150, EM.DEM_ND], np.int16)     # built median 150 m (no-data ignored)
    m = EM.match(mask, dem, basis)
    assert m.status == "matched" and m.applied
    assert m.zone_elev_m == 150 and m.band_m == (50, 250)
    kept_rows = (dem[:, 0] >= 50) & (dem[:, 0] <= 250)    # rows 0..15 → 100..250 m
    assert m.px_kept == int(kept_rows.sum()) * 40 == 640 and m.px_total == 1600
    assert (m.mask == (mask & kept_rows[:, None])).all()
    assert m.dz_before_m == pytest.approx(295 - 150) and m.dz_after_m == pytest.approx(175 - 150)
    info = m.info()
    assert info["applied"] is True and info["px_kept"] == 640 and info["dz_before_m"] == 145.0
    assert info["dz_after_m"] == 25.0 and info["tolerance_m"] == 100 and info["min_px"] == 200


def test_caveat_shown_only_for_a_meaningful_match():
    def m(kept, total, dz0, dz1, status="matched"):
        return EM.Match(status, dz_before_m=dz0, dz_after_m=dz1, px_kept=kept, px_total=total)
    assert not EM.shown(m(98180, 98333, 35.0, 35.0))          # Київ: 0.2 % dropped, Δz unchanged
    assert not EM.shown(m(97000, 100000, 50.0, 31.0))         # 3 %, Δz −19 m
    assert EM.shown(m(95000, 100000, 50.0, 49.0))             # 5 % dropped
    assert EM.shown(m(99000, 100000, 50.0, 30.0))             # Δz moved by 20 m
    assert EM.shown(m(24721, 99060, 232.0, -6.0))             # Ужгород
    assert not EM.shown(m(150, 1600, 295.0, 295.0, "fallback"))
    assert not EM.shown(m(100, 100, 5.0, 5.0, "all_within"))


def test_band_edges_are_inclusive_and_symmetric():
    assert EM.band(150.0) == (50, 250)
    assert EM.band(150.5) == (51, 250)                   # |e − 150.5| ≤ 100 for integer e


def test_fallback_below_200_px_keeps_the_whole_forest():
    mask, dem = _ref()
    basis = np.full(10, 590, np.int16)                    # band 490..690: only the top row (490 m) = 40 px
    m = EM.match(mask, dem, basis)
    assert m.status == "fallback" and not m.applied and m.mask is None
    assert m.px_kept == 40 < EM.MIN_MATCH_PX
    assert m.dz_after_m == m.dz_before_m == pytest.approx(295 - 590)


def test_no_op_when_all_forest_is_within_the_band():
    mask, dem = _ref(10)                                  # forest 100..190 m
    m = EM.match(mask, dem, np.full(20, 150, np.int16))
    assert m.status == "all_within" and not m.applied and m.mask is None
    assert m.px_kept == m.px_total == 100


def test_unavailable_without_dem_or_basis_elevation():
    mask, dem = _ref(10)
    assert EM.match(mask, None, np.full(20, 150, np.int16)).status == "unavailable"
    assert EM.match(mask, dem, np.full(3, EM.DEM_ND, np.int16)).status == "unavailable"
    assert EM.match(mask, dem, np.array([150, 150], np.int16)).status == "unavailable"   # < 5 basis px


def test_matched_reference_has_a_new_cache_key_and_band():
    mask, dem = _ref()
    m = EM.match(mask, dem, np.full(10, 150, np.int16))
    r = R.Reference(city="derived", name_uk="", kind="derived", aoi="ukraine", win=(0, 0, 40, 40), ref=mask,
                    green=np.zeros_like(mask), urban=np.zeros_like(mask), key="abc")
    rm = EM.matched_reference(r, m)
    assert rm.forest_px == 640 and rm.key == "abc:e50_250" and rm.elev_band == (50, 250)
    assert r.forest_px == 1600 and r.elev_band is None    # the cached unmatched reference is untouched


def test_matched_stats_sum_the_band_of_the_preset_bins(monkeypatch):
    EM.matched_stats.cache_clear()
    base = {"ref_px": 6, "green_px": 900, "clim": {"ref_lst": 0.0, "green_lst": 31.0},
            "composite": {"2013": {"ref_lst": 0.0, "ref_valid_share": 1.0, "green_lst": 33.0, "green_valid_share": 1.0}},
            "dates": {"2013": [{"date": "2013-07-01", "ref_lst": 0.0, "ref_lst_adj": 0.0, "ref_valid_share": 1.0,
                                "ref_valid_px": 6, "green_lst": 35.0, "green_lst_adj": 34.0, "green_valid_share": 0.9}]}}
    # bins at 100, 101, 102 m: 2 px each; composite 20/25/30 °C; one date with LST 21/26/40 and anomaly +1/+1/+10
    bins = dict(emin=np.array(100), years=np.array([2013]), px=np.array([2, 2, 2]),
                clim_sum=np.array([40.0, 50.0, 60.0]), clim_n=np.array([2, 2, 2]),
                comp_sum=np.array([[40.0, 50.0, 60.0]]), comp_n=np.array([[2, 2, 2]]),
                d2013_rsum=np.array([[42.0, 52.0, 80.0]]), d2013_vis=np.array([[2, 2, 2]]),
                d2013_asum=np.array([[2.0, 2.0, 20.0]]), d2013_an=np.array([[2, 2, 2]]))
    monkeypatch.setattr(EM, "_bins", lambda city: bins)
    monkeypatch.setattr(R, "preset_stats", lambda city: base)
    st = EM.matched_stats("kyiv", (0, 101))               # bins 100 and 101 only
    assert st["ref_px"] == 4 and st["green_px"] == 900 and st["clim"] == {"ref_lst": 22.5, "green_lst": 31.0}
    c = st["composite"]["2013"]
    assert c["ref_lst"] == 22.5 and c["ref_valid_share"] == 1.0 and c["green_lst"] == 33.0
    d = st["dates"]["2013"][0]
    assert d["ref_lst"] == 23.5 and d["ref_lst_adj"] == 23.5 and d["ref_valid_px"] == 4
    assert d["green_lst_adj"] == 34.0 and d["date"] == "2013-07-01"
    full = EM.matched_stats("kyiv", (-1000, 5000))
    assert full["dates"]["2013"][0]["ref_lst_adj"] == pytest.approx(25.0 + 24 / 6, abs=1e-3)
    EM.matched_stats.cache_clear()


def test_new_caveats_have_english_templates_for_the_current_version():
    assert METHOD_VERSION == "sci-v3.6" == EN.VERSIONS[-1]
    uk = CAVEATS_UK["ref_elev_matched"].format(km2="120,4", km2_all="356,6")
    assert EN.caveat_text_en("ref_elev_matched", uk, METHOD_VERSION) == (
        "Reference forest matched to the built-up elevation (±100 m): 120.4 km² of the ring's 356.6 km² of forest.")
    uk = CAVEATS_UK["ref_match_fallback"].format(km2="0,5")
    assert EN.caveat_text_en("ref_match_fallback", uk, METHOD_VERSION).startswith("Too little forest lies at the")
    uk = CAVEATS_UK["ref_higher"].format(dz=230)
    assert "230 m higher" in EN.caveat_text_en("ref_higher", uk, METHOD_VERSION)
    for code, text in CAVEATS_UK.items():                 # every current caveat has an English template
        if "{" not in text:
            assert EN.caveat_text_en(code, text, METHOD_VERSION), code


def test_reference_outline_follows_the_report_match():
    from uhd.services import reference_outline as RO

    assert RO._matched({"reference": {"elevation_match": {"applied": True}}})
    assert not RO._matched({"reference": {"elevation_match": {"applied": False, "status": "all_within"}}})
    assert not RO._matched({"reference": {"city": "kyiv"}})       # reports before sci-v3.6
    assert not RO._matched({})
