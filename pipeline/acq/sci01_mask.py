#!/usr/bin/env python3
"""SCI-01 mask: pixels with NO Landsat C2 L2 surface temperature in any summer (ASTER GED emissivity gap) but with
optical data, i.e. lst_n == 0 in all 13 /srv/landsat/ukraine/composites/*/lst_n.tif and ndvi_n > 0 in >= 1 year,
inside the Ukraine boundary (ROOT/aoi/Ukraine.geojson).

Output (ROOT/aoi/):
  sci01_mask.tif        uint8 on the Ukraine 60 m grid (1 = patch)
  sci01_clusters.json   clusters of patches (components dilated by 3 km): Ukraine-grid windows (+2 km margin),
                        pixel counts, km2, lon/lat bbox — the AOIs for sci01_radiance.py
usage: sci01_mask.py [composites_dir]
"""
import os, sys, glob, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

import numpy as np
import rasterio
from rasterio.windows import Window
from scipy import ndimage

SRC = sys.argv[1] if len(sys.argv) > 1 else "/srv/landsat/ukraine/composites"
years = sorted(glob.glob(f"{SRC}/*/lst_n.tif"))
assert len(years) == 13, years
G = C.UKRAINE_GRID
mask = np.zeros((G["H"], G["W"]), np.uint8)
B = 2048
for r0 in range(0, G["H"], B):
    h = min(B, G["H"] - r0)
    w = Window(0, r0, G["W"], h)
    nolst = np.ones((h, G["W"]), bool)
    anyndvi = np.zeros((h, G["W"]), bool)
    for f in years:
        with rasterio.open(f) as s:
            nolst &= s.read(1, window=w) == 0
        with rasterio.open(f.replace("lst_n.tif", "ndvi_n.tif")) as s:
            anyndvi |= s.read(1, window=w) > 0
    mask[r0:r0 + h] = nolst & anyndvi
# keep only pixels inside Ukraine (the grid includes a 20 km buffer + neighbours' corners)
import pyproj, shapely.geometry as sg
from shapely.ops import transform as stransform
from rasterio.features import rasterize
ua = sg.shape(json.load(open(f"{C.ROOT}/aoi/Ukraine.geojson"))["features"][0]["geometry"])
ua = stransform(pyproj.Transformer.from_crs(4326, 3035, always_xy=True).transform, ua)
inside = rasterize([(ua, 1)], out_shape=mask.shape, transform=C.grid_transform(G), fill=0, dtype="uint8")
print("km2 incl. buffer", round(float(mask.sum()) * 0.0036, 1))
mask &= inside
os.makedirs(f"{C.ROOT}/aoi", exist_ok=True)
prof = dict(C.GT_OPTS, height=G["H"], width=G["W"], count=1, dtype="uint8", nodata=None, crs=C.DST_CRS,
            transform=C.grid_transform(G))
with rasterio.open(f"{C.ROOT}/aoi/sci01_mask.tif", "w", **prof) as o:
    o.write(mask, 1)
# clusters: dilate by 3 km (50 px), label, window with 2 km margin; drop specks < 20 px (0.07 km2)
lab, n = ndimage.label(ndimage.binary_dilation(mask, iterations=50) if mask.any() else mask)
clusters = []
from rasterio.warp import transform_bounds
for k, sl in enumerate(ndimage.find_objects(lab), 1):
    px = int(mask[sl][lab[sl] == k].sum())
    if px < 20:
        continue
    m = 33
    r0, r1 = max(0, sl[0].start - m), min(G["H"], sl[0].stop + m)
    c0, c1 = max(0, sl[1].start - m), min(G["W"], sl[1].stop + m)
    x0, y1 = G["x0"] + c0 * C.RES, G["y1"] - r0 * C.RES
    g = dict(x0=x0, y1=y1, W=c1 - c0, H=r1 - r0, parent_col_off=c0, parent_row_off=r0)
    ll = transform_bounds(C.DST_CRS, "EPSG:4326", x0, y1 - g["H"] * C.RES, x0 + g["W"] * C.RES, y1)
    clusters.append(dict(id=f"c{len(clusters):02d}", grid=g, patch_px=px, patch_km2=round(px * 0.0036, 1),
                         bbox_ll=[round(v, 4) for v in ll]))
clusters.sort(key=lambda c: -c["patch_px"])
for i, c in enumerate(clusters):
    c["id"] = f"c{i:02d}"
C.atomic_json(dict(source=SRC, total_px=int(mask.sum()), total_km2=round(float(mask.sum()) * 0.0036, 1),
                   clusters=clusters), f"{C.ROOT}/aoi/sci01_clusters.json", indent=1)
print("total km2", round(float(mask.sum()) * 0.0036, 1), "clusters", len(clusters))
for c in clusters[:15]:
    print(c["id"], c["patch_km2"], c["grid"]["W"], c["grid"]["H"], c["bbox_ll"])
