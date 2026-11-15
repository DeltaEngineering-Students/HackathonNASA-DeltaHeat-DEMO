from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from uhd.tiles import render

router = APIRouter()


@router.get("/tiles/{layer}/{year}/{z}/{x}/{y}.png", responses={200: {"content": {"image/png": {}}}})
async def tile(layer: str, year: int, z: int, x: int, y: int, theme: str = Query("light"),
               base: int = Query(render.DNDVI_BASE),
               v: str | None = Query(None, max_length=200,
                                     description="layers.tiles_version from /api/meta (cache buster)")) -> Response:
    # cached tiles (most requests) are served on the event loop; only a miss goes to the thread pool (RB-02)
    png = render.cached(layer, year, z, x, y, theme=theme, base=base)
    if png is None:
        png = await run_in_threadpool(render.tile_png, layer, year, z, x, y, theme, base)
    if v is not None and v == render.tiles_version():
        cc = "public, max-age=31536000, immutable"  # URL is versioned: a new data version gets a new URL
    elif v is not None:
        cc = "public, max-age=60"  # stale/unknown version: current data, short cache
    else:
        cc = "public, max-age=3600"
    return Response(png, media_type="image/png", headers={"Cache-Control": cc})
