"""Integration tests on the real data (run on the server):

    cd /root/uhd/app/backend && UHD_LANDSAT_DIR=/srv/landsat UHD_DATA_DIR=/root/uhd/data \
        uv run --group dev pytest -m server_data
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

pytestmark = [pytest.mark.server_data, pytest.mark.real_science,
              pytest.mark.skipif(not Path("/srv/landsat/ukraine/composites").is_dir(), reason="no server data")]


@pytest.fixture(autouse=True)
def _real_dirs(monkeypatch):
    from uhd.config import get_settings
    from uhd.services import places, rasters

    monkeypatch.setenv("UHD_LANDSAT_DIR", "/srv/landsat")
    monkeypatch.setenv("UHD_DATA_DIR", os.environ.get("UHD_REAL_DATA_DIR", "/root/uhd/data"))
    get_settings.cache_clear()
    rasters.clear_caches()
    places.presets.cache_clear()


def test_analyze_district_under_2s_warm(client):
    body = {"place_id": "kyiv-pozniaky"}
    client.post("/api/analyze", json={"place_id": "kyiv-darnytskyi"})  # warm caches (other zone)
    t0 = time.perf_counter()
    rep = client.post("/api/analyze", json=body).json()
    dt = time.perf_counter() - t0
    assert dt < 2.0, dt
    assert rep["reference"]["city"] == "kyiv" and len(rep["series"]) == 13
    assert rep["trend"]["verdict"] in ("significant", "not_significant", "insufficient_data")


def test_real_tiles(client):
    for layer in ("gap", "lst", "ndvi", "dndvi"):
        r = client.get(f"/tiles/{layer}/2025/12/2396/1385.png")
        assert r.status_code == 200 and len(r.content) > 1000


def test_real_scenes_and_climate(client):
    b = client.get("/api/scenes", params={"place_id": "kyiv-pozniaky", "year": 2021}).json()
    assert b["count"] > 0 and b["source"] == "science"
    c = client.get("/api/climate", params={"lat": 50.45, "lon": 30.52}).json()
    assert c["variable"] == "tasmax"
