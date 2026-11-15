"""English texts for stored reports, computed on read (uhd/docs/I18N.md §6, phase 3; wording: TERMS-EN.md).

Stored reports are never changed. ``localize_report(rep)`` returns a copy with English siblings next to the Ukrainian
texts: ``verdict_text_en``, ``caveats[].text_en`` and ``series[].excluded_detail.text_en``.

The rule is "the same text, only the language differs", and a missing text is better than a wrong one:

- **caveats**: the parameters are recovered from ``text_uk`` with a regex compiled from the Ukrainian template that
  the report's ``method_version`` used (``{name}`` -> named group), and put into the English template written for
  that Ukrainian wording. The captured strings are reused as they are (decimal comma -> point, U+2212 kept).
- **verdict and excluded-year details**: they are built from the structured numbers stored in the report. The
  Ukrainian text is rebuilt first with the wording of that version, and the English text is given only when the
  rebuilt Ukrainian text equals the stored one character for character. The English sentences take the same branches,
  so they cannot say something the Ukrainian text does not.
- If nothing matches (unknown code or version, or a text from older code), the field is ``None``.

Versions covered: sci-v3.3 … sci-v3.6 (the mentor ids are sci-v3.4.1). Older reports (sci-v3, 3.1, 3.2, no
version) get ``None`` everywhere.
"""
from __future__ import annotations

import copy
import re
import string

from . import stats as ST

VERSIONS = ("sci-v3.3", "sci-v3.4", "sci-v3.4.1", "sci-v3.5", "sci-v3.5.1", "sci-v3.5.2", "sci-v3.5.3", "sci-v3.5.4",
            "sci-v3.6")
_VI = {v: i for i, v in enumerate(VERSIONS)}

NBSP = " "


def _since(v: str) -> int:
    return _VI[v]


# ── numbers ───────────────────────────────────────────────────────────────────────────────────────────────

def _uk_num(v: float, nd: int = 1) -> str:
    r = ST.rnd(v, nd)
    return f"{r:.{nd}f}".replace(".", ",").replace("-", "−")


def _en_num(v: float, nd: int = 1) -> str:
    """The same number as ``_uk_num`` (half-up, U+2212), with a decimal point."""
    r = ST.rnd(v, nd)
    return f"{r:.{nd}f}".replace("-", "−")


_DEC_COMMA = re.compile(r"(?<=\d),(?=\d)")


def _num_str(s: str) -> str:
    """A captured Ukrainian number or list of numbers -> English: decimal comma -> point; «2013–2016, 2024» kept."""
    return _DEC_COMMA.sub(".", s)


# ── names that appear inside Ukrainian texts ──────────────────────────────────────────────────────────────

CITY_GEN_EN = {"Києва": "Kyiv", "Харкова": "Kharkiv", "Львова": "Lviv", "міста": None}   # None: «the city»
REGION_EN = {   # data/places/war_oblasts.geojson names (TERMS-EN §8, KMU 2010)
    "Херсонська область": "Kherson Oblast",
    "Луганська область": "Luhansk Oblast",
    "Донецька область": "Donetsk Oblast",
    "Запорізька область": "Zaporizhzhia Oblast",
    "Автономна Республіка Крим": "Autonomous Republic of Crimea",
    "Севастополь": "Sevastopol",
}
SOURCE_EN = {"Мінрозвитку, наказ № 376": "Ministry of Development of Ukraine, order No. 376"}


def _city(s: str) -> str | None:
    if s not in CITY_GEN_EN or CITY_GEN_EN[s] is None:
        return None
    return CITY_GEN_EN[s]


def _lookup(table: dict):
    return lambda s: table.get(s)


_DATE = re.compile(r"\d{2}\.\d{2}\.\d{4}")


_MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December")


def _date_en(s: str) -> str | None:
    """«15.09.2026» → «15 September 2026» (TERMS-EN §10.4). Same output as backend services.i18n.date_en, kept here so
    the science package does not import the backend."""
    d, m, y = s.split(".")
    return f"{int(d)} {_MONTHS_EN[int(m) - 1]} {y}" if 1 <= int(m) <= 12 else None

