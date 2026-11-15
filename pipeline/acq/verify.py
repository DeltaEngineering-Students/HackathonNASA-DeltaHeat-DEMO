#!/usr/bin/env python3
"""Verify what the acquisition jobs produced under UHD_ACQ_ROOT (sample-based, read-only) -> ROOT/VERIFY.json.

Checks: CRS, alignment with the Ukraine 60 m grid, value ranges, coverage, counts, sizes.
usage: UHD_ACQ_ROOT=... verify.py
"""
import os, sys, json, glob, random, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

import numpy as np


def du(path):
    tot = 0
    for dp, _, fs in os.walk(path):
        for f in fs:
            try:
                tot += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return tot


def aligned(T, res=C.RES):
    g = C.UKRAINE_GRID
    return abs(T.a - res) < 1e-6 and abs(((T.c - g["x0"]) / res) - round((T.c - g["x0"]) / res)) < 1e-6 \
        and abs(((g["y1"] - T.f) / res) - round((g["y1"] - T.f) / res)) < 1e-6


def v_landsat(aoi_dir):
    import rasterio
    out = {}
    for ydir in sorted(glob.glob(f"{aoi_dir}/scenes/*")):
        metas = glob.glob(f"{ydir}/*.json")
        metas = [m for m in metas if not m.endswith("FAILED.json")]
        lst = glob.glob(f"{ydir}/*.lst.tif")
        r = dict(metas=len(metas), lst_files=len(lst), done=os.path.exists(f"{ydir}/DONE"), bytes=du(ydir))
        if lst:
            f = random.choice(lst)
            with rasterio.open(f) as s:
                a = s.read(1)
                v = a[a != -32768] / 100
                m = json.load(open(f.replace(".lst.tif", ".json")))
                exp = (C.UKRAINE_GRID["x0"] + m["col_off"] * C.RES, C.UKRAINE_GRID["y1"] - m["row_off"] * C.RES)
                r["sample"] = dict(file=os.path.basename(f), crs=str(s.crs), aligned=aligned(s.transform),
                                   origin_matches_meta=bool(abs(s.transform.c - exp[0]) < 1e-6 and abs(s.transform.f - exp[1]) < 1e-6)
                                   if "parent_col_off" not in json.load(open(f"{aoi_dir}/grid.json")) else None,
                                   valid_px=int(v.size), lst_p5_p50_p95=[round(float(x), 1) for x in np.percentile(v, [5, 50, 95])] if v.size else None)
        out[os.path.basename(ydir)] = r
    return out


def v_modis(root):
    import rasterio
    out = {}
    for pdir in sorted(glob.glob(f"{root}/modis/*")):
        fs = sorted(glob.glob(f"{pdir}/*/*.tif"))
        r = dict(files=len(fs), years=sorted({os.path.basename(os.path.dirname(f)) for f in fs}), bytes=du(pdir))
        if fs:
            f = random.choice(fs)
            with rasterio.open(f) as s:
                a = s.read([1, 2])
                d, n = a[0][a[0] != -32768] / 100, a[1][a[1] != -32768] / 100
                r["sample"] = dict(file=f[len(root) + 1:], crs=str(s.crs), aligned=aligned(s.transform, 960.0),
                                   shape=[s.height, s.width], day_valid=int(d.size), night_valid=int(n.size),
                                   day_p50=round(float(np.median(d)), 1) if d.size else None,
                                   night_p50=round(float(np.median(n)), 1) if n.size else None)
        out[os.path.basename(pdir)] = r
    return out


def v_cmip6(root):
    out = {}
    for vdir in sorted(glob.glob(f"{root}/extra/cmip6/*")):
        fs = sorted(glob.glob(f"{vdir}/*.npz"))
        var = os.path.basename(vdir)
        r = dict(files=len(fs), models=sorted({os.path.basename(f).split("_")[0] for f in fs}), bytes=du(vdir))
        if fs:
            f = random.choice(fs)
            z = np.load(f)
            a = z[f"{var}_mjjas"] / 100
            r["sample"] = dict(file=os.path.basename(f), shape=list(a.shape), lat=[float(z["lat"].min()), float(z["lat"].max())],
                               lon=[float(z["lon"].min()), float(z["lon"].max())],
                               kyiv_jja_mean=round(float(z["jja_mean"][np.abs(z["lat"] - 50.45).argmin(), np.abs(z["lon"] - 30.52).argmin()]), 1))
        out[var] = r
    return out


def v_maps(root):
    import rasterio
    out = {}
    for f in sorted(glob.glob(f"{root}/ukraine/maps/*.tif")):
        with rasterio.open(f) as s:
            ov = s.read(1, out_shape=(s.height // 16, s.width // 16))
            nd = s.nodata
            valid = (ov != nd) if nd is not None else np.ones(ov.shape, bool)
            out[os.path.basename(f)] = dict(crs=str(s.crs), shape=[s.height, s.width], aligned=aligned(s.transform),
                                            grid_match=(s.width, s.height) == (C.UKRAINE_GRID["W"], C.UKRAINE_GRID["H"]),
                                            valid_share=round(float(valid.mean()), 3),
                                            p5_p50_p95=[float(x) for x in np.percentile(ov[valid], [5, 50, 95])] if valid.any() else None,
                                            bytes=os.path.getsize(f))
    return out


def v_files(root):
    out = {}
    for d in ("extra/osm", "extra/hansen", "extra/worldpop", "extra/ghsl", "extra/overture", "osm/districts", "weather/openmeteo"):
        p = f"{root}/{d}"
        if os.path.isdir(p):
            fs = [os.path.join(dp, f) for dp, _, ff in os.walk(p) for f in ff if not f.endswith((".tmp", ".tmp.tif"))]
            r = dict(files=len(fs), bytes=du(p))
            tifs = [f for f in fs if f.endswith(".tif")]
            if tifs:
                import rasterio
                f = random.choice(tifs)
                with rasterio.open(f) as s:
                    r["sample"] = dict(file=os.path.basename(f), crs=str(s.crs), shape=[s.height, s.width],
                                       bounds=[round(x, 3) for x in s.bounds])
            gj = [f for f in fs if f.endswith(".geojson") and not f.endswith("_all.geojson")]
            if gj:
                r["district_counts"] = {os.path.basename(f)[:-8]: sum(1 for x in json.load(open(f))["features"]
                                                                    if x["properties"].get("role") == "district") for f in gj}
            out[d] = r
    return out


def main():
    root = C.ROOT
    res = dict(checked=time.strftime("%F %T"), root=root, free_gb=round(C.free_gb(), 1))
    for name, fn in [("landsat", None), ("modis", v_modis), ("cmip6", v_cmip6), ("maps", v_maps), ("files", v_files)]:
        try:
            if name == "landsat":
                res[name] = {os.path.basename(a): v_landsat(a) for a in sorted(glob.glob(f"{root}/ukraine*"))
                             if os.path.isdir(f"{a}/scenes")}
            else:
                res[name] = fn(root)
        except Exception as e:  # noqa
            res[name] = dict(error=repr(e))
    C.atomic_json(res, f"{root}/VERIFY.json", indent=1, ensure_ascii=False)
    print(json.dumps(res, indent=1, ensure_ascii=False)[:6000])


if __name__ == "__main__":
    main()
