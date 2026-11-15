"""API contract v1 (see uhd/docs/API.md)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from uhd import __version__
from uhd.config import get_settings
from uhd.errors import APIError, bad_request
from uhd.services import analysis, climate, meta, overview, places, rasters, reports, scenes, science, weather
from uhd.services.geometry import geometry_hash, parse_geometry

router = APIRouter(prefix="/api")
# item 32: ?lang=en ADDS *_en siblings (I18N.md §6); missing / uk → the unchanged response
LangQ = Query(None, pattern="^(uk|en)$", description="en adds *_en siblings; default/uk = unchanged")


def _read_build() -> str | None:
    """The commit this worker was started from: deploy.sh writes backend/BUILD before the reload (read once per worker)."""
    from pathlib import Path

    try:
        return (Path(__file__).resolve().parents[3] / "BUILD").read_text().strip() or None
    except OSError:
        return None


BUILD = _read_build()


@router.get("/health")
def health(deep: bool = False):  # noqa: ANN201 — dict or a 503 JSONResponse
    out = {"ok": True, "data_version": science.data_version(), "method_version": science.method_version(),
           "build": BUILD, "api_version": __version__,
           "science_ready": science.available(), "raw_data": bool(rasters.aois())}
    if not deep:
        return out
    # ?deep=1 (RB-13): what a monitor needs — data present, caches writable, disk free
    import shutil
    import tempfile

    s = get_settings()
    checks: dict[str, Any] = {}
    checks["landsat_dir"] = s.landsat_dir.is_dir() and any(s.landsat_dir.iterdir())
    checks["years"] = len(rasters.years(s.tiles_aoi))
    for name, d in (("cache_writable", s.cache_dir), ("reports_writable", s.reports_dir)):
        try:
            d.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=d, prefix=".health-"):
                pass
            checks[name] = True
        except OSError:
            checks[name] = False
    try:
        checks["disk_free_gb"] = round(shutil.disk_usage(s.cache_dir).free / 2**30, 1)
    except OSError:
        checks["disk_free_gb"] = None
    checks["disk_ok"] = (checks["disk_free_gb"] or 0) >= s.tile_cache_min_free_gb
    out["checks"] = checks
    out["ok"] = bool(checks["landsat_dir"] and checks["years"] and checks["cache_writable"]
                     and checks["reports_writable"] and out["science_ready"])
    return out if out["ok"] else JSONResponse(out, status_code=503)


@router.get("/meta")
def get_meta(lang: str | None = LangQ) -> dict:
    return _l(meta.meta(), lang)


def _l(d: Any, lang: str | None) -> Any:
    if lang != "en":
        return d
    from uhd.services import i18n

    return i18n.localize(d, i18n._war_extra)


# the country map data (overview/overlays) changes with every deploy/method bump: revalidate on each load (ETag → 304)
# so a browser never pins a pre-deploy copy for a day (marker numbers disagreeing with the freshly fetched card)
REVALIDATE = "public, max-age=0, must-revalidate"


def _cached_json(body: bytes, etag: str, request: Request, cache_control: str = "public, max-age=86400") -> Response:
    h = {"Cache-Control": cache_control, "ETag": etag}
    if etag in (request.headers.get("if-none-match") or ""):
        return Response(status_code=304, headers=h)
    return Response(body, media_type="application/json", headers=h)


@router.get("/overview")
def get_overview(request: Request, lang: str | None = LangQ) -> Response:
    """City / district results for the country map (precomputed at deploy; = POST /api/analyze {place_id})."""
    got = overview.load()
    if got is None:
        raise APIError(503, "overview_not_ready", "the overview is being prepared; try again in a few minutes")
    if lang == "en":
        from uhd.services import i18n

        got = i18n.localize_cached_json(*got)
    return _cached_json(*got, request, REVALIDATE)


@router.get("/overlays")
def get_overlays(request: Request, lang: str | None = LangQ) -> Response:
    """Ukraine outline, war regions (war_zone caveat), the occupied list (occupied caveat) and the no-LST mask (science) for the map."""
    got = overview.overlays()
    if lang == "en":
        from uhd.services import i18n

        got = i18n.localize_cached_json(*got)
    return _cached_json(*got, request, REVALIDATE)


@router.get("/places")
def search_places(q: str = Query("", max_length=200), limit: int = Query(10, ge=1, le=50),
                  geocoder: bool = True, lang: str | None = LangQ) -> dict:
    kwargs = {"english": True} if lang == "en" else {}
    return _l(places.search(q, limit=limit, geocoder=geocoder, **kwargs), lang)


@router.get("/places/{place_id}")
def get_place(place_id: str, lang: str | None = LangQ) -> dict:
    kwargs = {"english": True} if lang == "en" else {}
    return _l(places.get_place(place_id, **kwargs), lang)


class AnalyzeRequest(BaseModel):
    geometry: dict[str, Any] | None = Field(None, description="GeoJSON Polygon/MultiPolygon (WGS84), Feature accepted")
    place_id: str | None = Field(None, description="alternative to geometry: a preset or osm:… id from /api/places")
    years: list[int] | None = Field(None, description="[from, to], default = all years")
    name: str | None = Field(None, max_length=200)


def resolve_zone(geometry: dict | None, place_id: str | None, name: str | None = None) -> tuple[dict, str | None, str | None]:
    if geometry is None and not place_id:
        raise bad_request("missing_geometry", "geometry or place_id is required")
    if geometry is None:
        p = places.get_place(place_id)
        return p["geometry"], p["id"], name or p["name"]
    if place_id:  # keep place_id only if the geometry really is that place (REVIEW M8)
        try:
            p = places.get_place(place_id)
            same = geometry_hash(parse_geometry(p["geometry"])) == geometry_hash(parse_geometry(geometry))
        except APIError:
            same = False
        if not same:
            return geometry, None, name
        return geometry, p["id"], name or p["name"]
    return geometry, None, name


@router.post("/analyze")
def analyze(req: AnalyzeRequest, lang: str | None = LangQ) -> dict:
    geom, pid, name = resolve_zone(req.geometry, req.place_id, req.name)
    rep = analysis.analyze(geom, req.years, name=name, place_id=pid)
    if pid and pid.startswith("osm:"):  # say that we analysed a circle around a point-like geocoder result
        p = places.get_place(pid)  # disk-cached
        if p.get("kind") == "geocoder_circle":
            rep["caveats"] = [{"code": "geocoder_circle", "text_uk": places.CIRCLE_NOTE_UK}] + list(rep.get("caveats") or [])
    return _lr(rep, lang)


def _lr(rep: dict, lang: str | None) -> dict:
    if lang != "en":
        return rep
    from uhd.services import i18n

    return i18n.localize_report(rep)


@router.get("/reports")
def list_reports(limit: int = Query(50, ge=1, le=500), x_uhd_team_token: str | None = Header(None)) -> dict:
    """Team only (RB-11): the list shows every visitor's drawn polygons. A single report stays public by its id."""
    from uhd.api.routes.agent import _is_team

    if not _is_team(x_uhd_team_token):
        raise APIError(403, "team_only", "Список звітів доступний лише команді (X-UHD-Team-Token).")
    return {"reports": reports.list_reports(limit)}


