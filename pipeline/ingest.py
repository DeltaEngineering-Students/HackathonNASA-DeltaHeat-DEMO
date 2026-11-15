#!/usr/bin/env python3
"""Landsat 8 (Collection 2 Level 2) ingest for Urban Heat Detective.

For each AOI (demo city or all of Ukraine) and each year 2013-2025:
  1. search L8 scenes Apr-Oct, cloud < 70 % (Microsoft Planetary Computer STAC, no auth)
  2. per scene: read only the needed bands from the 60 m COG overview, mask clouds,
     compute indices, reproject onto a common EPSG:3035 60 m grid (aligned for all AOIs)
       summer (Jun-Aug): LST degC, NDVI, NDBI, MNDWI   (lwir11, qa_pixel, red, nir08, swir16, green)
       Apr-May, Sep-Oct: NDVI only                      (qa_pixel, red, nir08)
  3. per year composite (per pixel, same-date scenes merged first):
       lst_med, lst_n, ndvi_med, ndbi_med, mndwi_med (summer)  ndvi_max, ndvi_n (Apr-Oct)

Resumable: every scene / year writes an atomic "done" artifact, reruns skip them.
Usage:  ingest.py kyiv kharkiv lviv ukraine
"""
import os

os.environ.update({
    "GDAL_HTTP_MULTIPLEX": "YES", "GDAL_HTTP_VERSION": "2",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".TIF,.tif",
    "GDAL_HTTP_MAX_RETRY": "5", "GDAL_HTTP_RETRY_DELAY": "3",
    "GDAL_HTTP_TIMEOUT": "120", "GDAL_HTTP_CONNECTTIMEOUT": "30", "GDAL_CACHEMAX": "256",
    "CPL_LOG": "/dev/null",
})

import json, sys, time, math, shutil, logging, threading, warnings, traceback
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed

import numpy as np
import pyproj
import pystac
import pystac_client
import planetary_computer as pc
import rasterio
import shapely.geometry as sg
from shapely.ops import transform as stransform
from rasterio.transform import from_origin
from rasterio.warp import reproject, transform_bounds, Resampling
from rasterio.windows import Window
from rasterio.windows import transform as win_transform

ROOT = "/root/landsat"
DST_CRS = "EPSG:3035"
RES = 60.0
YEARS = list(range(2013, 2026))
SUMMER = (6, 7, 8)
CLOUD_MAX = 70
BUFFER_M = 20_000
N_DL = 12          # download/reproject processes (~1 GB RAM each at whole-scene reads)
N_COMP = 5         # composite processes (~1.5 GB RAM each)
BLOCK = 1024
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"

LST_ND, IDX_ND = -32768, -128
LAYERS = {  # name: (dtype, nodata)
    "lst_med": ("int16", LST_ND), "lst_n": ("uint8", 0),
    "ndvi_med": ("int8", IDX_ND), "ndbi_med": ("int8", IDX_ND), "mndwi_med": ("int8", IDX_ND),
    "ndvi_max": ("int8", IDX_ND), "ndvi_n": ("uint8", 0),
}
GT_OPTS = dict(driver="GTiff", tiled=True, blockxsize=512, blockysize=512, compress="zstd",
               zstd_level=1, bigtiff="IF_SAFER")

log = logging.getLogger("ingest")


# ---------------------------------------------------------------- AOI / grid
def make_grid(aoi):
    gj = json.load(open(f"{ROOT}/aoi/{'Ukraine' if aoi == 'ukraine' else aoi}.geojson"))
    geom = sg.shape(gj["features"][0]["geometry"])
    to_m = pyproj.Transformer.from_crs(4326, 3035, always_xy=True).transform
    to_ll = pyproj.Transformer.from_crs(3035, 4326, always_xy=True).transform
    g = stransform(to_m, geom).buffer(BUFFER_M)
    if aoi == "ukraine":
        g = g.simplify(2000)
    xmin, ymin, xmax, ymax = g.bounds
    xmin, ymin = math.floor(xmin / RES) * RES, math.floor(ymin / RES) * RES
    xmax, ymax = math.ceil(xmax / RES) * RES, math.ceil(ymax / RES) * RES
    grid = dict(x0=xmin, y1=ymax, W=int(round((xmax - xmin) / RES)), H=int(round((ymax - ymin) / RES)))
    search_geom = sg.mapping(stransform(to_ll, g).simplify(0.01))
    return grid, search_geom


