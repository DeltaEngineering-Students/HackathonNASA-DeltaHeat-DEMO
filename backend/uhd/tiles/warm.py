"""Pre-build tile pyramids and pre-render low-zoom tiles over the coverage (run after deploy / data updates).

    python -m uhd.tiles.warm [--max-zoom 9] [--min-zoom 5] [--jobs 8] [--layers gap,lst,ndvi,dndvi] [--themes light,dark]
    python -m uhd.tiles.warm --area cities --min-zoom 10 --max-zoom 13 --layers gap   # city-zoom tiles of the 3 cities
    python -m uhd.tiles.warm --area demo --min-zoom 14 --max-zoom 14 --layers gap     # demo zones at z14
"""

from __future__ import annotations

import argparse
import logging
import math
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

from uhd.config import get_settings
from uhd.logging_setup import setup_logging
from uhd.services import rasters
from uhd.tiles import pyramid, render

log = logging.getLogger("uhd.tiles.warm")


def _xy(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 1 << z
    return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)


def boxes(area: str, margin_km: float, aoi: str) -> list[tuple[float, float, float, float]]:
    """WGS84 boxes to render: the whole coverage, the city presets or the demo zones (+ margin)."""
    if area == "coverage":
        return [tuple(rasters.bbox_wgs84(aoi))]
    from uhd.services import places

    kinds = {"cities": ("city",), "demo": ("demo_zone",)}[area]
    out = []
    for p in places.presets().values():
        if p["kind"] in kinds and p.get("bbox"):
            w, s, e, n = p["bbox"]
            dy = margin_km / 111.0
            dx = dy / max(0.2, math.cos(math.radians((s + n) / 2)))
            out.append((w - dx, s - dy, e + dx, n + dy))
    return out


def _build(aoi: str, layer: str, year: int) -> str:
    for f in pyramid.FACTORS:
        pyramid.level(aoi, layer, year, f)
    return f"{layer}/{year}"


def _render(jobs: list[tuple]) -> int:
    for j in jobs:
        render.tile_png(*j)
    return len(jobs)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-zoom", type=int, default=5)
    ap.add_argument("--max-zoom", type=int, default=9)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--layers", default="gap,lst,ndvi,dndvi")
    ap.add_argument("--themes", default="light,dark")
    ap.add_argument("--years", default="")
    ap.add_argument("--area", choices=("coverage", "cities", "demo"), default="coverage")
    ap.add_argument("--margin-km", type=float, default=8.0)
    a = ap.parse_args(argv)
    setup_logging("INFO", True)
    aoi = get_settings().tiles_aoi
    years = [int(y) for y in a.years.split(",") if y] or rasters.years(aoi)
    layers = [l for l in a.layers.split(",") if (not l.endswith("_fill") or (render.fill_enabled() and l in render.FILL_SERVED))
              and (l != "nonbuilt" or pyramid.nonbuilt_available())]
    base = sorted({"ndvi" if l == "dndvi" else l for l in layers}
                  | ({pyramid.WATER} if "dndvi" in layers and render.dndvi_water_masked() else set()))
    t0 = time.time()
    with ProcessPoolExecutor(a.jobs) as ex:
        for f in as_completed([ex.submit(_build, aoi, l, y) for l in base for y in years]):
            log.info("pyramid ready", extra={"what": f.result()})
    log.info("pyramids done", extra={"s": round(time.time() - t0)})
    jobs = []
    for z in range(a.min_zoom, a.max_zoom + 1):
        tiles = set()
        for w, s, e, n in boxes(a.area, a.margin_km, aoi):
            x0, y0 = _xy(w, n, z)
            x1, y1 = _xy(e, s, z)
            tiles |= {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
        for layer in layers:
            for th in a.themes.split(","):
                for yr in years:
                    jobs += [(layer, yr, z, x, y, th) for x, y in sorted(tiles)]
    log.info("rendering", extra={"tiles": len(jobs), "area": a.area})
    chunks = [jobs[i:i + 200] for i in range(0, len(jobs), 200)]
    done = 0
    with ProcessPoolExecutor(a.jobs) as ex:
        for f in as_completed([ex.submit(_render, c) for c in chunks]):
            done += f.result()
    log.info("tiles done", extra={"tiles": done, "s": round(time.time() - t0)})


if __name__ == "__main__":
    main()