# parameter -> converter (str -> str | None); None from a converter makes the whole text None
PARAMS = {
    "km2": _num_str, "years": _num_str, "slope": _num_str, "n": _num_str, "r0": _num_str, "r1": _num_str,
    "dz": _num_str, "since": _num_str, "km2_all": _num_str,
    "city": _city,
    "region": _lookup(REGION_EN),
    "source": _lookup(SOURCE_EN),
    "date": lambda s: _date_en(s) if _DATE.fullmatch(s) else None,  # TERMS-EN §10.4: «15 September 2026» (backend)
}
_NUMERIC = re.compile(r"[0-9−\-,.–\s]+")
_NUMERIC_PARAMS = {"km2", "years", "slope", "n", "r0", "r1", "dz", "since", "km2_all"}


# ── caveats: (code, first version, last version, Ukrainian template, English template) ─────────────────────
# Ukrainian templates are verbatim from report.py CAVEATS_UK at each version (git history). One English template per
# distinct Ukrainian wording; the numbers in it are those of the Ukrainian text.

_ALW = ("Головний розрив рахуємо на ділянках, забудованих в усі роки періоду ({km2} км²): так поява нової забудови не "
        "створює хибного тренду. Варіант «забудова кожного року» — у деталях.")
_WAR_TAIL_UK = ("Зміни 2022–2025 р. можуть бути наслідком війни і руйнувань, а карти забудови після 2023 р. "
                "екстрапольовані й руйнувань не бачать.")
_WAR_TAIL_EN = ("Changes in 2022–2025 may result from the war and destruction, and the built-up maps after 2023 are "
                "estimated and do not show destruction.")
_NSP_EN = ("“Not yet significant” does not mean “nothing has changed”: over 10–13 summer seasons the gap with the "
           "forest varies by about 1 °C between individual summer seasons, and the morning shadow of new high-rises "
           "and the slow growth of trees hide the change. See also how greenness and built-up land have changed.")

