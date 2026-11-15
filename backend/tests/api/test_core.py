from __future__ import annotations

import json

import httpx
import pytest

from tests.conftest import POZNIAKY
from uhd.services import analysis, places, weather


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    b = r.json()
    assert b["ok"] is True and b["data_version"] == "fixture-1" and b["science_ready"] is True
    assert "method_version" in b and "build" in b  # deploy.sh checks every worker serves the new build
    assert "X-Request-Id" in r.headers


def test_meta(client):
    b = client.get("/api/meta").json()
    assert b["years"] == [2013, 2025]
    assert set(b["layers"]["ids"]) == {"gap", "lst", "ndvi", "dndvi"}
    assert set(b["layers"]["internal"]) == {"gap_fill", "nonbuilt"}  # item 17: never a layer choice in the UI
    gap = b["layers"]["scales"]["gap"]
    assert gap["domain"] == [-6, 16] and gap["neutral"] == 0
    assert gap["stops"]["light"][0] == {"value": -6, "color": "#5C8C7A"}
    assert b["layers"]["reference_color"]["light"] == "#1D3FBF"
    assert any(p["id"] == "kyiv-pozniaky" for p in b["presets"])
    assert all("geometry" not in p for p in b["presets"])
    assert b["agent_configured"] is False


def test_places_presets_search(client):
    b = client.get("/api/places", params={"q": "Позн", "geocoder": "false"}).json()
    assert b["presets"][0]["id"] == "kyiv-pozniaky"
    b = client.get("/api/places", params={"q": "солом'ян", "geocoder": "false"}).json()
    assert b["presets"][0]["id"] == "kyiv-solomianskyi"
    b = client.get("/api/places", params={"q": "", "geocoder": "false"}).json()
    assert len(b["presets"]) >= 10


@pytest.mark.parametrize("q", ["Соломянський", "соломʼянський", "СОЛОМ’ЯНСЬКИЙ", "solomianskyi", "Солом`янський"])
def test_places_apostrophe_and_case_variants(client, q):
    b = client.get("/api/places", params={"q": q, "geocoder": "false"}).json()
    assert b["presets"] and b["presets"][0]["id"] == "kyiv-solomianskyi", b["presets"][:2]


def test_places_whole_word_beats_prefix(client):
    # QA-18: «Київ» → «Увесь Київ», not «Київський район (Харків)»
    names = {p["name"] for p in client.get("/api/places", params={"q": "", "geocoder": "false"}).json()["presets"]}
    b = client.get("/api/places", params={"q": "Київ", "geocoder": "false"}).json()
    assert b["presets"][0]["id"] == "kyiv", [p["id"] for p in b["presets"][:3]]
    if any(n.startswith("Київський район") for n in names):
        assert any(p["name"].startswith("Київський район") for p in b["presets"])  # still listed, lower
    for q, want in (("Харків", "kharkiv"), ("Львів", "lviv"), ("позняки", "kyiv-pozniaky")):
        got = client.get("/api/places", params={"q": q, "geocoder": "false"}).json()["presets"]
        if any(p["id"] == want for p in got):
            assert got[0]["id"] == want, (q, [p["id"] for p in got[:3]])


def test_place_get_and_404(client):
    p = client.get("/api/places/kyiv-pozniaky").json()
    assert p["kind"] == "demo_zone" and p["geometry"]["type"] == "Polygon" and 3.0 < p["area_km2"] < 3.3
    r = client.get("/api/places/nope")
    assert r.status_code == 404 and r.json()["error"] == "place_not_found"


def test_geocoder_proxy_cached_and_rate_limited(client, monkeypatch):
    calls = []

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return [{"osm_type": "relation", "osm_id": 1, "name": "Бровари", "display_name": "Бровари, Україна",
                     "lat": "50.51", "lon": "30.79", "boundingbox": ["50.4", "50.6", "30.7", "30.9"],
                     "category": "boundary", "type": "administrative", "addresstype": "city"}]

    class C:
        def get(self, url, params=None):
            calls.append((url, params))
            return Resp()

    monkeypatch.setattr(places, "client", lambda: C())
    b = client.get("/api/places", params={"q": "Бровари"}).json()
    assert b["geocoder"][0]["id"] == "osm:R1" and b["geocoder"][0]["bbox"] == [30.7, 50.4, 30.9, 50.6]
    client.get("/api/places", params={"q": "Бровари"})
    assert len(calls) == 1  # disk cache hit
    assert calls[0][1]["countrycodes"] == "ua"


def test_geocoder_down_degrades(client, monkeypatch):
    class C:
        def get(self, *a, **k):
            raise httpx.ConnectError("down")

    monkeypatch.setattr(places, "client", lambda: C())
    r = client.get("/api/places", params={"q": "Деснянський парк"})
    assert r.status_code == 200 and r.json()["geocoder"] == []


def test_geocoder_limiter_is_global_and_non_blocking(client, monkeypatch):
    # REVIEW M7: one slot file for all workers; a busy limiter answers at once (presets only, geocoder_busy)
    import multiprocessing as mp
    import time

    from uhd.services.http import SlotLimiter

    lim = SlotLimiter("t-geo", 1.0)
    assert lim.reserve(0.0) == 0.0
    t0 = time.monotonic()
    assert lim.reserve(0.3) is None and time.monotonic() - t0 < 0.1  # busy → no sleeping
    w = lim.reserve(2.0)
    assert w is not None and 0.8 < w <= 1.0  # next slot exactly one interval later
    ctx = mp.get_context("spawn")
    with ctx.Pool(4) as pool:  # other processes see the same reservations
        res = pool.starmap(_reserve_in_other_process, [(str(lim.path), 0.0)] * 4)
    assert res == [None] * 4

    calls = []

    class C:
        def get(self, url, params=None):
            calls.append(params)
            raise AssertionError("must not call the geocoder while busy")

    monkeypatch.setattr(places, "client", lambda: C())
    monkeypatch.setattr(places, "_limiter", lambda: SlotLimiter("t-geo", 1.0))
    lim.reserve(10.0), lim.reserve(10.0)  # queue is now > 2 s long
    t0 = time.monotonic()
    b = client.get("/api/places", params={"q": "Деснянський парк"}).json()
    assert b["geocoder"] == [] and b["geocoder_status"] == "geocoder_busy" and not calls
    assert time.monotonic() - t0 < 1.0
    r = client.get("/api/places/osm:R123")
    assert r.status_code == 503 and r.json()["error"] == "geocoder_busy"


def test_analyze_and_report_roundtrip(client):
    r = client.post("/api/analyze", json={"geometry": POZNIAKY, "name": "Тест"})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert len(rep["report_id"]) == 16
    assert rep["zone"]["name"] == "Тест" and rep["zone"]["area_km2"] > 0
    assert rep["trend"]["verdict"] in ("significant", "not_significant", "insufficient_data")
    assert rep["params"]["data_version"] == "fixture-1" and rep["params"]["years"] == [2013, 2025]
    # same geometry → same id (cache), different winding/precision noise → same id
    ring = POZNIAKY["coordinates"][0][::-1]
    r2 = client.post("/api/analyze", json={"geometry": {"type": "Polygon", "coordinates": [ring]}})
    assert r2.json()["report_id"] == rep["report_id"]
    got = client.get(f"/api/reports/{rep['report_id']}").json()
    assert got["series"] == rep["series"]
    r = client.get("/api/reports")
    assert r.status_code == 403 and r.json()["error"] == "team_only"  # RB-11: visitors' polygons are private
    import os

    os.environ["UHD_AGENT_TEAM_TOKEN"] = "t0k"
    from uhd.config import get_settings

    get_settings.cache_clear()
    try:
        lst = client.get("/api/reports", headers={"x-uhd-team-token": "t0k"}).json()["reports"]
    finally:
        del os.environ["UHD_AGENT_TEAM_TOKEN"]
        get_settings.cache_clear()
    assert lst[0]["report_id"] == rep["report_id"]


def test_report_name_is_never_stored(client):
    """REVIEW M8: name/place_id of one caller must not leak to other callers or to the stored report."""
    from uhd.services import analysis, reports

    p = client.get("/api/places/kyiv-pozniaky").json()
    bad = client.post("/api/analyze", json={"geometry": p["geometry"], "name": "Звалище",
                                            "place_id": "kyiv-teremky"}).json()
    assert bad["zone"]["name"] == "Звалище" and bad["params"]["place_id"] is None  # place_id ≠ geometry → dropped
    anon = client.post("/api/analyze", json={"geometry": p["geometry"]}).json()
    assert anon["report_id"] == bad["report_id"]
    assert anon["zone"]["name"] is None and anon["params"]["place_id"] is None
    assert "Звалище" not in json.dumps(anon, ensure_ascii=False)
    stored = client.get(f"/api/reports/{anon['report_id']}").json()
    assert stored["zone"]["name"] is None and "Звалище" not in json.dumps(stored, ensure_ascii=False)
    named = client.post("/api/analyze", json={"place_id": "kyiv-pozniaky"}).json()
    assert named["zone"]["name"] == p["name"] and named["params"]["place_id"] == "kyiv-pozniaky"
    same = client.post("/api/analyze", json={"geometry": p["geometry"], "place_id": "kyiv-pozniaky"}).json()
    assert same["params"]["place_id"] == "kyiv-pozniaky"
    # verdict text gets the requested name at response time
    rep = {"verdict_text_uk": "Ця територія: забудова гарячіша.", "zone": {}, "params": {}}
    assert analysis.label(rep, "Позняки", None)["verdict_text_uk"] == "Позняки: забудова гарячіша."
    assert analysis.label(rep, None, None)["verdict_text_uk"] == "Забудова гарячіша."  # neutral, no placeholder
    assert reports.get(anon["report_id"])["zone"]["name"] is None
    assert not anon["verdict_text_uk"].startswith("Ця територія")
    assert not stored["verdict_text_uk"].startswith("Ця територія")
    lab = client.get(f"/api/reports/{anon['report_id']}", params={"name": "Мій двір"}).json()
    assert lab["zone"]["name"] == "Мій двір"
    raw = reports.get(anon["report_id"])["verdict_text_uk"]
    if raw.startswith("Ця територія"):  # real science text (the fake backend writes a test banner instead)
        assert lab["verdict_text_uk"].startswith("Мій двір: ") and named["verdict_text_uk"].startswith(p["name"])


def test_verdict_not_redecided_from_rounded_p(client):
    """REVIEW M10: science decides on the raw p; a rounded p = 0.05 must not flip 'significant'."""
    from uhd.services import analysis

    t = {"slope_per_decade": 1.0, "p": 0.05, "n_years": 13, "verdict": "significant"}
    analysis._check_verdict(t)
    assert t["verdict"] == "significant"
    t = {"slope_per_decade": 1.0, "p": 0.01, "n_years": 6, "verdict": "significant"}
    analysis._check_verdict(t)
    assert t["verdict"] == "insufficient_data"
    t = {"slope_per_decade": 1.0, "p": 0.01, "n_years": 13, "verdict": "bogus"}
    analysis._check_verdict(t)
    assert t["verdict"] == "significant"


def test_analyze_by_place_id_and_years(client):
    rep = client.post("/api/analyze", json={"place_id": "kyiv-pozniaky", "years": [2015, 2020]}).json()
    assert rep["zone"]["name"].startswith("Позняки") and [s["year"] for s in rep["series"]] == list(range(2015, 2021))
    assert rep["params"]["place_id"] == "kyiv-pozniaky"