@router.get("/reports/{report_id}")
def get_report(report_id: str, name: str | None = Query(None, max_length=200), lang: str | None = LangQ) -> dict:
    """Stored reports are name-free; ``?name=`` labels this response (zone.name + verdict sentence)."""
    return _lr(analysis.stored_report(report_id, name), lang)


@router.api_route("/reports/{report_id}/export", methods=["GET", "HEAD"])
def export_report(report_id: str, request: Request, format: str = Query("csv"),
                  name: str | None = Query(None, max_length=200),
                  place_id: str | None = Query(None, max_length=64), lang: str | None = LangQ) -> Response:
    """Board item 29: the stored report as csv (UTF-8 BOM, «;») | xlsx | json | pdf — no recompute.
    ``name`` / ``place_id`` (what the page shows) label the file and its link; the stored report is name-free.
    ``lang=en`` (item 32): English labels and *_en texts, csv with «,»; numbers unchanged."""
    from urllib.parse import quote

    from uhd.services import export

    if format not in export.FORMATS:
        raise bad_request("invalid_format", "format must be one of " + ", ".join(export.FORMATS))
    base = export.public_base(request.headers, str(request.base_url))
    body, media, fname = export.render(report_id, format, name, base, place_id, lang)
    h = {"Content-Disposition": f"attachment; filename=\"{fname}\"; filename*=UTF-8''{quote(fname)}",
         # English texts may still grow (science templates), so en is cached for an hour, not a day
         "Cache-Control": f"public, max-age={3600 if lang == 'en' else 86400}", "Vary": "X-Forwarded-Host, X-Forwarded-Proto, Host"}
    return Response(b"" if request.method == "HEAD" else body, media_type=media, headers=h)


@router.get("/reports/{report_id}/reference")
def get_report_reference(report_id: str, request: Request) -> Response:
    """Board item 20 D: simplified outline (GeoJSON Feature, < 100 kB) of the report's reference forest."""
    from uhd.services import reference_outline

    import hashlib

    body = reference_outline.get(report_id)
    return _cached_json(body, '"%s"' % hashlib.sha256(body).hexdigest()[:16], request)


def _geom_from_query(report_id: str | None, geometry: str | None, place_id: str | None):
    if report_id:
        return parse_geometry(reports.require(report_id)["params"]["geometry"])
    if geometry:
        try:
            gj = json.loads(geometry)
        except json.JSONDecodeError as e:
            raise bad_request("invalid_geometry", "geometry must be URL-encoded GeoJSON") from e
        return parse_geometry(gj)
    if place_id:
        return parse_geometry(places.get_place(place_id)["geometry"])
    raise bad_request("missing_geometry", "report_id, geometry or place_id is required")


@router.get("/scenes")
def list_scenes(report_id: str | None = None, geometry: str | None = None, place_id: str | None = None,
                year: int | None = None, summer_only: bool = True) -> dict:
    g = _geom_from_query(report_id, geometry, place_id)
    return scenes.list_scenes(g, year=year, summer_only=summer_only)


@router.get("/scenes/{scene_id}")
def scene_stats(scene_id: str, report_id: str | None = None, geometry: str | None = None,
                place_id: str | None = None) -> dict:
    return scenes.scene_stats(scene_id, _geom_from_query(report_id, geometry, place_id))


@router.get("/climate")
def get_climate(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180),
                lang: str | None = LangQ) -> dict:
    return _l(climate.projection(lat, lon), lang)


@router.get("/weather")
def get_weather(date: str, lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)) -> dict:
    return weather.get_weather(date, lat, lon)
