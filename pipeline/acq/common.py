"""Shared helpers for the data-acquisition jobs (pipeline/acq/*).

Every job writes under ACQ_ROOT (env UHD_ACQ_ROOT; VM: /root/landsat2, homelab: /tank0/uhd-data/landsat2),
never into /root/landsat. Grids are the SAME EPSG:3035 60 m grid as pipeline/ingest.py (the Ukraine grid
x0=5195100, y1=3534420, 21783 x 15227 px); city grids are aligned sub-windows of it.
"""
import os

os.environ.update({
    "GDAL_HTTP_MULTIPLEX": "YES", "GDAL_HTTP_VERSION": "2",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".TIF,.tif,.tiff",
    "GDAL_HTTP_MAX_RETRY": "5", "GDAL_HTTP_RETRY_DELAY": "3",
    "GDAL_HTTP_TIMEOUT": "120", "GDAL_HTTP_CONNECTTIMEOUT": "30", "GDAL_CACHEMAX": "256",
    "CPL_LOG": "/dev/null",
})

import json, math, time, shutil, logging, sys

ROOT = os.environ.get("UHD_ACQ_ROOT", "/root/landsat2")
MIN_FREE_GB = float(os.environ.get("UHD_MIN_FREE_GB", "35"))
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
UA = "uhd-data-acq/1.0 (hackathon research)"
DST_CRS = "EPSG:3035"
RES = 60.0
UKRAINE_GRID = dict(x0=5195100.0, y1=3534420.0, W=21783, H=15227)
GT_OPTS = dict(driver="GTiff", tiled=True, blockxsize=512, blockysize=512, compress="zstd",
               zstd_level=3, bigtiff="IF_SAFER")

# ~20 largest Ukrainian cities outside the three preset AOIs + the presets themselves (lon, lat of centre)
CITIES = {
    "kyiv": (30.523, 50.450), "kharkiv": (36.231, 49.993), "lviv": (24.031, 49.842),
    "odesa": (30.733, 46.482), "dnipro": (35.046, 48.465), "zaporizhzhia": (35.139, 47.838),
    "kryvyi_rih": (33.391, 47.910), "mykolaiv": (31.995, 46.975), "vinnytsia": (28.468, 49.233),
    "poltava": (34.551, 49.589), "chernihiv": (31.289, 51.494), "cherkasy": (32.059, 49.444),
    "sumy": (34.798, 50.907), "zhytomyr": (28.658, 50.254), "khmelnytskyi": (26.987, 49.422),
    "rivne": (26.251, 50.619), "ivano_frankivsk": (24.711, 48.922), "ternopil": (25.594, 49.553),
    "lutsk": (25.325, 50.747), "uzhhorod": (22.288, 48.621), "chernivtsi": (25.940, 48.292),
    "kropyvnytskyi": (32.262, 48.508), "kherson": (32.617, 46.636), "kremenchuk": (33.416, 49.065),
    "bila_tserkva": (30.112, 49.797), "mariupol": (37.543, 47.097), "donetsk": (37.803, 48.016),
    "luhansk": (39.307, 48.574), "sevastopol": (33.522, 44.616), "simferopol": (34.100, 44.952),
}

log = logging.getLogger("acq")


def setup_log(name):
    os.makedirs(f"{ROOT}/logs", exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(f"{ROOT}/logs/{name}.log"), logging.StreamHandler(sys.stdout)])
    logging.getLogger("rasterio").setLevel(logging.ERROR)
    return logging.getLogger(name)


def free_gb(path=None):
    return shutil.disk_usage(path or ROOT).free / 1e9


class DiskFull(RuntimeError):
    pass


def check_disk(path=None):
    """Raise DiskFull when free space is below MIN_FREE_GB or the watcher has set the STOP flag."""
    if os.path.exists(f"{ROOT}/STOP"):
        raise DiskFull("STOP flag set by watcher")
    f = free_gb(path)
    if f < MIN_FREE_GB:
        raise DiskFull(f"free {f:.1f} GB < {MIN_FREE_GB} GB")


def atomic_json(obj, path, **kw):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, **kw)
    os.replace(tmp, path)


def subgrid(lon, lat, half_km=25, base=UKRAINE_GRID):
    """Window of the Ukraine 60 m grid around a point (aligned: same origin and pixel size)."""
    import pyproj
    x, y = pyproj.Transformer.from_crs(4326, 3035, always_xy=True).transform(lon, lat)
    h = half_km * 1000
    c0 = max(0, math.floor((x - h - base["x0"]) / RES)); c1 = min(base["W"], math.ceil((x + h - base["x0"]) / RES))
    r0 = max(0, math.floor((base["y1"] - (y + h)) / RES)); r1 = min(base["H"], math.ceil((base["y1"] - (y - h)) / RES))
    return dict(x0=base["x0"] + c0 * RES, y1=base["y1"] - r0 * RES, W=c1 - c0, H=r1 - r0,
                parent_col_off=c0, parent_row_off=r0)


def grid_transform(grid, res=RES):
    from rasterio.transform import from_origin
    return from_origin(grid["x0"], grid["y1"], res, res)


def grid_bounds_ll(grid, res=RES):
    from rasterio.warp import transform_bounds
    return transform_bounds(DST_CRS, "EPSG:4326", grid["x0"], grid["y1"] - grid["H"] * res,
                            grid["x0"] + grid["W"] * res, grid["y1"], densify_pts=21)


def stac_search(collection, retries=6, **kw):
    import pystac_client
    for attempt in range(retries):
        try:
            cat = pystac_client.Client.open(STAC)
            return [i.to_dict() for i in cat.search(collections=[collection], **kw).items()]
        except Exception as e:  # noqa
            log.warning("search %s failed (%s), retry", collection, str(e)[:200])
            time.sleep(15 * (attempt + 1))
    raise RuntimeError(f"search {collection} failed")


def manifest_update(name, **kw):
    """ROOT/manifest.json: one entry per dataset (status, files, bytes, crs, notes)."""
    import fcntl
    path = f"{ROOT}/manifest.json"
    with open(path + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        m = {}
        if os.path.exists(path):
            try:
                m = json.load(open(path))
            except Exception:  # noqa
                pass
        m.setdefault(name, {}).update(kw, updated=time.strftime("%F %T"))
        atomic_json(m, path, indent=1, ensure_ascii=False)
