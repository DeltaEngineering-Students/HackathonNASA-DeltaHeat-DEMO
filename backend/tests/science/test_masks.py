import numpy as np

from uhd.science import classes as C
from uhd.science import data as D
from uhd.science import reference as R
from uhd.science import scenes as SC
from uhd.science.report import _years_str, verdict_text


def test_esri_mapping_worldcover_fallback_and_farmland():
    esri = np.array([[D.ESRI_BUILT, D.ESRI_CROPS, D.ESRI_TREES, D.ESRI_RANGE, D.ESRI_WATER, 0]], np.uint8)
    wc = np.array([[0, 0, 0, 0, 0, D.WC_BUILT]], np.uint8)
    farm = np.array([[0, 0, 0, 1, 0, 0]], np.uint8)
    c = C.esri_classes(esri, wc, farm)
    assert c.tolist() == [[C.BUILT, C.FIELD, C.NATURE, C.FIELD, C.WATER, C.BUILT]]


def test_extrapolate_before_greener_built_pixel_was_not_built():
    anchor = np.array([C.BUILT, C.BUILT, C.BUILT, C.NATURE], np.uint8)
    nmax_y = np.array([0.80, 0.45, np.nan, 0.80])
    nmax_a = np.array([0.40, 0.40, 0.40, 0.40])
    wc = np.array([D.WC_BUILT, D.WC_BUILT, D.WC_BUILT, D.WC_TREES], np.uint8)
    c = C.extrapolate_before(anchor, nmax_y, nmax_a, None, wc)
    assert c.tolist() == [C.NATURE, C.BUILT, C.BUILT, C.NATURE]
    farm = np.array([1, 0, 0, 0])
    assert C.extrapolate_before(anchor, nmax_y, nmax_a, farm, wc)[0] == C.FIELD


def test_extrapolate_after_new_construction_and_regreening():
    anchor = np.array([C.FIELD, C.NATURE, C.WATER, C.BUILT, C.BUILT], np.uint8)
    nmax_y = np.array([0.30, 0.70, 0.10, 0.75, 0.30])
    nmax_a = np.array([0.80, 0.75, 0.80, 0.30, 0.30])
    ndbi_y = np.array([0.05, -0.2, 0.1, -0.2, 0.0])
    ndbi_a = np.array([-0.15, -0.2, -0.3, 0.0, 0.0])
    c = C.extrapolate_after(anchor, nmax_y, nmax_a, ndbi_y, ndbi_a)
    assert c.tolist() == [C.BUILT, C.NATURE, C.WATER, C.NATURE, C.BUILT]


def test_stable_forest_requires_all_years_and_erodes_edges():
    wc = np.full((7, 7), D.WC_TREES, np.uint8)
    e1 = np.full((7, 7), D.ESRI_TREES, np.uint8)
    e2 = e1.copy()
    e2[0, 0] = D.ESRI_RANGE
    m = C.stable_forest(wc, [e1, e2], None, erode=0)
    assert not m[0, 0] and m.sum() == 48
    m = C.stable_forest(wc, [e1, e2], None, erode=1)
    assert m.sum() == 24 and not m[1, 1] and m[2, 2]
    farm = np.zeros((7, 7))
    farm[3, 3] = 1
    nd = np.full((7, 7), 0.8)
    nd[2, 4] = 0.3  # clear-cut in some year
    m = C.stable_forest(wc, [e1, e1], farm, nd, erode=0)
    assert not m[3, 3] and not m[2, 4] and m[1, 1]


def test_land_change_masks():
    built, nat, field = C.BUILT, C.NATURE, C.FIELD
    seq = {
        "always_built": [built] * 6,
        "new_built": [field, field, field, built, built, built],
        "always_green": [nat] * 6,
        "flicker": [built, nat, built, nat, built, built],
    }
    cls = np.array([[seq[k][t] for k in seq] for t in range(6)], np.uint8)[:, None, :]  # (6, 1, 4)
    m = C.land_change_masks(cls)
    assert m["always_built"][0].tolist() == [True, False, False, False]
    assert m["new_built"][0].tolist() == [False, True, False, False]
    assert m["always_green"][0].tolist() == [False, False, True, False]


def test_ring_mask_distances():
    urban = np.zeros((601, 601), bool)
    urban[290:311, 290:311] = True
    ring = R.ring_mask(urban, (2.0, 15.0))
    d_px = lambda km: int(km * 1000 / D.RES)  # noqa: E731
    assert not ring[300, 310 + d_px(1.5)]           # 1.5 km from the edge: too close
    assert ring[300, 310 + d_px(5)]                 # 5 km: inside
    assert not ring[300, min(600, 310 + d_px(16))]  # 16 km: outside
    assert not ring[urban].any()