def grid_transform(grid):
    return from_origin(grid["x0"], grid["y1"], RES, RES)


# ---------------------------------------------------------------- search
def search_year(aoi, year, search_geom):
    path = f"{ROOT}/{aoi}/items/{year}.json"
    if os.path.exists(path):
        return json.load(open(path))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for attempt in range(5):
        try:
            cat = pystac_client.Client.open(STAC)
            items = list(cat.search(
                collections=["landsat-c2-l2"], intersects=search_geom,
                datetime=f"{year}-04-01/{year}-10-31",
                query={"platform": {"in": ["landsat-8"]}, "eo:cloud_cover": {"lt": CLOUD_MAX}},
            ).items())
            break
        except Exception as e:  # noqa
            log.warning("search %s %s failed (%s), retry", aoi, year, e)
            time.sleep(10 * (attempt + 1))
    else:
        raise RuntimeError(f"search failed {aoi} {year}")
    ds = [i.to_dict() for i in items]
    tmp = path + ".tmp"
    json.dump(ds, open(tmp, "w"))
    os.replace(tmp, path)
    return ds


# ---------------------------------------------------------------- per scene
def _read_bands(d, bands, dst_bounds):
    item = pystac.Item.from_dict(d)
    pc.sign_inplace(item)
    with rasterio.open(item.assets["qa_pixel"].href, overview_level=0) as s:
        crs, T, W, H = s.crs, s.transform, s.width, s.height
    sb = transform_bounds(DST_CRS, crs, *dst_bounds, densify_pts=21)
    pad = 2 * abs(T.a)
    c0 = max(0, math.floor((sb[0] - pad - T.c) / T.a))
    c1 = min(W, math.ceil((sb[2] + pad - T.c) / T.a))
    r0 = max(0, math.floor((T.f - (sb[3] + pad)) / -T.e))
    r1 = min(H, math.ceil((T.f - (sb[1] - pad)) / -T.e))
    if c1 <= c0 or r1 <= r0:
        return None, None, None
    win = Window(c0, r0, c1 - c0, r1 - r0)

    def rd(b):
        with rasterio.open(item.assets[b].href, overview_level=0) as s:
            assert (s.width, s.height) == (W, H), f"{b} grid mismatch"
            return b, s.read(1, window=win)

    with ThreadPoolExecutor(len(bands)) as ex:
        arrs = dict(ex.map(rd, bands))
    return arrs, crs, win_transform(win, T)


