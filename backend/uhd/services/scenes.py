"""Landsat scenes over a zone: STAC item metadata + per-scene zone/reference LST when available."""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache

import numpy as np
from shapely.geometry import shape

from uhd.errors import bad_request, not_found
from uhd.services import rasters, science
from uhd.services.geometry import to_geojson
from uhd.services.num import rnd

log = logging.getLogger(__name__)
SCENE_RE = re.compile(r"^L[CO]0[89]_L2SP_(\d{3})(\d{3})_(\d{4})(\d{2})(\d{2})_\d{2}_T[12RT]$")
SUMMER = (6, 7, 8)


@lru_cache(maxsize=64)
def _items(aoi: str, year: int) -> list[dict]:
    p = rasters.root() / aoi / "items" / f"{year}.json"
    try:
        data = json.loads(p.read_text())
    except FileNotFoundError:
        return []
    feats = data.get("features", data) if isinstance(data, dict) else data
    out = []
    for f in feats:
        pr = f.get("properties", {})
        try:
            out.append({
                "id": f["id"], "date": pr["datetime"][:10], "datetime": pr["datetime"],
                "path": int(pr.get("landsat:wrs_path", 0)), "row": int(pr.get("landsat:wrs_row", 0)),
                "cloud_cover": pr.get("eo:cloud_cover"), "cloud_cover_land": pr.get("landsat:cloud_cover_land"),
                "sun_elevation": pr.get("view:sun_elevation"), "platform": pr.get("platform"),
                "_footprint": shape(f["geometry"]),
            })
        except (KeyError, ValueError, TypeError):
            continue
    out.sort(key=lambda x: x["datetime"])
    return out


def _scene_meta(aoi: str, year: int, sid: str) -> dict | None:
    p = rasters.root() / aoi / "scenes" / str(year) / f"{sid}.json"
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def parse_scene_id(sid: str) -> dict:
    m = SCENE_RE.match(sid)
    if not m:
        raise bad_request("invalid_scene_id", "expected a Landsat Collection 2 L2SP scene id")
    return {"path": int(m[1]), "row": int(m[2]), "year": int(m[3]), "date": f"{m[3]}-{m[4]}-{m[5]}"}


def _zone_lst_fallback(aoi: str, year: int, sid: str, geom) -> dict | None:
    p = rasters.root() / aoi / "scenes" / str(year) / f"{sid}.lst.tif"
    if not p.exists():
        return None
    r = rasters.read_zone(p, geom)
    if r is None:
        return None
    a, inside = r
    valid = inside & ~np.ma.getmaskarray(a)
    n_in = int(inside.sum())
    if not n_in:
        return None
    vals = a.data[valid].astype(np.float64) * rasters.LST_SCALE
    return {"zone_lst_all_px": rnd(np.median(vals), 2) if len(vals) else None,
            "valid_share": round(len(vals) / n_in, 3), "method": "median of all zone pixels (no built-up mask, no reference)"}


def _science_rows(geom, year: int) -> list[dict] | None:
    if not science.has_helper("list_scenes"):
        return None
    return science.helper("list_scenes", to_geojson(geom), year)


def scene_stats(scene_id: str, geom) -> dict:
    meta = parse_scene_id(scene_id)
    aoi = rasters.pick_aoi(geom)
    if aoi is None:
        raise bad_request("outside_coverage", "the area is outside the covered region")
    out = {"scene_id": scene_id, **meta, "aoi": aoi}
    item = next((x for x in _items(aoi, meta["year"]) if x["id"] == scene_id), None)
    if item:
        out.update({k: v for k, v in item.items() if not k.startswith("_")})
    rows = _science_rows(geom, meta["year"])
    if rows is not None:
        row = next((r for r in rows if scene_id in (r.get("ids") or [r.get("id")])), None)
        if row is None:
            same_date = [r for r in rows if r.get("date") == meta["date"]]
            row = same_date[0] if same_date else None
        if row is None:
            raise not_found("scene_not_found", f"scene {scene_id} is not a summer acquisition over this area")
        out.update(row)
        out["scene_id"] = scene_id
        out["source"] = "science"
        return out
    fb = _zone_lst_fallback(aoi, meta["year"], scene_id, geom)
    if fb is None and not item:
        raise not_found("scene_not_found", f"no data for scene {scene_id} over this area")
    out.update(fb or {"zone_lst_all_px": None, "note": "per-scene raster not kept on disk"})
    out["source"] = "fallback"
    return out


def _stac_rows(aoi: str, y: int, geom, summer_only: bool) -> list[dict]:
    out = []
    for it in _items(aoi, y):
        if summer_only and int(it["date"][5:7]) not in SUMMER:
            continue
        if not it["_footprint"].intersects(geom):
            continue
        sm = _scene_meta(aoi, y, it["id"])
        rec = {k: v for k, v in it.items() if not k.startswith("_")}
        rec.update(year=y, ids=[it["id"]], cloud=it["cloud_cover"], covers_zone_fully=it["_footprint"].contains(geom),
                   processed=sm is not None, used=None, zone_lst=None, ref_lst=None, gap=None)
        out.append(rec)
    return out


def _zone_weighted_ccl(its: list[dict], geom) -> float | None:
    rows = [(it["cloud_cover_land"], it["_footprint"].intersection(geom).area) for it in its
            if it.get("cloud_cover_land") is not None]
    if not rows:
        return None
    wsum = sum(w for _, w in rows)
    if wsum <= 0:  # no footprint overlaps the zone (should not happen): plain mean
        return rnd(sum(c for c, _ in rows) / len(rows), 2)
    return rnd(sum(c * w for c, w in rows) / wsum, 2)


def list_scenes(geom, year: int | None = None, summer_only: bool = True) -> dict:
    aoi = rasters.pick_aoi(geom)
    if aoi is None:
        raise bad_request("outside_coverage", "the area is outside the covered region")
    all_years = rasters.years(aoi) or list(range(2013, 2026))
    if year is not None and year not in all_years:
        raise bad_request("invalid_year", f"no data for {year}")
    ys = [year] if year else all_years
    out = []
    source = "stac"
    for y in ys:
        rows = _science_rows(geom, y) if summer_only else None
        if rows is None:
            out += _stac_rows(aoi, y, geom, summer_only)
            continue
        source = "science"
        items = {it["id"]: it for it in _items(aoi, y)}
        for r in rows:
            rec = {"year": y, **r}
            it = items.get(r.get("id")) or next((items[i] for i in r.get("ids") or [] if i in items), None)
            if it:
                rec.setdefault("datetime", it["datetime"])
                # same-date rows merged by science: like science's `cloud` (sci-v3.4), cloud_cover_land is weighted
                # by each row's overlap with the zone (a row that barely touches the zone barely counts)
                rec.setdefault("cloud_cover_land", _zone_weighted_ccl(
                    [items[i] for i in (r.get("ids") or [r.get("id")]) if i in items], geom))
                rec.setdefault("sun_elevation", it["sun_elevation"])
                rec.setdefault("covers_zone_fully", it["_footprint"].contains(geom))
            out.append(rec)
    return {"aoi": aoi, "year": year, "summer_only": summer_only, "source": source, "count": len(out), "scenes": out,
            "note": "Landsat 8 overpass ≈10:45–11:00 local mean solar time; dates are UTC acquisition dates. "
                    "used = the date entered the per-scene gap median."}