def test_masked_means_coverage():
    a = np.full((3, 4, 4), np.nan, np.float32)
    a[0] = 30.0
    a[1, :, :2] = 40.0
    mask = np.zeros((4, 4), bool)
    mask[:, :2] = True
    m, share = SC.masked_means(a, mask)
    assert m[0] == 30.0 and share[0] == 1.0
    assert m[1] == 40.0 and share[1] == 1.0
    assert np.isnan(m[2]) and share[2] == 0.0
    mask[:, :] = True
    m, share = SC.masked_means(a, mask)
    assert share[1] == 0.5


def test_path_row_and_years_str():
    assert SC.path_row("LC08_L2SP_181025_20200606_02_T1") == (181, 25)
    assert _years_str([2013, 2014, 2015, 2016, 2020, 2024, 2025]) == "2013–2016, 2020, 2024, 2025"


def test_verdict_text_both_halves_surface_and_driver():
    gs = dict(mean=6.4, last=7.0, min=5.0, max=8.0)
    tr = dict(slope_per_decade=1.2, ci95=[0.3, 2.0], p=0.01, n_years=13, verdict="significant")
    flat = dict(slope_per_decade=0.1, ci95=[-1, 1], p=0.8, n_years=13, verdict="not_significant")
    t = verdict_text("Позняки", "Києва", "built", gs, tr, flat, flat, None, flat)
    assert t.startswith("Позняки: поверхня забудови") and "на 6,4 °C гарячіша, ніж ліс навколо Києва" in t
    assert "за 13 літніх сезонів цей розрив зріс" in t and "статистично значуще, p = 0,010" in t
    ns = dict(flat, p=0.37, n_years=12)
    t = verdict_text(None, "Києва", "built", gs, ns, flat, flat, None, flat)
    assert t.startswith("Поверхня забудови") and "помітно не змінився (статистично незначуще, p = 0,37)" in t
    assert "не доведено" not in t.lower()
    # gap grows because the forest cooled
    cool = dict(slope_per_decade=-1.5, ci95=[-3, 0], p=0.2, n_years=13, verdict="not_significant")
    zone = dict(slope_per_decade=0.5, ci95=[-1, 2], p=0.5, n_years=13, verdict="not_significant")
    t = verdict_text("Нижні Сади", "Києва", "built", gs, tr, cool, flat, None, zone)
    assert "здебільшого через ліс-еталон" in t
    # zone-driven (M4): a non-significant forest trend is named, not taken as proof of a stable forest
    zsig = dict(slope_per_decade=1.9, ci95=[0.6, 3.1], p=0.009, n_years=13, verdict="significant")
    t = verdict_text("Нижні Сади", "Києва", "built", gs, tr, flat, flat, None, zsig)
    assert "Ліс-еталон не має статистично значущого тренду, тож зміна йде від самої території: її поверхня нагрівається на 1,9" in t
    assert "Змінюється саме ця територія" not in t
    rsig = dict(slope_per_decade=0.4, ci95=[0.1, 0.7], p=0.02, n_years=13, verdict="significant")
    t = verdict_text("Нижні Сади", "Києва", "built", gs, tr, rsig, flat, None, zsig)
    assert "Змінюється саме ця територія: її поверхня нагрівається на 1,9" in t
    # negative / near-zero gaps: no double negative
    t = verdict_text("Ліс", "Києва", "all_land", dict(gs, mean=-0.15), ns, flat, flat, None, flat)
    assert "майже така ж тепла" in t and "−" not in t.split("(")[1].split(")")[0]
    t = verdict_text("Ліс", "Києва", "all_land", dict(gs, mean=-1.9), ns, flat, flat, None, flat)
    assert "на 1,9 °C прохолодніша" in t
    ins = dict(tr, verdict="insufficient_data", n_years=5)
    assert "даних замало" in verdict_text(None, "міста", "built", gs, ins, flat, flat, None, flat)



def test_pixel_budget_refuses_scattered_zones():
    import pytest

    from uhd.science.geometry import ScienceError, _check_budget

    _check_budget((0, 0, 700, 700), "kyiv")
    _check_budget((0, 0, 1100, 1100), "ukraine")
    with pytest.raises(ScienceError) as e:
        _check_budget((0, 0, 1000, 19891), "ukraine")   # two small squares 800 km apart
    assert e.value.code == "too_large"
    with pytest.raises(ScienceError):
        _check_budget((0, 0, 1300, 1300), "ukraine")    # derived zones: max 72 km side


