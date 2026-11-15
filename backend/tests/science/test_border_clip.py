"""sci-v3.6 reference ring clipped to Ukraine (INVESTIGATION-FOREIGN-REFERENCE): no forest abroad, widening, note,
caveat texts; reffield sums only Ukrainian forest."""
import numpy as np
import pytest
import shapely.geometry as sg

from uhd.science import classes as C
from uhd.science import data as D
from uhd.science import i18n_en as EN
from uhd.science import reference as R
from uhd.science.geometry import Zone
from uhd.science.report import CAVEATS_UK, METHOD_VERSION

Z0, ZN, BORDER = 3000, 10, 505          # zone rows/cols 3000..3009; Ukraine = window columns < 505 (zone centre)


def _setup(monkeypatch, forest_fn):
    def classes(aoi, win, years=None):
        r0, c0, h, w = win
        rr, cc = np.mgrid[r0:r0 + h, c0:c0 + w]
        built = (rr >= Z0) & (rr < Z0 + ZN) & (cc >= Z0) & (cc < Z0 + ZN)
        one = np.where(built, C.BUILT, C.FIELD).astype(np.uint8)
        return np.repeat(one[None], len(years or D.YEARS), 0)

    def forest(aoi, win):
        r0, c0, h, w = win
        rr, cc = np.mgrid[r0:r0 + h, c0:c0 + w]
        return forest_fn(rr, cc)

    monkeypatch.setattr(R, "read_classes", classes)
    monkeypatch.setattr(R, "read_forest", forest)
    monkeypatch.setattr(R, "ukraine_mask", lambda aoi, win: np.mgrid[win[0]:win[0] + win[2], win[1]:win[1] + win[3]][1]
                        < Z0 - 500 + BORDER)
    m = np.ones((ZN, ZN), bool)
    return Zone(shape_ll=None, shape_m=sg.box(0, 0, 1, 1), aoi="ukraine", win=(Z0, Z0, ZN, ZN), mask=m)


def _abs_cols(ref):
    return np.nonzero(ref.ref)[1] + ref.win[1]


def test_ring_forest_abroad_is_dropped_and_noted(monkeypatch):
    zone = _setup(monkeypatch, lambda rr, cc: np.ones(rr.shape, bool))
    ref = R.derive(zone)
    assert ref.forest_px >= R.MIN_REF_PX and "ring_widened" not in ref.notes
    assert _abs_cols(ref).max() < Z0 - 500 + BORDER                 # no pixel abroad
    assert "ref_border_clipped" in ref.notes and ref.abroad_px > 0.4 * (ref.abroad_px + ref.forest_px)


def test_widening_applies_after_the_clip(monkeypatch):
    # forest abroad everywhere; in Ukraine only beyond 16 km from the zone → 2–15 km ring in Ukraine is empty
    def forest(rr, cc):
        d = np.hypot(rr - Z0 - 5, cc - Z0 - 5) * D.RES / 1000
        return (cc >= Z0 - 500 + BORDER) | (d > 16)
    ref = R.derive(_setup(monkeypatch, forest))
    assert ref.ring_km == R.RING_KM_WIDE and "ring_widened" in ref.notes and "ref_border_clipped" in ref.notes
    assert ref.forest_px >= R.MIN_REF_PX and _abs_cols(ref).max() < Z0 - 500 + BORDER


def test_no_note_when_little_is_abroad(monkeypatch):
    zone = _setup(monkeypatch, lambda rr, cc: cc < Z0 - 500 + BORDER + 3)   # 3 forest columns abroad
    ref = R.derive(zone)
    assert 0 < ref.abroad_px < 0.1 * ref.forest_px and "ref_border_clipped" not in ref.notes


def test_ukraine_mask_without_polygon_is_all_true(monkeypatch):
    def missing():
        raise FileNotFoundError("Ukraine.geojson")
    monkeypatch.setattr(R, "_ukraine_polygon", missing)
    assert R.ukraine_mask("ukraine", (12345, 0, 3, 4)).all()


def test_new_caveat_texts_and_english():
    assert METHOD_VERSION == "sci-v3.6"
    uk = CAVEATS_UK["few_reference_px"].format(km2="1,2")
    assert uk == "Навколо ділянки збереглося мало лісу (1,2 км²), показник розриву може бути неточним."
    assert EN.caveat_text_en("few_reference_px", uk, METHOD_VERSION) == (
        "Little forest is left around the area (1.2 km²), so the gap may be inaccurate.")
    old = "Лісу-еталона дуже мало (1,2 км²) — порівняння ненадійне."           # stored sci-v3.5.4 reports
    assert EN.caveat_text_en("few_reference_px", old, "sci-v3.5.4").startswith("There is very little")
    uk = CAVEATS_UK["ref_border_clipped"].format(km2="54,6")
    assert EN.caveat_text_en("ref_border_clipped", uk, METHOD_VERSION) == (
        "Part of the forest in the ring lies outside Ukraine (54.6 km²) and is left out: the reference is forest in "
        "Ukraine only.")


def test_reffield_sums_only_ukrainian_forest(monkeypatch, tmp_path):
    import importlib.util
    from pathlib import Path

    p = Path(__file__).resolve().parents[2] / "scripts" / "precompute_reffield.py"
    spec = importlib.util.spec_from_file_location("precompute_reffield", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    k = m.RA.COARSE
    monkeypatch.setattr(m.D, "grid", lambda aoi: type("G", (), {"height": 2 * k, "width": 2 * k})())
    monkeypatch.setattr(m.D, "read_lst", lambda aoi, y, win: np.full((win[2], win[3]), 30.0, np.float32))
    monkeypatch.setattr(m.D, "read_tif", lambda path, win, fill=0: np.ones((win[2], win[3]), np.uint8))
    monkeypatch.setattr(m.R, "ukraine_mask", lambda aoi, win: np.mgrid[0:win[2], 0:win[3]][1] < k)   # left half
    m._UA.clear()
    s, n = m.coarse_sums(2020, "forest.tif")
    assert n[:, 0].tolist() == [k * k, k * k] and n[:, 1].tolist() == [0, 0]
    assert s[:, 1].sum() == 0 and s[0, 0] == pytest.approx(30.0 * k * k)
