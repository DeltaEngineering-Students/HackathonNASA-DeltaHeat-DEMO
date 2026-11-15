"""Open-Meteo historical archive (ERA5-based reanalysis): local copy first, else a proxy with a disk cache.

Board item 34: the team's Open-Meteo download (30 cities, May–Sep, 2003/2013–2025, daily + hourly, Europe/Kyiv) lives in
``{data_dir}/weather/openmeteo/<city>/<year>.json[.gz]`` (read-only input). A point within ``LOCAL_RADIUS_KM`` of one of
those city points whose whole window (the date and ``LOOKBACK_DAYS`` before it) is in the file is answered from it —
no request to the live API (its free quota is shared with the homelab's jobs). Anything else goes to the live API.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import logging
import math
import time
from functools import lru_cache
from pathlib import Path

import httpx

from uhd.config import get_settings
from uhd.errors import bad_request
from uhd.services.geometry import UKRAINE_BBOX
from uhd.services.http import DiskCache, client

log = logging.getLogger(__name__)
_cache = DiskCache("weather")
DAILY = ["temperature_2m_max", "temperature_2m_min", "temperature_2m_mean", "precipitation_sum",
         "wind_speed_10m_max", "shortwave_radiation_sum", "relative_humidity_2m_mean", "cloud_cover_mean"]
HOURLY = ["temperature_2m", "relative_humidity_2m", "cloud_cover", "wind_speed_10m", "soil_moisture_0_to_7cm"]
OVERPASS_HOURS = ("10:00", "11:00", "12:00")  # local (Europe/Kyiv) hours around the Landsat overpass
LOOKBACK_DAYS = 3
LOCAL_RADIUS_KM = 25.0
LOCAL_SOURCE = "open-meteo-archive-local (ERA5)"
ATTRIBUTION = "Open-Meteo Historical Weather API (ERA5 / ERA5-Land reanalysis), https://open-meteo.com — CC BY 4.0"


def _local_dir() -> Path:
    return get_settings().data_dir / "weather" / "openmeteo"


def _read(f: Path) -> dict:
    raw = f.read_bytes()
    return json.loads(gzip.decompress(raw) if f.suffix == ".gz" else raw)


def _year_file(city: str, year: int) -> Path | None:
    for name in (f"{year}.json", f"{year}.json.gz"):
        f = _local_dir() / city / name
        if f.is_file():
            return f
    return None


def _cities(root: str) -> tuple[tuple[str, float, float], ...]:
    """(city, lat, lon) of the points the archive was fetched for. Nothing about the archive is in code: the list is
    ``cities.json`` next to it (copied from the downloader's ``acq/common.py`` CITIES), plus any city folder it does not
    list (that folder's ``_meta.query_lat/lon``). Re-read when the file / folder mtime changes, so a new city needs no deploy or restart."""
    d = Path(root)
    try:
        if not d.is_dir():
            return ()
        f = d / "cities.json"
        listed = _cities_file(str(f), f.stat().st_mtime) if f.is_file() else ()
        names = {c for c, _, _ in listed}
        # a city folder that cities.json does not list yet still counts (its files' own _meta point)
        return listed + tuple(c for c in _cities_scan(root, d.stat().st_mtime) if c[0] not in names)
    except OSError:
        return ()


@lru_cache(maxsize=4)
def _cities_file(path: str, mtime: float) -> tuple[tuple[str, float, float], ...]:
    try:
        c = json.loads(Path(path).read_text()).get("cities") or {}
        return tuple((k, float(v["lat"]), float(v["lon"])) for k, v in sorted(c.items()))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        log.warning("weather cities.json unreadable", extra={"file": path, "err": str(e)})
        return ()


@lru_cache(maxsize=4)
def _cities_scan(root: str, mtime: float) -> tuple[tuple[str, float, float], ...]:
    out = []
    d = Path(root)
    for c in sorted(p for p in d.iterdir() if p.is_dir() and not p.name.startswith(".")):  # not .incoming
        files = sorted(c.glob("*.json")) + sorted(c.glob("*.json.gz"))
        if not files:
            continue
        try:
            j = _read(files[-1])
            m = j.get("_meta") or {}
            out.append((c.name, float(m.get("query_lat", j["latitude"])), float(m.get("query_lon", j["longitude"]))))
        except (OSError, ValueError, KeyError, TypeError) as e:
            log.warning("weather archive file unreadable", extra={"file": str(files[-1]), "err": str(e)})
    return tuple(out)


@lru_cache(maxsize=64)
def _file_json(path: str, mtime: float) -> dict:
    return _read(Path(path))


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(min(1.0, a)))


def _slice(j: dict, start: dt.date, d: dt.date) -> dict | None:
    """The archive file cut to [start, d] in the live API's shape, or None unless the date itself is there (the days
    before it may be fewer at the start of the season, e.g. 1 May)."""
    daily, hourly = j.get("daily") or {}, j.get("hourly") or {}
    times = daily.get("time") or []
    idx = {t: i for i, t in enumerate(times)}
    want = [t for t in ((start + dt.timedelta(days=i)).isoformat() for i in range((d - start).days + 1)) if t in idx]
    if d.isoformat() not in idx or any(k not in daily for k in DAILY) or any(k not in hourly for k in HOURLY):
        return None
    di = [idx[t] for t in want]
    hi = [i for i, t in enumerate(hourly.get("time") or []) if start.isoformat() <= t[:10] <= d.isoformat()]
    keep = lambda units, keys: {k: v for k, v in (units or {}).items() if k == "time" or k in keys}  # noqa: E731
    return {"latitude": j.get("latitude"), "longitude": j.get("longitude"),
            "daily": {"time": want, **{k: [daily[k][i] for i in di] for k in DAILY}},
            "hourly": {"time": [hourly["time"][i] for i in hi], **{k: [hourly[k][i] for i in hi] for k in HOURLY}},
            "daily_units": keep(j.get("daily_units"), DAILY), "hourly_units": keep(j.get("hourly_units"), HOURLY)}


def _local(lat: float, lon: float, start: dt.date, d: dt.date) -> tuple[dict, str, float] | None:
    """(data, city, km) from the local archive, or None (no city within the radius / date not in the file). Files are
    per summer season (May–Sep), so a window never needs two files."""
    best = min(((_km(lat, lon, la, lo), c) for c, la, lo in _cities(str(_local_dir()))), default=None)
    if best is None or best[0] > LOCAL_RADIUS_KM:
        return None
    km, city = best
    f = _year_file(city, d.year)
    if f is None:
        return None
    try:
        j = _file_json(str(f), f.stat().st_mtime)
    except (OSError, ValueError) as e:
        log.warning("weather archive file unreadable", extra={"file": str(f), "err": str(e)})
        return None
    data = _slice(j, start, d) if j else None
    return (data, city, km) if data else None


def _check(lat: float, lon: float, date: str) -> dt.date:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise bad_request("invalid_coordinates", "lat/lon out of range")
    w, so, e, n = UKRAINE_BBOX
    if not (w <= lon <= e and so <= lat <= n):  # an open proxy only for the service's own region (REVIEW L)
        raise bad_request("outside_coverage", "weather is available only for points in Ukraine")
    try:
        d = dt.date.fromisoformat(date)
    except ValueError as e:
        raise bad_request("invalid_date", "date must be YYYY-MM-DD") from e
    if d < dt.date(1950, 1, 1) or d > dt.date.today() - dt.timedelta(days=5):
        raise bad_request("invalid_date", "date must be between 1950-01-01 and 5 days ago (archive delay)")
    return d


QUOTA_BACKOFF_S = 600
_quota_until = 0.0
UNAVAILABLE = {
    "quota": ("Погода зараз недоступна: вичерпано денний ліміт запитів до архіву Open-Meteo, а цієї дати й місця "
              "немає в нашій локальній копії. Спробуйте пізніше.",
              "Weather is unavailable right now: the daily request limit of the Open-Meteo archive is used up, and "
              "this date and place are not in our local copy. Try again later."),
    "upstream": ("Погода зараз недоступна: архів Open-Meteo не відповідає, а цієї дати й місця немає в нашій "
                 "локальній копії. Спробуйте пізніше.",
                 "Weather is unavailable right now: the Open-Meteo archive is not responding, and this date and place "
                 "are not in our local copy. Try again later."),
}


def unavailable(d: dt.date, lat: float, lon: float, reason: str) -> dict:
    uk, en = UNAVAILABLE[reason]
    return {"available": False, "reason": reason, "text_uk": uk, "text_en": en, "date": d.isoformat(), "lat": lat,
            "lon": lon}


def get_weather(date: str, lat: float, lon: float) -> dict:
    d = _check(lat, lon, date)
    lat_r, lon_r = round(lat, 2), round(lon, 2)
    start = d - dt.timedelta(days=LOOKBACK_DAYS)
    key = f"{lat_r},{lon_r},{start},{d}"
    old = (dt.date.today() - d).days > 60  # recent days may still be revised by the provider
    # 1) local archive copy, 2) live API (disk-cached), 3) a graceful «not available» (200, never a 5xx)
    hit = _local(lat, lon, start, d)
    data = hit[0] if hit else _cache.get(key, ttl=None if old else 24 * 3600)
    if data is None:
        global _quota_until
        if time.monotonic() < _quota_until:  # an upstream 429 is remembered per process — do not hammer the API
            return unavailable(d, lat_r, lon_r, "quota")
        params = {"latitude": lat_r, "longitude": lon_r, "start_date": start.isoformat(), "end_date": d.isoformat(),
                  "daily": ",".join(DAILY), "hourly": ",".join(HOURLY), "timezone": "Europe/Kyiv"}
        try:
            r = client().get(get_settings().open_meteo_archive_url, params=params)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPStatusError as e:
            quota = e.response.status_code == 429
            if quota:
                _quota_until = time.monotonic() + QUOTA_BACKOFF_S
            log.warning("open-meteo error", extra={"err": str(e), "status": e.response.status_code})
            return unavailable(d, lat_r, lon_r, "quota" if quota else "upstream")
        except (httpx.HTTPError, ValueError) as e:  # timeout, connection, bad JSON
            log.warning("open-meteo error", extra={"err": str(e)})
            return unavailable(d, lat_r, lon_r, "upstream")
        _cache.put(key, data)
    daily = data.get("daily") or {}
    days = []
    for i, t in enumerate(daily.get("time", [])):
        days.append({"date": t, **{k: (daily.get(k) or [None] * (i + 1))[i] for k in DAILY}})
    hourly = data.get("hourly") or {}
    overpass = []
    for i, t in enumerate(hourly.get("time", [])):
        if t.startswith(d.isoformat()) and t[11:16] in OVERPASS_HOURS:
            overpass.append({"time": t, **{k: (hourly.get(k) or [None] * (i + 1))[i] for k in HOURLY}})
    units = {**(data.get("daily_units") or {}), **(data.get("hourly_units") or {})}
    units.pop("time", None)
    out = {
        "available": True, "date": d.isoformat(), "lat": lat_r, "lon": lon_r, "grid_lat": data.get("latitude"), "grid_lon": data.get("longitude"),
        "day": next((x for x in days if x["date"] == d.isoformat()), None),
        "previous_days": [x for x in days if x["date"] != d.isoformat()],
        "overpass_hours_local": overpass, "units": units, "timezone": "Europe/Kyiv",
        "source": "Open-Meteo Historical Weather API (ERA5 / ERA5-Land reanalysis), https://open-meteo.com — CC BY 4.0",
        "note": "Air temperature at 2 m from reanalysis, not LST.",
    }
    if hit:
        out.update(source=LOCAL_SOURCE, attribution=ATTRIBUTION, city=hit[1], city_distance_km=round(hit[2], 1),
                   note=out["note"] + f" Local copy of the Open-Meteo archive for the {hit[1]} city point "
                                      f"({round(hit[2], 1)} km away; ERA5 cells are ≈ 25 km).")
    return out