@pytest.mark.parametrize("body,code", [
    ({}, "missing_geometry"),
    ({"geometry": {"type": "Point", "coordinates": [30, 50]}}, "invalid_geometry"),
    ({"geometry": {"type": "Polygon", "coordinates": [[[2, 48], [2.1, 48], [2.1, 48.1], [2, 48]]]}}, "outside_coverage"),
    ({"geometry": {"type": "Polygon", "coordinates": [[[30.5, 50.4], [30.505, 50.4], [30.505, 50.405], [30.5, 50.4]]]}},
     "area_too_small"),
    ({"geometry": {"type": "Polygon", "coordinates": [[[31.4656, 50.0178], [31.7557, 50.6285], [30.779, 50.8134], [30.5, 50.2], [31.4656, 50.0178]]]}},
     "area_too_large"),
    ({"geometry": {"type": "Polygon", "coordinates": [[[25, 46], [35, 46], [35, 51], [25, 46]]]}}, "bbox_too_large"),
    # REVIEW H1: two 0.4 km² squares ~1300 km apart (tiny area, huge raster window)
    ({"geometry": {"type": "MultiPolygon", "coordinates": [
        [[[22.3, 48.4], [22.309, 48.4], [22.309, 48.406], [22.3, 48.406], [22.3, 48.4]]],
        [[[39.6, 49.0], [39.609, 49.0], [39.609, 49.006], [39.6, 49.006], [39.6, 49.0]]]]}}, "bbox_too_large"),
    # 1 km wide, 400 km long sliver
    ({"geometry": {"type": "Polygon", "coordinates": [[[26, 49], [31.6, 49], [31.6, 49.01], [26, 49.01], [26, 49]]]}},
     "bbox_too_large"),
    ({"geometry": POZNIAKY, "years": [2010, 2020]}, "invalid_years"),
    ({"geometry": POZNIAKY, "years": [2020, 2015]}, "invalid_years"),
])
def test_analyze_validation(client, body, code):
    r = client.post("/api/analyze", json=body)
    assert r.status_code == 422 and r.json()["error"] == code, r.text


def test_self_intersecting_polygon_is_repaired(client):
    bow = {"type": "Polygon", "coordinates": [[[30.60, 50.40], [30.64, 50.42], [30.64, 50.40], [30.60, 50.42],
                                               [30.60, 50.40]]]}
    assert client.post("/api/analyze", json={"geometry": bow}).status_code == 200


def test_report_errors(client):
    assert client.get("/api/reports/xyz").json()["error"] == "invalid_report_id"
    assert client.get("/api/reports/0123456789abcdef").status_code == 404


def test_verdict_rule():
    d = analysis.decide_verdict
    assert d({"p": 0.01, "n_years": 13, "slope_per_decade": 1}) == "significant"
    assert d({"p": 0.2, "n_years": 13, "slope_per_decade": 1}) == "not_significant"
    assert d({"p": 0.01, "n_years": 7, "slope_per_decade": 1}) == "insufficient_data"
    assert d(None) == "insufficient_data"


def test_scenes_endpoint(client):
    b = client.get("/api/scenes", params={"place_id": "kyiv-pozniaky", "year": 2013}).json()
    assert b["count"] > 0 and b["scenes"][0]["zone_lst"] is not None
    rep = client.post("/api/analyze", json={"geometry": POZNIAKY}).json()
    b2 = client.get("/api/scenes", params={"report_id": rep["report_id"], "year": 2013}).json()
    assert b2["count"] == b["count"]
    b3 = client.get("/api/scenes", params={"geometry": json.dumps(POZNIAKY), "year": 2013}).json()
    assert b3["count"] == b["count"]
    sid = b["scenes"][0]["id"]
    st = client.get(f"/api/scenes/{sid}", params={"place_id": "kyiv-pozniaky"}).json()
    assert st["scene_id"] == sid and st["source"] == "science"
    assert client.get("/api/scenes", params={"year": 2013}).json()["error"] == "missing_geometry"


def test_merged_scene_cloud_fields_use_the_same_rule(client, monkeypatch):
    # SCI-08: a same-date merge of two rows: cloud and cloud_cover_land follow the same rule (equal overlap → mean)
    from shapely.geometry import box, shape

    from uhd.services import scenes as sc

    fp = box(29, 49, 32, 52)
    items = [{"id": "A", "datetime": "2021-06-16T09:00:00Z", "date": "2021-06-16", "cloud_cover": 30.0,
              "cloud_cover_land": 20.0, "sun_elevation": 60.0, "_footprint": fp},
             {"id": "B", "datetime": "2021-06-16T09:00:20Z", "date": "2021-06-16", "cloud_cover": 50.0,
              "cloud_cover_land": 51.62, "sun_elevation": 60.0, "_footprint": fp}]
    monkeypatch.setattr(sc, "_items", lambda aoi, y: items)
    monkeypatch.setattr(sc, "_science_rows", lambda g, y: [{"id": "A", "ids": ["A", "B"], "date": "2021-06-16",
                                                           "cloud": 40.0}])
    b = client.get("/api/scenes", params={"place_id": "kyiv-pozniaky", "year": 2013}).json()
    row = b["scenes"][0]
    assert row["cloud"] == 40.0 and row["cloud_cover_land"] == 35.81

    # sci-v3.4: weighted by zone overlap — row B covers only a sliver of the zone → cloud_cover_land ≈ A's
    from uhd.services.places import get_place

    z = shape(get_place("kyiv-pozniaky")["geometry"])
    x0, y0, x1, y1 = z.bounds
    items[1]["_footprint"] = box(x1 - 0.1 * (x1 - x0), 49, 32, 52)  # ~10 % of the zone
    monkeypatch.setattr(sc, "_science_rows", lambda g, y: [{"id": "A", "ids": ["A", "B"], "date": "2021-06-16",
                                                           "cloud": 23.0}])
    row = client.get("/api/scenes", params={"place_id": "kyiv-pozniaky", "year": 2013}).json()["scenes"][0]
    assert 20.0 < row["cloud_cover_land"] < 25.0, row


def test_weather_proxy_cache(client, monkeypatch):
    calls = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"latitude": 50.4, "longitude": 30.6,
                    "daily": {"time": ["2021-07-07", "2021-07-08", "2021-07-09", "2021-07-10"],
                              "temperature_2m_max": [28, 30, 31, 33.5], "precipitation_sum": [0, 4.2, 0, 0]},
                    "daily_units": {"temperature_2m_max": "°C"},
                    "hourly": {"time": ["2021-07-10T10:00", "2021-07-10T11:00", "2021-07-10T13:00"],
                               "temperature_2m": [27.1, 28.4, 30.0]}}

    class C:
        def get(self, url, params=None):
            calls.append(params)
            return Resp()

    monkeypatch.setattr(weather, "client", lambda: C())
    b = client.get("/api/weather", params={"date": "2021-07-10", "lat": 50.41, "lon": 30.627}).json()
    assert b["day"]["temperature_2m_max"] == 33.5 and len(b["previous_days"]) == 3
    assert [h["time"] for h in b["overpass_hours_local"]] == ["2021-07-10T10:00", "2021-07-10T11:00"]
    client.get("/api/weather", params={"date": "2021-07-10", "lat": 50.41, "lon": 30.627})
    assert len(calls) == 1
    assert client.get("/api/weather", params={"date": "2999-01-01", "lat": 50, "lon": 30}).json()["error"] == "invalid_date"
    assert client.get("/api/weather", params={"date": "bad", "lat": 50, "lon": 30}).status_code == 422
    # REVIEW L: not an open weather proxy for the whole world
    for lat, lon in ((48.85, 2.35), (40.7, -74.0), (55.75, 37.6)):
        r = client.get("/api/weather", params={"date": "2021-07-10", "lat": lat, "lon": lon})
        assert r.status_code == 422 and r.json()["error"] == "outside_coverage"


def test_spa_fallback(client, tmp_path):
    from uhd.config import get_settings

    dist = get_settings().frontend_dist
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>uhd</html>")
    (dist / "assets" / "a.js").write_text("x")
    assert client.get("/").text == "<html>uhd</html>"
    assert client.get("/report/abc").text == "<html>uhd</html>"
    r = client.get("/assets/a.js")
    assert r.text == "x" and "immutable" in r.headers["cache-control"]
    assert client.get("/api/does-not-exist").status_code == 404
    assert client.get("/../etc/passwd").text == "<html>uhd</html>"


def test_cors_preflight(client):
    r = client.options("/api/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_science_places_merge_keeps_ascii_ids(client, tmp_path):
    from uhd.config import get_settings

    d = get_settings().data_dir / "places"
    d.mkdir(parents=True)
    poly = {"type": "Polygon", "coordinates": [[[30.6, 50.4], [30.7, 50.4], [30.7, 50.45], [30.6, 50.45], [30.6, 50.4]]]}
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"id": "kyiv-дарницький-район", "name": "Дарницький район", "kind": "district",
                                           "city": "kyiv"}, "geometry": poly},
        {"type": "Feature", "properties": {"id": "kyiv-русанівка", "name": "Русанівка", "kind": "locality", "city": "kyiv"},
         "geometry": poly}]}
    (d / "kyiv.geojson").write_text(json.dumps(fc, ensure_ascii=False))
    places.presets.cache_clear()
    p = client.get("/api/places/kyiv-darnytskyi").json()
    assert p["geometry"] == poly and p["name"].startswith("Дарницький")
    ids = [x["id"] for x in client.get("/api/places", params={"q": "Дарни", "geocoder": "false"}).json()["presets"]]
    assert ids == ["kyiv-darnytskyi"]
    assert client.get("/api/places/kyiv-дарницький-район").json()["id"] == "kyiv-darnytskyi"  # alias
    p = client.get("/api/places/kyiv-rusanivka").json()
    assert p["kind"] == "locality" and p["aliases"] == ["kyiv-русанівка"]
    assert client.get("/api/places/kyiv-русанівка").json()["id"] == "kyiv-rusanivka"
    all_ids = [x["id"] for x in client.get("/api/meta").json()["presets"]]
    assert all(i.isascii() for i in all_ids) and len(all_ids) == len(set(all_ids))


def test_science_demo_presets(client):
    from uhd.config import get_settings

    d = get_settings().data_dir / "places"
    d.mkdir(parents=True)
    poly = {"type": "Polygon", "coordinates": [[[30.6, 50.4], [30.7, 50.4], [30.7, 50.45], [30.6, 50.45], [30.6, 50.4]]]}
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"id": "demo-desnianske", "name": "Деснянське", "kind": "demo", "city": "kyiv",
                                           "case": "greening", "note_uk": "зеленішає"}, "geometry": poly},
        {"type": "Feature", "properties": {"id": "demo-pozniaky", "name": "Позняки (≈1 км)", "kind": "demo",
                                           "city": "kyiv", "case": "hot_stable", "note_uk": "стик"}, "geometry": poly}]}
    (d / "demo.geojson").write_text(json.dumps(fc, ensure_ascii=False))
    places.presets.cache_clear()
    pre = client.get("/api/meta").json()["presets"]
    assert pre[0]["kind"] == "demo_zone" and pre[0].get("case")
    des = next(p for p in pre if p["id"] == "demo-desnianske")
    assert des["kind"] == "demo_zone" and des["case"] == "greening" and des["note_uk"] == "зеленішає"
    poz = client.get("/api/places/demo-pozniaky").json()
    assert poz["id"] == "kyiv-pozniaky" and poz["case"] == "hot_stable" and poz["geometry"] == poly
    assert sum(1 for p in pre if "pozniaky" in p["id"]) == 1


