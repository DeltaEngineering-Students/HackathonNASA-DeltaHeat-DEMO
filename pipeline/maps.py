#!/usr/bin/env python3
"""Land-cover maps on the same EPSG:3035 60 m grid as ingest.py.

  worldcover2021.tif   ESA WorldCover v200 (10 trees, 20 shrub, 30 grass, 40 crop, 50 built, 60 bare,
                       80 water, 90 wetland, ...)       -> which nature around the city is the reference
  esri_<year>.tif      Esri/IO annual LULC 2017-2023 (1 water, 2 trees, 4 flooded veg, 5 crops, 7 built,
                       8 bare, 11 rangeland)            -> check of our yearly built-up map
  osm_farmland.tif     OSM landuse farmland/orchard/... (cities only) -> fields are not built-up

Resampling: mode (majority class in each 60 m cell). Resumable: each finished map is a file.
Usage: maps.py kyiv kharkiv lviv   |   maps.py ukraine
"""
import os, sys, json, time, logging, subprocess
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ingest  # noqa: E402  (sets GDAL env, grid helpers)
from ingest import ROOT, DST_CRS, RES, make_grid, grid_transform, GT_OPTS

import numpy as np
import pystac_client
import planetary_computer as pc
import rasterio
from rasterio.features import rasterize
from rasterio.warp import reproject, Resampling
from rasterio.windows import Window
from rasterio.windows import transform as win_transform
import shapely.geometry as sg
from shapely.ops import transform as stransform
import pyproj

log = logging.getLogger("maps")
BLOCK = 1024
ESRI_YEARS = range(2017, 2024)


def search(collection, geom, **kw):
    for attempt in range(5):
        try:
            cat = pystac_client.Client.open(ingest.STAC)
            return [i.to_dict() for i in cat.search(collections=[collection], intersects=geom, **kw).items()]
        except Exception as e:  # noqa
            log.warning("search %s failed: %s", collection, e)
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"search {collection} failed")


def map_block(hrefs, asset, r0, c0, h, w, grid, ovr):
    import pystac
    dT = win_transform(Window(c0, r0, w, h), grid_transform(grid))
    out = np.zeros((h, w), np.uint8)
    for d in hrefs:
        item = pystac.Item.from_dict(d)
        for attempt in range(5):
            try:
                pc.sign_inplace(item)
                kw = {"overview_level": ovr} if ovr is not None else {}
                with rasterio.open(item.assets[asset].href, **kw) as s:
                    tmp = np.zeros((h, w), np.uint8)
                    reproject(rasterio.band(s, 1), tmp, dst_transform=dT, dst_crs=DST_CRS, src_nodata=0,
                              dst_nodata=0, resampling=Resampling.mode, num_threads=2)
                break
            except Exception as e:  # noqa
                if attempt == 4:
                    raise RuntimeError(f"{d['id']}: {e!r}")
                time.sleep(5 * (attempt + 1))
        fill = (out == 0) & (tmp != 0)
        out[fill] = tmp[fill]
    return out


def build_map(aoi, grid, sgeom, name, items, asset, ovr):
    path = f"{ROOT}/{aoi}/maps/{name}.tif"
    if os.path.exists(path):
        log.info("[%s] %s exists, skip", aoi, name); return
    t0 = time.time()
    to_ll = pyproj.Transformer.from_crs(3035, 4326, always_xy=True).transform
    gT = grid_transform(grid)
    jobs = []
    for r0 in range(0, grid["H"], BLOCK):
        for c0 in range(0, grid["W"], BLOCK):
            h, w = min(BLOCK, grid["H"] - r0), min(BLOCK, grid["W"] - c0)
            b = sg.box(*rasterio.windows.bounds(Window(c0, r0, w, h), gT))
            bll = stransform(to_ll, b)
            its = [d for d in items if sg.shape(d["geometry"]).intersects(bll)]
            if its:
                jobs.append((r0, c0, h, w, its))
    log.info("[%s] %s: %d source tiles, %d blocks", aoi, name, len(items), len(jobs))
    prof = dict(GT_OPTS, height=grid["H"], width=grid["W"], crs=DST_CRS, transform=gT, count=1, dtype="uint8", nodata=0)
    tmp = path + ".tmp"
    n_proc = 6
    with rasterio.open(tmp, "w", **prof) as o, \
            ProcessPoolExecutor(n_proc, mp_context=mp.get_context("spawn")) as ex:
        futs = {ex.submit(map_block, its, asset, r0, c0, h, w, grid, ovr): (r0, c0, h, w) for r0, c0, h, w, its in jobs}
        done = 0
        for f in as_completed(futs):
            r0, c0, h, w = futs[f]
            o.write(f.result(), 1, window=Window(c0, r0, w, h))
            done += 1
            if done % 20 == 0:
                log.info("[%s] %s %d/%d blocks", aoi, name, done, len(jobs))
    os.replace(tmp, path)
    log.info("[%s] %s done in %.0fs", aoi, name, time.time() - t0)