def process_scene(d, sdir, grid):
    sid = d["id"]
    meta_path = f"{sdir}/{sid}.json"
    if os.path.exists(meta_path):
        return json.load(open(meta_path))
    date = d["properties"]["datetime"][:10]
    summer = int(date[5:7]) in SUMMER
    meta = dict(id=sid, date=date, summer=summer, n_clear=0)

    # destination window on the common grid (scene bbox ∩ AOI grid)
    gT = grid_transform(grid)
    bx = transform_bounds("EPSG:4326", DST_CRS, *d["bbox"], densify_pts=21)
    c0 = max(0, math.floor((bx[0] - grid["x0"]) / RES)); c1 = min(grid["W"], math.ceil((bx[2] - grid["x0"]) / RES))
    r0 = max(0, math.floor((grid["y1"] - bx[3]) / RES)); r1 = min(grid["H"], math.ceil((grid["y1"] - bx[1]) / RES))
    if c1 <= c0 or r1 <= r0:
        json.dump(meta, open(meta_path, "w")); return meta
    dwin = Window(c0, r0, c1 - c0, r1 - r0)
    dT = win_transform(dwin, gT)
    dst_bounds = rasterio.windows.bounds(dwin, gT)

    bands = ["qa_pixel", "red", "nir08"] + (["lwir11", "swir16", "green"] if summer else [])
    err = None
    for attempt in range(5):
        try:
            arrs, scrs, sT = _read_bands(d, bands, dst_bounds)
            break
        except Exception as e:  # noqa
            err = e
            time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError(f"{sid}: read failed: {err!r}")
    if arrs is None:
        json.dump(meta, open(meta_path, "w")); return meta

    qa = arrs["qa_pixel"]
    # bit0 fill, bit1 dilated cloud, bit2 cirrus, bit3 cloud, bit4 shadow, bit5 snow, bit6 clear
    clear = ((qa & (1 << 6)) > 0) & ((qa & 0b111111) == 0)

    def refl(a):
        r = a.astype(np.float32) * 2.75e-5 - 0.2
        r[a == 0] = np.nan
        return r

    def nd(a, b):
        with np.errstate(divide="ignore", invalid="ignore"):
            v = (a - b) / (a + b)
        ok = clear & np.isfinite(v)
        out = np.full(v.shape, IDX_ND, np.int8)
        out[ok] = np.clip(np.round(v[ok] * 100), -100, 100).astype(np.int8)
        return out

    red, nir = refl(arrs["red"]), refl(arrs["nir08"])
    idx = [nd(nir, red)]
    lst = None
    if summer:
        sw, gr = refl(arrs["swir16"]), refl(arrs["green"])
        idx += [nd(sw, nir), nd(gr, sw)]
        t = arrs["lwir11"]
        ok = clear & (t > 0)
        lst = np.full(t.shape, LST_ND, np.int16)
        lst[ok] = np.round((t[ok].astype(np.float32) * 0.00341802 + 149.0 - 273.15) * 100).astype(np.int16)

    def warp(a, nodata):
        out = np.full((dwin.height, dwin.width), nodata, a.dtype)
        reproject(a, out, src_transform=sT, src_crs=scrs, src_nodata=nodata, dst_transform=dT,
                  dst_crs=DST_CRS, dst_nodata=nodata, resampling=Resampling.nearest, num_threads=1)
        return out

    widx = [warp(a, IDX_ND) for a in idx]
    n_clear = int((widx[0] != IDX_ND).sum())
    meta.update(row_off=r0, col_off=c0, h=dwin.height, w=dwin.width, n_clear=n_clear)
    if n_clear:
        prof = dict(GT_OPTS, height=dwin.height, width=dwin.width, crs=DST_CRS, transform=dT)
        tmp = f"{sdir}/{sid}.idx.tif.tmp"
        with rasterio.open(tmp, "w", count=len(widx), dtype="int8", nodata=IDX_ND, **prof) as o:
            for i, a in enumerate(widx, 1):
                o.write(a, i)
        os.replace(tmp, f"{sdir}/{sid}.idx.tif")
        if summer:
            tmp = f"{sdir}/{sid}.lst.tif.tmp"
            with rasterio.open(tmp, "w", count=1, dtype="int16", nodata=LST_ND, **prof) as o:
                o.write(warp(lst, LST_ND), 1)
            os.replace(tmp, f"{sdir}/{sid}.lst.tif")
    tmp = meta_path + ".tmp"
    json.dump(meta, open(tmp, "w"))
    os.replace(tmp, meta_path)
    return meta


# ---------------------------------------------------------------- download stage
def write_status(aoi, **kw):
    path = f"{ROOT}/{aoi}/status.json"
    st = json.load(open(path)) if os.path.exists(path) else {}
    st.update(kw, updated=time.strftime("%Y-%m-%d %H:%M:%S"))
    tmp = path + ".tmp"
    json.dump(st, open(tmp, "w"), indent=1)
    os.replace(tmp, path)


def download_year(aoi, year, items, grid):
    sdir = f"{ROOT}/{aoi}/scenes/{year}"
    os.makedirs(sdir, exist_ok=True)
    todo = [d for d in items if not os.path.exists(f"{sdir}/{d['id']}.json")]
    total, t0 = len(items), time.time()
    log.info("[%s %d] scenes: %d total, %d to fetch", aoi, year, total, len(todo))
    failed = []
    for attempt in range(4):
        failed, done = [], 0
        ctx = mp.get_context("spawn")
        # fresh pool per batch: workers leak memory (~2 GB each after ~100 scenes); recycling via
        # max_tasks_per_child deadlocks on CPython 3.12, so we recycle by recreating the pool
        batch = N_DL * 6
        for b0 in range(0, len(todo), batch):
            with ProcessPoolExecutor(N_DL, mp_context=ctx) as ex:
                futs = {ex.submit(process_scene, d, sdir, grid): d for d in todo[b0:b0 + batch]}
                for f in as_completed(futs):
                    d = futs[f]
                    try:
                        f.result()
                    except Exception as e:  # noqa
                        failed.append(d)
                        log.warning("[%s %d] scene %s failed: %s", aoi, year, d["id"], str(e)[:300])
                    done += 1
                    if done % 25 == 0 or done == len(todo):
                        el = time.time() - t0
                        write_status(aoi, year=year, scenes_done=total - len(todo) + done, scenes_total=total,
                                     failed=len(failed), sec_per_scene=round(el / max(done, 1), 2))
                        log.info("[%s %d] %d/%d  failed=%d  %.2fs/scene", aoi, year, done, len(todo),
                                 len(failed), el / max(done, 1))
        if not failed:
            break
        log.warning("[%s %d] retry pass %d for %d failed scenes", aoi, year, attempt + 1, len(failed))
        todo = failed
        time.sleep(60)
    return failed