CAVEATS = [
    ("basis_always_built", "sci-v3.3", "sci-v3.6", _ALW,
     "The main gap is computed over land that was built-up in every year of the period ({km2} km²), so new "
     "construction does not create a false trend. The “built-up each year” variant is in Details."),
    ("basis_built_each_year", "sci-v3.3", "sci-v3.6",
     "Постійно забудованої площі замало (< 0,5 км²), тому розрив рахуємо по забудові кожного року — тренд може "
     "відображати й саму появу нової забудови.",
     "There is too little permanently built-up land (< 0.5 km²), so the gap is computed over the built-up land of "
     "each year — the trend may also reflect new construction itself."),
    ("suburb_reference", "sci-v3.3", "sci-v3.5.3",
     "Зона за межею міста, але в його приміській смузі (до 15 км) — порівнюємо з тим самим еталоном, що й райони "
     "{city}, щоб цифри можна було ставити поруч.",
     "The area is outside the city boundary but in its suburban belt (up to 15 km), so it is compared with the same "
     "reference as the districts of {city}, so that the numbers can be put side by side."),
    ("suburb_reference", "sci-v3.5.4", "sci-v3.6",
     "Ділянка за межею міста, але в його приміській смузі (до 15 км) — порівнюємо з тим самим лісом-еталоном, що й "
     "райони {city}, щоб цифри можна було ставити поруч.",
     "The area is outside the city boundary but in its suburban belt (up to 15 km), so it is compared with the same "
     "reference forest as the districts of {city}, so that the numbers can be put side by side."),
    ("lst_not_air", "sci-v3.3", "sci-v3.5.3",
     "Це денна температура поверхні (знімок близько 10:30), а не температура повітря. Розрив між поверхнями "
     "зазвичай більший, ніж між температурами повітря.",
     "This is the daytime surface temperature (image taken at about 10:30), not the air temperature. The gap "
     "between surfaces is usually larger than between air temperatures."),
    ("lst_not_air", "sci-v3.5.4", "sci-v3.6",
     "Це денна температура підстильної поверхні (знімок близько 11:00 за місцевим сонячним часом), а не приземна "
     "температура повітря (на висоті 2 м). Розрив між поверхнями зазвичай більший, ніж між температурами приземного "
     "повітря.",
     "This is the daytime land surface temperature (image taken at about 11:00 local solar time), not the "
     "near-surface air temperature (at 2 m). The gap between surfaces is usually larger than between near-surface "
     "air temperatures."),
    ("composite_method", "sci-v3.3", "sci-v3.5.3",
     "Для цієї території немає окремих знімків по датах, тому використано середнє за літо. На стиках знімків "
     "Landsat у окремі роки можлива похибка розриву 1–2 °C.",
     "There are no separate dated images for this territory, so the summer mean is used. Where Landsat images "
     "meet, the gap may be off by 1–2 °C in some years."),
    ("composite_method", "sci-v3.5.4", "sci-v3.6",
     "Для цієї території немає окремих знімків по датах, тому використано середнє за літо. На стиках знімків "
     "Landsat в окремі роки можлива похибка розриву 1–2 °C.",
     "There are no separate dated images for this territory, so the summer mean is used. Where Landsat images "
     "meet, the gap may be off by 1–2 °C in some years."),
    ("mixed_method", "sci-v3.3", "sci-v3.6",
     "У {years} р. для зони замало чистих знімків, тому для цих років використано середнє за літо замість "
     "порівняння в межах одного знімка.",
     "In {years} there were too few clear images of the area, so for these years the summer mean is used instead "
     "of a comparison within one image."),
    ("low_coverage", "sci-v3.3", "sci-v3.6",
     "У {years} р. чисті знімки покривають лише частину зони — ці роки менш надійні.",
     "In {years} the clear images cover only part of the area — these years are less reliable."),
    ("years_excluded", "sci-v3.3", "sci-v3.6",
     "{years} р. виключено: замало даних (замало чистих знімків або замало забудови в зоні).",
     "{years} excluded: too few data (too few clear images or too little built-up land in the area)."),
    ("no_lst_product", "sci-v3.3", "sci-v3.6",
     "{years} р.: для цієї ділянки Landsat не дає температури поверхні — у продукті USGS тут прогалина (бракує "
     "даних про випромінювальну здатність поверхні). Це не хмари: знімки чисті, але температуру з них не "
     "розраховано.",
     "{years}: Landsat gives no surface temperature for this area — the USGS product has a gap here (surface "
     "emissivity data are missing). These are not clouds: the images are clear, but no temperature was computed "
     "from them."),
    ("zone_clipped", "sci-v3.3", "sci-v3.6",
     "Частина території (≈{km2} км²) лежить за кордоном України — її не аналізуємо.",
     "Part of the territory (≈{km2} km²) lies outside Ukraine — we do not analyse it."),
    ("war_zone", "sci-v3.3", "sci-v3.6",
     "Територія в регіоні, де з {since} р. тривають окупація або бойові дії ({region}). " + _WAR_TAIL_UK,
     "The territory is in a region affected by the war, with occupation or fighting since {since} ({region}). "
     + _WAR_TAIL_EN),
    ("occupied", "sci-v3.5", "sci-v3.6",
     "Окупована територія (станом на {date}, джерело: {source}). " + _WAR_TAIL_UK,
     "Temporarily occupied territory (as of {date}, source: {source}). " + _WAR_TAIL_EN),
    ("few_years", "sci-v3.3", "sci-v3.6",
     "Для висновку про тренд потрібно щонайменше 8 років з даними — зараз {n}.",
     "A conclusion about the trend needs at least 8 summer seasons with data — there are {n} now."),
    ("small_zone", "sci-v3.3", "sci-v3.5.3",
     "У зоні замало забудови (< 0,5 км²) — результат нерепрезентативний.",
     "There is too little built-up land in the area (< 0.5 km²) — the result is not representative."),
    ("small_zone", "sci-v3.5.4", "sci-v3.6",
     "На ділянці замало забудови (< 0,5 км²) — результат нерепрезентативний.",
     "There is too little built-up land in the area (< 0.5 km²) — the result is not representative."),
    ("all_land_zone", "sci-v3.3", "sci-v3.5.3",
     "У зоні майже немає забудови, тому з еталоном порівнюємо всю її поверхню (як контроль).",
     "There is almost no built-up land in the area, so its whole surface is compared with the reference (as a "
     "control)."),
    ("all_land_zone", "sci-v3.5.4", "sci-v3.6",
     "На ділянці майже немає забудови, тому з лісом-еталоном порівнюємо всю її поверхню (як контроль).",
     "There is almost no built-up land in the area, so its whole surface is compared with the reference forest (as "
     "a control)."),
    ("derived_reference", "sci-v3.3", "sci-v3.5.1",
     "Межу міста визначено автоматично за картою забудови; еталон — стабільний ліс у кільці {r0}–{r1} км навколо "
     "неї.",
     "The city boundary was found automatically from the built-up map; the reference is stable forest in a ring "
     "{r0}–{r1} km around it."),
    ("derived_reference", "sci-v3.5.2", "sci-v3.6",
     "Межу міста визначено автоматично за картою забудови; еталон — стабільний ліс у кільці {r0}–{r1} км від межі "
     "міста (забудованої території), не від центру.",
     "The city boundary was found automatically from the built-up map; the reference is stable forest in a ring "
     "{r0}–{r1} km from the city boundary (the edge of the built-up land), not from the centre."),
    ("ref_higher", "sci-v3.5.3", "sci-v3.6",
     "Ліс-еталон лежить у середньому на {dz} м вище за забудову, а вище поверхня прохолодніша, тож розрив може бути "
     "завищеним.",
     "The reference forest lies on average {dz} m higher than the built-up land, and higher ground is cooler, so "
     "the gap may be overstated."),
    ("ref_elev_matched", "sci-v3.6", "sci-v3.6",
     "Ліс-еталон підібрано на тій самій висоті (±100 м), що й забудова: {km2} км² із {km2_all} км² лісу кільця.",
     "Reference forest matched to the built-up elevation (±100 m): {km2} km² of the ring's {km2_all} km² of forest."),
    ("ref_match_fallback", "sci-v3.6", "sci-v3.6",
     "Лісу на тій самій висоті (±100 м), що й забудова, замало ({km2} км²), тому еталоном лишається весь ліс кільця.",
     "Too little forest lies at the built-up elevation (±100 m; {km2} km²), so the whole forest of the ring stays the "
     "reference."),
    ("ref_weak", "sci-v3.5.3", "sci-v3.6",
     "Ліс-еталон тут малий або подрібнений ({km2} км² лісосмуг і гаїв) і тепліший за великі ліси, тож розрив може "
     "бути заниженим.",
     "The reference forest here is small or fragmented ({km2} km² of shelterbelts and groves) and warmer than large "
     "forests, so the gap may be understated."),
    ("urban_area_is_zone", "sci-v3.3", "sci-v3.5.3",
     "Поруч немає суцільної забудови — кільце еталона побудовано навколо самої зони.",
     "There is no continuous built-up land nearby — the reference ring is built around the area itself."),
    ("urban_area_is_zone", "sci-v3.5.4", "sci-v3.6",
     "Поруч немає суцільної забудови — кільце лісу-еталона побудовано навколо самої ділянки.",
     "There is no continuous built-up land nearby — the reference forest ring is built around the area itself."),
    ("ring_widened", "sci-v3.3", "sci-v3.5.3",
     "Біля міста замало стабільного лісу, тому кільце еталона розширено до {r1} км.",
     "There is too little stable forest near the city, so the reference ring is widened to {r1} km."),
    ("ring_widened", "sci-v3.5.4", "sci-v3.6",
     "Біля міста замало стабільного лісу, тому кільце лісу-еталона розширено до {r1} км.",
     "There is too little stable forest near the city, so the reference forest ring is widened to {r1} km."),
    ("urban_area_clipped", "sci-v3.3", "sci-v3.6",
     "Агломерація дуже велика — межу міста обрізано в радіусі ~60 км від зони.",
     "The urban area is very large — the city boundary is cut at a radius of ~60 km from the area."),
    ("few_reference_px", "sci-v3.3", "sci-v3.5.3",
     "Еталонного лісу дуже мало ({km2} км²) — порівняння ненадійне.",
     "There is very little reference forest ({km2} km²) — the comparison is unreliable."),
    ("few_reference_px", "sci-v3.5.4", "sci-v3.5.4",
     "Лісу-еталона дуже мало ({km2} км²) — порівняння ненадійне.",
     "There is very little reference forest ({km2} km²) — the comparison is unreliable."),
    ("few_reference_px", "sci-v3.6", "sci-v3.6",     # Лідія's wording (15.11)
     "Навколо ділянки збереглося мало лісу ({km2} км²), показник розриву може бути неточним.",
     "Little forest is left around the area ({km2} km²), so the gap may be inaccurate."),
    ("ref_border_clipped", "sci-v3.6", "sci-v3.6",
     "Частина лісу в кільці лежить за кордоном України ({km2} км²) — її не беремо, еталон лише з лісу в Україні.",
     "Part of the forest in the ring lies outside Ukraine ({km2} km²) and is left out: the reference is forest in "
     "Ukraine only."),
    ("classes_extrapolated", "sci-v3.3", "sci-v3.6",
     "Щорічні карти забудови є лише за 2017–2023; для {years} їх оцінено за зеленню і «бетонним» індексом знімків "
     "відносно найближчого року. Руйнування ці оцінки не бачать.",
     "Yearly built-up maps exist only for 2017–2023; for {years} they are estimated from the greenness and the "
     "“concrete” index of the images relative to the nearest year. These estimates do not show destruction."),
    ("not_significant_physics", "sci-v3.3", "sci-v3.5.2",
     "«Поки не значуще» не означає «нічого не змінилось»: за 10–13 літ розрив з лісом від літа до літа коливається "
     "приблизно на 1 °C, а тінь нових висоток зранку і повільний ріст дерев приховують зміну. Подивіться також, як "
     "змінилися зелень і забудова.", _NSP_EN),
    ("not_significant_physics", "sci-v3.5.3", "sci-v3.6",
     "«Поки несуттєво» не означає «нічого не змінилось»: за 10–13 літніх сезонів розрив з лісом між окремими "
     "літніми сезонами коливається приблизно на 1 °C, а тінь нових висоток зранку і повільний ріст дерев приховують "
     "зміну. Подивіться також, як змінилися зелень і забудова.", _NSP_EN),
    ("reference_warming", "sci-v3.3", "sci-v3.6",
     "Сам ліс-еталон помітно змінюється ({slope} °C за 10 років) — частина зміни розриву пов'язана з погодою "
     "регіону, а не з містом.",
     "The reference forest itself is changing noticeably ({slope} °C per 10 years) — part of the change in the gap "
     "comes from the weather of the region, not from the city."),
]

