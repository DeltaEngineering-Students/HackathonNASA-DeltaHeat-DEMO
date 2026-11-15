#!/usr/bin/env python3
"""Post-crash integrity check of everything under UHD_ACQ_ROOT (read-only unless --fix).

  .tif   open + read the LAST block of every band (a truncated / zero-filled tail fails), first block too
  .npz   load every array (zip CRC)          .json / .geojson   parse          .parquet  read footer
  leftovers: *.tmp, *.tmp.tif, *.tmp.npz older than the last boot, *.parts directories (in-flight at the crash)
  Only files last modified before the last boot (+60 s) are checked: safe to run while jobs are writing.
--fix: delete bad files; for a bad Landsat/SCI-01 scene raster also delete its <scene>.json and the year's DONE,
       so the resumable jobs re-fetch it; delete leftovers except *.parts (pget resumes them).
Writes ROOT/INTEGRITY.json.  usage: integrity.py [--fix] [subdir ...]
"""
import os, sys, json, glob, time, zipfile
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

import numpy as np


def check(path):
    try:
        if path.endswith(".tif"):
            import rasterio
            from rasterio.windows import Window
            with rasterio.open(path) as s:
                bw, bh = s.block_shapes[0][1], s.block_shapes[0][0]
                last = Window(((s.width - 1) // bw) * bw, ((s.height - 1) // bh) * bh,
                              s.width - ((s.width - 1) // bw) * bw, s.height - ((s.height - 1) // bh) * bh)
                s.read(window=last)
                s.read(window=Window(0, 0, min(bw, s.width), min(bh, s.height)))
        elif path.endswith(".npz"):
            with zipfile.ZipFile(path) as z:
                bad = z.testzip()
                if bad:
                    raise RuntimeError(f"crc {bad}")
            z = np.load(path)
            for k in z.files:
                z[k]
        elif path.endswith((".json", ".geojson")):
            with open(path) as f:
                json.load(f)
        elif path.endswith(".parquet"):
            import pyarrow.parquet as pq
            pq.ParquetFile(path).metadata
        else:
            return None
        if os.path.getsize(path) == 0:
            raise RuntimeError("empty")
        return None
    except Exception as e:  # noqa
        return f"{type(e).__name__}: {str(e)[:150]}"


def main():
    fix = "--fix" in sys.argv
    boot = time.time() - float(open("/proc/uptime").read().split()[0])   # only pre-boot leftovers are crash debris
    subs = [a for a in sys.argv[1:] if not a.startswith("--")] or [""]
    root = C.ROOT
    files, leftovers = [], []
    for sub in subs:
        for dp, dns, fns in os.walk(os.path.join(root, sub)):
            if "/code" in dp[len(root):] or "/logs" in dp[len(root):] or dp.endswith(".parts"):
                if dp.endswith(".parts"):
                    leftovers.append(dp)
                continue
            for d in dns:
                if d.endswith(".parts"):
                    leftovers.append(os.path.join(dp, d))
            for f in fns:
                p = os.path.join(dp, f)
                if f.endswith((".tmp", ".tmp.tif", ".tmp.npz")):
                    if os.path.getmtime(p) < boot:
                        leftovers.append(p)
                elif f.endswith((".tif", ".npz", ".json", ".geojson", ".parquet")) and f not in ("manifest.json",) \
                        and os.path.getmtime(p) < boot + 60:      # files written after the reboot are not crash suspects
                    files.append(p)
    t0 = time.time()
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(check, files))
    bad = {p[len(root) + 1:]: r for p, r in zip(files, res) if r}
    fixed = []
    if fix:
        for rel in bad:
            p = os.path.join(root, rel)
            os.remove(p); fixed.append(rel)
            if "/scenes/" in p and p.endswith(".tif"):
                sid = os.path.basename(p).split(".")[0]
                for m in (os.path.join(os.path.dirname(p), sid + ".json"), os.path.join(os.path.dirname(p), "DONE")):
                    if os.path.exists(m):
                        os.remove(m); fixed.append(m[len(root) + 1:])
        for p in leftovers:
            if not p.endswith(".parts") and os.path.exists(p):
                os.remove(p); fixed.append(p[len(root) + 1:])
    by_kind = {}
    for p in files:
        k = os.path.relpath(p, root).split("/")[0]
        by_kind[k] = by_kind.get(k, 0) + 1
    out = dict(checked=time.strftime("%F %T"), root=root, files=len(files), by_top_dir=by_kind, bad=bad,
               leftovers=[p[len(root) + 1:] for p in leftovers], fixed=fixed, seconds=round(time.time() - t0))
    C.atomic_json(out, f"{root}/INTEGRITY.json", indent=1)
    print(json.dumps(dict(out, bad=dict(list(bad.items())[:30]), leftovers=out["leftovers"][:30]), indent=1))


if __name__ == "__main__":
    main()
