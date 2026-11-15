"""Integration tests on the real rasters (run on the server: pytest -m server_data tests/science)."""
import json
import time

import numpy as np
import pytest
import shapely.geometry as sg

pytestmark = pytest.mark.server_data

S = pytest.importorskip("uhd.science")
from uhd.science import analysis as A  # noqa: E402
from uhd.science import data as D  # noqa: E402

if not (D.RAW / "kyiv" / "composites" / "2013" / "info.json").exists():
    pytest.skip("real data not available", allow_module_level=True)

POZ = (812.5, 712.9)


def _validation_module():
    import importlib.util
    from pathlib import Path

    p = Path(__file__).resolve().parents[2] / "scripts" / "precompute_validation.py"
    spec = importlib.util.spec_from_file_location("precompute_validation", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _circle(city, col, row, r):
    from uhd.science.geometry import to_wgs84

    g = D.grid(city)
    return sg.mapping(to_wgs84(sg.Point(g.x0 + col * D.RES, g.y1 - row * D.RES).buffer(r, 64)))


def _box(lon, lat, r_m):
    from uhd.science.geometry import to_3035, to_wgs84

    return sg.mapping(to_wgs84(to_3035(sg.Point(lon, lat)).buffer(r_m, cap_style="square")))


@pytest.fixture(scope="module")
def poz_report():
    t = time.time()
    rep = S.analyze(_circle("kyiv", *POZ, 1000), name="Позняки")
    rep["_seconds"] = time.time() - t
    return rep


def test_legacy_composite_ballpark_reproduced():
    city = _validation_module().legacy("kyiv")
    assert 6.4 < city["wc_trees_ring"]["mean"] < 7.2          # old method: ≈ 6.8 °C
    assert 5.2 < city["wc_nature_ring"]["mean"] < 6.0         # first check (nature ring): 5.59 °C
    g = D.grid("kyiv")
    rr, cc = np.mgrid[0:g.height, 0:g.width]
    circ = ((cc + 0.5 - POZ[0]) ** 2 + (rr + 0.5 - POZ[1]) ** 2) <= (1000 / D.RES) ** 2
    poz = _validation_module().legacy("kyiv", circ)
    assert 8.4 < poz["wc_trees_ring"]["mean"] < 9.4           # Pozniaky ≈ 9.0 °C


def test_report_shape_and_json(poz_report):
    rep = poz_report
    for k in ("zone", "reference", "series", "gap_summary", "trend", "ref_trend", "ndvi_trend", "land_change",
              "green_gap", "caveats", "verdict_text_uk", "method", "years", "data_version"):
        assert k in rep
    assert set(rep["series"][0]) == {"year", "zone_lst", "ref_lst", "gap", "ndvi", "ndbi", "built_share", "built_share_land",
                                     "built_share_zone", "scenes", "valid_share", "method", "excluded",
                                     "excluded_detail"}
    assert set(rep["trend"]) == {"slope_per_decade", "ci95", "p", "n_years", "verdict"}
    assert set(rep["land_change"]) == {"always_built", "new_built", "always_green"}
    json.dumps({k: v for k, v in rep.items() if not k.startswith("_")})
    assert len(rep["series"]) == 13
    assert all(c["text_uk"] for c in rep["caveats"])


def test_pozniaky_numbers_and_speed(poz_report):
    rep = poz_report
    assert rep["reference"]["city"] == "kyiv"
    assert rep["method"] in ("per_scene", "mixed")
    assert sum(r["method"] == "per_scene" for r in rep["series"]) >= 10
    assert 9.0 < rep["gap_summary"]["mean"] < 12.5
    assert rep["trend"]["verdict"] in ("significant", "not_significant")
    assert rep["trend"]["n_years"] >= 12
    assert rep["_seconds"] < 3.0


def test_per_scene_reduces_interannual_noise_at_pozniaky():
    ctx = A.build_context(_circle("kyiv", *POZ, 1000))
    g1 = [r["gap"] for r in A.series(ctx) if r["gap"] is not None]
    g2 = [r["gap"] for r in A.composite_series(ctx) if r["gap"] is not None]
    assert np.std(g1) < np.std(g2)


def test_whole_kyiv():
    from uhd.science.geometry import to_wgs84

    rep = S.analyze(sg.mapping(to_wgs84(D.aoi_polygon_3035("kyiv"))), name="Київ")
    assert 6.0 < rep["gap_summary"]["mean"] < 9.0
    assert rep["zone"]["analysed"] == "built"
    assert rep["green_gap"] is not None


def test_derived_place_uses_composite_and_says_so():
    rep = S.analyze(_box(28.47, 49.233, 1500), name="Вінниця")
    assert rep["reference"]["city"] == "derived"
    assert rep["method"] == "composite"
    codes = {c["code"] for c in rep["caveats"]}
    assert {"composite_method", "derived_reference"} <= codes
    assert "від межі міста (забудованої території), не від центру" in next(
        c["text_uk"] for c in rep["caveats"] if c["code"] == "derived_reference")
    assert rep["reference"]["forest_px"] > 500


def test_forest_control_has_small_gap():
    # Holosiivskyi forest, Kyiv
    rep = S.analyze(_box(30.505, 50.375, 700), name="Голосіївський ліс")
    assert rep["zone"]["analysed"] == "all_land"
    assert abs(rep["gap_summary"]["mean"]) < 2.5


def test_tiny_zone_insufficient():
    rep = S.analyze(_box(30.633, 50.397, 150))
    assert rep["trend"]["verdict"] == "insufficient_data"
    assert "small_zone" in {c["code"] for c in rep["caveats"]}


def test_outside_ukraine_rejected():
    with pytest.raises(S.ScienceError):
        S.analyze(_box(13.4, 52.5, 1000))


def test_list_scenes_land_change_reference_climate_rasters():
    geom = _circle("kyiv", *POZ, 1000)
    sc = S.list_scenes(geom, 2020)
    assert sc and all({"date", "path", "cloud", "used", "zone_lst", "ref_lst"} <= set(s) for s in sc)
    assert any(s["used"] for s in sc)
    lc = S.land_change(geom)
    assert lc["always_built"] > 2.0
    ref = S.reference_for("kyiv")
    assert ref["forest_px"] > 50000 and ref["ring_geometry"]["type"] in ("Polygon", "MultiPolygon")
    cl = S.climate_projection(50.45, 30.52)
    assert cl["ssp585"]["2081-2100"]["delta"] > cl["ssp245"]["2041-2060"]["delta"] - 1   # CMIP6 v2 periods
    arr, T, crs = S.gap_raster("ukraine", 2021, (4900, 9500, 256, 256))
    assert arr.shape == (256, 256) and np.isfinite(arr).mean() > 0.5 and crs == "EPSG:3035"
    arr, _, _ = S.gap_raster("kyiv", 2021, (650, 750, 128, 128))
    assert 5 < np.nanmean(arr) < 15


def test_lines_consistent_with_gap(poz_report):
    for r in poz_report["series"]:
        if r["gap"] is not None:
            assert abs(r["zone_lst"] - r["ref_lst"] - r["gap"]) <= 0.011, r


def test_scattered_multipolygon_refused():
    a = _box(22.3, 48.4, 300)
    b = _box(39.6, 49.0, 300)
    mp = {"type": "MultiPolygon", "coordinates": [a["coordinates"], b["coordinates"]]}
    with pytest.raises(S.ScienceError) as e:
        S.analyze(mp)
    assert e.value.code == "too_large"


def test_name_does_not_leak_between_callers():
    geom = _circle("kyiv", *POZ, 990)
    r1 = S.analyze(geom, name="Перший")
    r2 = S.analyze(geom)
    assert r1["zone"]["name"] == "Перший" and r1["verdict_text_uk"].startswith("Перший")
    assert r2["zone"]["name"] is None and "Перший" not in r2["verdict_text_uk"]


def test_basis_always_built_with_secondary(poz_report):
    assert poz_report["zone"]["basis"] == "always_built"
    assert poz_report["secondary"]["basis"] == "built_each_year"
    assert "basis_always_built" in {c["code"] for c in poz_report["caveats"]}
    assert poz_report["method_version"] == S.METHOD_VERSION


def test_gap_tiles_agree_with_report_at_pozniaky(poz_report):
    ctx = A.build_context(_circle("kyiv", *POZ, 1000))
    tile = []
    for i, y in enumerate(D.YEARS):
        arr, _, _ = S.gap_raster("kyiv", y, ctx.zone.win)
        tile.append(float(np.nanmean(arr[ctx.year_mask(i)])))
    rep = [r["gap"] for r in poz_report["series"]]
    diffs = [t - r for t, r in zip(tile, rep) if r is not None]
    assert max(abs(d) for d in diffs) < 2.0
    from uhd.science import stats as ST
    assert np.sign(ST.trend(D.YEARS, tile)["slope_per_decade"]) == np.sign(poz_report["trend"]["slope_per_decade"])
    # the Ukraine aoi shows the same values inside the city
    g = D.grid("kyiv")
    dr, dc = g.offset_of(D.grid("ukraine"))
    r0, c0, h, w = ctx.zone.win
    u, _, _ = S.gap_raster("ukraine", 2021, (r0 + dr, c0 + dc, h, w))
    k, _, _ = S.gap_raster("kyiv", 2021, ctx.zone.win)
    assert np.nanmax(np.abs(u - k)) < 0.01


def test_excluded_year_is_explicit(poz_report):
    y2020 = next(r for r in poz_report["series"] if r["year"] == 2020)
    assert y2020["gap"] is None and y2020["method"] is None and y2020["excluded"] == "too_few_scenes"
    d = y2020["excluded_detail"]        # INVESTIGATION-2020: one usable pass (08-16, path 182), path 181 cloudy
    assert d["usable_dates"] == ["2020-08-16"] and d["n_passes_total"] == 12
    assert d["n_cloudy"] == 4 and d["n_outside_swath"] == 7 and "16.08" in d["text_uk"]
    assert all(r["excluded_detail"] is None for r in poz_report["series"] if r["excluded"] != "too_few_scenes")
    assert all(r["excluded"] is None and r["method"] in ("per_scene", "composite")
               for r in poz_report["series"] if r["gap"] is not None)


def test_green_gap_is_parks_not_forest(poz_report):
    gg = poz_report["green_gap"]
    assert gg["scope"] == "urban_parks"
    assert gg["mean"] < poz_report["gap_summary"]["mean"] - 0.5   # parks are warmer than the forest reference


def test_suburb_uses_city_reference():
    rep = S.analyze(_box(30.426, 50.357, 1200), name="Гатне")
    assert rep["reference"]["city"] == "kyiv" and rep["reference"]["kind"] == "preset"
    assert "suburb_reference" in {c["code"] for c in rep["caveats"]}
    assert rep["method"] in ("per_scene", "mixed")


def test_lst_product_gap_is_not_blamed_on_clouds():
    """SCI-01: central Маріуполь has clear NDVI every summer but no Landsat ST (ASTER GED emissivity gap)."""
    rep = S.analyze(_box(37.55, 47.10, 1000))
    reasons = {r["excluded"] for r in rep["series"]}
    assert reasons == {"no_lst_product"}
    codes = {c["code"] for c in rep["caveats"]}
    assert "no_lst_product" in codes and "years_excluded" not in codes
    assert "Це не хмари" in next(c["text_uk"] for c in rep["caveats"] if c["code"] == "no_lst_product")
    assert rep["zone"]["war_region"]["name"] == "Донецька область"
    # PM 4b: Маріуполь is in the official occupied list -> «окупована територія», not the generic war_zone
    assert "occupied" in codes and "war_zone" not in codes
    assert "станом на 15.09.2026" in next(c["text_uk"] for c in rep["caveats"] if c["code"] == "occupied")
    assert rep["zone"]["occupied"]["snapshot_date"] == "2026-09-15"


def test_front_line_city_keeps_war_zone():
    rep = S.analyze(_box(37.55, 48.72, 1500))       # Краматорськ: Donetsk oblast, not occupied
    codes = {c["code"] for c in rep["caveats"]}
    assert "war_zone" in codes and "occupied" not in codes and rep["zone"]["occupied"] is None


def test_zone_clipped_to_ukraine_border():
    """SCI-10: a box over Ужгород and Slovakia is analysed only on the Ukrainian side."""
    rep = S.analyze(_box(22.225, 48.62, 1500))
    assert rep["zone"]["clipped_km2"] and rep["zone"]["clipped_km2"] > 0.5
    assert rep["zone"]["area_km2"] + rep["zone"]["clipped_km2"] == pytest.approx(9.0, abs=0.2)
    assert "zone_clipped" in {c["code"] for c in rep["caveats"]}
    assert rep["zone"]["war_region"] is None


def test_analysed_area_never_exceeds_zone_area():
    """SCI-07: pixel counts are capped at the polygon area."""
    for lon, lat in ((30.52, 50.45), (30.62, 50.40), (36.23, 49.99)):
        z = S.analyze(_box(lon, lat, 440))["zone"]
        assert z["analysed_area_km2"] <= z["area_km2"] and z["built_area_km2"] <= z["area_km2"]


def test_derived_reference_masks_cropped_and_cache_bounded():
    """RB-01: derived masks are cropped to their content and the cache is bounded by bytes."""
    from uhd.science import reference as R
    from uhd.science.geometry import make_zone

    z, _ = make_zone(sg.mapping(sg.box(28.44, 49.21, 28.50, 49.25)))      # Вінниця
    r = R.derive_cached(z)
    for m in (r.ref | r.green | r.urban,):
        assert m[0].any() and m[-1].any() and m[:, 0].any() and m[:, -1].any()   # tight bbox
    assert r.nbytes < 8 * 2**20
    assert R._DERIVE_CACHE.maxbytes == R.DERIVE_CACHE_BYTES and R._DERIVE_CACHE.nbytes <= R.DERIVE_CACHE_BYTES


def test_scenes_outside_swath_and_zone_cloud():
    """/api/scenes: path-180 and edge-of-182 passes are outside_swath, not zone_cloudy; merged rows use the cloud of
    the row over the zone (INVESTIGATION-2020)."""
    poz = next(f for f in json.load(open(D.DATA / "places" / "demo.geojson"))["features"]
               if f["properties"]["id"] == "demo-pozniaky")
    sc = {r["date"]: r for r in S.list_scenes(poz["geometry"], 2020)}
    assert sc["2020-08-16"]["used"] and sc["2020-08-16"]["reason"] is None
    assert sc["2020-06-15"]["reason"] == "outside_swath" and sc["2020-06-15"]["zone_in_swath"] == 0
    assert sc["2020-06-13"]["reason"] == "outside_swath"
    assert sc["2020-06-06"]["reason"] == "zone_cloudy" and sc["2020-06-22"]["reason"] == "zone_cloudy"
    assert sc["2020-06-13"]["cloud"] < 13.8          # not the mean of rows 24 (25.2 %) and 25 (2.4 %)


def test_gapfill_rivne_2022_fills_year_holes_only():
    from uhd.science import gapfill as F
    from uhd.science.rasters import layer_raster

    g = D.grid("ukraine")
    from pyproj import Transformer
    x, y = Transformer.from_crs(4326, 3035, always_xy=True).transform(26.25, 50.9)
    r, c = int((g.y1 - y) / D.RES), int((x - g.x0) / D.RES)
    win = (r - 256, c - 256, 512, 512)
    base = layer_raster("ukraine", "gap", 2022, win)[0]
    f = layer_raster("ukraine", "gap_fill", 2022, win)[0]
    h = F.holes("ukraine", 2022, win)
    assert not (np.isfinite(f) & np.isfinite(base)).any()
    assert np.isfinite(f).mean() > 0.02                                 # Rivne 2022 has year-specific holes
    assert not (np.isfinite(f) & (F.hole_years("ukraine", win) >= F.PERSISTENT_YEARS)).any()
    assert not (np.isfinite(f) & ~h).any()


def test_built_share_land_zone_and_ghsl_sealed():
    """Board item 14 (INVESTIGATION-BUILT-SHARE): Франківськ lake + park circle — the old built_share is a share of the
    land; the zone share and the GHSL sealed-surface share are reported next to it (numbers unchanged)."""
    g = sg.Point(24.692, 48.914)
    from pyproj import Transformer
    from shapely.ops import transform
    to_m = Transformer.from_crs(4326, 3035, always_xy=True).transform
    to_ll = Transformer.from_crs(3035, 4326, always_xy=True).transform
    circle = transform(to_ll, transform(to_m, g).buffer(750))
    rep = S.analyze(sg.mapping(circle))
    r = rep["series"][0]
    assert r["built_share"] == r["built_share_land"] and r["built_share"] > 0.85
    assert r["built_share_zone"] < r["built_share_land"] - 0.1          # ~20 % of the circle is the lake
    sealed = rep["zone"]["sealed_share_ghsl"]
    assert set(sealed) == {"2015", "2020", "2025"} and 0 < sealed["2020"] < r["built_share_zone"] / 2


def test_reference_quality_caveats():
    """INVESTIGATION-REGIONAL-GAP caveats 1/2 and fix 3: Ужгород's forest is ~230 m higher, so since sci-v3.6 its
    reference is elevation-matched (and no longer «higher»); Миколаїв's reference is weak; Київ gets neither."""
    from uhd.science import elevmatch as EM
    from uhd.science import refquality as Q
    if not Q.dem_path().exists() or not EM.dem60_path().exists():
        pytest.skip("dem600.tif / dem60.tif not built")
    rep = S.analyze(_box(22.29, 48.62, 1500))
    uzh = {c["code"]: c["text_uk"] for c in rep["caveats"]}
    em = rep["reference"]["elevation_match"]
    assert em["applied"] and em["dz_before_m"] >= 150 and abs(em["dz_after_m"]) < 100
    assert 200 <= em["px_kept"] < em["px_total"] and rep["reference"]["forest_px"] == em["px_kept"]
    assert "ref_elev_matched" in uzh and "ref_higher" not in uzh
    myk = {c["code"] for c in S.analyze(_box(32.00, 46.96, 1500))["caveats"]}
    assert "ref_weak" in myk and "ref_higher" not in myk
    kyiv = {c["code"] for c in S.analyze(_box(30.52, 50.45, 1500))["caveats"]}
    assert not {"ref_higher", "ref_weak"} & kyiv


def test_reference_clipped_to_ukraine():
    """sci-v3.6 (INVESTIGATION-FOREIGN-REFERENCE): no reference forest abroad; Ужгород loses ~24 % to Slovakia/Hungary
    (caveat ref_border_clipped); the preset references are unchanged."""
    from uhd.science import reference as R
    from uhd.science.geometry import make_zone, rasterize

    poly = R._ukraine_polygon()
    for lon, lat in ((22.29, 48.62), (28.84, 45.35)):           # Ужгород, Ізмаїл
        zone, city = make_zone(_box(lon, lat, 1500))
        ref = R.derive(zone)
        _, ua = rasterize(poly, ref.aoi, ref.win)
        assert ref.forest_px > 0 and not (ref.ref & ~ua).any()
    rep = S.analyze(_box(22.29, 48.62, 1500))
    assert "ref_border_clipped" in {c["code"] for c in rep["caveats"]} and rep["reference"]["abroad_km2"] > 50
    assert R.preset("kyiv").forest_px == 98333