def _reserve_in_other_process(path: str, max_wait: float):
    from pathlib import Path

    from uhd.services.http import SlotLimiter

    lim = SlotLimiter("t-geo", 1.0)
    type(lim).path = property(lambda self: Path(path))
    return lim.reserve(max_wait)


def test_round2_robustness(client):
    # deeply nested wrappers → 422, never a RecursionError 500
    g: dict = {"type": "Polygon", "coordinates": [[[30.5, 50.4], [30.52, 50.4], [30.52, 50.42], [30.5, 50.4]]]}
    for _ in range(2000):
        g = {"type": "Feature", "geometry": g}
    r = client.post("/api/analyze", json={"geometry": g})
    assert r.status_code == 422 and r.json()["error"] == "invalid_geometry"
    deep = "[" * 100000 + "]" * 100000
    r = client.post("/api/analyze", content=deep, headers={"content-type": "application/json"})
    assert r.status_code in (400, 422)
    # NUL byte / junk SPA paths → 404, not 500
    for path in ("/index.html%00.js", "/%00", "/a" * 400):
        assert client.get(path).status_code in (200, 404)
    assert client.get("/index.html%00.js").status_code == 404
    # absurd osm ids are rejected locally
    for pid, code in (("osm:N999999999999999999999999999", 422), ("osm:X1", 422), ("osm:N12a", 422), ("osm:R0", 404)):
        r = client.get(f"/api/places/{pid}")
        assert r.status_code == code, (pid, r.text)
        r = client.post("/api/analyze", json={"place_id": pid})
        assert r.status_code == code, (pid, r.text)


@pytest.mark.parametrize("gj", [
    {"type": "Point", "coordinates": [30.5234, 50.4501]},
    {"type": "Polygon", "coordinates": [[[30.523, 50.45], [30.525, 50.45], [30.525, 50.451], [30.523, 50.45]]]},
])
def test_point_like_geocoder_result_becomes_1km_circle(client, monkeypatch, gj):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"osm_type": "way", "osm_id": 5, "name": "площа Ринок", "display_name": "площа Ринок, Київ",
                     "lat": "50.4501", "lon": "30.5234", "geojson": gj}]

    monkeypatch.setattr(places, "client", lambda: type("C", (), {"get": lambda self, *a, **k: Resp()})())
    p = client.get("/api/places/osm:W5").json()
    assert p["kind"] == "geocoder_circle" and p["name"] == "площа Ринок (≈1 км навколо)" and 3.0 < p["area_km2"] < 3.3
    rep = client.post("/api/analyze", json={"place_id": "osm:W5"}).json()
    assert rep["zone"]["name"] == "площа Ринок (≈1 км навколо)", rep
    assert rep["caveats"][0]["code"] == "geocoder_circle"