# ---------------------------------------------------------------- composite stage
def comp_block(sdir, metas, r0, c0, h, w):
    warnings.simplefilter("ignore")
    by_date = {}  # date -> dict(layer -> float32 array)
    for m in metas:
        rr0, rr1 = max(r0, m["row_off"]), min(r0 + h, m["row_off"] + m["h"])
        cc0, cc1 = max(c0, m["col_off"]), min(c0 + w, m["col_off"] + m["w"])
        if rr1 <= rr0 or cc1 <= cc0:
            continue
        win = Window(cc0 - m["col_off"], rr0 - m["row_off"], cc1 - cc0, rr1 - rr0)
        sl = (slice(rr0 - r0, rr1 - r0), slice(cc0 - c0, cc1 - c0))
        layers = {}
        with rasterio.open(f"{sdir}/{m['id']}.idx.tif") as s:
            a = s.read(window=win)
        names = ["ndvi", "ndbi", "mndwi"] if m["summer"] else ["ndvi"]
        for i, n in enumerate(names):
            layers[n] = np.where(a[i] == IDX_ND, np.nan, a[i].astype(np.float32))
        if m["summer"]:
            with rasterio.open(f"{sdir}/{m['id']}.lst.tif") as s:
                t = s.read(1, window=win)
            layers["lst"] = np.where(t == LST_ND, np.nan, t.astype(np.float32) / 100)
        key = (m["date"], m["summer"])
        slot = by_date.setdefault(key, {})
        for n, v in layers.items():
            cur = slot.get(n)
            if cur is None:
                cur = slot[n] = np.full((h, w), np.nan, np.float32)
            sub = cur[sl]
            fill = np.isnan(sub)
            sub[fill] = v[fill]  # same-date overlap of adjacent rows: keep first valid
    if not by_date:
        return None

    def stack(name, summer_only):
        ls = [s[name] for (dt, su), s in by_date.items() if name in s and (su or not summer_only)]
        return np.stack(ls) if ls else None

    out = {}
    def put_idx(name, arr):
        o = np.full((h, w), IDX_ND, np.int8)
        ok = np.isfinite(arr)
        o[ok] = np.round(arr[ok]).astype(np.int8)
        out[name] = o

    S = stack("lst", True)
    if S is not None:
        med = np.nanmedian(S, axis=0)
        o = np.full((h, w), LST_ND, np.int16); ok = np.isfinite(med)
        o[ok] = np.round(med[ok] * 100).astype(np.int16)
        out["lst_med"] = o
        out["lst_n"] = np.minimum(np.isfinite(S).sum(0), 255).astype(np.uint8)
        for n in ("ndvi", "ndbi", "mndwi"):
            put_idx(f"{n}_med", np.nanmedian(stack(n, True) if n == "ndvi" else stack(n, True), axis=0))
    A = stack("ndvi", False)
    if A is not None:
        put_idx("ndvi_max", np.nanmax(A, axis=0))
        out["ndvi_n"] = np.minimum(np.isfinite(A).sum(0), 255).astype(np.uint8)
    return out


