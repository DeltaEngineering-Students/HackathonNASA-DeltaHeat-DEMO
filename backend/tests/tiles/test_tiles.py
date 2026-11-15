from __future__ import annotations

import io
import math

import numpy as np
import pytest
from PIL import Image

from uhd.config import get_settings
from uhd.services import science
from uhd.tiles import palettes, pyramid, render


def tile_xy(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 1 << z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def img(b: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(b)).convert("RGBA"))


def test_colorize_stops_and_nodata():
    v = np.array([[-6, 0, 12, np.nan, 100, -100]], np.float32)
    rgba = palettes.colorize(v, "gap", "light")
    assert tuple(rgba[0, 0, :3]) == (92, 140, 122)
    assert tuple(rgba[0, 1, :3]) == (240, 239, 236)
    assert tuple(rgba[0, 2, :3]) == (128, 18, 96)
    assert rgba[0, 3, 3] == 0 and rgba[0, 0, 3] == 255
    assert tuple(rgba[0, 4, :3]) == (64, 6, 52) and tuple(rgba[0, 5, :3]) == (92, 140, 122)  # clamped at −6 / +16


def test_meta_scales_have_both_themes():
    m = palettes.meta()
    for layer in (l for l in render.LAYERS if l not in pyramid.FILL_LAYERS and l != "nonbuilt"):  # fill: base scale; nonbuilt: overlay
        assert set(m[layer]["stops"]) == {"light", "dark"}


