"""POST /api/analyze core: validate → hash → cached report or science.analyze → store."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import threading
import time
from typing import Any

from uhd import __version__
from uhd.config import get_settings
from uhd.errors import APIError, bad_request
from uhd.services import reports, science
from uhd.services.geometry import check_area, geometry_hash, parse_geometry, to_geojson

log = logging.getLogger(__name__)
YEARS = (2013, 2025)
MIN_YEARS_FOR_VERDICT = 8
P_SIGNIFICANT = 0.05
_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def _lock_for(rid: str) -> threading.Lock:
    with _locks_guard:
        if len(_locks) > 1024:
            for k in [k for k, v in _locks.items() if not v.locked()]:
                del _locks[k]
        return _locks.setdefault(rid, threading.Lock())


_compute_sem: threading.BoundedSemaphore | None = None
COMPUTE_WAIT_S = 30.0


@contextlib.contextmanager
def _compute_slot():
    global _compute_sem
    if _compute_sem is None:
        _compute_sem = threading.BoundedSemaphore(max(1, get_settings().analyze_concurrency))
    if not _compute_sem.acquire(timeout=COMPUTE_WAIT_S):
        raise APIError(503, "busy", "Сервер зараз рахує інші території — спробуйте за хвилину.")
    try:
        yield
    finally:
        _compute_sem.release()


@contextlib.contextmanager
def _file_lock(rid: str):
    """Cross-process lock file ``{reports_dir}/.locks/{rid}.lock`` (flock; released by the kernel if a worker dies)."""
    import fcntl

    d = get_settings().reports_dir / ".locks"
    try:
        d.mkdir(parents=True, exist_ok=True)
        f = open(d / f"{rid}.lock", "a+")
    except OSError:  # read-only store etc.: fall back to the in-process lock only
        yield
        return
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(f, fcntl.LOCK_UN)
        finally:
            f.close()


def _trim_heap() -> None:
    """Give freed science arrays back to the OS (glibc keeps them in arenas otherwise — RB-01)."""
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


VERDICTS = ("significant", "not_significant", "insufficient_data")
REPORT_SCHEMA = "r2"  # stored reports are name-free (REVIEW M8); bump when the stored shape changes
GENERIC_NAME_UK = "Ця територія"


def decide_verdict(trend: dict | None) -> str:
    """Backend rule (PLAN.md): significant iff p < 0.05 and ≥ 8 valid years; insufficient_data if < 8 years."""
    if not trend:
        return "insufficient_data"
    n = trend.get("n_years") or 0
    p = trend.get("p")
    if n < MIN_YEARS_FOR_VERDICT or p is None or trend.get("slope_per_decade") is None:
        return "insufficient_data"
    return "significant" if p < P_SIGNIFICANT else "not_significant"


def parse_years(years: Any) -> tuple[int, int]:
    if years is None:
        return YEARS
    if not (isinstance(years, (list, tuple)) and len(years) == 2 and all(isinstance(y, int) for y in years)):
        raise bad_request("invalid_years", "years must be [from, to]")
    y0, y1 = years
    if not (YEARS[0] <= y0 <= y1 <= YEARS[1]):
        raise bad_request("invalid_years", f"years must lie within {YEARS[0]}–{YEARS[1]} and from ≤ to")
    return y0, y1


def report_id(geom_hash: str, years: tuple[int, int], data_version: str, method_version: str) -> str:
    key = f"{geom_hash}|{years[0]}-{years[1]}|{data_version}|{method_version}|{REPORT_SCHEMA}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _check_verdict(t: dict) -> None:
    """Science decides the verdict on the raw p (REVIEW M10); the backend never re-decides from the rounded p.
    It only fills a missing/invalid verdict and enforces the minimum number of years."""
    v = t.get("verdict")
    if v not in VERDICTS:
        t["verdict"] = decide_verdict(t)
    elif v != "insufficient_data" and (t.get("n_years") or 0) < MIN_YEARS_FOR_VERDICT:
        log.warning("verdict with too few years; forcing insufficient_data", extra={"verdict": v})
        t["verdict"] = "insufficient_data"


def _finalize(raw: dict, *, rid: str, geom, area: float, years, dv: str, mv: str) -> dict:
    rep = dict(raw)
    rep["report_id"] = rid
    zone = dict(rep.get("zone") or {})
    if zone.get("area_km2") is None:
        zone["area_km2"] = round(area, 3)
    zone["name"] = None
    rep["zone"] = zone
    for k in ("trend", "ref_trend", "ndvi_trend"):
        if isinstance(rep.get(k), dict):
            _check_verdict(rep[k])
    gg = rep.get("green_gap")
    if isinstance(gg, dict) and isinstance(gg.get("trend"), dict):
        _check_verdict(gg["trend"])
    rep.setdefault("caveats", [])
    rep["params"] = {"geometry": to_geojson(geom), "geometry_hash": geometry_hash(geom), "years": list(years),
                     "place_id": None, "data_version": dv, "method_version": mv, "api_version": __version__,
                     "schema": REPORT_SCHEMA}
    rep["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return rep


def label(rep: dict, name: str | None, place_id: str | None) -> dict:
    """Stored reports are name-free and shared by every request with the same geometry (REVIEW M8): the name, the
    place id and the name at the start of ``verdict_text_uk`` are applied per response and never stored."""
    out = {**rep, "zone": {**(rep.get("zone") or {}), "name": name or None},
           "params": {**(rep.get("params") or {}), "place_id": place_id or None}}
    txt = rep.get("verdict_text_uk")
    if isinstance(txt, str) and txt.startswith(GENERIC_NAME_UK):
        rest = txt[len(GENERIC_NAME_UK):]
        if name:
            out["verdict_text_uk"] = name + rest
        else:  # neutral sentence without a placeholder name: «Забудова влітку вдень …»
            rest = rest.lstrip(": ").lstrip()
            out["verdict_text_uk"] = rest[:1].upper() + rest[1:]
    return out


def stored_report(report_id: str, name: str | None = None) -> dict:
    """A stored report as every reader sees it (REST ``GET /api/reports/{id}`` and the agent's ``get_report``):
    the same labelling function, so the site and the chat never word one report differently (SCI-05)."""
    rep = reports.require(report_id)
    pid = (rep.get("params") or {}).get("place_id")
    return label(add_context(rep, pid), name, pid)


def add_context(rep: dict, place_id: str | None) -> dict:
    """Card context (frontend v2): ``hotspots`` (geometry-only → stored once with the report) and ``context`` (rank
    among the city's districts, CMIP6 at the centre — computed per response from cached tables)."""
    from uhd.services import context

    t0 = time.perf_counter()
    if rep.get("hotspots_version") != context.HOTSPOTS_VERSION:
        try:
            hs = context.hotspots(rep)
        except Exception:  # noqa: BLE001 — optional block, never fail the report
            log.exception("hotspots failed", extra={"report_id": rep.get("report_id")})
            hs = None
        try:
            zo = context.zone_outline(rep)
        except Exception:  # noqa: BLE001
            log.exception("zone outline failed", extra={"report_id": rep.get("report_id")})
            zo = None
        rep = {**rep, "hotspots": hs, "zone_outline": zo, "hotspots_version": context.HOTSPOTS_VERSION}
        if rep.get("report_id") and reports.get(rep["report_id"]) is not None:
            reports.put(rep)
    out = {**rep, "context": {"rank": context.rank(rep, place_id), "climate": context.climate(rep)}}
    dt = time.perf_counter() - t0
    if dt > 0.3:
        log.info("enrich slow", extra={"report_id": rep.get("report_id"), "ms": round(dt * 1000)})
    return out


def analyze(geometry: Any, years: Any = None, name: str | None = None, place_id: str | None = None,
            use_cache: bool = True, enrich: bool = True) -> dict:
    return _analyze(geometry, years, name, place_id, use_cache, enrich)


def _analyze(geometry: Any, years: Any, name: str | None, place_id: str | None, use_cache: bool,
             do_enrich: bool) -> dict:
    def fin(r: dict) -> dict:
        return label(add_context(r, place_id) if do_enrich else r, name, place_id)
    geom = parse_geometry(geometry)
    area = check_area(geom)
    yrs = parse_years(years)
    dv, mv = science.data_version(), science.method_version()
    rid = report_id(geometry_hash(geom), yrs, dv, mv)
    if use_cache and (hit := reports.get(rid)):
        return fin(hit)
    with _lock_for(rid), _file_lock(rid):  # one computation per report across threads *and* workers (RB-10)
        if use_cache and (hit := reports.get(rid)):
            return fin(hit)
        with _compute_slot():  # bounded cold computations per worker (RB-01)
            t0 = time.perf_counter()
            try:
                raw = science.analyze(to_geojson(geom), yrs, name=None)
            finally:
                _trim_heap()
            dt = time.perf_counter() - t0
        rep = _finalize(raw, rid=rid, geom=geom, area=area, years=yrs, dv=dv, mv=mv)
        rep["compute_s"] = round(dt, 3)
        reports.put(rep)
        log.info("analyze computed", extra={"report_id": rid, "area_km2": round(area, 2), "seconds": round(dt, 3)})
    return fin(rep)