def test_rb05_body_limit_request_id_and_security_headers(client):
    big = b'{"geometry": {"type": "Polygon", "coordinates": []}, "pad": "' + b"x" * 2_100_000 + b'"}'
    r = client.post("/api/analyze", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json()["error"] == "payload_too_large"

    def chunks():
        for _ in range(30):
            yield b"x" * 100_000

    r = client.post("/api/analyze", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413
    r = client.get("/api/health", headers={"x-request-id": "a" * 500})
    assert len(r.headers["x-request-id"]) <= 64 and r.headers["x-request-id"] != "a" * 500
    r = client.get("/api/health", headers={"x-request-id": "qa-run.1"})
    assert r.headers["x-request-id"] == "qa-run.1"
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "tiles.openfreemap.org" in r.headers["content-security-policy"]
    csp = dict(d.strip().split(" ", 1) for d in r.headers["content-security-policy"].split(";"))
    for d in ("img-src", "connect-src"):  # item 7 «Супутник»: EOX raster tiles are fetched by MapLibre
        assert "https://tiles.maps.eox.at" in csp[d].split(), d
        assert "https://wayback.maptiles.arcgis.com" in csp[d].split(), d
    # satellite capture dates (frontend lib/wayback.ts): the Wayback release list and the per-release imagery metadata
    assert "https://metadata.maptiles.arcgis.com" in csp["connect-src"].split()
    assert "https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/" in csp["connect-src"].split()


def test_rb09_strict_coordinates_and_hole_equal_to_shell(client):
    sq = [[30.5, 50.4], [30.53, 50.4], [30.53, 50.42], [30.5, 50.42], [30.5, 50.4]]
    for coords in ([[[str(a), str(b)] for a, b in sq]], [[[True, 50.4]] + sq[1:]], [[[30.5]] + sq[1:]], [["x"]]):
        r = client.post("/api/analyze", json={"geometry": {"type": "Polygon", "coordinates": coords}})
        assert r.status_code == 422 and r.json()["error"] == "invalid_geometry", (coords, r.text)
    r = client.post("/api/analyze", json={"geometry": {"type": "Polygon", "coordinates": [sq, sq[::-1]]}})
    assert r.status_code == 422 and r.json()["error"] == "invalid_geometry"
    bowtie = [[30.5, 50.4], [30.53, 50.42], [30.53, 50.4], [30.5, 50.42], [30.5, 50.4]]
    assert client.post("/api/analyze", json={"geometry": {"type": "Polygon", "coordinates": [bowtie]}}).status_code == 200


def test_health_deep(client):
    b = client.get("/api/health", params={"deep": 1}).json()
    assert b["checks"]["cache_writable"] and b["checks"]["reports_writable"] and b["checks"]["years"] > 0
    assert "disk_free_gb" in b["checks"] and b["ok"] is True


def test_report_context_hotspots_and_rank(client, monkeypatch):
    from uhd.services import context, reports

    rep = client.post("/api/analyze", json={"place_id": "kyiv-pozniaky"}).json()
    assert isinstance(rep["hotspots"], list)  # the fixture raster is flat → usually none (no place ≥ 1 °C hotter)
    assert reports.get(rep["report_id"])["hotspots_version"] == context.HOTSPOTS_VERSION  # stored once with the report
    assert "context" not in reports.get(rep["report_id"])  # per-response, never stored
    hs = rep["hotspots"]

    m = rep["gap_summary"]["mean"]
    basis = rep["zone"].get("basis")
    tbl = {"city": "kyiv", "districts": [{"place_id": f"kyiv-d{i}", "name": f"d{i}", "gap_mean": m + d, "basis": basis,
                                          "analysed_area_km2": 40.0 + i}
                                         for i, d in enumerate((3.0, 1.0, -1.0, -2.0, -4.0))]
           + [{"place_id": "kyiv-other", "name": "x", "gap_mean": m + 9, "basis": "other_basis"}]}  # never mixed in
    monkeypatch.setattr(context, "table", lambda city, build_if_missing=True: tbl)
    r = client.post("/api/analyze", json={"place_id": "kyiv-pozniaky"}).json()
    rk = r["context"]["rank"]
    za = rep["zone"].get("analysed_area_km2")
    assert {k: rk[k] for k in ("rank", "of", "percentile", "city", "metric", "compared_with", "is_district",
                               "district_gap_range", "basis", "compared_to_uk", "district_analysed_km2_range")} == {
        "rank": 3, "of": 6, "percentile": 60, "city": "kyiv", "metric": "gap_mean", "compared_with": "districts",
        "is_district": False, "district_gap_range": [m - 4.0, m + 3.0], "basis": basis,
        "compared_to_uk": f"порівняно із {'забудовою' if basis == 'always_built' else 'територією'} 5 районів Києва",
        "district_analysed_km2_range": [40.0, 44.0]}
    assert rk["district_extremes"] == {
        "hottest": {"id": "kyiv-d0", "name": "d0", "short_name": "d0", "gap": m + 3.0},
        "coolest": {"id": "kyiv-d4", "name": "d4", "short_name": "d4", "gap": m - 4.0}}  # other-basis row ignored
    assert rk["zone_analysed_km2"] == za
    assert rk["like_for_like"] is (not (za and za < 10.0)) and (rk["note_uk"] is None) is rk["like_for_like"]
    tbl["districts"][1]["place_id"] = "kyiv-pozniaky"  # a district is ranked among the others, not twice
    r = client.post("/api/analyze", json={"place_id": "kyiv-pozniaky"}).json()
    assert r["context"]["rank"]["of"] == 5 and r["context"]["rank"]["is_district"] is True
    got = client.get(f"/api/reports/{rep['report_id']}").json()
    assert "rank" in got["context"] and got["hotspots"] == hs
    assert client.post("/api/analyze", json={"place_id": "kyiv"}).json()["context"]["rank"] is None


def test_rank_table_builds_in_background_and_never_blocks(client, monkeypatch):
    from uhd.services import context

    calls = []
    monkeypatch.setattr(context, "_build_bg", lambda city: calls.append(city))
    context._tables.clear()
    rep = client.post("/api/analyze", json={"place_id": "kyiv-pozniaky"}).json()
    assert rep["context"]["rank"] is None  # no table yet → null now, built in the background
    import time

    time.sleep(0.2)
    assert calls == ["kyiv"]
    context._building.clear()


def test_rank_small_zone_note_and_plural():
    from uhd.services import context

    assert context._districts_word(1) == "району" and context._districts_word(10) == "районів"
    assert context._districts_word(21) == "району" and context._districts_word(11) == "районів"
    rep = {"zone": {"city": "kyiv", "basis": "always_built", "analysed_area_km2": 2.891}, "gap_summary": {"mean": 11.41}}
    tbl = {"districts": [{"place_id": f"d{i}", "name": "d", "gap_mean": 7 + i * 0.1, "basis": "always_built",
                          "analysed_area_km2": a} for i, a in enumerate((50.7, 43.0, 319.1))]}
    import unittest.mock as um

    with um.patch.object(context, "table", lambda city, build_if_missing=True: tbl):
        rk = context.rank(rep, "kyiv-pozniaky")
    assert rk["compared_to_uk"] == "порівняно із забудовою 3 районів Києва"
    assert rk["district_extremes"]["hottest"]["id"] == "d2" and rk["district_extremes"]["coolest"]["gap"] == 7
    assert rk["like_for_like"] is False and rk["note_uk"].startswith("Ділянка невелика (2,9 км² забудови), а в районах — 43–319 км²")


def test_half_up_rounding_matches_texts():
    from uhd.services.num import rnd

    assert rnd(7.55, 1) == 7.6 and round(7.55, 1) == 7.5  # R3-9: Python's round is binary, ours is decimal half-up
    assert rnd(7.550000000000001, 1) == 7.6 and rnd(-0.05, 1) == -0.1 and rnd(2.675, 2) == 2.68
    assert rnd(None) is None and rnd(float("nan")) is None


def test_multipolygon_empty_part_clean_message(client):  # RB-15
    g = {"type": "MultiPolygon", "coordinates": [[[[30.5, 50.4], [30.52, 50.4], [30.52, 50.42], [30.5, 50.4]]], []]}
    r = client.post("/api/analyze", json={"geometry": g})
    assert r.status_code == 422, r.text
    msg = r.json()["message"]
    assert "index" not in msg and "list" not in msg and "Не вдалося прочитати межі" in msg


def test_search_major_city_before_districts(client):  # R3-5
    for q, name in (("Дніпро", "Дніпро"), ("дніпро", "Дніпро"), ("Днепр", "Дніпро"), ("Одеса", "Одеса"),
                    ("Запоріжжя", "Запоріжжя"), ("Маріуполь", "Маріуполь"), ("Кривий", "Кривий Ріг"),
                    ("Слов'янськ", "Слов’янськ"), ("Odesa", "Одеса")):
        pre = client.get("/api/places", params={"q": q, "geocoder": "false"}).json()["presets"]
        assert pre and pre[0]["name"] == name and pre[0]["kind"] == "city", (q, pre[:2])
        assert pre[0]["id"].startswith("osm:R") and "geometry" not in pre[0]
    pre = client.get("/api/places", params={"q": "Дніпро", "geocoder": "false"}).json()["presets"]
    assert [p["id"] for p in pre[:2]] == [pre[0]["id"], "kyiv-dniprovskyi"]
    assert client.get("/api/places", params={"q": "Київ", "geocoder": "false"}).json()["presets"][0]["id"] == "kyiv"
    meta = client.get("/api/meta").json()
    assert not any(p["id"].startswith("osm:") for p in meta["presets"])  # the default list stays analysed presets


def test_rank_geometry_equal_to_district_is_that_district(client, monkeypatch):  # R4-2
    from uhd.services import context, places

    d = places.get_place("kyiv-solomianskyi")
    rep = client.post("/api/analyze", json={"geometry": d["geometry"]}).json()  # no place_id (share link, old client)
    basis = rep["zone"].get("basis")
    ids = [p["id"] for p in context._districts("kyiv")]
    tbl = {"districts": [{"place_id": pid, "name": pid, "gap_mean": 5 + i * 0.5, "basis": basis, "analysed_area_km2": 40}
                         for i, pid in enumerate(ids)]}
    monkeypatch.setattr(context, "table", lambda city, build_if_missing=True: tbl)
    rk = client.post("/api/analyze", json={"geometry": d["geometry"]}).json()["context"]["rank"]
    assert rk["of"] == len(ids) and rk["is_district"] is True
    assert rk["compared_to_uk"] == f"порівняно із {'забудовою' if basis == 'always_built' else 'територією'} {len(ids) - 1} районів Києва"
    small = places.get_place("kyiv-pozniaky")  # a different zone is still compared with all districts
    rk = client.post("/api/analyze", json={"geometry": small["geometry"]}).json()["context"]["rank"]
    assert rk["of"] == len(ids) + 1 and rk["is_district"] is False


def _synthetic_hot_field(monkeypatch, geom):
    """Gap raster: 5 °C everywhere, a compact +6 °C blob (3×3 px) and a +3 °C one inside the zone ≥ 1 km apart,
    a +8 °C strip just outside the zone edge (must not pull a marker out) and a +9 °C pixel block that is not built."""
    import numpy as np

    from uhd.services import context, rasters
    from uhd.services.geometry import parse_geometry, to_3035
    from uhd.tiles import pyramid

    g = parse_geometry(geom)
    aoi = rasters.pick_aoi(g)
    gr = rasters.grid(aoi)
    res = gr["res"]
    x0, y0, x1, y1 = to_3035(g).bounds

    def rc(fx, fy):  # fraction of the zone bbox → absolute pixel
        return int((gr["y1"] - (y0 + fy * (y1 - y0))) // res), int((x0 + fx * (x1 - x0) - gr["x0"]) // res)

    blobs = [(rc(0.25, 0.7), 6.0, 1), (rc(0.75, 0.25), 3.0, 1)]
    edge_r, edge_c = rc(0.5, 1.0)
    unbuilt = rc(0.5, 0.5)

    def field(r0, c0, h, w):
        rr, cc = np.mgrid[r0:r0 + h, c0:c0 + w]
        a = np.full((h, w), 5.0, np.float32)
        for (r, c), d, k in blobs:
            a[(abs(rr - r) <= k) & (abs(cc - c) <= k)] += d
        a[(rr >= edge_r - 3) & (rr <= edge_r - 1)] += 8.0  # just outside the zone's top edge
        a[(abs(rr - unbuilt[0]) <= 1) & (abs(cc - unbuilt[1]) <= 1)] += 9.0
        return a

    monkeypatch.setattr(pyramid, "read_window", lambda aoi, layer, y, r0, c0, h, w: field(r0, c0, h, w))

    def classes(aoi, win, years):
        r0, c0, h, w = win
        rr, cc = np.mgrid[r0:r0 + h, c0:c0 + w]
        cls = np.ones((len(years), h, w), np.uint8)
        cls[:, (abs(rr - unbuilt[0]) <= 1) & (abs(cc - unbuilt[1]) <= 1)] = 3  # nature: never a hotspot
        return cls

    monkeypatch.setattr(context, "_classes", classes)
    return blobs


def test_hotspots_compact_synthetic(monkeypatch):
    import math

    from shapely.geometry import Point, shape

    from tests.conftest import POZNIAKY
    from uhd.services import context

    _synthetic_hot_field(monkeypatch, POZNIAKY)
    rep = {"params": {"geometry": POZNIAKY}, "series": [{"year": y, "gap": 5.0} for y in (2023, 2024, 2025)]}
    hs = context.hotspots(rep)
    zone = shape(POZNIAKY)
    assert 1 <= len(hs) <= 3, hs
    # the hottest is the +6 °C blob, compact, distinctly hotter than the zone, marker inside the zone
    h0 = hs[0]
    assert h0["area_km2"] <= 0.25 and h0["delta_vs_zone"] >= 1.0 and h0["gap"] > h0["zone_built_mean_gap"] + 1
    assert h0["gap_peak_px"] >= 10.9 and h0["land_class"]["class"] == "built" and h0["years"][-1] == 2025
    assert h0["scale"] == "local"
    for h in hs:
        pt = Point(h["lon"], h["lat"])
        assert zone.contains(pt), h  # never on/outside the edge (the hot strip outside the zone is ignored)
        poly = shape(h["polygon"])
        assert poly.is_valid and not poly.is_empty and poly.buffer(1e-4).contains(pt)
        assert zone.buffer(1e-5).contains(poly), h  # QA R6: the outline never leaves the zone (≤ 1 m rounding)
        assert h["area_km2"] <= 0.25
    assert len({h["gap_peak_px"] for h in hs}) == len(hs) or len(hs) == 1  # per cluster, not one global max
    for a in hs:
        for b in hs:
            if a is not b:
                d = math.hypot((a["lon"] - b["lon"]) * 111.3 * math.cos(math.radians(50.4)), (a["lat"] - b["lat"]) * 111.3)
                assert d > 0.45
    # the unbuilt +9 °C block is never a hotspot
    assert all(h["gap_peak_px"] < 13 for h in hs)


def test_hotspots_flat_zone_has_none(monkeypatch):
    import numpy as np

    from tests.conftest import POZNIAKY
    from uhd.services import context
    from uhd.tiles import pyramid

    monkeypatch.setattr(pyramid, "read_window", lambda aoi, layer, y, r0, c0, h, w: np.full((h, w), 5.0, np.float32))
    monkeypatch.setattr(context, "_classes", lambda aoi, win, years: None)
    rep = {"params": {"geometry": POZNIAKY}, "series": [{"year": y, "gap": 5.0} for y in (2023, 2024, 2025)]}
    assert context.hotspots(rep) == []  # nothing ≥ 1 °C hotter than the zone → no points at all


def test_hotspots_stale_version_recomputed(client):
    from uhd.services import context, reports

    rep = client.post("/api/analyze", json={"place_id": "kyiv-pozniaky"}).json()
    stored = reports.get(rep["report_id"])
    reports.put({**stored, "hotspots": [{"lon": 0, "lat": 0}], "hotspots_version": None})
    got = client.get(f"/api/reports/{rep['report_id']}").json()
    assert got["hotspots"] != [{"lon": 0, "lat": 0}]
    assert reports.get(rep["report_id"])["hotspots_version"] == context.HOTSPOTS_VERSION


def test_overview_build_serve_and_match_analyze(client, monkeypatch):
    from uhd.services import overview, places

    overview.clear_cache()
    monkeypatch.setattr(places, "city_shortcuts", lambda: {})
    r = client.get("/api/overview")
    assert r.status_code == 503 and r.json()["error"] == "overview_not_ready"
    d = overview.build(jobs=2)
    ids = [p["place_id"] for p in d["places"]]
    assert ids[:3] == ["kyiv", "kharkiv", "lviv"]  # cities first, by size
    assert sum(p["kind"] == "district" for p in d["places"]) >= 20 and all(p["rank"] > 99 for p in d["places"]
                                                                         if p["kind"] == "district")
    r = client.get("/api/overview")
    assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=0, must-revalidate"
    etag = r.headers["etag"]
    assert d["version"] in etag
    assert client.get("/api/overview", headers={"if-none-match": etag}).status_code == 304
    body = r.json()
    kyiv = next(p for p in body["places"] if p["place_id"] == "kyiv")
    rep = client.post("/api/analyze", json={"place_id": "kyiv"}).json()
    assert kyiv["gap_mean"] == rep["gap_summary"]["mean"] and kyiv["name"] == "Київ" and kyiv["kind"] == "city"
    zl = [x["zone_lst"] for x in rep["series"] if x.get("gap") is not None and x.get("zone_lst") is not None]
    assert abs(kyiv["lst_mean"] - sum(zl) / len(zl)) <= 0.05 and abs(kyiv["lst_last"]["value"] - zl[-1]) <= 0.05  # item 21
    assert kyiv["gap_by_year"] == {str(s["year"]): s["gap"] for s in rep["series"]}
    assert kyiv["method"] == rep.get("method") and kyiv["oblast"] == "Київ"
    assert set(kyiv) >= {"place_id", "name", "kind", "city", "oblast", "lon", "lat", "bbox", "rank", "status",
                         "gap_mean", "gap_by_year", "trend", "method", "caveats", "war_region", "reason_uk"}
    from shapely.geometry import Point, shape

    assert shape(places.get_place("kyiv")["geometry"]).contains(Point(kyiv["lon"], kyiv["lat"]))


def test_overview_statuses(monkeypatch):
    from uhd.services import analysis, overview

    p = {"id": "kyiv-darnytskyi", "name": "Дарницький район (Київ)", "kind": "district", "city": "kyiv"}
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: {
        "gap_summary": {"mean": None}, "trend": {"verdict": "insufficient_data"}, "series": [{"year": 2020, "gap": None}],
        "caveats": [{"code": "no_lst_product"}, {"code": "war_zone"}], "method": None,
        "zone": {"war_region": {"name": "Донецька область", "since": 2014}}})
    e = overview.place_entry(p)
    assert e["status"] == "no_data" and "USGS" in e["reason_uk"] and e["trend"] is None
    assert e["war_region"] == {"name": "Донецька область", "since": 2014} and e["caveats"] == ["no_lst_product", "war_zone"]
    monkeypatch.setattr(analysis, "analyze", lambda *a, **k: {
        "gap_summary": {"mean": 3.2}, "trend": {"verdict": "insufficient_data"}, "series": [], "caveats": [], "zone": {}})
    assert overview.place_entry(p)["status"] == "insufficient_data"

    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(analysis, "analyze", boom)
    e = overview.place_entry(p)
    assert e["status"] == "error" and e["gap_mean"] is None and e["lon"] is not None


def test_overlays(client, monkeypatch):
    import json

    from uhd.config import get_settings
    from uhd.services import overview

    overview.clear_cache()
    s = get_settings()
    (s.landsat_dir / "aoi").mkdir(parents=True, exist_ok=True)
    (s.landsat_dir / "aoi" / "Ukraine.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [
            [[22.1, 48.0], [30.0, 52.4], [40.2, 49.0], [33.0, 44.4], [22.1, 48.0]]]}}]}))
    r = client.get("/api/overlays")
    assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=0, must-revalidate"
    et = r.headers["etag"]
    r304 = client.get("/api/overlays", headers={"if-none-match": et})
    assert r304.status_code == 304 and r304.headers["cache-control"] == "public, max-age=0, must-revalidate" and r304.headers["etag"] == et
    d = r.json()
    assert d["ukraine"]["bbox"] == [22.1, 44.4, 40.2, 52.4] and d["ukraine"]["geometry"]["type"] == "Polygon"
    w = d["war_regions"]["features"]
    assert len(w) >= 5 and all(set(f["properties"]) == {"name", "since", "text_uk"} for f in w)
    assert all(str(f["properties"]["since"]) in f["properties"]["text_uk"] for f in w)
    o = d["occupied"]
    assert len(o["features"]) == 7 and {f["properties"]["oblast"] for f in o["features"]} >= {"АР Крим", "Севастополь"}
    assert "станом на 15.09.2026" in o["properties"]["label_uk"] and "OpenStreetMap" in o["properties"]["attribution"]
    assert o["properties"]["snapshot_date"] == "2026-09-15" and o["properties"]["source_url"].startswith("https://")
    assert d["no_lst"] == {"type": "FeatureCollection", "features": []}
    assert len(r.content) < 300_000
    assert client.get("/api/overlays", headers={"if-none-match": r.headers["etag"]}).status_code == 304
    p = s.data_dir / overview.NO_LST_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {
        "label_uk": "немає супутникової температури поверхні"}, "geometry": {"type": "Polygon", "coordinates": [
        [[37.5, 47.0], [37.6, 47.0], [37.6, 47.1], [37.5, 47.0]]]}}]}))
    assert len(client.get("/api/overlays").json()["no_lst"]["features"]) == 1  # served once science writes it
    assert client.get("/api/overlays").json()["no_scenes"] == {"type": "FeatureCollection", "features": []}
    q = s.data_dir / overview.NO_SCENES_FILE
    q.write_text(json.dumps({"type": "FeatureCollection", "properties": {
        "label_uk": "замало безхмарних знімків цієї смуги в цьому році"}, "features": [{"type": "Feature", "properties": {
            "year": 2022, "area_km2": 51234.5, "label_uk": "2022: замало безхмарних знімків цієї смуги"},
            "geometry": {"type": "Polygon", "coordinates": [[[30.0, 46.0], [31.0, 46.0], [31.0, 52.0], [30.0, 46.0]]]}}]}))
    ns = client.get("/api/overlays").json()["no_scenes"]  # picked up without a restart (file key changed)
    assert [f["properties"]["year"] for f in ns["features"]] == [2022] and "безхмарних" in ns["properties"]["label_uk"]