# the English template for the current wording of each code (for callers that only need the table)
CAVEATS_EN = {code: en for code, _, last, _, en in CAVEATS if last == VERSIONS[-1]}


def _compile(uk: str) -> tuple[re.Pattern, list[str]]:
    rx, names = ["^"], []
    for lit, field, spec, conv in string.Formatter().parse(uk):
        rx.append(re.escape(lit))
        if field is not None:
            assert not spec and not conv and field not in names, (uk, field)
            names.append(field)
            rx.append(f"(?P<{field}>.+?)")
    rx.append("$")
    return re.compile("".join(rx), re.S), names


_TEMPLATES: dict[tuple[str, str], list[tuple[re.Pattern, list[str], str]]] = {}
for _code, _a, _b, _uk, _en in CAVEATS:
    _pat, _names = _compile(_uk)
    assert set(_names) == {f for _, f, _, _ in string.Formatter().parse(_en) if f}, _code
    for _v in VERSIONS[_since(_a):_since(_b) + 1]:
        _TEMPLATES.setdefault((_v, _code), []).append((_pat, _names, _en))


def caveat_text_en(code: str, text_uk: str | None, method_version: str | None) -> str | None:
    """English caveat from the stored Ukrainian one, or None when the version/code/text is not a known template."""
    if not text_uk or method_version not in _VI:
        return None
    for pat, names, en in _TEMPLATES.get((method_version, code), ()):
        m = pat.match(text_uk)
        if not m:
            continue
        vals = {}
        for k in names:
            s = m.group(k)
            if k in _NUMERIC_PARAMS and not _NUMERIC.fullmatch(s):
                return None
            v = PARAMS[k](s)
            if v is None:
                return None
            vals[k] = v
        return en.format(**vals)
    return None


