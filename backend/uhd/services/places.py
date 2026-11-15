"""Places: presets (districts / demo zones / whole cities) + Nominatim geocoder fallback.

Preset sources, merged in this order (later ids override earlier ones):
1. bundled ``uhd/resources/presets.geojson`` (OSM boundaries, demo circles);
2. ``uhd/backend/data/places/*.geojson`` and ``{data_dir}/places/*.geojson`` written by the science precompute
   (scripts/precompute_places.py: real district / locality polygons);
3. ``uhd.science.list_presets()`` if the science package provides it.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from shapely.geometry import shape

from uhd.config import get_settings
from uhd.errors import APIError, bad_request, not_found
from uhd.services import science
from uhd.services.geometry import area_km2, circle, to_geojson
from uhd.services.http import DiskCache, SlotLimiter, client

log = logging.getLogger(__name__)
RESOURCES = Path(__file__).resolve().parent.parent / "resources"
NOT_PRESETS = {"war_oblasts.geojson", "occupied.geojson"}  # science reference data that lives next to the presets but is not searchable
REPO_PLACES = Path(__file__).resolve().parent.parent.parent / "data" / "places"  # science --repo-copy
_geocache = DiskCache("nominatim")
GEOCODER_TTL_S = 30 * 24 * 3600
_OSM_ID = re.compile(r"osm:[NWR][0-9]{1,16}")
CIRCLE_KM = 1.0
CIRCLE_NOTE_UK = ("Обраний об'єкт — точка або дуже мала ділянка, тому аналізуємо коло радіусом ≈1 км навколо "
                  "нього.")
SEARCH_MAX_WAIT_S = 1.2  # one slot at most: a sequential client is served, a burst gets geocoder_busy
LOOKUP_MAX_WAIT_S = 2.0  # opening a geocoder result: worth a short wait, then 503 geocoder_busy


def _limiter() -> SlotLimiter:
    return SlotLimiter("nominatim", get_settings().nominatim_min_interval_s)


_APOSTROPHES = set("'’ʼ`´‘ʹ")


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.casefold())
    # apostrophes are dropped, not normalised: «Соломянський» = «Солом'янський» = «Соломʼянський»
    return "".join(c for c in s if not unicodedata.combining(c) and c not in _APOSTROPHES)


_TRANSLIT = {"а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ie", "ж": "zh", "з": "z",
             "и": "y", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
             "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh",
             "щ": "shch", "ь": "", "ю": "iu", "я": "ia", "'": "", "’": "", "ʼ": "", "«": "", "»": ""}
_KIND_ALIASES = {"demo": "demo_zone"}
_EXTRA_PROPS = ("case", "note_uk", "source")


def ascii_id(s: str) -> str:
    """Stable URL-safe id (Ukrainian national transliteration, lower-case, '-' separated)."""
    out = "".join(_TRANSLIT.get(c, c) for c in s.lower())
    out = re.sub(r"[^a-z0-9]+", "-", out).strip("-")
    return out


def _feature_to_place(f: dict) -> dict:
    p = f.get("properties") or {}
    g = shape(f["geometry"])
    raw_id = str(p["id"])
    pid = raw_id if raw_id.isascii() else ascii_id(raw_id.removesuffix("-район").removesuffix("-raion"))
    pl = {
        "id": pid,
        "name": p.get("name") or raw_id,
        "kind": _KIND_ALIASES.get(p.get("kind", "district"), p.get("kind", "district")),
        "city": p.get("city"),
        "bbox": [round(v, 5) for v in g.bounds],
        "area_km2": round(area_km2(g), 2),
        "geometry": f["geometry"],
        **{k: p[k] for k in _EXTRA_PROPS if p.get(k)},
    }
    if raw_id != pid:
        pl["aliases"] = [raw_id]
    return pl


def _match_key(p: dict) -> tuple:
    name = _fold(p["name"]).split("(")[0].strip()
    return (p.get("city"), p["kind"], name)


def _merge(out: dict[str, dict], pl: dict) -> None:
    """Later sources override earlier ones (geometry + extra props); a place with the same city + name (+ district-ness)
    keeps the first (bundled, ASCII) id and display name; same kind only, so URLs stay stable and nothing is listed twice."""
    if pl["id"] in out:
        same = pl["id"]
    else:
        key = _match_key(pl)
        same = next((k for k, v in out.items() if _match_key(v) == key), None)
    if same is not None:
        kept = out[same]
        out[same] = {**kept, **pl, "id": same, "name": kept["name"], "kind": kept["kind"],
                     "aliases": sorted(set(kept.get("aliases", [])) | set(pl.get("aliases", [])) | ({pl["id"]} - {same}))}
        if not out[same]["aliases"]:
            out[same].pop("aliases")
    else:
        out[pl["id"]] = pl


@lru_cache(maxsize=1)
def presets() -> dict[str, dict]:
    out: dict[str, dict] = {}
    files = [RESOURCES / "presets.geojson"]
    for pdir in (REPO_PLACES, get_settings().data_dir / "places"):
        if pdir.is_dir():
            files += sorted(f for f in pdir.glob("*.geojson") if f.name not in NOT_PRESETS)
    for fp in files:
        try:
            fc = json.loads(fp.read_text())
            for f in fc.get("features", []):
                _merge(out, _feature_to_place(f))
        except Exception:  # noqa: BLE001
            log.exception("cannot read presets file", extra={"file": str(fp)})
    try:
        for pl in science.list_presets() or []:
            if "geometry" in pl and "id" in pl:
                _merge(out, _feature_to_place({"type": "Feature", "properties": pl, "geometry": pl["geometry"]}))
    except science.ScienceNotReady:
        pass
    except Exception:  # noqa: BLE001
        log.exception("science.list_presets failed")
    return out


@lru_cache(maxsize=1)
def city_shortcuts() -> dict[str, dict]:
    """Major Ukrainian cities outside the bundled presets (QA R3-5): searchable by name/aliases, opened through their
    OSM boundary relation (``get_place`` fetches the polygon on demand, cached), so «Дніпро» finds the city first."""
    try:
        rows = json.loads((RESOURCES / "cities_ua.json").read_text())["cities"]
    except (OSError, ValueError, KeyError):
        log.exception("cannot read cities_ua.json")
        return {}
    have = {_fold(p["name"]).replace("увесь ", "") for p in presets().values() if p["kind"] == "city"}
    return {c["id"]: {"id": c["id"], "name": c["name"], "kind": "city", "city": None, "bbox": c["bbox"],
                      "center": c["center"], "aliases": c.get("aliases", []), "oblast": c.get("oblast"),
                      "source": "osm", "geometry": None}
            for c in rows if _fold(c["name"]) not in have}


def _summary(p: dict) -> dict:
    return {k: v for k, v in p.items() if k != "geometry"}


def _words(s: str) -> list[str]:
    return [w for w in re.split(r"[^\w]+", s) if w]


def _rank(fq: str, p: dict) -> int | None:
    """0 exact name/id/alias · 1 a whole word equals the query («Київ» → «Увесь Київ») · 2 name/id prefix ·
    3 word prefix · 4 substring · None no match. Text is folded (case, diacritics, apostrophes)."""
    name = _fold(p["name"])
    keys = [name, _fold(p["id"])] + [_fold(a) for a in p.get("aliases", ())]
    if fq in keys:
        return 0
    words = _words(name)
    qw = _words(fq)
    if qw and all(w in words for w in qw):
        return 1
    if any(k.startswith(fq) for k in keys):
        return 2
    if qw and all(any(w.startswith(x) for w in words) for x in qw):
        return 3
    if any(fq in k for k in keys):
        return 4
    return None


def search_presets(q: str) -> list[dict]:
    order = {"demo_zone": 0, "city": 1, "district": 2, "locality": 3}
    allp = sorted([*presets().values(), *city_shortcuts().values()], key=lambda p: (order.get(p["kind"], 9), 0 if p.get("case") else 1, p["name"]))
    if not q.strip():  # the default list stays the analysed presets (no remote cities)
        return [_summary(p) for p in allp if p.get("source") != "osm"]
    fq = _fold(q.strip())
    scored = []
    for p in allp:
        r = _rank(fq, p)
        if r is not None:
            scored.append((r, p))
    scored.sort(key=lambda t: (t[0], order.get(t[1]["kind"], 9), 0 if t[1].get("case") else 1, t[1]["name"]))
    return [_summary(p) for _, p in scored]


def _nominatim(path: str, params: dict[str, Any], max_wait_s: float) -> Any:
    s = get_settings()
    key = path + "?" + json.dumps(params, sort_keys=True, ensure_ascii=False)
    hit = _geocache.get(key, ttl=GEOCODER_TTL_S)
    if hit is not None:
        return hit
    if not _limiter().acquire(max_wait_s):
        raise APIError(503, "geocoder_busy", "the geocoder is rate-limited (1 request/s); try again in a moment")
    try:
        r = client().get(f"{s.nominatim_url}/{path}", params=params)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        log.warning("nominatim error", extra={"err": str(e)})
        raise APIError(502, "geocoder_unavailable", "the geocoder is not reachable right now") from e
    _geocache.put(key, data)
    return data


def _osm_id(x: dict) -> str:
    return f"osm:{x['osm_type'][0].upper()}{x['osm_id']}"


# Роман P2-2: the search lists places people live in — settlements, districts, streets and addresses — not river
# banks, forests, shops or bus stops (Nominatim jsonv2 `category` / `type` / `addresstype`).
_PLACE_DROP = {"locality", "island", "islet", "sea", "ocean", "archipelago", "farm", "isolated_dwelling"}


def wanted_hit(x: dict) -> bool:
    """A Nominatim hit worth offering: a settlement, a district, a street or an address."""
    cat, typ, at = x.get("category"), x.get("type"), x.get("addresstype")
    if cat == "place":
        return typ not in _PLACE_DROP
    if cat == "boundary":
        return typ == "administrative"
    if cat == "building":
        return True
    if cat == "highway":
        return at == "road"
    if cat == "landuse":
        return typ == "residential"
    return False


def _english_labels(path: str, params: dict[str, Any], max_wait_s: float) -> dict[str, dict]:
    """Optional labels only: a separate language-aware cache entry, matched by OSM identity.

    Never make a successful native lookup fail because the second request is busy, unavailable or incomplete.
    Both requests use the same cross-worker limiter; an uncached English response can cost another time slot.
    """
    try:
        rows = _nominatim(path, {**params, "accept-language": "en,uk"}, max_wait_s)
    except (APIError, ValueError):
        return {}
    if not isinstance(rows, list):
        return {}
    out = {}
    for row in rows:
        try:
            out[_osm_id(row)] = row
        except (KeyError, TypeError, IndexError, AttributeError):
            continue
    return out


def _label(row: dict, key: str, fallback: str) -> str:
    value = row.get(key)
    return value if isinstance(value, str) and value.strip() else fallback


def _name_label(row: dict, fallback: str) -> str:
    display_name = _label(row, "display_name", "")
    prefix = display_name.split(",")[0].strip()
    return _label(row, "name", prefix or fallback)


def geocode(q: str, limit: int = 5, english: bool = False) -> list[dict]:
    if len(q.strip()) < 3:
        return []
    # ask for a few more: some are filtered out (wanted_hit)
    params = {"q": q.strip(), "format": "jsonv2", "countrycodes": "ua", "limit": min(10, limit * 2),
              "accept-language": "uk", "addressdetails": 0}
    data = _nominatim("search", params, SEARCH_MAX_WAIT_S)
    out = []
    for x in data:
        if len(out) >= limit:
            break
        if not wanted_hit(x):
            continue
        try:
            bb = [float(v) for v in x["boundingbox"]]  # [south, north, west, east]
            out.append({"id": _osm_id(x), "name": x.get("name") or x["display_name"].split(",")[0],
                        "display_name": x["display_name"], "kind": "geocoder", "osm_class": x.get("category"),
                        "osm_type": x.get("addresstype") or x.get("type"),
                        "center": [round(float(x["lon"]), 6), round(float(x["lat"]), 6)],
                        "bbox": [bb[2], bb[0], bb[3], bb[1]]})
        except (KeyError, ValueError):
            continue
    if english and out:
        labels = _english_labels("search", params, SEARCH_MAX_WAIT_S)
        for hit in out:
            en = labels.get(hit["id"], {})
            # Explicit fallback siblings prevent the generic i18n walker from inventing a romanised address.
            hit["name_en"] = _name_label(en, hit["name"])
            hit["display_name_en"] = _label(en, "display_name", hit["display_name"])
    return out


def search(q: str, limit: int = 10, geocoder: bool = True, english: bool = False) -> dict:
    pre = search_presets(q)[:limit]
    geo: list[dict] = []
    status = None
    if geocoder and q.strip() and len(pre) < limit:
        try:
            ids = {p["id"] for p in pre}
            kwargs = {"english": True} if english else {}
            geo = [g for g in geocode(q, limit=min(5, limit - len(pre)), **kwargs) if g["id"] not in ids]
            status = "ok"
        except APIError as e:
            geo, status = [], e.code
    return {"query": q, "presets": pre, "geocoder": geo, "geocoder_status": status,
            "attribution": "Geocoding © OpenStreetMap contributors (Nominatim)" if geo else None}


def _by_alias(place_id: str) -> dict | None:
    for p in presets().values():
        if place_id in p.get("aliases", ()):
            return p
    return None


def get_place(place_id: str, english: bool = False) -> dict:
    p = presets().get(place_id) or _by_alias(place_id)
    if p:
        return p
    if place_id.startswith("osm:"):
        if not _OSM_ID.fullmatch(place_id):  # never forward junk ids to Nominatim (it answers 500 to huge ones)
            raise bad_request("invalid_place_id", "osm place ids look like osm:N123, osm:W123 or osm:R123")
        if int(place_id[5:]) == 0:
            raise not_found("place_not_found", f"no such place: {place_id}")
        data = _nominatim("lookup", {"osm_ids": place_id[4:], "format": "jsonv2", "polygon_geojson": 1,
                                     "polygon_threshold": 0.0002, "accept-language": "uk"}, LOOKUP_MAX_WAIT_S)
        if not data:
            raise not_found("place_not_found", f"no such place: {place_id}")
        x = data[0]
        gj = x.get("geojson") or {}
        name = x.get("name") or x["display_name"].split(",")[0]
        g = None
        if gj.get("type") in ("Polygon", "MultiPolygon"):
            try:
                g = shape(gj)
                if not g.is_valid:
                    g = g.buffer(0)
            except Exception:  # noqa: BLE001
                g = None
            if g is not None and (g.is_empty or area_km2(g) < get_settings().min_area_km2):
                g = None  # a square, a building, a tiny park: too small to analyse on its own
        out = {"id": place_id, "name": name, "display_name": x["display_name"], "kind": "geocoder", "city": None}
        sc = city_shortcuts().get(place_id)
        if sc:
            out.update(name=sc["name"], kind="city", source="osm")
        if g is None:  # a point / line / tiny polygon → ≈1 km circle around it (better than area_too_small)
            c = shape(gj).representative_point() if gj.get("type") in ("Polygon", "MultiPolygon") else None
            lon, lat = (c.x, c.y) if c is not None else (float(x["lon"]), float(x["lat"]))
            g = circle(lon, lat, CIRCLE_KM)
            out.update(name=f"{name} (≈1 км навколо)", kind="geocoder_circle", note_uk=CIRCLE_NOTE_UK)
        if english:
            # Labels only: the Ukrainian response remains the sole source of coordinates and geometry.
            labels = _english_labels("lookup", {"osm_ids": place_id[4:], "format": "jsonv2",
                                                "polygon_geojson": 0}, LOOKUP_MAX_WAIT_S)
            en = labels.get(place_id, {})
            base_name = name if out["kind"] == "geocoder_circle" else out["name"]
            out["name_en"] = _name_label(en, base_name)
            if out["kind"] == "geocoder_circle":
                out["name_en"] += " (≈1 km around)"
            out["display_name_en"] = _label(en, "display_name", out["display_name"])
        return {**out, "bbox": [round(v, 5) for v in g.bounds], "area_km2": round(area_km2(g), 2),
                "geometry": to_geojson(g)}
    raise not_found("place_not_found", f"no such place: {place_id}")