def test_dark_gap_near_zero_is_light_and_opaque():
    from uhd.tiles import palettes

    def lstar(c):
        def f(v):
            v /= 255
            return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
        y = 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])
        return 116 * y ** (1 / 3) - 16

    bg = lstar((0x1C, 0x24, 0x38))  # frontend dark basemap land
    st = dict(palettes.SCALES["gap"]["stops"]["dark"])
    assert all(lstar(st[v]) - bg >= 10 for v in (-2, 0, 1, 2))
    warm = [lstar(st[v]) for v in (0, 1, 2, 4, 6)]
    assert warm == sorted(warm)  # lightness rises with heat into the existing warm stops
    m = palettes.meta()["gap"]["stops"]["dark"]
    assert {"value": 0, "color": "#424A60"} in m


def test_hotspot_outline_clipped_to_round_zone(monkeypatch):  # QA R6: Позняки circle, hot blob on its edge
    import numpy as np
    from shapely.geometry import shape

    from uhd.services import context, places, rasters
    from uhd.services.geometry import parse_geometry, to_3035
    from uhd.tiles import pyramid

    geom = places.get_place("kyiv-pozniaky")["geometry"]
    g = parse_geometry(geom)
    gr = rasters.grid(rasters.pick_aoi(g))
    x0, y0, x1, y1 = to_3035(g).bounds
    er, ec = int((gr["y1"] - (y0 + y1) / 2) // gr["res"]), int((x1 - gr["x0"]) // gr["res"])  # east edge

    def field(r0, c0, h, w):
        rr, cc = np.mgrid[r0:r0 + h, c0:c0 + w]
        return (5.0 + 8.0 * ((abs(rr - er) <= 4) & (abs(cc - ec) <= 4))).astype(np.float32)

    monkeypatch.setattr(pyramid, "read_window", lambda aoi, layer, y, r0, c0, h, w: field(r0, c0, h, w))
    monkeypatch.setattr(context, "_classes", lambda aoi, win, years: None)
    hs = context.hotspots({"params": {"geometry": geom}, "series": [{"year": 2025, "gap": 5.0}]})
    assert hs, "the edge blob is a hotspot"
    zone = shape(geom)
    for h in hs:
        assert zone.buffer(1e-5).contains(shape(h["polygon"])), h["polygon"]  # ≤ 1 m (5-decimal rounding)
        assert shape(h["polygon"]).area > 0


def test_report_reference_outline(client):
    """Board item 20 D: light outline of the reference forest; the report and its id are unchanged."""
    rep = client.post("/api/analyze", json={"place_id": "kyiv-pozniaky"}).json()
    rid = rep["report_id"]
    r = client.get(f"/api/reports/{rid}/reference")
    assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=86400"
    f = r.json()
    assert f["type"] == "Feature" and f["geometry"]["type"] == "Polygon" and len(r.content) < 100_000
    p = f["properties"]
    assert p["report_id"] == rid and p["label_uk"] == "ліс-еталон" and p["ring_km"] == [2, 15]
    assert p["simplify_m"] in (30, 60, 120, 240, 480) and p["report_method_version"] == client.get(f"/api/reports/{rid}").json().get("method_version")
    assert client.get(f"/api/reports/{rid}/reference", headers={"if-none-match": r.headers["etag"]}).status_code == 304
    assert client.get(f"/api/reports/{rid}").json()["report_id"] == rid
    assert client.get("/api/reports/0123456789abcdef/reference").status_code == 404
    assert client.get("/api/reports/nope/reference").status_code == 422


def test_report_reference_outline_size_cap(client, monkeypatch):
    from uhd.services import reference_outline

    rid = client.post("/api/analyze", json={"place_id": "kyiv-darnytskyi"}).json()["report_id"]
    monkeypatch.setattr(reference_outline, "MAX_BYTES", 3_000)  # 30 m is too heavy here → coarser step chosen
    f = client.get(f"/api/reports/{rid}/reference").json()
    assert f["properties"]["simplify_m"] > 30


UZH_TRIANGLE = {"type": "Polygon", "coordinates": [[[22.25766, 48.64753], [22.22363, 48.65641], [22.25054, 48.62557],
                                                    [22.25766, 48.64753]]]}  # 24/28 repro: NW tip across the border


def _ukraine_east_of(lon: float):
    import json

    from uhd.config import get_settings
    from uhd.services import context

    p = get_settings().landsat_dir / "aoi"
    p.mkdir(parents=True, exist_ok=True)
    (p / "Ukraine.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature",
        "properties": {}, "geometry": {"type": "Polygon", "coordinates": [  # dense west edge = a meridian in 3035
            [[lon, 44.0], [41.0, 44.0], [41.0, 53.0]] + [[lon, 53.0 - i * 0.001] for i in range(9001)]]}}]}))
    context._ukraine_3035.cache_clear()


def test_zone_clipped_at_border_uzhhorod_triangle():
    """24/28: the analysed zone (hotspots, outline) is cut at Ukraine's border like science make_zone (> 1 % outside)."""
    from shapely.geometry import box, shape

    from uhd.services import context

    _ukraine_east_of(22.235)  # a straight stand-in for the Slovak border through the triangle's NW tip
    g, clipped = context.clipped_zone(shape(UZH_TRIANGLE))
    assert clipped and g.bounds[0] >= 22.235 - 1e-9 and g.area < shape(UZH_TRIANGLE).area
    zo = context.zone_outline({"params": {"geometry": UZH_TRIANGLE}})
    assert zo["type"] in ("Polygon", "MultiPolygon") and shape(zo).bounds[0] >= 22.235 - 1e-5
    assert box(22.235, 44, 41, 53).buffer(1e-5).contains(shape(zo))
    _ukraine_east_of(22.0)  # whole triangle inside → nothing cut, the frontend draws params.geometry
    assert context.clipped_zone(shape(UZH_TRIANGLE))[1] is False
    assert context.zone_outline({"params": {"geometry": UZH_TRIANGLE}}) is None
    _ukraine_east_of(22.22363 + 0.0005)  # a sliver (≤ 1 %) is ignored, as in science
    assert context.clipped_zone(shape(UZH_TRIANGLE))[1] is False


def test_hotspots_never_abroad(monkeypatch):
    """24/28: the hottest blob lies in the part of the zone outside Ukraine → no marker or outline there."""
    from shapely.geometry import Point, box, shape

    from tests.conftest import POZNIAKY
    from uhd.services import context

    _synthetic_hot_field(monkeypatch, POZNIAKY)
    rep = {"params": {"geometry": POZNIAKY}, "series": [{"year": y, "gap": 5.0} for y in (2023, 2024, 2025)]}
    with_abroad = context.hotspots(rep)
    assert any(h["lon"] < 30.6242 for h in with_abroad)  # sanity: without a border the +6 °C blob (west) wins
    cut = 30.613 + 0.4 * 0.028
    _ukraine_east_of(cut)
    hs = context.hotspots(rep)
    ua = box(cut, 44, 41, 53)
    for h in hs:
        assert ua.contains(Point(h["lon"], h["lat"])), h
        assert ua.buffer(1e-5).contains(shape(h["polygon"])), h
    assert all(h["gap_peak_px"] < 10.9 for h in hs)  # the +6 °C blob abroad is not reported


def test_report_zone_outline_stored(client):
    from tests.conftest import POZNIAKY
    from uhd.services import context, reports

    _ukraine_east_of(30.613 + 0.4 * 0.028)
    rep = client.post("/api/analyze", json={"geometry": POZNIAKY}).json()
    assert rep["zone_outline"]["type"] in ("Polygon", "MultiPolygon")
    assert reports.get(rep["report_id"])["hotspots_version"] == context.HOTSPOTS_VERSION == "hs4"
    _ukraine_east_of(20.0)
    rep2 = client.post("/api/analyze", json={"place_id": "kyiv-pozniaky"}).json()
    assert rep2["zone_outline"] is None


def _exported(client, fmt, **q):
    rep = client.post("/api/analyze", json={"place_id": "kyiv-pozniaky"}).json()
    r = client.get(f"/api/reports/{rep['report_id']}/export", params={"format": fmt, **q})
    assert r.status_code == 200, r.text
    return rep, r


