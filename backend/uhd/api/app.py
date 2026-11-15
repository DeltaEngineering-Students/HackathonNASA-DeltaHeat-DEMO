from __future__ import annotations

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from uhd import __version__
from uhd.config import get_settings
from uhd.errors import APIError
from uhd.logging_setup import setup_logging

log = logging.getLogger("uhd.api")
_RID = re.compile(r"[A-Za-z0-9._-]{1,64}")
_SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin", "X-Frame-Options": "DENY"}
# MapLibre: style/glyphs/vector tiles from OpenFreeMap, «Супутник» raster tiles from Esri World Imagery Wayback (301s stay on the same host), EOX as the fallback (fetched → connect-src too),
# web workers from blob:, inline styles on map elements
_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https://tiles.openfreemap.org https://wayback.maptiles.arcgis.com https://tiles.maps.eox.at; "
        "connect-src 'self' https://tiles.openfreemap.org https://wayback.maptiles.arcgis.com https://tiles.maps.eox.at "
        "https://metadata.maptiles.arcgis.com https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/; font-src 'self' data: https://tiles.openfreemap.org; "
        "worker-src 'self' blob:; child-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")


class BodyLimit:
    """413 for request bodies over ``max_bytes`` — by Content-Length, and counted for chunked bodies (RB-05)."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        for k, v in scope.get("headers", []):
            if k == b"content-length":
                try:
                    too_big = int(v) > self.max_bytes
                except ValueError:
                    too_big = True
                if too_big:
                    return await self._reject(send)
        state = {"seen": 0, "over": False, "sent": False}

        async def limited():
            if state["over"]:
                return {"type": "http.request", "body": b"", "more_body": False}
            msg = await receive()
            if msg["type"] == "http.request":
                state["seen"] += len(msg.get("body", b""))
                if state["seen"] > self.max_bytes:  # stop reading; the app sees a truncated body
                    state["over"] = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return msg

        async def guarded_send(msg):
            if state["over"]:  # replace whatever the app answered to the truncated body with a 413
                if not state["sent"]:
                    state["sent"] = True
                    await self._reject(send)
                return
            await send(msg)

        await self.app(scope, limited, guarded_send)

    async def _reject(self, send):
        body = (b'{"error":"payload_too_large","message":"request body is too large (max %d bytes)"}'
                % self.max_bytes)
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})



@asynccontextmanager
async def _lifespan(_: FastAPI):
    """Import the science package and open the tile grids before the worker takes traffic, so the first tile/report
    request of a fresh worker does not pay ~1–2 s of imports (with a rolling reload the old worker serves meanwhile)."""
    t0 = time.perf_counter()
    try:
        from uhd.services import science
        from uhd.tiles import render

        if science.available():
            science.module()
        render.grid_bounds_3857(get_settings().tiles_aoi)
        render.tiles_version()
    except Exception:  # noqa: BLE001 — never block startup on a warm-up
        log.exception("startup warm-up failed")
    log.info("worker ready", extra={"warmup_s": round(time.perf_counter() - t0, 2)})
    yield


def create_app() -> FastAPI:
    s = get_settings()
    setup_logging(s.log_level, s.log_json)
    app = FastAPI(title="DELTAHEAT API", version=__version__, docs_url="/api/docs",
                  openapi_url="/api/openapi.json", redoc_url=None, lifespan=_lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    if s.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_methods=["*"], allow_headers=["*"],
                           expose_headers=["X-Request-Id"])

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        rid = request.headers.get("x-request-id") or ""
        if not _RID.fullmatch(rid):  # never echo/log arbitrary client strings (RB-05)
            rid = uuid.uuid4().hex[:12]
        request.state.request_id = rid
        t0 = time.perf_counter()
        try:
            resp = await call_next(request)
        except RecursionError:  # absurdly nested JSON body
            resp = JSONResponse({"error": "invalid_request", "message": "request body is nested too deeply",
                                 "request_id": rid}, status_code=422)
        except Exception:
            log.exception("unhandled", extra={"request_id": rid, "path": request.url.path})
            resp = JSONResponse({"error": "internal_error", "message": "internal server error", "request_id": rid},
                                status_code=500)
        dt = (time.perf_counter() - t0) * 1000
        resp.headers["X-Request-Id"] = rid
        for k, v in _SECURITY_HEADERS.items():
            resp.headers.setdefault(k, v)
        if not request.url.path.startswith("/api/docs"):  # Swagger UI loads its assets from a CDN
            resp.headers.setdefault("Content-Security-Policy", _CSP)
        if not request.url.path.startswith("/tiles/") or resp.status_code >= 400 or dt > 500:
            log.info("request", extra={"request_id": rid, "method": request.method, "path": request.url.path,
                                       "status": resp.status_code, "ms": round(dt, 1)})
        return resp

    @app.exception_handler(APIError)
    async def api_error(_: Request, e: APIError):
        headers = getattr(e, "headers", None) or ({"Retry-After": "60"} if e.status in (429, 503) else None)
        return JSONResponse(e.body(), status_code=e.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, e: RequestValidationError):
        errs = [{"loc": list(x.get("loc", [])), "msg": x.get("msg")} for x in e.errors()]
        return JSONResponse({"error": "invalid_request", "message": "request validation failed", "details": errs},
                            status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, e: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(e.status_code, "http_error")
        return JSONResponse({"error": code, "message": str(e.detail)}, status_code=e.status_code)

    app.add_middleware(BodyLimit, max_bytes=s.max_body_bytes)
    from uhd.api.routes import agent, core, tiles

    app.include_router(core.router)
    app.include_router(tiles.router)
    app.include_router(agent.router)
    _mount_frontend(app, s.frontend_dist)
    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built SPA at / with index.html fallback for client-side routes."""
    dist = dist.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith(("api/", "tiles/")):
            return JSONResponse({"error": "not_found", "message": "no such endpoint"}, status_code=404)
        index = dist / "index.html"
        if full_path:
            if "\x00" in full_path or len(full_path) > 512:
                return JSONResponse({"error": "not_found", "message": "no such file"}, status_code=404)
            try:
                f = (dist / full_path).resolve()
                ok = f.is_file() and f.is_relative_to(dist)
            except (OSError, ValueError):
                return JSONResponse({"error": "not_found", "message": "no such file"}, status_code=404)
            if ok:
                cache = "public, max-age=31536000, immutable" if "/assets/" in f"/{full_path}" else "no-cache"
                return FileResponse(f, headers={"Cache-Control": cache})
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return JSONResponse({"error": "frontend_not_built", "message": f"no frontend build at {dist}"},
                            status_code=404)