# ── verdict ──────────────────────────────────────────────────────────────────────────────────────────────
# Ukrainian wording per version (report.py verdict_text in git history). Only the strings that changed differ:
#   v33  sci-v3.3, 3.4     «літ», «значуще», «поки не значуще», zone driver always «Змінюється саме ця територія»
#   v341 sci-v3.4.1 … 3.5.3  + M4: «Ліс-еталон не має значущого тренду…» when the forest trend is not significant
#   v354 sci-v3.5.4, 3.6   «літніх сезонів», «статистично значуще / незначуще» (TERMS-UK)

def _flavour(v: str) -> str:
    return "v33" if _VI[v] < _VI["sci-v3.4.1"] else ("v341" if _VI[v] < _VI["sci-v3.5.4"] else "v354")


def _lit(n: int, fl: str) -> str:
    one, few, many = (("літо", "літа", "літ") if fl != "v354" else ("літній сезон", "літні сезони", "літніх сезонів"))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _seasons_en(n: int) -> str:
    return f"{n} summer season" + ("" if n == 1 else "s")


def _driver(tr: dict, zone_tr: dict, ref_tr: dict) -> str | None:
    """report.driver (unchanged since sci-v3.3)."""
    if tr["verdict"] != "significant" or zone_tr.get("slope_per_decade") is None \
            or ref_tr.get("slope_per_decade") is None:
        return None
    g, z, r = tr["slope_per_decade"], zone_tr["slope_per_decade"], ref_tr["slope_per_decade"]
    if (g > 0 > r or g < 0 < r) and abs(r) >= abs(z):
        return "reference"
    return "zone"