def test_export_csv(client):
    """Item 29: UTF-8 BOM, «;», header block then the per-year series; from the stored report."""
    import csv
    import io

    rep, r = _exported(client, "csv", name="Позняки", place_id="kyiv-pozniaky")
    assert r.content.startswith(b"\xef\xbb\xbf") and r.headers["content-type"].startswith("text/csv")
    cd = r.headers["content-disposition"]
    assert f'deltaheat_pozniaky_{rep["report_id"]}.csv' in cd and cd.startswith("attachment")
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    head = {row[0]: row[1] for row in rows if len(row) == 2}
    assert head["Зона"] == "Позняки" and head["report_id"] == rep["report_id"]
    from uhd.services import reports

    assert head["method_version"] == (reports.get(rep["report_id"]).get("method_version") or "")
    assert "?zone=kyiv-pozniaky" in head["Посилання"]
    assert float(head["Середній розрив, °C"]) == round(rep["gap_summary"]["mean"], 2)
    i = next(k for k, row in enumerate(rows) if row and row[0] == "Рік")
    assert rows[i] == ["Рік", "LST зони, °C", "LST лісу-еталону, °C", "Розрив, °C", "NDVI", "Частка забудови",
                       "Знімків", "Метод", "Причина виключення"]
    assert len(rows) - i - 1 == len(rep["series"]) and rows[i + 1][0] == str(rep["series"][0]["year"])


def test_export_xlsx_json_and_errors(client):
    import io

    from openpyxl import load_workbook

    rep, r = _exported(client, "xlsx")
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Підсумок", "За роками", "Про метод"]
    ys = wb["За роками"]
    assert ys["A1"].value == "Рік" and ys.freeze_panes == "A2" and ys.max_row == len(rep["series"]) + 1
    assert wb["Підсумок"]["A1"].value == "Показник"
    _, r = _exported(client, "json", place_id="kyiv-pozniaky")
    d = r.json()
    assert d["report_id"] == rep["report_id"] and d["link"].endswith("?zone=kyiv-pozniaky") and "context" not in d
    _, r = _exported(client, "json", place_id="bad id!")  # ignored, not echoed
    assert "bad" not in r.json()["link"]
    assert client.get(f"/api/reports/{rep['report_id']}/export?format=docx").status_code == 422
    assert client.get("/api/reports/0123456789abcdef/export?format=csv").status_code == 404
    assert client.head(f"/api/reports/{rep['report_id']}/export?format=csv").status_code == 200


def test_export_en_csv_xlsx_json(client):
    """Item 32: ?lang=en — English labels, csv with «,», ``-en`` file name, link with lang=en; numbers unchanged."""
    import csv
    import io

    from openpyxl import load_workbook

    rep, uk = _exported(client, "csv", name="Позняки", place_id="kyiv-pozniaky")
    _, uk2 = _exported(client, "csv", name="Позняки", place_id="kyiv-pozniaky", lang="uk")
    assert uk2.content == uk.content.replace(b"?zone=kyiv-pozniaky", b"?zone=kyiv-pozniaky&lang=uk")
    assert f'{rep["report_id"]}-uk.csv' in uk2.headers["content-disposition"]
    _, r = _exported(client, "csv", name="Позняки", place_id="kyiv-pozniaky", lang="en")
    assert r.content.startswith(b"\xef\xbb\xbf") and f'deltaheat_pozniaky_{rep["report_id"]}-en.csv' in \
        r.headers["content-disposition"] and "max-age=3600" in r.headers["cache-control"]
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=","))
    head = {row[0]: row[1] for row in rows if len(row) == 2}
    assert head["Zone"] == "Pozniaky" and head["report_id"] == rep["report_id"]
    assert head["Link"].endswith("?zone=kyiv-pozniaky&lang=en")
    assert float(head["Mean gap, °C"]) == round(rep["gap_summary"]["mean"], 2)
    assert head["Verdict"].startswith(("Significant", "Not significant", "not enough"))
    uk_head = {row[0]: row[1] for row in csv.reader(io.StringIO(uk.content.decode("utf-8-sig")), delimiter=";")
               if len(row) == 2}
    if uk_head["Текст"].startswith("Позняки"):  # named verdict: science needs name_en (passed by i18n)
        assert head["Text"].startswith("Pozniaky")
    i = next(k for k, row in enumerate(rows) if row and row[0] == "Year")
    assert rows[i][:4] == ["Year", "Zone LST, °C", "Reference forest LST, °C", "Gap, °C"]
    uk_rows = list(csv.reader(io.StringIO(uk.content.decode("utf-8-sig")), delimiter=";"))
    j = next(k for k, row in enumerate(uk_rows) if row and row[0] == "Рік")
    assert [row[:7] for row in rows[i + 1:]] == [row[:7] for row in uk_rows[j + 1:]]  # same numbers
    assert not any(ch in r.content.decode("utf-8-sig") for ch in "ієїґщ")  # no Ukrainian text left

    _, r = _exported(client, "xlsx", lang="en")
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Summary", "By year", "About the method"]
    assert wb["Summary"]["A1"].value == "Item" and wb["By year"]["A1"].value == "Year"
    assert "not air temperature" in " ".join(str(c.value) for c in wb["About the method"]["A"] if c.value)
    _, r = _exported(client, "json", name="Позняки", place_id="kyiv-pozniaky", lang="en")
    d = r.json()
    assert d["link"].endswith("&lang=en") and d["zone"]["name_en"] == "Pozniaky"
    assert client.get(f"/api/reports/{rep['report_id']}/export?format=csv&lang=de").status_code == 422


def test_localize_report_passes_name_en(monkeypatch):
    """Item 32 wiring: science's localize_report(rep, name_en=…) gets the KMU 2010 name for named verdicts."""
    from uhd.services import i18n, science

    seen = {}

    def fake(name, rep, **kw):
        seen.update(kw, fn=name)
        return {**rep, "verdict_text_en": f"{kw['name_en']}: …"}

    monkeypatch.setattr(science, "has_helper", lambda n: n == "localize_report")
    monkeypatch.setattr(science, "helper", fake)
    out = i18n.localize_report({"report_id": "x", "zone": {"name": "Позняки"}, "verdict_text_uk": "Позняки: …"})
    assert seen == {"fn": "localize_report", "name_en": "Pozniaky"} and out["verdict_text_en"] == "Pozniaky: …"
    i18n.localize_report({"report_id": "x", "zone": {"name": None}})
    assert seen["name_en"] is None


def test_export_en_pdf(client):
    """Item 32: English PDF — TERMS-EN labels and decimal points; the Ukrainian default stays as it was."""
    import io

    from pypdf import PdfReader

    from uhd.services import export_pdf

    rep, uk = _exported(client, "pdf", name="Позняки", place_id="kyiv-pozniaky")
    _, r = _exported(client, "pdf", name="Позняки", place_id="kyiv-pozniaky", lang="en")
    assert r.content != uk.content and f'{rep["report_id"]}-en.pdf' in r.headers["content-disposition"]
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
    assert "Gap with the forest" in text and "Pozniaky" in text
    assert export_pdf.fnum(rep["gap_summary"]["mean"], 1, True).replace(",", ".") in text
    assert export_pdf.fnum(rep["gap_summary"]["mean"], 1, True) not in text  # no decimal comma in en
    uk_text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(uk.content)).pages)
    assert "Розрив із лісом" in uk_text and "Gap with the forest" not in uk_text


def test_export_drawn_area_link_and_slug():
    from uhd.services import export

    rep = {"report_id": "0123456789abcdef", "zone": {"name": "Двір на Оболоні №5"},
           "params": {"place_id": None, "geometry": {"type": "Polygon", "coordinates": [
               [[30.5, 50.5], [30.51, 50.5], [30.51, 50.51], [30.5, 50.5]]]}}}
    assert export.filename(rep, "csv") == "deltaheat_dvir-na-oboloni-5_0123456789abcdef.csv"
    assert export.report_link(rep, "http://h:8100/") == "http://h:8100/?area=30.50000,50.50000;30.51000,50.50000;30.51000,50.51000"
    assert export.slug("Жовква, Щасливе") == "zhovkva-shchaslyve"


def test_export_pdf(client, monkeypatch):
    """Item 29 PDF: ≥ 1 page, Ukrainian text with the headline number (decimal comma), cached and LRU-capped."""
    import io

    from fpdf import FPDF  # noqa: F401 — dependency present
    from uhd.config import get_settings
    from uhd.services import export_pdf

    rep, r = _exported(client, "pdf", name="Позняки", place_id="kyiv-pozniaky")
    assert r.content.startswith(b"%PDF-") and r.headers["content-type"] == "application/pdf"
    assert f'deltaheat_pozniaky_{rep["report_id"]}.pdf' in r.headers["content-disposition"]
    from pypdf import PdfReader

    doc = PdfReader(io.BytesIO(r.content))
    text = "".join(p.extract_text() for p in doc.pages)
    assert len(doc.pages) >= 1 and "Позняки" in text
    assert export_pdf.fnum(rep["gap_summary"]["mean"], 1, True) in text  # «+11,4» style headline number
    files = list((get_settings().cache_dir / "export").glob(f"{rep['report_id']}.*.pdf"))
    assert len(files) == 1
    monkeypatch.setattr(export_pdf, "CACHE_MAX_BYTES", 1)  # next write trims everything older
    _exported(client, "pdf", name="Інша назва", place_id="kyiv-pozniaky")
    assert len(list((get_settings().cache_dir / "export").glob("*.pdf"))) <= 1


def test_pdf_number_format():
    from uhd.services.export_pdf import fnum

    assert fnum(11.44, 1, True) == "+11,4" and fnum(-1.25, 1) == "−1,3" and fnum(None) == "—" and fnum(0.0, 1, True) == "0,0"


def test_pdf_terms_link_host_and_wrap(client):
    """TERMS-UK labels on any stored report; links follow the public mirror's host; ?area= wraps only at separators."""
    import io

    from pypdf import PdfReader

    from uhd.services import export
    from uhd.services.export_pdf import seasons_uk, wrap_link

    assert [seasons_uk(n) for n in (1, 3, 5, 11, 12, 21, 22)] == [
        "1 літній сезон", "3 літні сезони", "5 літніх сезонів", "11 літніх сезонів", "12 літніх сезонів",
        "21 літній сезон", "22 літні сезони"]
    link = "https://h/?area=" + ";".join(f"{30 + i / 1000:.5f},{50 + i / 1000:.5f}" for i in range(12))
    lines = wrap_link(link, lambda s: len(s), 40)
    assert "".join(lines) == link and all(len(l) <= 40 for l in lines[1:])
    assert all(l.endswith((";", ",", "?")) for l in lines[:-1])  # never inside a number
    rep = client.post("/api/analyze", json={"place_id": "kyiv-pozniaky"}).json()
    r = client.get(f"/api/reports/{rep['report_id']}/export", params={"format": "pdf", "place_id": "kyiv-pozniaky"},
                   headers={"x-forwarded-host": "mirror.example.org", "x-forwarded-proto": "https"})
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
    assert "Літні сезони 2013–2025" in text and "https://mirror.example.org/?zone=kyiv-pozniaky" in text
    assert "статистично" in text and "із даними" in text and "Висновок" in text
    hs = client.get(f"/api/reports/{rep['report_id']}").json().get("hotspots") or []
    if hs:
        from uhd.services.export_pdf import years_span

        assert f"Гарячі точки ({years_span(sorted({y for h in hs for y in h['years']}))})" in text
    assert "Vary" in r.headers or "vary" in r.headers
    j = client.get(f"/api/reports/{rep['report_id']}/export", params={"format": "json"},
                   headers={"x-forwarded-host": "evil host/x"}).json()
    assert j["link"].startswith("http://testserver/")  # an invalid forwarded host is ignored
    assert export.public_base({"host": ""}, "http://x/") == "http://x/"