def composite_year(aoi, year, grid):
    sdir = f"{ROOT}/{aoi}/scenes/{year}"
    cdir = f"{ROOT}/{aoi}/composites/{year}"
    if os.path.exists(cdir):
        return
    t0 = time.time()
    metas = [json.load(open(f"{sdir}/{f}")) for f in os.listdir(sdir) if f.endswith(".json")]
    metas = [m for m in metas if m["n_clear"] > 0]
    tmpdir = cdir + ".tmp"
    shutil.rmtree(tmpdir, ignore_errors=True)
    os.makedirs(tmpdir)
    prof = dict(GT_OPTS, height=grid["H"], width=grid["W"], crs=DST_CRS, transform=grid_transform(grid), count=1)
    outs = {n: rasterio.open(f"{tmpdir}/{n}.tif", "w", dtype=dt, nodata=nd, **prof) for n, (dt, nd) in LAYERS.items()}
    jobs = []
    for r0 in range(0, grid["H"], BLOCK):
        for c0 in range(0, grid["W"], BLOCK):
            h, w = min(BLOCK, grid["H"] - r0), min(BLOCK, grid["W"] - c0)
            ms = [m for m in metas if m["row_off"] < r0 + h and m["row_off"] + m["h"] > r0
                  and m["col_off"] < c0 + w and m["col_off"] + m["w"] > c0]
            if ms:
                jobs.append((r0, c0, h, w, ms))
    log.info("[%s %d] composite: %d scenes with data, %d blocks", aoi, year, len(metas), len(jobs))
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(N_COMP, mp_context=ctx) as ex:
        futs = {ex.submit(comp_block, sdir, ms, r0, c0, h, w): (r0, c0, h, w) for r0, c0, h, w, ms in jobs}
        nb = 0
        for f in as_completed(futs):
            r0, c0, h, w = futs[f]
            res = f.result()
            nb += 1
            if nb % 25 == 0:
                log.info("[%s %d] composite %d/%d blocks", aoi, year, nb, len(jobs))
            if res:
                for n, a in res.items():
                    outs[n].write(a, 1, window=Window(c0, r0, w, h))
    for o in outs.values():
        o.close()
    json.dump(dict(year=year, scenes=len(metas), grid=grid, crs=DST_CRS, res=RES,
                   seconds=round(time.time() - t0)), open(f"{tmpdir}/info.json", "w"))
    os.replace(tmpdir, cdir)
    log.info("[%s %d] composite done in %.0fs", aoi, year, time.time() - t0)
    # disk guard: drop per-scene files of finished years when space gets low
    if shutil.disk_usage(ROOT).free < 30e9:
        log.warning("[%s %d] low disk, removing per-scene files", aoi, year)
        shutil.rmtree(sdir, ignore_errors=True)


# ---------------------------------------------------------------- main
def run_aoi(aoi):
    grid, sgeom = make_grid(aoi)
    log.info("[%s] grid %dx%d px (%.0fx%.0f km)", aoi, grid["W"], grid["H"], grid["W"] * RES / 1e3, grid["H"] * RES / 1e3)
    comp_err = []

    def comp_safe(y):
        try:
            composite_year(aoi, y, grid)
        except Exception:  # noqa
            comp_err.append(y)
            log.error("[%s %d] composite failed\n%s", aoi, y, traceback.format_exc())

    th = None
    for y in YEARS:
        if os.path.exists(f"{ROOT}/{aoi}/composites/{y}"):
            log.info("[%s %d] already composited, skip", aoi, y)
            continue
        items = search_year(aoi, y, sgeom)
        failed = download_year(aoi, y, items, grid)
        if failed:
            log.error("[%s %d] %d scenes still failing after retries: %s", aoi, y, len(failed),
                      [d["id"] for d in failed][:20])
            write_status(aoi, **{f"failed_{y}": [d["id"] for d in failed]})
        if th:
            th.join()
        th = threading.Thread(target=comp_safe, args=(y,))
        th.start()
        write_status(aoi, years_downloaded=y)
    if th:
        th.join()
    missing = [y for y in YEARS if not os.path.exists(f"{ROOT}/{aoi}/composites/{y}")]
    write_status(aoi, finished=not missing, missing_years=missing)
    if missing:
        raise RuntimeError(f"{aoi}: composites missing for {missing}")
    log.info("[%s] ALL DONE", aoi)


def main():
    os.makedirs(f"{ROOT}/logs", exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(f"{ROOT}/logs/ingest.log"), logging.StreamHandler()])
    logging.getLogger("rasterio").setLevel(logging.ERROR)
    aois = sys.argv[1:] or ["kyiv", "kharkiv", "lviv", "ukraine"]
    years = os.environ.get("INGEST_YEARS")
    if years:
        global YEARS
        YEARS = [int(y) for y in years.split(",")]
    for aoi in aois:
        run_aoi(aoi)
    log.info("INGEST FINISHED: %s", aois)


if __name__ == "__main__":
    main()
