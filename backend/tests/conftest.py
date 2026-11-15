"""Test isolation: every test gets temp data/cache/report dirs, a synthetic Landsat layout and the fixture
science engine (unless a test opts into the real one)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from uhd.config import get_settings
from uhd.services import places, rasters, reports, science, science_fake
from uhd.tiles import render

# Synthetic "ukraine" grid around Kyiv: 300×300 px at 60 m (18 km), EPSG:3035
X0, Y1, N = 5_756_000.0, 3_247_000.0, 300
YEARS = (2013, 2025)


def make_landsat(root: Path) -> None:
    aoi = root / "ukraine"
    prof = dict(driver="GTiff", width=N, height=N, count=1, crs="EPSG:3035", transform=from_origin(X0, Y1, 60, 60),
                tiled=True, blockxsize=128, blockysize=128)
    yy, xx = np.mgrid[0:N, 0:N]
    for y in YEARS:
        d = aoi / "composites" / str(y)
        d.mkdir(parents=True)
        lst = (3000 + 10 * xx / N * 100 + (y - 2013) * 5).astype(np.int16)  # 30..40 °C ramp ×100
        lst[:20, :20] = -32768  # no-data corner
        with rasterio.open(d / "lst_med.tif", "w", dtype="int16", nodata=-32768, **prof) as o:
            o.write(lst, 1)
        ndvi = (20 + 60 * yy / N - (y - 2013)).astype(np.int8)
        with rasterio.open(d / "ndvi_med.tif", "w", dtype="int8", nodata=-128, **prof) as o:
            o.write(ndvi, 1)
        (d / "info.json").write_text(json.dumps({"year": y, "scenes": 3, "grid": {"x0": X0, "y1": Y1, "W": N, "H": N},
                                                 "crs": "EPSG:3035", "res": 60.0}))
        items = aoi / "items"
        items.mkdir(exist_ok=True)
        (items / f"{y}.json").write_text(json.dumps([{
            "type": "Feature", "id": f"LC08_L2SP_181025_{y}0710_02_T1",
            "geometry": {"type": "Polygon", "coordinates": [[[29, 49], [33, 49], [33, 52], [29, 52], [29, 49]]]},
            "properties": {"datetime": f"{y}-07-10T08:49:30Z", "landsat:wrs_path": "181", "landsat:wrs_row": "025",
                           "eo:cloud_cover": 12.5, "landsat:cloud_cover_land": 10.1, "view:sun_elevation": 58.2,
                           "platform": "landsat-8"}}]))


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch, request):
    landsat = tmp_path / "landsat"
    make_landsat(landsat)
    monkeypatch.setenv("UHD_LANDSAT_DIR", str(landsat))
    monkeypatch.setenv("UHD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("UHD_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("UHD_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("UHD_FRONTEND_DIST", str(tmp_path / "dist"))
    monkeypatch.setenv("UHD_LOG_JSON", "false")
    monkeypatch.setenv("UHD_TILE_CACHE_MIN_FREE_GB", "0")
    from uhd.tiles import render as _render

    _render._disk_check["t"] = 0.0
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("UHD_AGENT_TEAM_TOKEN", raising=False)
    get_settings.cache_clear()
    rasters.clear_caches()
    places.presets.cache_clear()
    reports.clear_memory()
    render.grid_bounds_3857.cache_clear()
    render.ukraine_clip.cache_clear()
    render.sea_info.cache_clear()
    render._inputs_tag.cache_clear()
    from uhd.tiles import pyramid as _pyr

    _pyr.reffield_tag.cache_clear()
    _pyr.classes_tag.cache_clear()
    science.set_module(None if request.node.get_closest_marker("real_science") else science_fake)
    from uhd.services import context as _context

    _context._tables.clear()
    _context._building.clear()
    _context._district_shapes.cache_clear()
    _context._ukraine_3035.cache_clear()
    from uhd.services import weather as _weather

    _weather._quota_until = 0.0  # an upstream 429 is remembered per process
    # no background rank-table builds racing the test's own reports (tests that need it patch _build_bg themselves)
    monkeypatch.setattr(_context, "_build_bg", lambda city: None)
    yield
    science.set_module(None)
    get_settings.cache_clear()
    rasters.clear_caches()
    places.presets.cache_clear()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from uhd.api.app import create_app

    return TestClient(create_app())


POZNIAKY = {"type": "Polygon", "coordinates": [[[30.613, 50.402], [30.641, 50.402], [30.641, 50.42], [30.613, 50.42],
                                                [30.613, 50.402]]]}
