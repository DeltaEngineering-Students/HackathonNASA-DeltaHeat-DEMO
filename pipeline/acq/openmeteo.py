#!/usr/bin/env python3
"""Daily + hourly reanalysis weather (Open-Meteo archive API, ERA5/ERA5-Land) for the cities in common.CITIES.

Weather context for anomalies (heat wave, rain the day before, wind) and the analyst's get_weather tool,
without hitting the API at request time. Period: May-Sep of 2013-2025, then 2003-2012 (MODIS era).
Output: ROOT/weather/openmeteo/<city>/<year>.json (raw API response: daily + hourly arrays, timezone Europe/Kyiv)
Polite: <= 1 request / 20 s (well under the free-tier weighted limits), generic User-Agent, retries on 429.
"""
import os, sys, json, time, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

URL = "https://archive-api.open-meteo.com/v1/archive"
DAILY = ("temperature_2m_max,temperature_2m_min,temperature_2m_mean,apparent_temperature_max,precipitation_sum,"
         "wind_speed_10m_max,shortwave_radiation_sum,cloud_cover_mean,relative_humidity_2m_mean,sunshine_duration")
HOURLY = ("temperature_2m,relative_humidity_2m,cloud_cover,wind_speed_10m,shortwave_radiation,"
          "soil_temperature_0_to_7cm,soil_moisture_0_to_7cm")
log = None


def fetch(city, lon, lat, year):
    out = f"{C.ROOT}/weather/openmeteo/{city}/{year}.json"
    if os.path.exists(out):
        return False
    os.makedirs(os.path.dirname(out), exist_ok=True)
    q = (f"{URL}?latitude={lat}&longitude={lon}&start_date={year}-05-01&end_date={year}-09-30"
         f"&daily={DAILY}&hourly={HOURLY}&timezone=Europe%2FKyiv")
    for attempt in range(10):
        r = subprocess.run(["curl", "-s", "-A", C.UA, "--max-time", "120", "-w", "\n%{http_code}", q],
                           capture_output=True, text=True)
        body, _, code = r.stdout.rpartition("\n")
        if code == "200":
            d = json.loads(body)
            d["_meta"] = dict(city=city, query_lon=lon, query_lat=lat, source="open-meteo archive (ERA5/ERA5-Land)")
            C.atomic_json(d, out)
            return True
        wait = 600 if code == "429" else 60 * (attempt + 1)
        log.warning("%s %d http %s, wait %ds: %s", city, year, code, wait, body[:150])
        time.sleep(wait)
    raise RuntimeError(f"{city} {year} failed")


def main():
    global log
    log = C.setup_log("openmeteo")
    n = 0
    for years in (range(2013, 2026), range(2003, 2013)):
        for c, (lon, lat) in C.CITIES.items():
            for y in years:
                try:
                    if fetch(c, lon, lat, y):
                        n += 1
                        time.sleep(20)
                except Exception as e:  # noqa
                    log.warning("%s", e)
            log.info("%s done (%d requests so far)", c, n)
        C.manifest_update("weather/openmeteo", path=f"{C.ROOT}/weather/openmeteo", cities=len(C.CITIES),
                          years=f"{years.start}-{years.stop - 1}", months="May-Sep", files_fetched_total=n)
    log.info("OPENMETEO DONE")


if __name__ == "__main__":
    main()