def osm_farmland(aoi, grid, sgeom):
    path = f"{ROOT}/{aoi}/maps/osm_farmland.tif"
    if os.path.exists(path):
        return
    w, s, e, n = sg.shape(sgeom).bounds
    q = (f'[out:json][timeout:300];(way["landuse"~"^(farmland|farmyard|orchard|vineyard|greenhouse_horticulture)$"]'
         f'({s},{w},{n},{e});relation["landuse"~"^(farmland|farmyard|orchard|vineyard)$"]({s},{w},{n},{e}););out geom;')
    for attempt in range(5):
        r = subprocess.run(["curl", "-s", "-A", "hackathon-trend-detective", "--max-time", "360",
                            "--data-urlencode", f"data={q}", "https://overpass-api.de/api/interpreter"],
                           capture_output=True)
        try:
            data = json.loads(r.stdout); break
        except Exception:  # noqa
            log.warning("[%s] overpass retry %d", aoi, attempt); time.sleep(30 * (attempt + 1))
    else:
        raise RuntimeError("overpass failed")
    to_m = pyproj.Transformer.from_crs(4326, 3035, always_xy=True).transform
    polys = []
    for el in data["elements"]:
        rings = [el["geometry"]] if el["type"] == "way" else \
            [m["geometry"] for m in el.get("members", []) if m.get("role") == "outer" and "geometry" in m]
        for g in rings:
            if len(g) >= 4:
                p = sg.Polygon([(c["lon"], c["lat"]) for c in g])
                if p.is_valid:
                    polys.append(stransform(to_m, p))
    arr = rasterize([(p, 1) for p in polys], out_shape=(grid["H"], grid["W"]), transform=grid_transform(grid),
                    fill=0, dtype="uint8", all_touched=False) if polys else np.zeros((grid["H"], grid["W"]), np.uint8)
    prof = dict(GT_OPTS, height=grid["H"], width=grid["W"], crs=DST_CRS, transform=grid_transform(grid),
                count=1, dtype="uint8", nodata=None)
    with rasterio.open(path + ".tmp", "w", **prof) as o:
        o.write(arr, 1)
    os.replace(path + ".tmp", path)
    log.info("[%s] osm_farmland: %d polygons, %.1f%% of grid", aoi, len(polys), 100 * arr.mean())


def run(aoi):
    grid, sgeom = make_grid(aoi)
    os.makedirs(f"{ROOT}/{aoi}/maps", exist_ok=True)
    ovr = 0 if aoi == "ukraine" else None   # Ukraine: 20 m overview of the 10 m maps (still majority -> 60 m)
    wc = [d for d in search("esa-worldcover", sgeom) if d["properties"].get("esa_worldcover:product_version") == "2.0.0"]
    build_map(aoi, grid, sgeom, "worldcover2021", wc, "map", ovr)
    for y in ESRI_YEARS:
        its = search("io-lulc-annual-v02", sgeom, datetime=f"{y}-01-01/{y}-12-31")
        build_map(aoi, grid, sgeom, f"esri_{y}", its, "data", 0)  # Esri tiles are huge: 20 m overview
    if aoi != "ukraine":
        osm_farmland(aoi, grid, sgeom)
    open(f"{ROOT}/{aoi}/maps/DONE", "w").write(time.strftime("%F %T"))
    log.info("[%s] MAPS DONE", aoi)


if __name__ == "__main__":
    os.makedirs(f"{ROOT}/logs", exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(f"{ROOT}/logs/maps.log"), logging.StreamHandler()])
    aois = sys.argv[1:]
    for a in aois:
        run(a)
    if set(aois) >= {"kyiv", "kharkiv", "lviv"} or all(os.path.exists(f"{ROOT}/{c}/maps/DONE") for c in ("kyiv", "kharkiv", "lviv")):
        os.makedirs(f"{ROOT}/maps", exist_ok=True)
        open(f"{ROOT}/maps/DONE", "w").write(time.strftime("%F %T"))
