"""DELTAHEAT science package — public API (see uhd/docs/METHOD.md §0).

Everything returns JSON-serialisable values except the *_raster helpers (numpy + affine + CRS string).
"""
from __future__ import annotations

import json
from functools import lru_cache

import numpy as np

from . import analysis as _A
from . import data as _D
from . import reference as _R
from . import scenes as _SC
from .climate import climate_projection
from .geometry import ScienceError, make_zone
from .rasters import classes_raster, gap_raster, layer_raster
from .stats import rnd
from .i18n_en import localize_report
from .report import DATA_VERSION, METHOD_VERSION, TILES_VERSION, analyze

YEARS = (_D.YEARS[0], _D.YEARS[-1])

__all__ = ["DATA_VERSION", "METHOD_VERSION", "TILES_VERSION", "YEARS", "ScienceError", "analyze", "cities", "classes_raster", "climate_projection",
           "gap_raster", "ghsl_built", "grid_info", "land_change", "layer_raster", "list_scenes", "localize_report", "reference_for",
           "zone_timeseries"]


def grid_info(aoi: str = "ukraine") -> dict:
    return _D.grid(aoi).info()


def cities() -> list[dict]:
    out = []
    for c in _D.CITY_AOIS:
        from .geometry import to_wgs84

        poly = to_wgs84(_D.aoi_polygon_3035(c))
        b = poly.bounds
        ctr = poly.representative_point()
        out.append(dict(id=c, name_uk=_D.CITY_NAMES_UK[c], bbox_wgs84=[round(v, 5) for v in b],
                        center=[round(ctr.x, 5), round(ctr.y, 5)]))
    return out


def reference_for(city_or_geometry, with_geometry: bool = True) -> dict:
    """Reference info for a preset city id ("kyiv") or for the place a geometry belongs to."""
    if isinstance(city_or_geometry, str):
        if city_or_geometry not in _D.CITY_AOIS:
            raise ScienceError("bad_geometry", f"Невідоме місто: {city_or_geometry}")
        return _preset_ref_info(city_or_geometry) if with_geometry else _R.preset(city_or_geometry).info()
    zone, city = make_zone(city_or_geometry)
    if city is not None:
        return _preset_ref_info(city) if with_geometry else _R.preset(city).info()
    return _R.derive_cached(zone).info(with_geometry=with_geometry)


@lru_cache(maxsize=3)
def _preset_ref_info(city: str) -> dict:
    return _R.preset(city).info(with_geometry=True)


def zone_timeseries(geometry: dict, years=None) -> list[dict]:
    return analyze(geometry, years)["series"]


def land_change(geometry: dict, years=None) -> dict:
    ctx = _A.build_context(geometry, years)
    out = _A.land_change(ctx)
    out["classes_source"] = {str(y): ("esri" if y in _D.ESRI_YEARS else "esri+landsat") for y in ctx.years}
    out["ghsl_built_surface_km2"] = ghsl_built(geometry)
    return out


@lru_cache(maxsize=16)
def _items(aoi: str, year: int) -> list[dict]:
    p = _D.RAW / aoi / "items" / f"{year}.json"
    if not p.exists():
        return []
    out = []
    for d in json.load(open(p)):
        pr = d["properties"]
        out.append(dict(id=d["id"], date=pr["datetime"][:10], path=int(pr.get("landsat:wrs_path", 0)),
                        row=int(pr.get("landsat:wrs_row", 0)), cloud=pr.get("eo:cloud_cover"), bbox=d.get("bbox")))
    return out


def _r(v, nd=2):
    return rnd(v, nd)


def list_scenes(geometry: dict, year: int) -> list[dict]:
    """Summer (Jun–Aug) Landsat 8 acquisitions over the zone for a year, with per-scene zone/reference LST
    where per-scene files exist (preset cities). ``used`` = the date entered the per-scene gap median."""
    year = int(year)
    ctx = _A.build_context(geometry)
    if year not in ctx.years:
        raise ScienceError("bad_geometry", f"Рік поза діапазоном {YEARS[0]}–{YEARS[1]}.")
    lon0, lat0, lon1, lat1 = ctx.zone.shape_ll.bounds
    rows = _A.scene_rows(ctx, year) if ctx.city else None
    if rows is not None:
        info = {d["date"]: d for d in _SC.dates(ctx.city, year)}
        out = []
        for r in rows:
            d = info[r["date"]]
            reason = _A.classify_pass(r)
            # cloud: scene cloud % weighted by each merged row's overlap with the zone (not the mean of the rows)
            cloud = _r(r["cloud_zone"], 1) if r.get("cloud_zone") is not None else d["cloud"]
            out.append(dict(id=d["ids"][0], ids=d["ids"], date=r["date"], path=d["path"], row=d["rows"][0],
                            rows=d["rows"], cloud=cloud, used=r["used"], reason=reason,
                            zone_in_swath=_r(r["zone_in_swath"], 3) if r.get("zone_in_swath") is not None else None,
                            zone_lst=_r(r["zone"]), ref_lst=_r(r["ref"]),
                            gap=_r(r["zone"] - r["ref"]) if r["ref"] is not None else None,
                            zone_valid_share=_r(r["zone_cover"], 3), ref_valid_px=r["ref_px"]))
        return out
    out = []
    for it in _items(ctx.zone.aoi if ctx.zone.aoi != "ukraine" else "ukraine", year):
        if it["date"][5:7] not in ("06", "07", "08"):
            continue
        b = it["bbox"]
        if b and (b[0] > lon1 or b[2] < lon0 or b[1] > lat1 or b[3] < lat0):
            continue
        out.append(dict(id=it["id"], ids=[it["id"]], date=it["date"], path=it["path"], row=it["row"],
                        rows=[it["row"]], cloud=it["cloud"], used=None, reason="no_per_scene_data",
                        zone_lst=None, ref_lst=None, gap=None, zone_valid_share=None, ref_valid_px=None))
    return sorted(out, key=lambda r: (r["date"], r["row"]))


GHSL_YEARS = (2015, 2020, 2025)


def ghsl_built(geometry: dict) -> dict:
    """GHSL GHS-BUILT-S built-up surface (km² of roofs/paved built surface, R2023A, 100 m) inside the zone for
    2015/2020/2025 — independent evidence of densification (Esri classes only say built / not built)."""
    import rasterio
    from rasterio.features import geometry_mask
    from rasterio.windows import from_bounds

    from .geometry import to_shape

    g = to_shape(geometry)
    from pyproj import Transformer
    import shapely

    t = Transformer.from_crs(4326, "ESRI:54009", always_xy=True)
    gm = shapely.transform(g, lambda xy: np.column_stack(t.transform(xy[:, 0], xy[:, 1])))
    out = {}
    for y in GHSL_YEARS:
        name = f"GHS_BUILT_S_E{y}_GLOBE_R2023A_54009_100"
        p = _D.RAW / "extra" / "ghsl" / name / f"{name}_V1_0.tif"
        if not p.exists():
            out[str(y)] = None
            continue
        with rasterio.open(p) as s:
            w = from_bounds(*gm.buffer(200).bounds, transform=s.transform).round_offsets().round_lengths()
            a = s.read(1, window=w, boundless=True, fill_value=0).astype(np.float64)
            a[a == s.nodata] = 0
            m = ~geometry_mask([shapely.geometry.mapping(gm)], a.shape, s.window_transform(w))
            out[str(y)] = round(float(a[m].sum()) / 1e6, 3)
    return out
