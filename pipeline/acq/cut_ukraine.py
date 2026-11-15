#!/usr/bin/env python3
"""Cut the first .tif found in <dir> to the Ukraine box (lon 21.5-41, lat 43.8-53, + margin) in its native CRS.
usage: cut_ukraine.py <dir-with-unzipped-tif> <out.tif>"""
import os, sys, glob
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

src_dir, out = sys.argv[1], sys.argv[2]
tif = sorted(glob.glob(f"{src_dir}/**/*.tif", recursive=True))[0]
with rasterio.open(tif) as s:
    b = transform_bounds("EPSG:4326", s.crs, 21.5, 43.8, 41.0, 53.0, densify_pts=101)
    win = from_bounds(*b, transform=s.transform).round_offsets().round_lengths()
    win = win.intersection(rasterio.windows.Window(0, 0, s.width, s.height))
    prof = s.profile.copy()
    prof.update(driver="GTiff", width=win.width, height=win.height, transform=s.window_transform(win),
                tiled=True, blockxsize=512, blockysize=512, compress="zstd", bigtiff="IF_SAFER")
    with rasterio.open(out + ".tmp.tif", "w", **prof) as o:
        for _, w in o.block_windows(1):
            o.write(s.read(window=rasterio.windows.Window(w.col_off + win.col_off, w.row_off + win.row_off,
                                                          w.width, w.height)), window=w)
os.replace(out + ".tmp.tif", out)
print("cut", tif, "->", out, win)