NEW_BUILT_MIN_KM2, NEW_BUILT_MIN_JUMP = 0.2, 1.0   # report.py, unchanged since sci-v3.3


def _verdict_pair(rep: dict, name_uk: str | None, name_en: str | None, fl: str) -> tuple[str, str | None]:
    """(Ukrainian text as report.verdict_text of flavour ``fl`` wrote it, English text with the same branches)."""
    zone, ref = rep["zone"], rep.get("reference") or {}
    gs, tr = rep["gap_summary"], rep["trend"]
    ref_tr, ndvi_tr = rep.get("ref_trend") or {}, rep.get("ndvi_trend") or {}
    zone_tr = rep.get("zone_trend") or {"slope_per_decade": None}
    green, nb = rep.get("green_gap"), rep.get("new_built_gap")
    mode = zone.get("analysed")
    city = ref.get("city") if ref.get("kind") == "preset" else None
    city_gen = {"kyiv": "Києва", "kharkiv": "Харкова", "lviv": "Львова"}.get(city, "міста")
    city_en = {"kyiv": "Kyiv", "kharkiv": "Kharkiv", "lviv": "Lviv"}.get(city, "the city")

    pre_uk = f"{name_uk}: " if name_uk else ""
    pre_en = f"{name_en}: " if name_uk else ""
    if gs["mean"] is None:
        return ((f"{pre_uk}недостатньо даних для висновку." if name_uk else "Недостатньо даних для висновку."),
                (f"{pre_en}too little data for a conclusion." if name_uk else "Too little data for a conclusion."))
    mean = gs["mean"]
    subj_uk = "поверхня забудови" if mode == "built" else "поверхня тут"
    subj_en = "the built-up surface" if mode == "built" else "the surface here"
    forest_en = f"the forest around {city_en}"
    if abs(mean) < 0.5:
        s1_uk = f"{subj_uk} влітку вдень майже така ж тепла, як ліс навколо {city_gen} (різниця {_uk_num(abs(mean))} °C)"
        s1_en = f"{subj_en} is almost as warm on summer days as {forest_en} (a difference of {_en_num(abs(mean))} °C)"
    else:
        s1_uk = (f"{subj_uk} влітку вдень у середньому на {_uk_num(abs(mean))} °C "
                 f"{'гарячіша' if mean > 0 else 'прохолодніша'}, ніж ліс навколо {city_gen}")
        s1_en = (f"{subj_en} is on average {_en_num(abs(mean))} °C {'hotter' if mean > 0 else 'cooler'} on summer "
                 f"days than {forest_en}")
    stat = "статистично " if fl == "v354" else ""
    v, n = tr["verdict"], tr["n_years"]
    if v == "insufficient_data":
        s2_uk = ", але даних замало, щоб сказати, чи цей розрив змінюється."
        s2_en = ", but there are too few data to say whether this gap is changing."
    elif v == "significant":
        sl = tr["slope_per_decade"]
        s2_uk = (f", і за {n} {_lit(n, fl)} цей розрив {'зріс' if sl > 0 else 'зменшився'} — приблизно на "
                 f"{_uk_num(abs(sl))} °C за 10 років ({stat}значуще, p = {_uk_num(tr['p'], 3)}).")
        s2_en = (f", and over {_seasons_en(n)} this gap has {'grown' if sl > 0 else 'shrunk'} — by about "
                 f"{_en_num(abs(sl))} °C per 10 years (statistically significant, p = {_en_num(tr['p'], 3)}).")
    else:
        ns = "статистично незначуще" if fl == "v354" else "поки не значуще"
        s2_uk = f", і за {n} {_lit(n, fl)} цей розрив помітно не змінився ({ns}, p = {_uk_num(tr['p'], 2)})."
        s2_en = (f", and over {_seasons_en(n)} this gap has not changed noticeably (not statistically significant, "
                 f"p = {_en_num(tr['p'], 2)}).")
    lead_uk, lead_en = pre_uk + s1_uk + s2_uk, pre_en + s1_en + s2_en
    if not name_uk:
        lead_uk, lead_en = lead_uk[0].upper() + lead_uk[1:], lead_en[0].upper() + lead_en[1:]
    uk, en = [lead_uk], [lead_en]

    d = _driver(tr, zone_tr, ref_tr)
    if d == "reference":
        grown = tr["slope_per_decade"] > 0
        rs, zs = ref_tr["slope_per_decade"], zone_tr["slope_per_decade"]
        seasons = "літні сезони" if fl == "v354" else "літа"
        uk.append(f"Розрив {'зріс' if grown else 'зменшився'} здебільшого через ліс-еталон: у ці {seasons} він був "
                  f"{'прохолоднішим' if rs < 0 else 'теплішим'} ({_uk_num(rs)} °C за 10 років), а сама поверхня тут "
                  f"змінилась менше ({_uk_num(zs)} °C за 10 років).")
        en.append(f"The gap has {'grown' if grown else 'shrunk'} mostly because of the reference forest: in these "
                  f"summer seasons it was {'cooler' if rs < 0 else 'warmer'} ({_en_num(rs)} °C per 10 years), while "
                  f"the surface here changed less ({_en_num(zs)} °C per 10 years).")
    elif d == "zone" and zone_tr.get("verdict") == "significant":
        zs = zone_tr["slope_per_decade"]
        num_uk = f"її поверхня {'нагрівається' if zs > 0 else 'охолоджується'} на {_uk_num(abs(zs))} °C за 10 років."
        num_en = f"its surface is {'warming' if zs > 0 else 'cooling'} by {_en_num(abs(zs))} °C per 10 years."
        if fl == "v33" or ref_tr.get("verdict") == "significant":
            uk.append(f"Змінюється саме ця територія: {num_uk}")
            en.append(f"It is this area itself that is changing: {num_en}")
        else:
            uk.append(f"Ліс-еталон не має {stat}значущого тренду, тож зміна йде від самої території: {num_uk}")
            en.append("The reference forest has no statistically significant trend, so the change comes from the "
                      f"area itself: {num_en}")
    if nb and nb["area_km2"] >= NEW_BUILT_MIN_KM2 and nb["before"]["gap"] is not None \
            and nb["after"]["gap"] is not None and abs(nb["after"]["gap"] - nb["before"]["gap"]) >= NEW_BUILT_MIN_JUMP:
        b, a = nb["before"]["gap"], nb["after"]["gap"]
        yb, ya = nb["before"]["years"], nb["after"]["years"]
        uk.append(f"Там, де за ці роки з’явилась нова забудова (≈{_uk_num(nb['area_km2'])} км²), поверхня стала "
                  f"{'гарячішою' if a > b else 'прохолоднішою'}: розрив із лісом був {_uk_num(b)} °C у "
                  f"{yb[0]}–{yb[-1]} р., а став {_uk_num(a)} °C у {ya[0]}–{ya[-1]} р.")
        en.append(f"Where new buildings appeared during these years (≈{_en_num(nb['area_km2'])} km²), the surface "
                  f"became {'hotter' if a > b else 'cooler'}: the gap with the forest was {_en_num(b)} °C in "
                  f"{yb[0]}–{yb[-1]} and {_en_num(a)} °C in {ya[0]}–{ya[-1]}.")
    if ndvi_tr.get("verdict") == "significant":
        up = ndvi_tr["slope_per_decade"] > 0
        uk.append(f"Зелені на ділянці {stat}значуще " + ("більшає." if up else "меншає."))
        en.append(f"Greenness in the area is {'increasing' if up else 'decreasing'} (statistically significant).")
    if green and green.get("mean") is not None and mode == "built" and green["mean"] > 0:
        uk.append(f"Парки й сквери всередині міста на {_uk_num(green['mean'])} °C прохолодніші за цю забудову.")
        en.append(f"Parks and squares inside the city are {_en_num(green['mean'])} °C cooler than this built-up land.")
    return " ".join(uk), " ".join(en)


