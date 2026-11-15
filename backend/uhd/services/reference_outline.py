"""Board item 20 D: a light outline of a report's reference forest for the map (GET /api/reports/{id}/reference).

Rebuilt from the stored report's geometry with the current science reference code (the same preset / derived
reference the report used), simplified from ~30 m up until the GeoJSON is under MAX_BYTES; cached on disk per
report id. Does not touch the stored report or its id.

sci-v3.6: when the report's ``reference.elevation_match.applied`` is true, the outline is the elevation-matched forest
(the context is rebuilt with the report's years, so the same built basis and band); older reports, and reports
without an applied match, keep the whole forest of the ring, as they were computed.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from uhd.config import get_settings
from uhd.services import reports, science

log = logging.getLogger(__name__)

SIMPLIFY_STEPS_M = (30, 60, 120, 240, 480)
MAX_BYTES = 100_000
COORD_DIGITS = 5          # ~1 m
SCHEMA = "ref1"
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _round(o: Any) -> Any:
    if isinstance(o, float):
        return round(o, COORD_DIGITS)
    if isinstance(o, (list, tuple)):
        return [_round(v) for v in o]
    return o


def _geometry(geom: dict) -> dict:
    return {"type": geom["type"], "coordinates": _round(geom["coordinates"])} if "coordinates" in geom else \
        {"type": geom["type"], "geometries": [_geometry(g) for g in geom.get("geometries", [])]}


def _matched(rep: dict) -> bool:
    em = (rep.get("reference") or {}).get("elevation_match")
    return bool(isinstance(em, dict) and em.get("applied"))


def _raw_outline(geometry: dict, simplify_m: float, rep: dict | None = None) -> dict:
    """GeoJSON geometry (WGS84) of the reference forest at this simplification, from the active science engine."""
    mod = science.module()
    fn = getattr(mod, "reference_outline", None)  # the fixture engine provides one; the real package does not
    if fn is not None:
        return fn(geometry, simplify_m=simplify_m)
    from uhd.science import analysis as A
    from uhd.science import reference as R

    if rep is not None and _matched(rep):
        ref = A.build_context(geometry, (rep.get("params") or {}).get("years")).ref
    else:
        zone, city = A.make_zone(geometry)
        ref = A.reference_for_zone(zone, city)
    return R.mask_to_geojson(ref.ref, ref.aoi, ref.win, simplify_m=simplify_m)


def build(rid: str, rep: dict) -> dict:
    geometry = rep["params"]["geometry"]
    r = rep.get("reference") or {}
    info = {k: r.get(k) for k in ("city", "kind", "ring_km", "area_km2")}
    info["elevation_matched"] = _matched(rep)
    feat = None
    for s in SIMPLIFY_STEPS_M:
        try:
            g = _raw_outline(geometry, s, rep)
        except Exception as e:  # noqa: BLE001 — mapped below
            mapped = science._map_error(e)
            if mapped is not None:
                raise mapped from e
            raise
        feat = {"type": "Feature", "properties": {
            "report_id": rid, "label_uk": "ліс-еталон", **info, "simplify_m": s,
            "report_method_version": rep.get("method_version"), "method_version": science.method_version(),
            "schema": SCHEMA}, "geometry": _geometry(g)}
        if len(json.dumps(feat, separators=(",", ":"))) < MAX_BYTES:
            break
    return feat


def get(rid: str) -> bytes:
    rep = reports.require(rid)  # 422 bad id / 404 unknown
    d = get_settings().cache_dir / "reference"
    p = d / f"{rid}.{SCHEMA}.json"
    try:
        return p.read_bytes()
    except FileNotFoundError:
        pass
    with _locks_guard:
        lock = _locks.setdefault(rid, threading.Lock())
    with lock:  # one build per id per worker
        try:
            return p.read_bytes()
        except FileNotFoundError:
            pass
        body = json.dumps(build(rid, rep), ensure_ascii=False, separators=(",", ":")).encode()
        try:
            d.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp%d" % threading.get_ident())
            tmp.write_bytes(body)
            tmp.replace(p)
        except OSError as e:
            log.warning("reference outline: cache not written", extra={"err": str(e)})
        return body
