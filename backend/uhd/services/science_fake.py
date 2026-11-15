"""Deterministic FIXTURE science engine (UHD_SCIENCE_FAKE=1 / tests). Not real data — every report says so."""

from __future__ import annotations

import hashlib
import math

DATA_VERSION = "fixture-1"
METHOD_VERSION = "fixture"


def _rng(seed: str):
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    while True:
        h = (h * 6364136223846793005 + 1442695040888963407) % 2**64
        yield (h >> 11) / 2**53


def analyze(geometry_wgs84: dict, years: list[int] | None, name: str | None = None) -> dict:
    y0, y1 = years or (2013, 2025)
    r = _rng(str(geometry_wgs84))
    base = 3 + 4 * next(r)
    slope = -0.5 + 2 * next(r)
    series = []
    for y in range(y0, y1 + 1):
        ref = 27 + 2 * math.sin(y) + next(r)
        gap = base + slope * (y - y0) / 10 + (next(r) - 0.5)
        series.append({"year": y, "zone_lst": round(ref + gap, 2), "ref_lst": round(ref, 2), "gap": round(gap, 2),
                       "ndvi": round(0.35 - 0.01 * (y - y0) * next(r), 3), "ndbi": round(0.05 + 0.005 * (y - y0), 3),
                       "built_share": round(0.6 + 0.01 * (y - y0), 3), "scenes": 5 + int(6 * next(r)),
                       "valid_share": round(0.8 + 0.2 * next(r), 3), "method": "per_scene"})
    gaps = [s["gap"] for s in series]
    n = len(series)
    p = 0.01 if abs(slope) > 0.7 else 0.3
    return {
        "fixture": True,
        "zone": {"name": name, "area_km2": None, "built_area_km2": None},
        "reference": {"city": "kyiv", "ring_km": [2, 15], "area_km2": 210.0, "forest_px": 58000},
        "series": series,
        "gap_summary": {"mean": round(sum(gaps) / n, 2), "last": gaps[-1], "min": min(gaps), "max": max(gaps)},
        "trend": {"slope_per_decade": round(slope, 2), "ci95": [round(slope - 0.6, 2), round(slope + 0.6, 2)],
                  "p": p, "n_years": n},
        "ref_trend": {"slope_per_decade": 0.4, "ci95": [-0.2, 1.0], "p": 0.2, "n_years": n},
        "ndvi_trend": {"slope_per_decade": -0.02, "ci95": [-0.04, 0.0], "p": 0.08, "n_years": n},
        "land_change": {"always_built": 3.1, "new_built": 0.4, "always_green": 0.6},
        "green_gap": {"mean": 2.9},
        "caveats": [{"code": "fixture_data", "text_uk": "Це тестові дані, а не результат аналізу знімків."}],
        "verdict_text_uk": "ТЕСТОВІ ДАНІ: вердикт не відображає реальних вимірювань.",
    }


def list_scenes(geometry_wgs84: dict, year: int) -> list[dict]:
    r = _rng(f"{year}{geometry_wgs84}")
    out = []
    for i, day in enumerate(("06-05", "06-21", "07-07", "07-23", "08-08", "08-24")):
        ref = 26 + 3 * next(r)
        sid = f"LC08_L2SP_181025_{year}{day.replace('-', '')}_02_T1"
        out.append({"id": sid, "ids": [sid], "date": f"{year}-{day}", "path": 181, "row": 25, "rows": [25],
                    "cloud": round(40 * next(r), 1), "used": i % 3 != 2, "reason": None if i % 3 != 2 else "zone_cloudy",
                    "zone_lst": round(ref + 6, 2), "ref_lst": round(ref, 2), "gap": 6.0, "zone_valid_share": 0.9,
                    "ref_valid_px": 50000, "fixture": True})
    return out


def layer_raster(aoi: str, layer: str, year: int, window=None):
    """Fixture rasters straight from the composites; gap = LST − 30 °C (constant fake reference)."""
    from uhd.tiles import pyramid

    r0, c0, h, w = window
    if layer == "gap":
        return pyramid._read_direct(aoi, "lst", year, r0, c0, h, w) - 30.0, None, "EPSG:3035"
    if layer == "dndvi":
        return (pyramid._read_direct(aoi, "ndvi", year, r0, c0, h, w)
                - pyramid._read_direct(aoi, "ndvi", 2013, r0, c0, h, w)), None, "EPSG:3035"
    return pyramid._read_direct(aoi, layer, year, r0, c0, h, w), None, "EPSG:3035"


def reference_outline(geometry_wgs84: dict, simplify_m: float = 30) -> dict:
    """Fixture reference forest: a 2–15 km ring around the zone bbox (lon/lat degrees, roughly), vertex count ∝ 1/simplify."""
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0]); ys.append(c[1])
        else:
            for v in c:
                walk(v)
    walk(geometry_wgs84["coordinates"])
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    n = max(16, int(4000 / simplify_m))

    def circle(r):
        pts = [[cx + r * math.cos(2 * math.pi * i / n) / math.cos(math.radians(cy)), cy + r * math.sin(2 * math.pi * i / n)]
               for i in range(n)]
        return pts + [pts[0]]
    return {"type": "Polygon", "coordinates": [circle(0.135), circle(0.018)[::-1]]}