def verdict_text_en(rep: dict, name_en: str | None = None) -> str | None:
    """English verdict for a stored report, or None when it cannot be shown to say the same as ``verdict_text_uk``.
    ``name_en``: the romanised zone name (KMU 2010) when the report has a name; without it a named verdict is None."""
    mv, stored = rep.get("method_version"), rep.get("verdict_text_uk")
    if mv not in _VI or not stored:
        return None
    name_uk = (rep.get("zone") or {}).get("name")
    if name_uk and not name_en:
        return None
    try:
        uk, en = _verdict_pair(rep, name_uk, name_en, _flavour(mv))
    except (KeyError, TypeError, IndexError):
        return None
    return en if uk == stored else None


# ── excluded-year details (analysis.scenes_detail, since sci-v3.4) ───────────────────────────────────────

def _ddmm(date: str) -> str:
    return f"{date[8:10]}.{date[5:7]}"


MIN_DATES = 2   # analysis.MIN_DATES, unchanged since sci-v3.4


def _detail_pair(det: dict, w: dict) -> tuple[str, str]:
    """(Ukrainian as analysis.scenes_detail wrote it with zone words ``w``, English with the same branches)."""
    usable = det.get("usable_dates")
    if usable is None:
        n, o = det.get("n_passes_total") or 0, det.get("n_outside_swath") or 0
        uk = (f"Замало чистих знімків: менше двох чистих спостережень {w['gen']} за літо (з {n} прольотів над нею"
              + (f", у {o} {w['nom']} поза смугою знімання або на її краю" if o else "") + ").")
        en = (f"Too few clear images: fewer than two clear observations of the area in the summer (out of {n} "
              f"overpass{'' if n == 1 else 'es'} over it" + (f"; in {o} of them the area is outside the image swath or on its edge" if o
                                      else "") + ").")
        return uk, en
    n_cl, n_out, n_ref = det.get("n_cloudy") or 0, det.get("n_outside_swath") or 0, det.get("n_reference_cloudy") or 0
    if not usable:
        lead_uk, lead_en = f"Жодного чистого прольоту над {w['ins']}", "No clear overpass over the area"
    elif len(usable) == 1:
        lead_uk = f"Лише один чистий проліт над {w['ins']} ({_ddmm(usable[0])})"
        lead_en = f"Only one clear overpass over the area ({_ddmm(usable[0])})"
    else:
        ds = ", ".join(_ddmm(d) for d in usable)
        lead_uk = f"Лише {len(usable)} чисті прольоти над {w['ins']} ({ds})"
        lead_en = f"Only {len(usable)} clear overpasses over the area ({ds})"
    puk, pen = [], []
    if n_cl:
        puk.append(f"{n_cl} — хмарні над {w['ins']}")
        pen.append(f"{n_cl} were cloudy over the area")
    if n_out:
        puk.append(f"у {n_out} {w['nom']} поза смугою знімання або на її краю")
        pen.append(f"in {n_out} the area was outside the image swath or on its edge")
    if n_ref:
        puk.append(f"{n_ref} — хмарно над лісом-еталоном")
        pen.append(f"{n_ref} were cloudy over the reference forest")
    tot = det.get("n_passes_total")
    uk = lead_uk + "." + (f" З {tot} прольотів за літо {', '.join(puk)}." if puk else "") + \
        f" Для річного значення потрібно щонайменше {MIN_DATES}."
    en = lead_en + "." + (f" Of {tot} overpasses in the summer, {'; '.join(pen)}." if pen else "") + \
        f" A yearly value needs at least {MIN_DATES} clear overpasses."
    return uk, en


