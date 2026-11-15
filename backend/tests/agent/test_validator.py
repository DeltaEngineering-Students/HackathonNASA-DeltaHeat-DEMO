import json
from pathlib import Path

import pytest

from uhd.agent.validator import collect_numbers, extract_numbers, validate

TOOL = [{"gap_summary": {"mean": 6.23, "last": 5.81}, "trend": {"slope_per_decade": 1.04, "p": 0.012, "n_years": 13},
         "series": [{"year": 2013, "gap": 5.1}, {"year": 2025, "gap": 5.81}], "valid_share": 0.834,
         "date": "2021-07-10", "note": "area 3.14 km²"}]


def test_extract_ukrainian_formats():
    vals = [v for _, v, _ in extract_numbers("розрив 6,2 °C, площа 1 250 км², −1.5 і -0.3, 12 345,6")]
    assert vals == [6.2, 1250.0, -1.5, -0.3, 12345.6]


def test_ignores_ids_urls_and_list_markers():
    text = "1. Сцена LC08_L2SP_181025_20210710 (ssp245) — див. https://x.org/a/2024/99 та `report 9f3a`\n2. Ок"
    assert validate(text, TOOL).ok


def test_sourced_numbers_pass_at_written_precision():
    ans = "Позняки гарячіші на 6,2 °C (останній рік 5,8 °C); тренд +1,0 °C за 10 років, p = 0,012, 13 років, 83 % пікселів."
    v = validate(ans, TOOL)
    assert v.ok, v.to_dict()


def test_unsourced_number_is_flagged():
    v = validate("Розрив зріс на 2,7 °C.", TOOL)
    assert not v.ok and [c.text for c in v.unsourced] == ["2,7"]


def test_derived_difference_is_flagged():
    # 6.23 - 5.1 = 1.13 is arithmetic by the model → must not pass
    assert not validate("Різниця між першим і середнім — 1,13 °C.", TOOL).ok


def test_sign_insensitive_and_question_numbers():
    assert validate("На −5,81 °C прохолодніше.", TOOL).ok
    assert validate("Ви питали про 2019 рік і 42 °C.", TOOL, question="що було у 2019 при 42 °C?").ok


def test_dates_must_be_sourced():
    assert validate("Найближчий знімок — 10.07.2021.", TOOL).ok
    assert validate("Найближчий знімок — 2021-07-10.", TOOL).ok
    v = validate("Знімок 2021-07-26.", TOOL)
    assert not v.ok and v.unsourced[0].kind == "date"


def test_collect_numbers_reads_strings():
    nums, dates = collect_numbers(TOOL)
    assert 3.14 in nums and "2021-07-10" in dates


def test_small_counts_not_checked():
    assert validate("Є 3 можливі причини і 2 сценарії.", TOOL).ok


# REVIEW M5: these five sentences used to pass against the live Pozniaky report.
POZNIAKY = [json.loads((Path(__file__).parent / "pozniaky_report.json").read_text())]


@pytest.mark.parametrize("ans", [
    "Розрив виріс на 5 °C за 10 років.",            # small integer with a unit is checked
    "Тренд розриву −0.26 °C за 10 років.",          # slope is +0.26: sign flip without «менше/прохолодніше»
    "Розрив у 2019 році 39.7 °C.",                  # that is zone_lst, not the gap
    "Забудова займає 34 %.",                        # ×100 only for *_share fields
    "Тренд не значущий, p = 0.29.",                 # 0.29 exists (ndvi), but not as a p field
])
def test_review_m5_wrong_numbers_are_flagged(ans):
    assert not validate(ans, POZNIAKY).ok, ans


@pytest.mark.parametrize("ans", [
    "Позняки в середньому на 11,2 °C гарячіші за ліс; у 2019 році розрив був 10,14 °C.",
    "Тренд розриву +0,26 °C за 10 років, p = 0,73 — поки не значущий.",
    "Зелень усередині міста на 11,2 °C прохолодніша; поверхня у 2019 р. — 39,71 °C.",
    "Забудова займає 96 % зони, завжди забудовано 2,891 км².",
    "Лісова зона відліку прохолодніша: −0,15 °C за 10 років (p = 1,0).",
])
def test_review_m5_correct_numbers_still_pass(ans):
    v = validate(ans, POZNIAKY)
    assert v.ok, v.to_dict()


