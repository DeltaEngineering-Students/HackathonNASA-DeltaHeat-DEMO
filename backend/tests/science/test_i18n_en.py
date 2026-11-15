"""English texts computed on read (I18N.md §6, uhd/science/i18n_en.py): same numbers as Ukrainian, None when unsure."""
import copy
import json
import os
import random
import re
import string
from pathlib import Path

import pytest

from uhd.science import i18n_en as E
from uhd.science import report as R

NUM = re.compile(r"\d+(?:\.\d+)?")
MENTOR_IDS = ("685c1d7e9f90ac02", "ee9c32bb6eebaa52", "f9008712da839bcd")
SAMPLE = {"km2": "7,46", "years": "2013–2016, 2024, 2025", "slope": "−0,5", "n": "6", "r0": "2", "r1": "15",
          "dz": "120", "since": "2014", "km2_all": "356,6", "city": "Києва", "region": "Донецька область",
          "source": "Мінрозвитку, наказ № 376", "date": "15.09.2026"}


def numbers(text: str) -> list[str]:
    """Number multiset of a text (I18N.md §6.5): decimal comma -> point, U+2212 -> '-'; sign ignored."""
    t = re.sub(r"(?<=\d),(?=\d)", ".", text).replace("−", "-")
    t = _dates_as_numbers(t)  # «15.09.2026» (uk) and «15 September 2026» (en, TERMS-EN §10.4) are the same date
    return sorted(NUM.findall(t))


def _dates_as_numbers(t: str) -> str:
    from uhd.services.i18n import _MONTHS_EN

    t = re.sub(r"\b(\d{2})\.(\d{2})\.(\d{4})\b", lambda m: f"{int(m[1])} {int(m[2])} {m[3]}", t)
    return re.sub(r"\b(\d{1,2}) (" + "|".join(_MONTHS_EN) + r") (\d{4})\b",
                  lambda m: f"{int(m[1])} {_MONTHS_EN.index(m[2]) + 1} {m[3]}", t)


def same_numbers(uk: str, en: str) -> bool:
    return numbers(uk) == numbers(en)


def no_cyrillic(text: str) -> bool:
    return not re.search(r"[А-Яа-яІіЇїЄєҐґ]", text)


# ── caveats ──────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("entry", E.CAVEATS, ids=lambda e: f"{e[0]}@{e[1]}")
def test_caveat_round_trip_every_template(entry):
    code, first, last, uk_t, _ = entry
    fields = [f for _, f, _, _ in string.Formatter().parse(uk_t) if f]
    uk = uk_t.format(**{f: SAMPLE[f] for f in fields})
    for v in (first, last):
        en = E.caveat_text_en(code, uk, v)
        assert en is not None, (code, v)
        assert same_numbers(uk, en), (uk, en)
        assert no_cyrillic(en), en


def test_current_caveats_are_covered():
    """A wording change in report.py without a new template here would silently give None: fail instead."""
    assert R.METHOD_VERSION == E.VERSIONS[-1]
    current = {(c, uk) for c, _, last, uk, _ in E.CAVEATS if last == R.METHOD_VERSION}
    assert {(c, uk) for c, uk in R.CAVEATS_UK.items()} == current


def test_caveat_none_when_unsure():
    uk = R.CAVEATS_UK["few_reference_px"].format(km2="3,1")
    assert E.caveat_text_en("few_reference_px", uk, R.METHOD_VERSION) is not None
    assert E.caveat_text_en("few_reference_px", uk, "sci-v3.1") is None          # version not covered
    assert E.caveat_text_en("few_reference_px", uk, None) is None
    assert E.caveat_text_en("no_such_code", uk, R.METHOD_VERSION) is None        # unknown code
    assert E.caveat_text_en("few_reference_px", uk + " Ще щось.", R.METHOD_VERSION) is None   # changed text
    assert E.caveat_text_en("few_reference_px", "Лісу-еталона дуже мало (багато км²) — порівняння ненадійне.",
                            R.METHOD_VERSION) is None                              # not a number
    war = R.CAVEATS_UK["war_zone"].format(since=2014, region="Невідома область")
    assert E.caveat_text_en("war_zone", war, R.METHOD_VERSION) is None            # unknown name: no guess
    sub = R.CAVEATS_UK["suburb_reference"].format(city="міста")
    assert E.caveat_text_en("suburb_reference", sub, R.METHOD_VERSION) is None


def test_caveat_numbers_keep_sign_and_point():
    uk = R.CAVEATS_UK["reference_warming"].format(slope="−0,4")
    assert "(−0.4 °C per 10 years)" in E.caveat_text_en("reference_warming", uk, R.METHOD_VERSION)
    uk = R.CAVEATS_UK["classes_extrapolated"].format(years="2013–2016, 2024, 2025")
    assert "for 2013–2016, 2024, 2025 they" in E.caveat_text_en("classes_extrapolated", uk, R.METHOD_VERSION)