def test_lru_thread_safe_basic():
    import threading

    from uhd.science._lru import LRU

    c = LRU(10)
    def work(k):
        for i in range(200):
            c.put((k, i), i)
            c.get((k, i - 1))
    ts = [threading.Thread(target=work, args=(k,)) for k in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(c._d) == 10


def test_urban_parks_drop_big_forests():
    m = np.zeros((200, 200), bool)
    m[10:20, 10:20] = True          # 100 px = 0.36 km² park
    m[50:150, 50:150] = True        # 10 000 px = 36 km² forest
    p = C.urban_parks(m, max_km2=5.0)
    assert p[15, 15] and not p[100, 100] and p.sum() == 100


def test_war_region_lookup():
    import shapely.geometry as sg

    from uhd.science import data as D
    from uhd.science.geometry import to_3035

    def at(lon, lat):
        return D.war_region(to_3035(sg.Point(lon, lat)).buffer(1000))

    assert at(37.80, 48.00)["name"] == "Донецька область"           # Донецьк
    assert at(34.10, 44.95) == {"name": "Автономна Республіка Крим", "since": 2014}
    assert at(32.62, 46.64)["since"] == 2022                          # Херсон
    assert at(30.52, 50.45) is None and at(36.23, 49.99) is None      # Київ, Харків


def test_new_built_sentence_only_for_clear_jump():
    from uhd.science.report import new_built_sentence

    nb = dict(area_km2=1.217, before=dict(years=[2013, 2014], gap=5.71), after=dict(years=[2024, 2025], gap=7.21))
    s = new_built_sentence(nb)
    assert "≈1,2 км²" in s and "гарячішою" in s and "5,7 °C у 2013–2014" in s and "7,2 °C у 2024–2025" in s
    assert new_built_sentence(nb | dict(after=dict(years=[2024, 2025], gap=6.2))) is None   # < 1 °C jump
    assert new_built_sentence(nb | dict(area_km2=0.1)) is None
    assert new_built_sentence(None) is None


def test_lru_bounded_by_bytes_and_count():
    from uhd.science._lru import LRU

    c = LRU(10, maxbytes=100, sizeof=lambda v: v)
    for k in range(5):
        c.put(k, 30)                       # 30 bytes each: at most 3 fit
    assert len(c) == 3 and c.nbytes == 90 and c.get(0) is None and c.get(4) == 30
    c.put(4, 50)                           # replacing an entry updates the byte count
    assert c.nbytes <= 100
    c.put("huge", 500)                     # larger than the budget: not cached, nothing evicted for it
    assert c.get("huge") is None and c.nbytes <= 100
    d = LRU(2)
    for k in range(4):
        d.put(k, k)
    assert len(d) == 2 and d.get(3) == 3


def test_crop_keeps_masks_aligned():
    import numpy as np

    from uhd.science.reference import _crop

    a = np.zeros((50, 60), bool); a[10:20, 5:9] = True
    b = np.zeros((50, 60), bool); b[30, 40] = True
    win, (a2, b2) = _crop((100, 200, 50, 60), a, b)
    assert win == (110, 205, 21, 36) and a2.shape == b2.shape == (21, 36)
    assert a2.sum() == a.sum() and b2[30 - 10, 40 - 5]
    win0, (e,) = _crop((1, 2, 3, 4), np.zeros((3, 4), bool))
    assert win0 == (1, 2, 3, 4) and e.shape == (3, 4)


def test_npz_mmap_shares_and_refreshes(tmp_path):
    import os

    import numpy as np

    from uhd.science.data import npz_mmap

    p = tmp_path / "x.npz"
    np.savez(p, a=np.arange(6, dtype=np.float16).reshape(2, 3))
    z = npz_mmap(p)
    assert isinstance(z["a"], np.memmap) and z["a"].tolist() == [[0, 1, 2], [3, 4, 5]]
    np.savez(p, a=np.zeros((2, 3), np.float16))
    os.utime(p, (os.path.getmtime(p) + 10,) * 2)            # newer .npz -> re-extracted
    assert npz_mmap(p)["a"].sum() == 0


def test_year_detail_text_and_pass_classes():
    from uhd.science.analysis import classify_pass, scenes_detail

    def row(date, used, cover, swath):
        return dict(date=date, used=used, zone_cover=cover, zone_in_swath=swath)

    rows = ([row("2020-06-06", False, 0.33, 1.0)] + [row(f"2020-07-0{i}", False, 0.0, 1.0) for i in range(1, 4)]
            + [row("2020-06-13", False, 0.21, 0.12), row("2020-06-15", False, 0.0, 0.0)]
            + [row("2020-08-16", True, 0.75, 0.63), row("2020-08-20", False, 0.9, 1.0)])
    assert classify_pass(rows[4]) == "outside_swath"          # 0.21 clear but only ~12-21 % of the zone in the scene
    assert classify_pass(rows[0]) == "zone_cloudy" and classify_pass(rows[-1]) == "reference_cloudy"
    assert classify_pass(row("x", False, 0.55, 0.3)) == "reference_cloudy"   # clear share bounds the footprint
    d = scenes_detail(rows)
    assert d["usable_dates"] == ["2020-08-16"] and d["n_passes_total"] == 8
    assert (d["n_outside_swath"], d["n_cloudy"], d["n_reference_cloudy"]) == (2, 4, 1)
    assert d["text_uk"] == ("Лише один чистий проліт над ділянкою (16.08). З 8 прольотів за літо 4 — хмарні над ділянкою, "
                            "у 2 ділянка поза смугою знімання або на її краю, 1 — хмарно над лісом-еталоном. "
                            "Для річного значення потрібно щонайменше 2.")
    assert scenes_detail([])["text_uk"].startswith("Жодного чистого прольоту")
    c = scenes_detail(None, 9, 3)
    assert c["usable_dates"] is None and c["n_outside_swath"] == 3 and "з 9 прольотів" in c["text_uk"]


def test_nolst_block_rule_synthetic():
    import numpy as np

    from uhd.science import nolst_mask as NM

    B2 = NM.BLOCK * NM.BLOCK
    land = np.full((6, 6), B2, np.int32)
    land[0, 0] = int(0.2 * B2)                      # mostly sea: ignored even if all its land pixels qualify
    nolst = np.zeros((6, 6), np.int32)
    nolst[0, 0] = land[0, 0]
    nolst[2:4, 2:4] = B2 // 2                       # exactly 50 % of land -> no-LST
    nolst[4, 4] = B2 // 2 - 1                       # just below 50 % -> not
    m = NM.mask_from_blocks(dict(land_px=land, nolst_px=nolst))
    assert m[2:4, 2:4].all() and not m[0, 0] and not m[4, 4]
    assert m.sum() == 4                             # closing fills gaps but adds nothing around a solid block


def test_gapfill_neighbour_median_and_persistent_left(monkeypatch):
    """Display fill (PM item 9): holes get the median of Y±1, else Y±2; persistent holes and non-holes stay NaN."""
    from uhd.science import gapfill as F
    from uhd.science import rasters as RR

    vals = {2018: [1.0, 1.0, 1.0, 1.0], 2019: [2.0, np.nan, np.nan, 5.0], 2020: [np.nan, np.nan, np.nan, np.nan],
            2021: [4.0, np.nan, 7.0, 9.0], 2022: [9.0, 6.0, 8.0, 9.0]}
    monkeypatch.setattr(RR, "layer_raster", lambda aoi, layer, y, win: (np.array([vals.get(y, [np.nan] * 4)]), None, None))
    monkeypatch.setattr(F, "holes", lambda aoi, y, win: np.array([[True, True, False, True]]))
    monkeypatch.setattr(F, "hole_years", lambda aoi, win: np.array([[1, 2, 1, 9]], np.uint8))
    out = F.fill_raster("ukraine", "gap", 2020, (0, 0, 1, 4))
    assert out[0, 0] == 3.0                      # median(2019 = 2, 2021 = 4)
    assert out[0, 1] == 3.5                      # ±1 both empty -> median(2018 = 1, 2022 = 6)
    assert np.isnan(out[0, 2])                   # not a hole (e.g. water) -> never filled
    assert np.isnan(out[0, 3])                   # persistent ASTER-GED hole -> stays hatched
    base = np.array([[5.0, np.nan, np.nan, np.nan]])
    assert np.isnan(F.fill_raster("ukraine", "gap", 2020, (0, 0, 1, 4), base=base)[0, 0])   # has a value -> no fill


def test_gapfill_layers_are_not_used_by_analysis():
    import pathlib

    import uhd.science as S
    root = pathlib.Path(S.__file__).parent
    users = [p.name for p in root.glob("*.py") if p.name not in ("gapfill.py", "rasters.py", "noscene_mask.py")
             and ("gapfill" in p.read_text() or "_fill\"" in p.read_text())]
    assert users == []


def test_occupied_lookup_and_caveat():
    """PM 4b: zones mostly inside the official occupied list get «окупована територія (станом на …)»."""
    import shapely.geometry as sg

    from uhd.science import data as D
    from uhd.science.geometry import to_3035
    from uhd.science.report import CAVEATS_UK, _uk_date

    def at(lon, lat):
        return D.occupied(to_3035(sg.Point(lon, lat)).buffer(1000))

    assert at(37.80, 48.00)["snapshot_date"] == "2026-09-15"          # Донецьк
    assert at(34.10, 44.95) is not None and at(33.52, 44.60) is not None   # Сімферополь, Севастополь
    assert at(35.37, 46.85) is not None                                # Мелітополь
    assert at(37.55, 48.72) is None                                    # Краматорськ: Donetsk oblast, not occupied
    assert at(32.62, 46.64) is None                                    # Херсон (right bank)
    assert at(35.14, 47.84) is None and at(30.52, 50.45) is None       # Запоріжжя, Київ
    assert "станом на 15.09.2026" in CAVEATS_UK["occupied"].format(date=_uk_date("2026-09-15"), source="x")


def test_occupied_list_parsing():
    import importlib.util
    import pathlib

    p = pathlib.Path(__file__).parents[2] / "scripts" / "precompute_occupied.py"
    spec = importlib.util.spec_from_file_location("precompute_occupied", p)
    import sys
    sys.path.insert(0, str(p.parent))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    occ = m.OCCUPIED
    rows = [["", "", "", "", "UA14020050100062404", occ, "24.02.2022", "05.09.2022", ""],   # liberated
            ["", "", "", "", "UA14020050100062404", "Територія активних бойових дій", "05.09.2022", "", ""],
            ["", "", "", "", "UA14020050110000001", occ, "24.02.2022", "", ""],
            ["", "", "", "", "UA44020010010037242", occ, "07.04.2014", "", ""]]
    sh = m.hromada_shares(rows)
    assert sh == {"UA1402005": (1, 2, False), "UA4402001": (1, 1, True)}
    assert m.drawn(*sh["UA4402001"]) and not m.drawn(*sh["UA1402005"])   # partial with a free centre: not drawn
    assert m.drawn(3, 4, True) and not m.drawn(3, 4, False) and not m.drawn(1, 4, True)
    assert m.label_uk("2026-09-15") == "окуповано (станом на 15.09.2026, джерело: Мінрозвитку, наказ № 376)"


def test_season_wording_item31():
    from uhd.science.report import CAVEATS_UK, _lit
    assert [_lit(n) for n in (1, 3, 11, 12, 13, 21, 22)] == ["літній сезон", "літні сезони", "літніх сезонів",
                                                             "літніх сезонів", "літніх сезонів", "літній сезон",
                                                             "літні сезони"]
    t = CAVEATS_UK["not_significant_physics"]
    assert "«Поки несуттєво»" in t and "між окремими літніми сезонами" in t and "літ " not in t


def test_noscene_block_rule_and_label():
    from uhd.science import noscene_mask as N
    B = N.BLOCK * N.BLOCK
    land = np.array([[B, B, B // 10]])
    q = np.array([[B // 2, B // 4, B // 10]])
    m = N.year_mask(land, q)
    assert m[0, 0] and not m[0, 2]                      # >= 50 % of land; mostly-water block ignored
    assert N.label_uk(2022) == "2022: замало безхмарних знімків цієї смуги"


def test_cmip6_v2_median_and_p10_p90():
    """CMIP6 v2 proposal (METHOD.md §9b): median across models with the P10–P90 range, 20-year windows."""
    from uhd.science import climate as CL
    lat, lon = np.array([50.0, 50.25]), np.array([30.0, 30.25])
    s = {"lat": lat, "lon": lon, "version": np.array("v2")}
    for i, m in enumerate(["A", "B", "C", "D", "E"]):
        s[f"{m}|historical|historical|jja_mean"] = np.full((2, 2), 25.0, np.float32)
        for scen in CL.SCENARIOS:
            for per, d in (("2041-2060", 1.0 + i), ("2081-2100", 2.0 + i)):
                s[f"{m}|{scen}|{per}|jja_mean"] = np.full((2, 2), 25.0 + d, np.float32)
    out = CL._projection_v2(s, 50.1, 30.1, 0, 0)
    b = out["ssp245"]["2041-2060"]
    assert b["delta"] == 3.0 and b["delta_range"] == [1.4, 4.6] and b["n_models"] == 5
    assert out["baseline"]["period"] == [1995, 2014] and set(out["ssp585"]) == {"2041-2060", "2081-2100"}
    assert out["statistic"] == "median_p10_p90" and out["climate_version"] == "cmip6-v2"
