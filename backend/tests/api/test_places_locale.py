"""English OSM labels are additive, identity-matched, optional and independently cached."""
from __future__ import annotations

from copy import deepcopy

import httpx
import pytest

from uhd.services import places

POLYGON = {"type": "Polygon", "coordinates": [[[30.5, 50.4], [30.53, 50.4], [30.53, 50.43],
                                                [30.5, 50.43], [30.5, 50.4]]]}


def hit(osm_id=101, name="вулиця Хрещатик", display="вулиця Хрещатик, Київ, Україна", **extra):
    return {"osm_type": "way", "osm_id": osm_id, "name": name, "display_name": display,
            "lat": "50.415", "lon": "30.515", "boundingbox": ["50.4", "50.43", "30.5", "30.53"],
            "category": "highway", "type": "residential", "addresstype": "road", **extra}


def fake_nominatim(monkeypatch, native, english, *, fail_en=False, acquire=None):
    calls, reservations = [], []

    class Limiter:
        def acquire(self, wait):
            reservations.append(wait)
            return acquire(len(reservations)) if acquire else True

    limiter = Limiter()

    class Client:
        def get(self, url, params=None):
            calls.append((url.rsplit("/", 1)[-1], dict(params)))
            is_en = params["accept-language"] == "en,uk"
            if is_en and fail_en:
                raise httpx.ConnectError("English provider request unavailable")
            data = english if is_en else native
            return type("Response", (), {"raise_for_status": lambda self: None,
                                          "json": lambda self: deepcopy(data)})()

    monkeypatch.setattr(places, "_limiter", lambda: limiter)
    monkeypatch.setattr(places, "client", lambda: Client())
    return calls, reservations


def strip_en(value):
    if isinstance(value, dict):
        return {k: strip_en(v) for k, v in value.items() if not k.endswith("_en")}
    if isinstance(value, list):
        return [strip_en(v) for v in value]
    return value


def test_search_en_labels_match_identity_not_response_order(client, monkeypatch):
    native = [hit(), hit(202, "майдан Незалежності", "майдан Незалежності, Київ, Україна")]
    en = [hit(202, "Independence Square", "Independence Square, Kyiv, Ukraine"),
          hit(101, "Khreshchatyk Street", "Khreshchatyk Street, Kyiv, Ukraine", lon="1", lat="1")]
    calls, reservations = fake_nominatim(monkeypatch, native, en)
    uk = client.get("/api/places", params={"q": "localized street"}).json()
    got = client.get("/api/places", params={"q": "localized street", "lang": "en"}).json()
    assert strip_en(got) == uk
    assert [r["name_en"] for r in got["geocoder"]] == ["Khreshchatyk Street", "Independence Square"]
    assert got["geocoder"][0]["display_name_en"] == "Khreshchatyk Street, Kyiv, Ukraine"
    assert got["geocoder"][0]["center"] == [30.515, 50.415]
    assert [p["accept-language"] for _, p in calls] == ["uk", "en,uk"]
    assert reservations == [places.SEARCH_MAX_WAIT_S] * 2


def test_default_and_uk_search_use_no_english_request(client, monkeypatch):
    calls, _ = fake_nominatim(monkeypatch, [hit()], [hit(name="Khreshchatyk Street")])
    a = client.get("/api/places", params={"q": "localized street"})
    b = client.get("/api/places", params={"q": "localized street", "lang": "uk"})
    assert a.content == b.content
    assert "name_en" not in a.json()["geocoder"][0]
    assert len(calls) == 1 and calls[0][1]["accept-language"] == "uk"


@pytest.mark.parametrize("failure", ["busy", "unavailable", "missing", "malformed"])
def test_english_search_failure_keeps_successful_native_hits(client, monkeypatch, failure):
    en = [] if failure == "missing" else ({"unexpected": True} if failure == "malformed" else [hit(name="EN")])
    calls, _ = fake_nominatim(monkeypatch, [hit()], en, fail_en=failure == "unavailable",
                             acquire=(lambda n: n == 1) if failure == "busy" else None)
    r = client.get("/api/places", params={"q": "localized street", "lang": "en"})
    assert r.status_code == 200
    out = r.json()
    assert out["geocoder_status"] == "ok"
    g = out["geocoder"][0]
    assert g["name_en"] == g["name"] == "вулиця Хрещатик"
    assert g["display_name_en"] == g["display_name"]
    assert len(calls) == (1 if failure == "busy" else 2)


def test_cache_keys_separate_language_and_lookup_mode(client, monkeypatch):
    native = [hit(geojson=POLYGON)]
    en = [hit(name="Khreshchatyk Street", display="Khreshchatyk Street, Kyiv, Ukraine")]
    calls, reservations = fake_nominatim(monkeypatch, native, en)
    for _ in range(2):
        client.get("/api/places", params={"q": "localized street", "lang": "en"})
        client.get("/api/places/osm:W101", params={"lang": "en"})
    assert [(path, p["accept-language"]) for path, p in calls] == [
        ("search", "uk"), ("search", "en,uk"), ("lookup", "uk"), ("lookup", "en,uk")]
    assert len(reservations) == 4
    assert calls[2][1]["polygon_geojson"] == 1
    assert calls[3][1]["polygon_geojson"] == 0
    # Switching back to UK reuses only native cache entries, with no English siblings or extra HTTP.
    for path in ("/api/places?q=localized+street", "/api/places/osm:W101"):
        assert "name_en" not in str(client.get(path).json())
    assert len(calls) == 4