# ── verdict ──────────────────────────────────────────────────────────────────────────────────────────────

def _tr(slope, p, verdict, n=13):
    return dict(slope_per_decade=slope, ci95=[None, None], p=p, n_years=n, verdict=verdict)


BASE = dict(zone=dict(name=None, analysed="built", city="kyiv"), reference=dict(city="kyiv", kind="preset"),
            gap_summary=dict(mean=5.13), trend=_tr(1.85, 0.002, "significant"),
            ref_trend=_tr(0.13, 0.669, "not_significant"), zone_trend=_tr(2.35, 0.004, "significant"),
            ndvi_trend=_tr(0.01, 0.328, "not_significant"), green_gap=dict(mean=3.62), new_built_gap=None,
            method_version=R.METHOD_VERSION, caveats=[], series=[])


def _variants():
    nb = dict(area_km2=0.84, before=dict(gap=3.0, years=[2013, 2014]), after=dict(gap=4.45, years=[2024, 2025]))
    yield "base", {}
    yield "near_zero", dict(gap_summary=dict(mean=-0.25))
    yield "cooler", dict(gap_summary=dict(mean=-1.25))
    yield "all_land_derived", dict(zone=dict(name=None, analysed="all_land", city=None),
                                   reference=dict(city="derived", kind="derived"))
    yield "not_significant", dict(trend=_tr(0.31, 0.37, "not_significant", 11))
    yield "insufficient", dict(trend=_tr(None, None, "insufficient_data", 5))
    yield "no_data", dict(gap_summary=dict(mean=None))
    yield "ref_driver", dict(trend=_tr(-1.3, 0.024, "significant"), ref_trend=_tr(1.6, 0.03, "significant"),
                             zone_trend=_tr(-0.1, 0.8, "not_significant"))
    yield "zone_both_sig", dict(ref_trend=_tr(0.6, 0.04, "significant"))
    yield "new_built_ndvi", dict(new_built_gap=nb, ndvi_trend=_tr(-0.02, 0.01, "significant"))
    yield "one_season", dict(trend=_tr(0.5, 0.5, "not_significant", 21))


@pytest.mark.parametrize("name,patch", list(_variants()), ids=[n for n, _ in _variants()])
def test_verdict_mirrors_current_report_wording(name, patch):
    rep = copy.deepcopy(BASE) | copy.deepcopy(patch)
    city_gen = {"kyiv": "Києва"}.get(rep["reference"]["city"], "міста") if rep["reference"]["kind"] == "preset" \
        else "міста"
    rep["verdict_text_uk"] = R.verdict_text(None, city_gen, rep["zone"]["analysed"], rep["gap_summary"], rep["trend"],
                                            rep["ref_trend"], rep["ndvi_trend"], rep["green_gap"], rep["zone_trend"],
                                            rep["new_built_gap"])
    en = E.verdict_text_en(rep)
    assert en is not None, rep["verdict_text_uk"]
    assert same_numbers(rep["verdict_text_uk"], en), (rep["verdict_text_uk"], en)
    assert no_cyrillic(en) and en[0].isupper()


def test_verdict_mentor_wording_sci_v341():
    rep = copy.deepcopy(BASE) | dict(method_version="sci-v3.4.1")
    rep["verdict_text_uk"] = ("Поверхня забудови влітку вдень у середньому на 5,1 °C гарячіша, ніж ліс навколо Києва, "
                              "і за 13 літ цей розрив зріс — приблизно на 1,9 °C за 10 років (значуще, p = 0,002). "
                              "Ліс-еталон не має значущого тренду, тож зміна йде від самої території: її поверхня "
                              "нагрівається на 2,4 °C за 10 років. Парки й сквери всередині міста на 3,6 °C "
                              "прохолодніші за цю забудову.")
    assert E.verdict_text_en(rep) == (
        "The built-up surface is on average 5.1 °C hotter on summer days than the forest around Kyiv, and over 13 "
        "summer seasons this gap has grown — by about 1.9 °C per 10 years (statistically significant, p = 0.002). "
        "The reference forest has no statistically significant trend, so the change comes from the area itself: its "
        "surface is warming by 2.4 °C per 10 years. Parks and squares inside the city are 3.6 °C cooler than this "
        "built-up land.")


