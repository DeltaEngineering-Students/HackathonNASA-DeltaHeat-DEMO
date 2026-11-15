"""Rule-based caveat checker (CLAUDE-API-PLAN §4.2): one test per rule, positive and negative."""

from __future__ import annotations

from uhd.agent.caveats import check_caveats


def rep(verdict="not_significant", caveats=("lst_not_air",), excluded=(), driver=None, **kw):
    series = [{"year": y, "gap": None if y in excluded else 7.1, "excluded": "too_few_scenes" if y in excluded else None}
              for y in range(2013, 2026)]
    return {"report_id": "0123456789abcdef", "gap_summary": {"mean": 7.4, "last": 7.1}, "series": series,
            "trend": {"slope_per_decade": 0.4, "p": 0.62, "verdict": verdict}, "gap_driver": driver,
            "caveats": [{"code": c} for c in caveats], **kw}


def codes(answer, sources):
    return [m.code for m in check_caveats(answer, sources)]


def test_surface_word_required_for_lst_numbers():
    assert codes("Позняки на 7,1 °C гарячіші за ліс.", [rep()]) == ["lst_not_air"]
    assert codes("Поверхня Позняків на 7,1 °C гарячіша за ліс.", [rep()]) == []
    assert codes("Привіт! Чим допомогти?", [rep()]) == []  # no temperature number → nothing to caveat


def test_air_claim_about_lst():
    assert "air_claim" in codes("Поверхня гаряча: повітря на 7,1 °C тепліше, ніж у лісі.", [rep()])
    assert codes("Температура поверхні на 7,1 °C вища — це поверхня, а не повітря.", [rep()]) == []


def test_not_significant_wording():
    a = "Поверхня на 7,1 °C гарячіша, розрив зріс на 0,4 °C за 10 років."
    assert codes(a, [rep()]) == ["significance_wording"]
    assert codes(a + " Це статистично незначуще.", [rep()]) == []
    assert "significance_claim" in codes(a + " Це статистично значуще зростання.", [rep()])
    assert codes(a + " Це статистично значуще зростання.", [rep(verdict="significant")]) == []


def test_insufficient_data_wording():
    a = "Поверхня на 7,1 °C гарячіша; тренд за 10 років +0,4 °C."
    assert "insufficient_data" in codes(a, [rep(verdict="insufficient_data")])
    assert codes(a + " Але даних недостатньо даних для висновку.", [rep(verdict="insufficient_data")]) == []


def test_occupied_and_war_zone():
    assert codes("Поверхня на 7,1 °C гарячіша за ліс.", [rep(caveats=("occupied",))]) == ["war_zone"]
    assert codes("Поверхня на 7,1 °C гарячіша за ліс. Це окупована територія, зміни можуть бути руйнуваннями.",
                 [rep(caveats=("war_zone",))]) == []


def test_excluded_year_needs_explanation_not_a_number():
    r = rep(excluded=(2020,))
    assert "excluded_year" in codes("Поверхня: у 2020 році розрив 9,4 °C.", [r])
    assert codes("Поверхня: для 2020 року значення немає — замало чистих знімків.", [r]) == []
    assert codes("Поверхня гарячіша на 7,1 °C у 2013–2020 роках.", [r]) == []  # a range is not a claim about 2020


def test_cmip6_is_air():
    clim = {"variable": "tasmax", "ssp585": {"2081-2100": {"delta": 4.6}}, "ssp245": {}}
    assert codes("У 2080–2090-х влітку буде на 4,6 °C спекотніше.", [clim]) == ["cmip6_air"]
    assert codes("Температура повітря влітку зросте на 4,6 °C.", [clim]) == []


def test_causal_share():
    assert "causal_share" in codes("Поверхня гарячіша на 40 % через нові ЖК.", [rep()])
    assert codes("Хмарність 40 % через погоду; поверхня гаряча.", [rep()]) == []


def test_gap_driver_reference():
    r = rep(verdict="significant", driver="reference")
    assert "gap_driver_reference" in codes("Поверхня: розрив зріс на 0,4 °C за 10 років, статистично значуще.", [r])
    assert codes("Поверхня: розрив зріс на 0,4 °C за 10 років, статистично значуще — здебільшого через еталон.",
                 [r]) == []


def test_new_built_no_significance():
    r = rep(new_built_gap={"area_km2": 0.4, "before": {"gap": 6.0}, "after": {"gap": 8.0}})
    assert "new_built_significance" in codes("Поверхня нової забудови стала значуще гарячішою: 6,0 → 8,0 °C.", [r])


def test_web_section_not_checked():
    a = "Поверхня на 7,1 °C гарячіша.\n\nГіпотези з інтернету: статистично значуще потепління https://x.org"
    assert codes(a, [rep()]) == []


def test_report_climate_note_counts_as_a_projection():
    clim = {"variable": "tasmax", "scenario": "ssp245", "period": "2041-2060", "delta": 2.21}
    ans = ("Температура поверхні лісу помітно не змінилась (статистично незначущий тренд). Моделі CMIP6 дають для "
           "приземної температури повітря (2 м) медіану +2,21 °C — це температура повітря, а не поверхні.")
    assert "air_claim" not in codes(ans, [rep(context={"climate": clim})])


def test_absence_of_significance_is_not_a_claim():
    for s in ("Тренд у межах шуму. Водночас відсутність значущого тренду не доводить, що змін не було.",
              "The trend is within the noise. However, a non-significant result doesn't prove there was no change.",
              "A trend that isn't significant doesn't prove nothing changed, though."):
        assert "significance_claim" not in codes(s, [rep()])
    assert "significance_claim" in codes("Тренд розриву значущий.", [rep()])