def test_lookup_en_adds_labels_preserves_native_geometry_and_internal_default(client, monkeypatch):
    native = [hit(geojson=POLYGON)]
    en = [hit(name="Khreshchatyk Street", display="Khreshchatyk Street, Kyiv, Ukraine",
              geojson={"type": "Point", "coordinates": [1, 1]})]
    calls, _ = fake_nominatim(monkeypatch, native, en)
    canonical = places.get_place("osm:W101")
    assert len(calls) == 1
    response = client.get("/api/places/osm:W101", params={"lang": "en"})
    assert response.status_code == 200
    got = response.json()
    assert strip_en(got) == canonical
    assert got["geometry"] == POLYGON and got["name"] == "вулиця Хрещатик"
    assert got["name_en"] == "Khreshchatyk Street"
    assert got["display_name_en"] == "Khreshchatyk Street, Kyiv, Ukraine"
    assert calls[-1][1] == {"osm_ids": "W101", "format": "jsonv2", "polygon_geojson": 0,
                           "accept-language": "en,uk"}


def test_lookup_missing_matching_english_id_falls_back_native(client, monkeypatch):
    calls, _ = fake_nominatim(monkeypatch, [hit(geojson=POLYGON)], [hit(999, name="Wrong identity")])
    r = client.get("/api/places/osm:W101", params={"lang": "en"})
    assert r.status_code == 200
    got = r.json()
    assert got["name_en"] == got["name"]
    assert got["display_name_en"] == got["display_name"]
    assert len(calls) == 2


def test_circle_english_suffix_native_fields_and_geometry_unchanged(client, monkeypatch):
    native = [hit(geojson={"type": "Point", "coordinates": [30.515, 50.415]})]
    en = [hit(name="Khreshchatyk Street", display="Khreshchatyk Street, Kyiv, Ukraine")]
    fake_nominatim(monkeypatch, native, en)
    uk = client.get("/api/places/osm:W101").json()
    got = client.get("/api/places/osm:W101?lang=en").json()
    assert got["kind"] == "geocoder_circle"
    assert got["name"] == "вулиця Хрещатик (≈1 км навколо)"
    assert got["name_en"] == "Khreshchatyk Street (≈1 km around)"
    assert strip_en(got) == uk


def test_english_display_prefix_used_when_provider_omits_short_name(client, monkeypatch):
    en = hit(display="Khreshchatyk Street, Kyiv, Ukraine")
    del en["name"]
    fake_nominatim(monkeypatch, [hit()], [en])
    got = client.get("/api/places", params={"q": "localized street", "lang": "en"}).json()["geocoder"][0]
    assert got["name_en"] == "Khreshchatyk Street"


def test_presets_and_geocoder_still_deduplicate_by_osm_id(client, monkeypatch):
    preset = {"id": "osm:W101", "name": "вулиця Хрещатик", "kind": "city", "geometry": POLYGON}
    monkeypatch.setattr(places, "search_presets", lambda q: [preset])
    fake_nominatim(monkeypatch, [hit(), hit(202, "Інша вулиця")], [hit(name="Khreshchatyk Street")])
    got = client.get("/api/places", params={"q": "localized street", "lang": "en"}).json()
    assert [g["id"] for g in got["geocoder"]] == ["osm:W202"]
    assert got["presets"][0]["id"] == "osm:W101"


@pytest.mark.parametrize("failure", ["busy", "unavailable"])
def test_lookup_english_request_failure_keeps_native_geometry(client, monkeypatch, failure):
    fake_nominatim(monkeypatch, [hit(geojson=POLYGON)], [hit(name="EN")],
                    fail_en=failure == "unavailable", acquire=(lambda n: n == 1) if failure == "busy" else None)
    r = client.get("/api/places/osm:W101?lang=en")
    assert r.status_code == 200
    out = r.json()
    assert out["geometry"] == POLYGON
    assert out["name_en"] == out["name"]
    assert out["display_name_en"] == out["display_name"]


@pytest.mark.parametrize("display", [", Kyiv, Ukraine", "   , Kyiv, Ukraine"])
@pytest.mark.parametrize("endpoint", ["/api/places?q=localized+street&lang=en", "/api/places/osm:W101?lang=en"])
def test_empty_english_display_prefix_uses_native_name(client, monkeypatch, display, endpoint):
    en = hit(display=display)
    del en["name"]
    fake_nominatim(monkeypatch, [hit(geojson=POLYGON)], [en])
    response = client.get(endpoint)
    assert response.status_code == 200
    body = response.json()
    place = body["geocoder"][0] if "geocoder" in body else body
    assert place["name_en"] == place["name"] == "вулиця Хрещатик"