_ZONE_WORDS = ({"gen": "зони", "nom": "зона", "ins": "зоною"},            # sci-v3.4 … 3.5.3
               {"gen": "ділянки", "nom": "ділянка", "ins": "ділянкою"})   # sci-v3.5.4 …


def excluded_detail_text_en(det: dict | None, method_version: str | None) -> str | None:
    if not det or not det.get("text_uk") or method_version not in _VI or _VI[method_version] < _VI["sci-v3.4"]:
        return None
    w = _ZONE_WORDS[1] if _VI[method_version] >= _VI["sci-v3.5.4"] else _ZONE_WORDS[0]
    try:
        uk, en = _detail_pair(det, w)
    except (KeyError, TypeError, IndexError):
        return None
    return en if uk == det["text_uk"] else None


# ── whole report ─────────────────────────────────────────────────────────────────────────────────────────

def localize_report(rep: dict, name_en: str | None = None) -> dict:
    """A copy of a stored report with ``verdict_text_en``, ``caveats[].text_en`` and
    ``series[].excluded_detail.text_en`` (None where no template matches). Numbers and ``*_uk`` are not touched.
    ``name_en`` (or ``rep["zone"]["name_en"]``): the romanised zone name for a named verdict."""
    out = copy.deepcopy(rep)
    mv = out.get("method_version")
    out["verdict_text_en"] = verdict_text_en(out, name_en or (out.get("zone") or {}).get("name_en"))
    for c in out.get("caveats") or []:
        c["text_en"] = caveat_text_en(c.get("code"), c.get("text_uk"), mv)
    for s in out.get("series") or []:
        det = s.get("excluded_detail")
        if isinstance(det, dict):
            det["text_en"] = excluded_detail_text_en(det, mv)
    return out