# QA-SCIENCE SCI-04: the 25 tricky sentences (uhd/qa/science/validator_cases.py) against the sci-v3.2 Pozniaky report
V32 = [json.loads((Path(__file__).parent / "pozniaky_report_v32.json").read_text())]
SCI04 = [
    ("Позняки в середньому на 11,4 °C гарячіші за ліс навколо Києва.", True),
    ("Розрив становить 11,41 °C.", True),
    ("Розрив у середньому 9,1 °C.", False),
    ("Розрив до лісу навколо міста в середньому 9,7 °C.", False),       # 9.73 is the parks gap
    ("Розрив дорівнює 29,16 °C.", False),                               # a ref_lst value
    ("Тренд розриву −0,4 °C за 10 років.", False),
    ("Розрив зменшився на 0,4 °C за 10 років.", False),                 # trend is +0.40
    ("p = 0,37, тобто тренд не значущий.", True),
    ("p = 0,73 — значущий тренд розриву.", False),                      # that is the reference trend's p
    ("Частка забудови в зоні — 100 %.", True),
    ("Частка забудови в зоні — 40 %.", False),
    ("Еталон — 354 км² стабільного лісу (98 333 пікселі).", True),
    ("Площа зони 3,14 км².", True),
    ("Площа зони 31 км².", False),
    ("У 2020 році даних замало.", True),
    ("У 2011 році даних замало.", False),
    ("Розрив виріс на 2 °C за 10 років.", False),                       # only the CI upper bound is ~2
    ("У різні роки розрив був 10–13 °C.", True),
    ("Розрив коливався від 10,4 до 13,0 °C.", True),
    ("Температура повітря того дня була 31,1 °C.", False),
    ("Парки й сквери всередині міста на 9,7 °C прохолодніші.", True),
    ("Зелень усередині міста на 15 °C прохолодніша.", False),
    ("NDVI зростає на 0,06 за 10 років (p = 0,024).", True),
    ("Дані: 13 літ, 12 з них придатні.", True),
    ("Різниця 1 000 °C.", False),
    ("Розрив зростає на 0,4 °C за 10 років, але це не значуще (p = 0,37).", True),
    ("Довірчий інтервал тренду — від −1,03 до 2,12 °C за 10 років.", True),
]


@pytest.mark.parametrize("ans,expected", SCI04)
def test_sci04_semantic_fields(ans, expected):
    assert validate(ans, V32).ok is expected, validate(ans, V32).to_dict()


V33 = json.loads((Path(__file__).parent / "v33_reports.json").read_text())


@pytest.mark.parametrize("rep", V33, ids=lambda r: r["params"]["place_id"])
def test_sci_v33_verdict_numbers_map_to_fields(rep):
    # every number of the science verdict (zone_trend, driver, new construction, parks, p) maps to a structured field
    bare = {k: v for k, v in rep.items() if k not in ("verdict_text_uk", "caveats")}
    v = validate(rep["verdict_text_uk"], [bare])
    assert v.ok, v.to_dict()
    # quoting a caveat verbatim is sourced; changing its number is not
    cav = rep["caveats"][-1]["text_uk"]
    assert validate(cav, [rep]).ok


def test_new_built_numbers_need_their_clause():
    rep = next(r for r in V33 if r.get("new_built_gap"))
    nb = rep["new_built_gap"]
    a = f"{nb['after']['gap']:.1f}".replace(".", ",")
    assert validate(f"Там, де з’явилась нова забудова, розрив із лісом став {a} °C.", [rep]).ok


def test_scenario_names_are_not_numbers():
    from uhd.agent.validator import validate as _v

    assert _v("Сценарій високих викидів (SSP5‑8.5) і помірний (SSP2-4.5), ssp245.", [{}]).ok


def test_gap_word_binds_its_comma_part_only():
    scenes = {"scenes": [{"date": "2021-06-09", "zone_lst": 37.48, "ref_lst": 26.53, "gap": 10.95}]}
    ans = "Тоді температура поверхні району була 37,48 °C, лісу-еталону — 26,53 °C, а розрив з лісом — 10,95 °C."
    assert validate(ans, [scenes]).ok
    # a gap number still has to be a gap
    assert not validate("Розрив з лісом — 37,48 °C.", [scenes]).ok


def test_day_of_written_date_is_not_a_number():
    res = {"scenes": [{"date": "2019-08-23", "gap": 10.75}]}
    assert validate("Знімки 29 липня, 7 і 23 серпня 2019 року; розрив 10,75 °C.", [res, {"year": 2019}]).ok
    assert validate("On 23 August the gap was 10.75 °C.", [res]).ok


def test_climate_period_keys_are_year_sources():
    clim = {"ssp585": {"2041-2060": {"delta": 3.15}, "2081-2100": {"delta": 6.79}}, "baseline": {"period": [1995, 2014]}}
    assert validate("У 2081-2100 роках +6,79 °C, у 2041–2060 — +3,15 °C (база 1995–2014).", [clim]).ok


def test_unitless_number_after_ndvi_is_not_a_gap():
    rep = {"series": [{"year": 2023, "ndvi": 0.366, "gap": 12.94}]}
    assert validate("У 2023 році були одночасно найвище NDVI (0,366) і один з найбільших розривів.", [rep]).ok


def test_numbers_inside_table_cells_are_checked():
    rank = {"zones": [{"name": "Оболонський", "gap_mean": 9.38, "gap_last": 9.12, "trend_per_decade": 0.31},
                      {"name": "Деснянський", "gap_mean": 9.7, "gap_last": 8.28, "trend_per_decade": -0.12}]}
    table = ("| Район | Середній розрив, °C | Останнє літо, °C | Тренд, °C/10 р. |\n|---|---|---|---|\n"
             "| Деснянський | 9,7 | 8,28 | −0,12 |\n| Оболонський | 9,38 | 9,12 | +0,31 |")
    assert validate(table, [rank]).ok
    bad = validate(table.replace("9,12", "9,52"), [rank])
    assert not bad.ok and [c.text for c in bad.unsourced] == ["9,52"]