@pytest.mark.parametrize("layer", ["lst", "ndvi", "gap", "dndvi"])
def test_tile_renders_over_data(client, layer):
    x, y = tile_xy(30.627, 50.411, 12)
    r = client.get(f"/tiles/{layer}/2025/12/{x}/{y}.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    a = img(r.content)
    assert a.shape == (256, 256, 4)
    assert (a[..., 3] == 255).mean() > 0.5


def test_tile_values_match_source(client):
    # lst ramp 30..40 °C west→east; centre of the grid ≈ 35 °C → colour between the 31 and 36 stops
    x, y = tile_xy(30.627, 50.411, 13)
    v = render.values("lst", 2013, 13, x, y)
    fin = v[np.isfinite(v)]
    assert 30 <= fin.min() and fin.max() <= 40.1


def test_tile_outside_coverage_is_empty(client):
    r = client.get("/tiles/lst/2025/10/0/0.png")
    assert r.status_code == 200 and r.content == render.empty_png()


def test_tile_cache_written(client):
    x, y = tile_xy(30.627, 50.411, 12)
    client.get(f"/tiles/lst/2025/12/{x}/{y}.png?theme=dark")
    files = list((get_settings().cache_dir / "tiles").rglob("*.png"))
    assert len(files) == 1 and "/dark/" in str(files[0])


def test_low_zoom_uses_pyramid(client):
    x, y = tile_xy(30.627, 50.411, 7)
    r = client.get(f"/tiles/lst/2025/7/{x}/{y}.png")
    assert r.status_code == 200
    assert (get_settings().cache_dir / "pyramid").exists()
    assert pyramid.status("ukraine")["lst"] == [2025]


@pytest.mark.parametrize("path,code", [
    ("/tiles/foo/2025/12/1/1.png", "invalid_layer"),
    ("/tiles/lst/2000/12/1/1.png", "invalid_year"),
    ("/tiles/lst/2025/30/1/1.png", "invalid_tile"),
    ("/tiles/lst/2025/2/9/1.png", "invalid_tile"),
    ("/tiles/lst/2025/12/1/1.png?theme=pink", "invalid_theme"),
])
def test_tile_validation(client, path, code):
    r = client.get(path)
    assert r.status_code == 422 and r.json()["error"] == code


def test_gap_without_science_is_503(client, monkeypatch):
    science.set_module(type("M", (), {"analyze": staticmethod(lambda *a, **k: {}), "DATA_VERSION": "x"})())
    x, y = tile_xy(30.627, 50.411, 12)
    r = client.get(f"/tiles/gap/2025/12/{x}/{y}.png")
    assert r.status_code == 503 and r.json()["error"] == "science_not_ready"


def test_block_mean_nan_aware():
    a = np.array([[1, np.nan, 3, 3], [1, 1, 3, 3]], np.float32)
    assert pyramid._block_mean(a, 2).tolist() == [[1.0, 3.0]]


def test_tile_version_param_controls_caching(client):
    x, y = tile_xy(30.627, 50.411, 12)
    base = f"/tiles/gap/2025/12/{x}/{y}.png"
    cur = client.get(base, params={"v": client.get("/api/meta").json()["layers"]["tiles_version"]})
    assert cur.status_code == 200 and "immutable" in cur.headers["cache-control"]
    old = client.get(base, params={"v": "old-version"})
    assert old.status_code == 200 and old.headers["cache-control"] == "public, max-age=60"
    plain = client.get(base)
    assert plain.content == cur.content and plain.headers["cache-control"] == "public, max-age=3600"


def test_gap_scale_is_wide_and_dark_ramp_separates_heat_levels():
    sc = palettes.SCALES["gap"]
    assert sc["domain"] == [-6, 16]
    for th in palettes.THEMES:
        assert sc["stops"][th][0][0] == -6 and sc["stops"][th][-1][0] == 16
    rgb = palettes.colorize(np.array([[6.0, 9.0, 12.0, 15.0]], np.float32), "gap", "dark")[0, :, :3].astype(int)
    d = [np.abs(rgb[i] - rgb[j]).sum() for i in range(4) for j in range(i + 1, 4)]
    assert min(d) > 60, rgb  # 6/9/12/15 °C are clearly different colours on the dark map
    lum = (rgb * [0.2126, 0.7152, 0.0722]).sum(1)
    assert lum[-1] > lum[0]  # hottest is the brightest on dark


def test_tiles_version_changes_with_palette(monkeypatch):
    v0 = render.tiles_version()
    monkeypatch.setitem(palettes.SCALES["gap"], "domain", [-6, 20])
    assert render.tiles_version() != v0


def test_tiles_are_palette_pngs_with_transparency(client):
    x, y = tile_xy(30.627, 50.411, 12)
    r = client.get(f"/tiles/gap/2025/12/{x}/{y}.png")
    im = Image.open(io.BytesIO(r.content))
    assert im.mode == "P" and len(im.getpalette()) // 3 <= 128 and im.info.get("transparency") == 0
    rgba = img(r.content)
    v = render.values("gap", 2025, 12, x, y)
    assert ((rgba[..., 3] == 0) == ~np.isfinite(v)).all()  # no-data stays fully transparent
    ref = palettes.colorize(v, "gap", "light")[..., :3].astype(int)
    fin = np.isfinite(v)
    assert np.abs(rgba[..., :3].astype(int)[fin] - ref[fin]).max() <= 12  # ≤ one palette step off the exact ramp


def test_evict_drops_old_versions_and_lru(client, monkeypatch):
    import os
    import time

    from uhd.tiles import evict

    x, y = tile_xy(30.627, 50.411, 12)
    for yr in (2013, 2025):
        client.get(f"/tiles/lst/{yr}/12/{x}/{y}.png")
    root = get_settings().cache_dir / "tiles"
    old = root / "old-version" / "gap"
    old.mkdir(parents=True)
    (old / "a.png").write_bytes(b"x")
    files = sorted(root.rglob("*.png"))
    os.utime(files[0], (time.time() - 3600, time.time() - 3600))
    monkeypatch.setenv("UHD_TILE_CACHE_MAX_GB", "0")
    get_settings.cache_clear()
    out = evict.run()
    assert "old-version" in out["removed_dirs"] and not old.exists()
    assert out["removed_files"] >= 2 and not list(root.rglob("*.png"))


def test_tile_not_persisted_when_disk_is_low(client, monkeypatch):
    monkeypatch.setenv("UHD_TILE_CACHE_MIN_FREE_GB", "1000000")
    get_settings.cache_clear()
    render._disk_check["t"] = 0.0
    x, y = tile_xy(30.627, 50.411, 12)
    assert client.get(f"/tiles/ndvi/2025/12/{x}/{y}.png").status_code == 200
    assert not list((get_settings().cache_dir / "tiles").rglob("*.png"))
    render._disk_check["t"] = 0.0


def _ukraine(coords):
    import json

    p = get_settings().landsat_dir / "aoi"
    p.mkdir(parents=True, exist_ok=True)
    (p / "Ukraine.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [coords]}}]}))
    render.ukraine_clip.cache_clear()


@pytest.mark.parametrize("layer", ["lst", "ndvi", "gap", "dndvi"])
def test_tiles_clipped_to_ukraine(client, layer):
    # task 2a: the outline's east edge runs through the tile; pixels > 1.5 km east of it are transparent
    x, y = tile_xy(30.627, 50.411, 12)
    edge = 30.627
    _ukraine([[20.0, 44.0], [edge, 44.0], [edge, 53.0], [20.0, 53.0], [20.0, 44.0]])
    assert "+ua1500+" in render.tiles_version()
    a = img(client.get(f"/tiles/{layer}/2025/12/{x}/{y}.png").content)
    n_ = 1 << 12
    lon0, lon1 = x / n_ * 360 - 180, (x + 1) / n_ * 360 - 180
    col_edge = (edge - lon0) / (lon1 - lon0) * 256
    col_buf = col_edge + 1500 / (111320 * math.cos(math.radians(50.41)) * (lon1 - lon0) / 256)
    left, right = a[:, : int(col_edge) - 2, 3], a[:, int(col_buf) + 3:, 3]
    assert (left == 255).mean() > 0.9 and (right == 0).all()


def test_tile_fully_outside_ukraine_is_shared_empty_and_not_cached(client):
    x, y = tile_xy(30.627, 50.411, 12)
    _ukraine([[22.0, 44.0], [25.0, 44.0], [25.0, 46.0], [22.0, 46.0], [22.0, 44.0]])  # far from the tile
    r = client.get(f"/tiles/gap/2025/12/{x}/{y}.png")
    assert r.content == render.empty_png()
    assert not render._cache_path("gap", "light", 2025, 12, x, y, render.DNDVI_BASE).exists()


def test_tiles_not_clipped_without_outline(client):
    assert "+ua1500" not in render.tiles_version()  # the fixture layout has no aoi/Ukraine.geojson


def test_sea_pixels_transparent_in_every_layer(client):
    import rasterio
    from rasterio.transform import from_origin

    from tests.conftest import N, X0, Y1

    # sea = the eastern half of the fixture grid (science's sea_mask.tif on the same grid)
    p = get_settings().data_dir / "ukraine" / "sea_mask.tif"
    p.parent.mkdir(parents=True, exist_ok=True)
    a = np.zeros((N, N), np.uint8)
    a[:, N // 2:] = 1
    with rasterio.open(p, "w", driver="GTiff", width=N, height=N, count=1, dtype="uint8", crs="EPSG:3035",
                       transform=from_origin(X0, Y1, 60, 60)) as ds:
        ds.write(a, 1)
    render.sea_info.cache_clear()
    render._inputs_tag.cache_clear()
    assert "+sea1" in render.tiles_version()
    from pyproj import Transformer

    lon, lat = Transformer.from_crs(3035, 4326, always_xy=True).transform(X0 + N * 60 / 2, Y1 - N * 60 / 2)
    for z in (9, 12, 14):  # coarse level, ×4 window, native window
        x, y = tile_xy(lon, lat, z)
        X, Y = render._sample_coords(z, x, y)
        for layer in ("gap", "lst", "ndvi", "dndvi"):
            im = img(client.get(f"/tiles/{layer}/2025/{z}/{x}/{y}.png").content)
            sea = X > X0 + N * 60 / 2 + 1000  # clearly inside the sea half
            land = (X < X0 + N * 60 / 2 - 1000) & (X > X0 + 1000) & (Y < Y1 - 1000) & (Y > Y1 - N * 60 + 1000)
            assert (im[..., 3][sea] == 0).all(), (z, layer)
            if land.any():
                assert (im[..., 3][land] == 255).mean() > 0.9, (z, layer)


def test_tiles_version_follows_derived_inputs(monkeypatch, tmp_path):
    import os

    p = get_settings().data_dir / "ukraine" / "sea_mask.tif"
    p.parent.mkdir(parents=True, exist_ok=True)
    v0 = render.tiles_version()
    p.write_bytes(b"x")  # a rebuilt input file (here: unreadable as a mask, but its identity still counts)
    render._inputs_tag.cache_clear()
    v1 = render.tiles_version()
    assert v1 != v0
    os.utime(p, ns=(1, 1))
    render._inputs_tag.cache_clear()
    assert render.tiles_version() != v1


def _fill_on(monkeypatch):
    real = pyramid.read_window

    def rw(aoi, layer, year, r0, c0, h, w):
        if layer == "gap_fill":  # filled only in the left half of the window, NaN elsewhere
            a = np.full((h, w), np.nan, np.float32)
            a[:, : w // 2] = 4.0
            return a
        if layer == "lst_fill":
            return np.full((h, w), np.nan, np.float32)
        return real(aoi, layer, year, r0, c0, h, w)

    monkeypatch.setattr(pyramid, "fill_available", lambda: True)
    monkeypatch.setattr(pyramid, "read_window", rw)


def test_fill_layers_served_with_base_palette(client, monkeypatch):
    _fill_on(monkeypatch)
    assert render.tiles_version().endswith("+fill1")
    m = client.get("/api/meta").json()["layers"]
    assert m["fill"] == {"gap": "gap_fill", "lst": None, "internal": True, "label_uk": "заповнено з сусідніх років"}
    assert "gap_fill" in m["ids"] and "lst_fill" not in m["ids"]
    x, y = tile_xy(30.627, 50.411, 13)
    a = img(client.get(f"/tiles/gap_fill/2025/13/{x}/{y}.png?theme=dark").content)
    assert 0.2 < (a[..., 3] == 255).mean() < 0.8  # only the filled pixels are drawn
    stop4 = dict(palettes.SCALES["gap"]["stops"]["dark"])[4]  # gap palette (4 °C is a stop)
    assert max(abs(int(c) - s) for c, s in zip(a[a[..., 3] == 255][0][:3], stop4)) <= 4  # 127-level quantisation
    assert client.get(f"/tiles/lst_fill/2025/13/{x}/{y}.png").status_code == 422  # not served (disk budget)


def test_fill_layers_off_without_science_gapfill(client):
    assert "+fill1" not in render.tiles_version()
    assert client.get("/api/meta").json()["layers"]["fill"] is None
    x, y = tile_xy(30.627, 50.411, 13)
    r = client.get(f"/tiles/gap_fill/2025/13/{x}/{y}.png")
    assert r.status_code == 422 and r.json()["error"] == "invalid_layer"


def test_analysis_never_reads_fill_layers(client, monkeypatch):
    real = pyramid.read_window

    def rw(aoi, layer, *a):
        assert not layer.endswith("_fill"), "analysis must not read display-only fill"
        return real(aoi, layer, *a)

    monkeypatch.setattr(pyramid, "fill_available", lambda: True)
    monkeypatch.setattr(pyramid, "read_window", rw)
    rep = client.post("/api/analyze", json={"place_id": "kyiv-pozniaky"}).json()
    assert rep["report_id"] and "hotspots" in rep
    from uhd.services import science

    assert all("fill" not in str(k) for k in (rep.get("gap_summary") or {}))
    del science


def test_gap_pyramid_keyed_by_reffield_and_stale_dirs_evicted(monkeypatch, tmp_path):
    from uhd.tiles import evict

    rf = tmp_path / "reffield.npz"
    rf.write_bytes(b"a")
    monkeypatch.setattr(pyramid, "reffield_path", lambda: rf)
    pyramid.reffield_tag.cache_clear()
    d1 = pyramid._dir("ukraine", "gap", 2025)
    assert d1.parent.name.startswith("gap@") and pyramid._dir("ukraine", "lst", 2025).parent.name == "lst"
    d1.mkdir(parents=True)
    rf.write_bytes(b"bb")  # science rebuilt the field
    pyramid.reffield_tag.cache_clear()
    d2 = pyramid._dir("ukraine", "gap", 2025)
    assert d2 != d1
    d2.mkdir(parents=True)
    out = evict.run()
    assert not d1.parent.exists() and d2.exists()
    assert any(r.endswith(d1.parent.name) for r in out["removed_dirs"])


def _classes_tif(cls_fn):
    import rasterio
    from rasterio.transform import from_origin

    from tests.conftest import N, X0, Y1

    p = get_settings().data_dir / "ukraine" / "classes.tif"
    p.parent.mkdir(parents=True, exist_ok=True)
    years = list(range(2013, 2026))
    with rasterio.open(p, "w", driver="GTiff", width=N, height=N, count=len(years), dtype="uint8", crs="EPSG:3035",
                       transform=from_origin(X0, Y1, 60, 60)) as ds:
        for i, y in enumerate(years, 1):
            ds.write(cls_fn(y), i)
            ds.set_band_description(i, str(y))
    pyramid.classes_tag.cache_clear()
    render._inputs_tag.cache_clear()
    return p


def _halves(y):
    from tests.conftest import N

    a = np.full((N, N), 2, np.uint8)  # field
    a[:, : N // 2] = 1  # built (west half)
    a[: N // 10, N // 2:] = 4  # water strip (north-east): faded too
    a[-N // 10:, N // 2:] = 0  # no class (sea): transparent
    return a


def test_nonbuilt_overlay_native_and_pyramid(client):
    from pyproj import Transformer

    from tests.conftest import N, X0, Y1

    v0 = render.tiles_version()
    _classes_tif(_halves)
    assert render.tiles_version() != v0  # classes.tif identity is part of tiles_version
    m = client.get("/api/meta").json()["layers"]
    ov = m["overlays"]["nonbuilt"]
    assert ov["alpha"] == 1.0 and ov["default_strength"] == 0.7 and ov["applies_to"] == ["gap"]
    assert ov["internal"] is True
    assert ov["colors"]["dark"] == "#1C2438" and ov["label_uk"] == "Приглушити не-забудову"
    assert "nonbuilt" not in m["ids"]
    tr = Transformer.from_crs(3035, 4326, always_xy=True)
    lon, lat = tr.transform(X0 + N * 60 / 2, Y1 - N * 60 / 2)
    for z in (13, 10):  # native 60 m window / uint8 pyramid level
        x, y = tile_xy(lon, lat, z)
        X, Y = render._sample_coords(z, x, y)
        im = img(client.get(f"/tiles/nonbuilt/2025/{z}/{x}/{y}.png?theme=dark").content)
        inside = (X > X0 + 1500) & (X < X0 + N * 60 - 1500) & (Y < Y1 - 1500) & (Y > Y1 - N * 60 + 1500)
        mid = (Y < Y1 - N * 6 - 1500) & (Y > Y1 - N * 54 + 1500)
        west, east = inside & mid & (X < X0 + N * 30 - 1500), inside & mid & (X > X0 + N * 30 + 1500)
        if not (west.any() and east.any()):
            continue
        assert (im[..., 3][west] == 0).all(), z  # built → no fade
        assert int(np.median(im[..., 3][east])) >= 253, z  # field → full alpha (the slider scales it)
        assert tuple(im[east][0][:3]) == (0x1C, 0x24, 0x38)
    # water faded, class 0 transparent (native zoom)
    x, y = tile_xy(*tr.transform(X0 + N * 45, Y1 - N * 3), 14)
    im = img(client.get(f"/tiles/nonbuilt/2025/14/{x}/{y}.png").content)
    assert (im[..., 3] > 240).mean() > 0.5
    x, y = tile_xy(*tr.transform(X0 + N * 45, Y1 - N * 57), 14)
    im = img(client.get(f"/tiles/nonbuilt/2025/14/{x}/{y}.png").content)
    assert (im[..., 3] == 0).mean() > 0.5
    lv = pyramid.level(get_settings().tiles_aoi, "nonbuilt", 2025, 4)
    assert lv.dtype == np.uint8  # ≈ 22 MB per year on the real grid


def test_nonbuilt_off_without_classes(client):
    assert client.get("/api/meta").json()["layers"]["overlays"]["nonbuilt"] is None
    x, y = tile_xy(30.627, 50.411, 13)
    assert client.get(f"/tiles/nonbuilt/2025/13/{x}/{y}.png").status_code == 422


def _water_ne(y):
    from tests.conftest import N

    a = np.full((N, N), 3, np.uint8)  # nature
    a[: N // 2, N // 2:] = 4  # water (north-east quarter) in every year: masked
    if y == 2013:
        a[N // 2:, : N // 2] = 4  # water (south-west quarter) in the base year only (a drained bed): shown
    if y == 2025:
        a[N // 2:, N // 2:] = 4  # water (south-east quarter) in the shown year only (a new pond): shown
    return a


def test_dndvi_masks_inland_water_only_in_dndvi(client):
    from pyproj import Transformer

    from tests.conftest import N, X0, Y1

    _classes_tif(_water_ne)
    assert render.dndvi_water_masked() and render.tiles_version().endswith("+dndviw2")
    # the per-layer tag is not part of the server cache dir: the other layers' rendered tiles stay valid
    import re

    assert render.cache_tag() == re.sub(r"[^A-Za-z0-9._-]+", "_", render.tiles_version().removesuffix("+dndviw2"))
    tr = Transformer.from_crs(3035, 4326, always_xy=True)
    # quadrant centres (EPSG:3035): ne water in both years → masked; sw water in the base year only (drained bed),
    # se water in the shown year only (new pond), nw land → shown
    q = {"ne": (45, 15, False), "sw": (15, 45, True), "se": (45, 45, True), "nw": (15, 15, True)}
    for z in (13, 10):  # native 60 m window / uint8 water pyramid
        for name, (cx, cy, shown) in q.items():
            px, py = X0 + N * cx, Y1 - N * cy
            x, y = tile_xy(*tr.transform(px, py), z)
            X, Y = render._sample_coords(z, x, y)
            m = (np.abs(X - px) < N * 15 - 1500) & (np.abs(Y - py) < N * 15 - 1500)  # well inside the quadrant
            assert m.any(), (z, name)
            d = img(client.get(f"/tiles/dndvi/2025/{z}/{x}/{y}.png").content)[..., 3]
            if shown:
                assert (d[m] == 255).mean() > 0.9, (z, name)
            else:
                assert (d[m] == 0).all(), (z, name)
                n = img(client.get(f"/tiles/ndvi/2025/{z}/{x}/{y}.png").content)[..., 3]
                assert (n[m] == 255).mean() > 0.9, (z, name)  # the ndvi layer is untouched
    tag = render.cache_tag()
    root = get_settings().cache_dir / "tiles" / tag
    assert (root / "dndvi-w2-b2013").is_dir() and (root / "ndvi").is_dir()


def test_evict_drops_stale_dndvi_dir_only(client):
    from uhd.tiles import evict

    _classes_tif(_water_ne)
    root = get_settings().cache_dir / "tiles" / render.cache_tag()
    for name in ("dndvi-b2013", "dndvi-w1-b2013", "gap", "dndvi-w2-b2013"):
        (root / name).mkdir(parents=True, exist_ok=True)
        (root / name / "a.png").write_bytes(b"x")
    out = evict.run(dry_run=False)
    assert not (root / "dndvi-b2013").exists() and not (root / "dndvi-w1-b2013").exists()
    assert (root / "gap" / "a.png").exists() and (root / "dndvi-w2-b2013" / "a.png").exists()
    assert {f"{render.cache_tag()}/dndvi-b2013", f"{render.cache_tag()}/dndvi-w1-b2013"} <= set(out["removed_dirs"])


def test_kakhovka_exemption_box():
    from pyproj import Transformer

    t = Transformer.from_crs(4326, 3035, always_xy=True)
    X, Y = (np.array(v) for v in t.transform([34.25, 30.56, 33.0], [47.52, 50.44, 47.5]))
    assert render._in_kakhovka(X, Y).tolist() == [True, False, False]  # drained bed / Дніпро at Kyiv / west of the box