def test_pdf_scale_bar_and_hotspot_table_helpers():
    from uhd.services.export_pdf import scale_bar, years_span

    m, px = scale_bar(14, 50.4, 240)  # z14 at Kyiv ≈ 6,1 m/px → 1 km = 164 px fits 240 px, 2 km does not
    assert m == 1000 and 150 < px < 175
    assert years_span([2023, 2024, 2025]) == "2023–2025" and years_span([2019, 2021]) == "2019, 2021" and years_span([]) == "—"


# ------------------------------------------------------------------ item 32: lang=en (I18N.md §6)

def test_i18n_default_is_byte_identical(client):
    """No lang / lang=uk → exactly today's response bytes (current clients)."""
    import json

    rep = client.post("/api/analyze", json={"place_id": "kyiv-pozniaky"}).json()
    rid = rep["report_id"]
    for url in (f"/api/reports/{rid}", "/api/meta", "/api/places?q=Позн&geocoder=false", "/api/places/kyiv-pozniaky"):
        a = client.get(url)
        b = client.get(url + ("&" if "?" in url else "?") + "lang=uk")
        assert a.status_code == b.status_code == 200 and a.content == b.content, url
        assert "_en" not in json.dumps(a.json(), ensure_ascii=False).replace("_entries", ""), url
    assert client.get(f"/api/reports/{rid}?lang=de").status_code == 422


def test_i18n_en_adds_siblings_keeps_uk(client):
    from uhd.services import i18n

    rid = client.post("/api/analyze", json={"place_id": "kyiv-pozniaky"}).json()["report_id"]
    uk = client.get(f"/api/reports/{rid}").json()
    en = client.get(f"/api/reports/{rid}?lang=en").json()

    def strip(o):  # remove every *_en key → must equal the uk response
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if not (k.endswith("_en") or k in ("name_en", "short_name_en"))}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o
    assert strip(en) == uk  # nothing changed, only added

    def pairs(o, out):
        if isinstance(o, dict):
            for k, v in o.items():
                if k.endswith("_uk") and isinstance(v, str):
                    out.append((v, o.get(k[:-3] + "_en")))
                pairs(v, out)
        elif isinstance(o, list):
            for v in o:
                pairs(v, out)
        return out
    ps = pairs(en, [])
    assert ps and all(e is None or i18n.numbers(e) == i18n.numbers(u) for u, e in ps)
    m = client.get("/api/meta?lang=en").json()
    assert m["notes_en"]["lst"].startswith("LST is the daytime land surface temperature")
    assert m["layers"]["scales"]["gap"]["title_en"].startswith("Surface heat gap")
    assert any(p.get("name_en") == "Pozniaky (≈1 km)" for p in m["presets"])
    pl = client.get("/api/places/kyiv-pozniaky?lang=en").json()
    assert pl["name_en"] == "Pozniaky (≈1 km)"


def test_i18n_overview_overlays_en(client, monkeypatch):
    import json

    from uhd.config import get_settings
    from uhd.services import overview, places

    overview.clear_cache()
    monkeypatch.setattr(places, "city_shortcuts", lambda: {})
    overview.build(jobs=2)
    a, b = client.get("/api/overview"), client.get("/api/overview?lang=en")
    assert a.headers["etag"] != b.headers["etag"] and b.headers["etag"].endswith('-en"')
    assert client.get("/api/overview?lang=en", headers={"if-none-match": b.headers["etag"]}).status_code == 304
    kyiv = next(p for p in b.json()["places"] if p["place_id"] == "kyiv")
    assert kyiv["name_en"] == "Kyiv"
    s = get_settings()
    (s.landsat_dir / "aoi").mkdir(parents=True, exist_ok=True)
    o = client.get("/api/overlays?lang=en").json()
    assert o["occupied"]["properties"]["label_en"].startswith("occupied (as of 15 September 2026, source: Ministry of Development")
    assert o["occupied"]["properties"]["source_en"].startswith("List of temporarily occupied territories")
    assert all(f["properties"]["name_en"] for f in o["war_regions"]["features"])
    assert client.get("/api/overlays").content == json.dumps(json.loads(client.get("/api/overlays").content),
                                                                ensure_ascii=False, separators=(",", ":")).encode()


def test_i18n_texts_and_romanisation():
    from uhd.services import i18n

    assert [i18n.place_name_en(n) for n in ("Позняки (≈1 км)", "Оболонь", "Теремки", "Деснянський район (Київ)",
                                             "Голосіївський район (Київ)", "Нижні Сади", "Мікрорайон 759-А")] == [
        "Pozniaky (≈1 km)", "Obolon", "Teremky", "Desnianskyi District (Kyiv)", "Holosiivskyi District (Kyiv)",
        "Nyzhni Sady", "Microdistrict 759-A"]
    assert i18n.romanize("Згурівка") == "Zghurivka" and i18n.romanize("Їжакевич") == "Yizhakevych"
    assert i18n.text_en("порівняно із забудовою 9 районів Києва") == "compared with the built-up land of 9 districts of Kyiv"
    t = i18n.text_en("Ділянка невелика (2,9 км² забудови), а в районах — 12–40 км²: щільний квартал зазвичай гарячіший "
                     "за середнє по цілому району.")
    assert t.startswith("The area is small (2.9 km²") and i18n.numbers(t) == [2.9, 12.0, 40.0]
    assert i18n.text_en("2022: замало безхмарних знімків цієї смуги") == "2022: too few cloud-free images of this swath"
    assert i18n.text_en("щось невідоме") is None  # null, never a guess
    out = i18n.localize({"note_uk": "щось невідоме", "label_uk": "вода", "name": "Харків", "x": 1})
    assert out == {"note_uk": "щось невідоме", "note_en": None, "label_uk": "вода", "label_en": "water",
                   "name": "Харків", "name_en": "Kharkiv", "x": 1}


def test_climate_v2_texts_have_english():
    """CMIP6 v2: the per-response climate note and the fallback caveats all have an English text; no short_baseline."""
    import inspect

    from uhd.services import climate, context, i18n

    src = inspect.getsource(context)
    note = "Прогноз приземної температури повітря (на висоті 2 м; CMIP6, комірка сітки ≈25 км), а не поверхні. " \
           "Медіана 12 моделей, діапазон 10–90 %; 20-річні вікна, база 1995–2014."
    assert "Медіана 12 моделей" in src and i18n.text_en(note).endswith("baseline 1995–2014.")
    assert "short_baseline" not in inspect.getsource(climate)


def test_pdf_cache_key_follows_template_code(client, monkeypatch):
    """QA polish batch: a template change must not serve PDFs cached by an older build."""
    import io

    from pypdf import PdfReader

    from uhd.services import export_pdf

    assert export_pdf.SCHEMA.startswith("pdf2-") and len(export_pdf.SCHEMA) == 13
    rep, r1 = _exported(client, "pdf", place_id="kyiv-pozniaky")
    monkeypatch.setattr(export_pdf, "SCHEMA", "pdf2-other000")  # as after a code change
    monkeypatch.setattr(export_pdf, "_build", lambda rep, link: b"%PDF-new")
    _, r2 = _exported(client, "pdf", place_id="kyiv-pozniaky")
    assert r2.content == b"%PDF-new" and r1.content != r2.content
    hs = rep.get("hotspots") or []
    if hs:
        text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(r1.content)).pages)
        assert f"Гарячі точки ({export_pdf.years_span(sorted({y for h in hs for y in h['years']}))})" in text


def _weather_archive(root, city="kyiv", year=2024, gz=False, lat=50.45, lon=30.523):
    """A tiny Open-Meteo archive file in the downloader's shape (daily + hourly, Europe/Kyiv, ``_meta``)."""
    import datetime as dt
    import gzip
    import json

    days = [(dt.date(year, 7, 1) + dt.timedelta(days=i)).isoformat() for i in range(10)]
    hours = [f"{d}T{h:02d}:00" for d in days for h in range(24)]
    j = {"latitude": 50.439365, "longitude": 30.476192, "timezone": "Europe/Kyiv",
         "daily": {"time": days, **{k: [float(i) for i in range(10)] for k in weather.DAILY}, "sunshine_duration": [0] * 10},
         "daily_units": {"time": "iso8601", "temperature_2m_max": "°C", "sunshine_duration": "s"},
         "hourly": {"time": hours, **{k: [float(i % 24) for i in range(len(hours))] for k in weather.HOURLY}},
         "hourly_units": {"time": "iso8601", "temperature_2m": "°C"},
         "_meta": {"city": city, "query_lat": lat, "query_lon": lon, "source": "open-meteo archive (ERA5/ERA5-Land)"}}
    d = root / "weather" / "openmeteo" / city
    d.mkdir(parents=True, exist_ok=True)
    body = json.dumps(j).encode()
    (d / f"{year}.json{'.gz' if gz else ''}").write_bytes(gzip.compress(body) if gz else body)


def test_weather_local_archive_hit(client, monkeypatch):
    """Item 34: a point ≤ 25 km from an archive city, date in the file → answered locally, no live call."""
    from uhd.config import get_settings

    _weather_archive(get_settings().data_dir)
    _weather_archive(get_settings().data_dir, city="lviv", gz=True, lat=49.84, lon=24.03)

    class C:
        def get(self, *a, **k):
            raise AssertionError("live API must not be called")

    monkeypatch.setattr(weather, "client", lambda: C())
    b = client.get("/api/weather", params={"date": "2024-07-05", "lat": 50.41, "lon": 30.627}).json()
    assert b["source"] == "open-meteo-archive-local (ERA5)" and b["city"] == "kyiv" and b["city_distance_km"] < 10
    assert "CC BY 4.0" in b["attribution"] and b["grid_lat"] == 50.439365
    assert b["day"]["date"] == "2024-07-05" and b["day"]["temperature_2m_max"] == 4.0
    assert [x["date"] for x in b["previous_days"]] == ["2024-07-02", "2024-07-03", "2024-07-04"]
    assert [h["time"] for h in b["overpass_hours_local"]] == ["2024-07-05T10:00", "2024-07-05T11:00", "2024-07-05T12:00"]
    assert set(b["day"]) == {"date", *weather.DAILY} and b["units"]["temperature_2m_max"] == "°C"
    assert "sunshine_duration" not in b["units"]
    first = client.get("/api/weather", params={"date": "2024-07-01", "lat": 50.45, "lon": 30.52}).json()
    assert first["city"] == "kyiv" and first["previous_days"] == []  # start of the file: fewer days before
    lv = client.get("/api/weather", params={"date": "2024-07-03", "lat": 49.84, "lon": 24.03}).json()
    assert lv["city"] == "lviv"  # gzipped file
    # the analyst's get_weather tool goes through the same service
    from uhd.agent import tools

    assert tools.t_get_weather("2024-07-05", lat=50.41, lon=30.627)["source"] == "open-meteo-archive-local (ERA5)"