def test_verdict_none_when_unsure():
    rep = copy.deepcopy(BASE)
    rep["verdict_text_uk"] = "Поверхня забудови трохи тепліша."                  # does not match the numbers
    assert E.verdict_text_en(rep) is None
    rep["method_version"] = "sci-v3.1"
    assert E.verdict_text_en(rep) is None
    rep = copy.deepcopy(BASE) | dict(zone=dict(name="Позняки", analysed="built", city="kyiv"))
    rep["verdict_text_uk"] = "Позняки: недостатньо даних для висновку."
    rep["gap_summary"] = dict(mean=None)
    assert E.verdict_text_en(rep) is None                                         # named, but no English name
    assert E.verdict_text_en(rep, "Pozniaky") == "Pozniaky: too little data for a conclusion."


# ── excluded-year details ────────────────────────────────────────────────────────────────────────────────

def test_excluded_detail_mirrors_analysis():
    from uhd.science import analysis as A

    rows = ([dict(used=True, date="2020-08-16", zone_cover=0.9, zone_in_swath=1.0)]
            + [dict(used=False, date="2020-07-01", zone_cover=0.1, zone_in_swath=1.0)] * 4
            + [dict(used=False, date="2020-07-02", zone_cover=0.0, zone_in_swath=0.2)] * 7
            + [dict(used=False, date="2020-07-03", zone_cover=0.9, zone_in_swath=1.0)])
    for det in (A.scenes_detail(rows), A.scenes_detail(rows[1:]), A.scenes_detail(None, 1, 0),
                A.scenes_detail(None, 9, 3), A.scenes_detail(rows[:1] * 2 + rows[1:3])):
        en = E.excluded_detail_text_en(det, R.METHOD_VERSION)
        assert en is not None, det["text_uk"]
        assert same_numbers(det["text_uk"], en), (det["text_uk"], en)
        assert no_cyrillic(en)
    det = A.scenes_detail(rows)
    assert E.excluded_detail_text_en(det, "sci-v3.3") is None                      # before excluded_detail existed
    assert E.excluded_detail_text_en(det | {"n_cloudy": 5}, R.METHOD_VERSION) is None


# ── whole report ─────────────────────────────────────────────────────────────────────────────────────────

def test_localize_report_copies_and_adds_only_en():
    rep = copy.deepcopy(BASE)
    rep["verdict_text_uk"] = "щось інше"
    rep["caveats"] = [R._caveat("lst_not_air"), dict(code="mystery", text_uk="Невідомо.")]
    rep["series"] = [dict(year=2013, gap=1.0, excluded_detail=None),
                     dict(year=2014, gap=None, excluded_detail=dict(text_uk="Старий текст."))]
    before = json.dumps(rep, sort_keys=True)
    out = E.localize_report(rep)
    assert json.dumps(rep, sort_keys=True) == before                              # input untouched
    assert out["verdict_text_en"] is None
    assert out["caveats"][0]["text_en"].startswith("This is the daytime land surface temperature")
    assert out["caveats"][1]["text_en"] is None
    assert out["series"][0]["excluded_detail"] is None and out["series"][1]["excluded_detail"]["text_en"] is None
    strip = json.loads(json.dumps(out))
    strip.pop("verdict_text_en")
    for c in strip["caveats"]:
        c.pop("text_en")
    strip["series"][1]["excluded_detail"].pop("text_en")
    assert json.dumps(strip, sort_keys=True) == before                            # nothing else changed


# ── stored reports (server only: $I18N_REPORTS_DIR or the default store) ─────────────────────────────────

def _reports_dir() -> Path | None:
    for p in (os.environ.get("I18N_REPORTS_DIR"), "/root/uhd/reports"):
        if p and Path(p).is_dir():
            return Path(p)
    return None


def _pairs(rep: dict, out: dict):
    yield rep.get("verdict_text_uk"), out["verdict_text_en"]
    for c in out.get("caveats") or []:
        yield c.get("text_uk"), c["text_en"]
    for s in out.get("series") or []:
        d = s.get("excluded_detail")
        if isinstance(d, dict):
            yield d.get("text_uk"), d["text_en"]


@pytest.mark.skipif(_reports_dir() is None, reason="no stored reports here")
def test_stored_reports_same_numbers():
    d = _reports_dir()
    files = sorted(d.glob("*.json"))
    random.Random(32).shuffle(files)
    pick = [d / f"{i}.json" for i in MENTOR_IDS if (d / f"{i}.json").exists()] + files[:50]
    n_en = 0
    for f in pick:
        rep = json.loads(f.read_text())
        out = E.localize_report(rep)
        for uk, en in _pairs(rep, out):
            if en is not None:
                n_en += 1
                assert same_numbers(uk, en), (f.name, uk, en)
                assert no_cyrillic(en), (f.name, en)
        if f.stem in MENTOR_IDS:
            assert out["verdict_text_en"] and all(c["text_en"] for c in out["caveats"]), f.name
    assert n_en > 0