def test_weather_local_archive_miss_goes_live(client, monkeypatch):
    """Item 34: far from every archive city, or a date not in the file → the live API (mocked); 429 / 5xx / timeout →
    200 {available: false, reason}; a 429 is remembered for ~10 min."""
    import httpx

    from uhd.config import get_settings

    _weather_archive(get_settings().data_dir)
    calls = []

    class Resp:
        status = 200

        def raise_for_status(self):
            if self.status != 200:
                raise httpx.HTTPStatusError(str(self.status), request=httpx.Request("GET", "http://x"),
                                            response=httpx.Response(self.status))

        def json(self):
            return {"latitude": 48.5, "longitude": 32.3, "daily": {"time": ["2024-07-05"], "temperature_2m_max": [31.0]},
                    "hourly": {"time": []}}

    class C:
        status = 200

        def get(self, url, params=None):
            calls.append(params)
            r = Resp()
            r.status = C.status
            return r

    monkeypatch.setattr(weather, "client", lambda: C())
    far = client.get("/api/weather", params={"date": "2024-07-05", "lat": 48.5, "lon": 32.26}).json()  # no archive city here in this fixture
    assert len(calls) == 1 and "city" not in far and far["source"].startswith("Open-Meteo Historical Weather API")
    assert far["day"]["temperature_2m_max"] == 31.0
    client.get("/api/weather", params={"date": "2024-08-20", "lat": 50.45, "lon": 30.52})  # near Kyiv, not in file
    assert len(calls) == 2 and calls[-1]["start_date"] == "2024-08-17"
    C.status = 429
    r = client.get("/api/weather", params={"date": "2023-07-05", "lat": 50.45, "lon": 30.52})
    assert r.status_code == 200 and r.json()["available"] is False and r.json()["reason"] == "quota"
    assert {"text_uk", "text_en"} <= set(r.json())
    n = len(calls)
    C.status = 200  # the 429 is remembered ~10 min per process: no new live request even if the API is back
    r = client.get("/api/weather", params={"date": "2022-07-05", "lat": 50.45, "lon": 30.52}).json()
    assert r["available"] is False and r["reason"] == "quota" and len(calls) == n
    b = client.get("/api/weather", params={"date": "2024-07-05", "lat": 50.45, "lon": 30.52}).json()
    assert b["available"] is True and b["city"] == "kyiv"  # the local copy still answers during the back-off
    monkeypatch.setattr(weather, "_quota_until", 0.0)
    for status, reason in ((503, "upstream"), (500, "upstream")):
        C.status = status
        r = client.get("/api/weather", params={"date": "2021-07-05", "lat": 48.5, "lon": 32.26})
        assert r.status_code == 200 and r.json()["reason"] == reason

    class Slow:
        def get(self, *a, **k):
            raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(weather, "client", lambda: Slow())
    r = client.get("/api/weather", params={"date": "2021-07-06", "lat": 48.5, "lon": 32.26}).json()
    assert r["available"] is False and r["reason"] == "upstream"


def test_weather_cities_from_data_file_and_new_city_without_restart(client, monkeypatch):
    """Item 34: no city list in code — cities.json next to the archive; a new city / year is picked up live."""
    import json

    from uhd.config import get_settings

    root = get_settings().data_dir / "weather" / "openmeteo"
    _weather_archive(get_settings().data_dir, lat=10.0, lon=10.0)  # _meta says elsewhere; cities.json wins
    (root / "cities.json").write_text(json.dumps({"cities": {"kyiv": {"lat": 50.45, "lon": 30.523}}}))

    class C:
        def get(self, *a, **k):
            raise httpx.ConnectError("offline")

    import httpx

    monkeypatch.setattr(weather, "client", lambda: C())
    assert client.get("/api/weather", params={"date": "2024-07-05", "lat": 50.45, "lon": 30.52}).json()["city"] == "kyiv"
    assert client.get("/api/weather", params={"date": "2024-07-05", "lat": 46.48, "lon": 30.73}).json()["available"] is False
    _weather_archive(get_settings().data_dir, city="odesa", lat=46.482, lon=30.733)
    import os
    import time as _t

    later = _t.time() + 5
    (root / "cities.json").write_text(json.dumps({"cities": {"kyiv": {"lat": 50.45, "lon": 30.523},
                                                            "odesa": {"lat": 46.482, "lon": 30.733}}}))
    os.utime(root / "cities.json", (later, later))
    assert client.get("/api/weather", params={"date": "2024-07-05", "lat": 46.48, "lon": 30.73}).json()["city"] == "odesa"
    _weather_archive(get_settings().data_dir, city="odesa", year=2023, lat=46.482, lon=30.733)  # new year: no index
    assert client.get("/api/weather", params={"date": "2023-07-05", "lat": 46.48, "lon": 30.73}).json()["city"] == "odesa"
    # a new city folder not (yet) in cities.json counts by its own _meta point; the sync's temp dir never does
    (root / ".incoming").mkdir()
    (root / ".incoming" / "cities.json").write_text("{}")
    _weather_archive(get_settings().data_dir, city="lviv", lat=49.842, lon=24.031)
    os.utime(root, (later + 5, later + 5))
    assert client.get("/api/weather", params={"date": "2024-07-05", "lat": 49.84, "lon": 24.03}).json()["city"] == "lviv"
    assert client.get("/api/weather", params={"date": "2023-07-05", "lat": 46.48, "lon": 30.73}).json()["city"] == "odesa"


def test_weather_unavailable_tool_and_agent_answer_go_on(client, monkeypatch):
    """Item 34: a live 429 → the get_weather tool says «unavailable, continue without it» and the chat still answers."""
    import httpx
    from types import SimpleNamespace as NS

    from uhd.agent import loop, tools
    from uhd.config import get_settings

    class C:
        def get(self, *a, **k):
            return httpx.Response(429, request=httpx.Request("GET", "http://x"))

    monkeypatch.setattr(weather, "client", lambda: C())
    r = tools.t_get_weather("2021-07-10", lat=48.5, lon=32.26)
    assert r["available"] is False and r["reason"] == "quota" and "Do not call get_weather again" in r["agent_note"]
    assert client.get("/api/weather", params={"date": "2021-07-10", "lat": 48.5, "lon": 32.26}).json() == \
        {k: v for k, v in r.items() if k != "agent_note"}

    script = [([NS(type="tool_use", id="w1", name="get_weather", input={"date": "2021-07-10", "lat": 48.5, "lon": 32.26})],
               "tool_use"),
              ([NS(type="text", text="Дані про погоду зараз тимчасово недоступні. Поверхня в місті гарячіша за ліс.")],
               "end_turn")]
    sent = []

    class Stream:
        def __init__(self, msg):
            self.msg = msg

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            return iter([NS(type="text", text=b.text) for b in self.msg.content if b.type == "text"])

        def get_final_message(self):
            return self.msg

    def stream(**kw):
        sent.append(list(kw["messages"]))
        content, stop = script.pop(0)
        return Stream(NS(content=content, stop_reason=stop, usage=NS(input_tokens=1, output_tokens=1,
                                                                    cache_read_input_tokens=0,
                                                                    cache_creation_input_tokens=0)))

    fc = NS(beta=NS(messages=NS(stream=stream)))
    evs = list(loop.run_chat([{"role": "user", "content": "Яка була погода 10 липня 2021?"}], client=fc,
                             settings=get_settings()))
    assert evs[-1]["type"] == "done" and not script  # one tool call, then the answer — no retry loop
    res = sent[1][-1]["content"][0]
    assert res["type"] == "tool_result" and "unavailable" in json.dumps(res["content"])


def test_english_dates_long_form():
    """TERMS-EN §10.4: «as of 15 September 2026» in English; the number-multiset check treats both forms as one date."""
    from uhd.science import i18n_en
    from uhd.services import i18n

    assert i18n.date_en("15.09.2026") == "15 September 2026" and i18n.date_en("01.01.2025") == "1 January 2025"
    assert i18n.date_en("bad") == "bad"
    uk = "окуповано (станом на 15.09.2026, джерело: Мінрозвитку, наказ № 376)"
    en = i18n.text_en(uk)
    assert en == "occupied (as of 15 September 2026, source: Ministry of Development of Ukraine, order No. 376)"
    assert i18n.numbers(en) == i18n.numbers(uk)
    cav_uk = "Окупована територія (станом на 15.09.2026, джерело: Мінрозвитку, наказ № 376). " + i18n_en._WAR_TAIL_UK
    rep = {"method_version": "sci-v3.5.4", "caveats": [{"code": "occupied", "text_uk": cav_uk}]}
    cav_en = i18n_en.localize_report(rep)["caveats"][0]["text_en"]
    assert cav_en.startswith("Temporarily occupied territory (as of 15 September 2026, source: Ministry of Development")
    assert i18n.numbers(cav_en) == i18n.numbers(cav_uk)


def test_agent_budget_503_before_any_model_call(client, monkeypatch):
    """Spent budget → 503 agent_budget_exhausted without ever building or calling the model client (no spend)."""
    from uhd.agent import loop, spend
    from uhd.config import get_settings

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    get_settings.cache_clear()

    def no_client(*a, **k):
        raise AssertionError("the model client must not be created when the budget is spent")

    monkeypatch.setattr(loop, "_client", no_client)
    spend.add_spend("public", 10.01)
    r = client.post("/api/agent/chat", json={"messages": [{"role": "user", "content": "Привіт"}]})
    assert r.status_code == 503 and r.json()["error"] == "agent_budget_exhausted"


def test_geocoder_keeps_settlements_districts_streets_addresses():
    # Роман P2-2: no river banks, forests, shops or bus stops in the search list
    keep = [{"category": "place", "type": "city"}, {"category": "place", "type": "suburb"},
            {"category": "place", "type": "house"}, {"category": "boundary", "type": "administrative"},
            {"category": "highway", "type": "residential", "addresstype": "road"},
            {"category": "building", "type": "apartments"}, {"category": "landuse", "type": "residential"}]
    drop = [{"category": "natural", "type": "wood"}, {"category": "waterway", "type": "river"},
            {"category": "place", "type": "locality"}, {"category": "place", "type": "island"},
            {"category": "shop", "type": "supermarket"}, {"category": "highway", "type": "bus_stop", "addresstype": "highway"},
            {"category": "leisure", "type": "park"}, {"category": "boundary", "type": "protected_area"}]
    assert all(places.wanted_hit(x) for x in keep)
    assert not any(places.wanted_hit(x) for x in drop)


def test_geocoder_filters_hits(client, monkeypatch):
    def hit(i, cat, typ):
        return {"osm_type": "way", "osm_id": i, "name": f"x{i}", "display_name": f"x{i}, Україна", "lat": "50.4",
                "lon": "30.5", "boundingbox": ["50.3", "50.5", "30.4", "30.6"], "category": cat, "type": typ,
                "addresstype": typ}

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return [hit(1, "waterway", "river"), hit(2, "place", "village"), hit(3, "natural", "wood")]

    class C:
        def get(self, url, params=None):
            return Resp()

    monkeypatch.setattr(places, "client", lambda: C())
    b = client.get("/api/places", params={"q": "Річкове околиця"}).json()
    assert [g["id"] for g in b["geocoder"]] == ["osm:W2"]
