"""Item 32 (I18N.md §6): English on read, never on write.

``localize(obj)`` walks a response and ADDS an ``*_en`` sibling next to every ``*_uk`` string (and ``name_en`` /
``short_name_en`` next to Cyrillic names, ``source_en`` / ``attribution_en`` next to Cyrillic sources). Stored JSON and
every ``*_uk`` field stay untouched; numbers in an English text are the captured Ukrainian ones (decimal comma → point),
so both languages carry identical numbers. A text with no exact entry or template gets ``null`` — never a guess.

Science-owned report texts (``verdict_text_uk``, report ``caveats[].text_uk``, ``series[].excluded_detail.text_uk``) are
localised by science (``localize_report``) before this walker runs; the walker never overwrites an existing ``*_en``.
Terminology: docs/TERMS-EN.md.
"""

from __future__ import annotations

import re
from typing import Any, Callable

LANGS = ("uk", "en")
_CYR = re.compile(r"[А-Яа-яЄєІіЇїҐґ]")

# ------------------------------------------------------------------ romanisation (KMU 2010, Cabinet resolution № 55)

_KMU = {"а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ie", "ж": "zh", "з": "z",
        "и": "y", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
        "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
        "ь": "", "ю": "iu", "я": "ia", "'": "", "’": "", "ʼ": ""}
_KMU_FIRST = {"є": "ye", "ї": "yi", "й": "y", "ю": "yu", "я": "ya"}


def romanize(s: str) -> str:
    """KMU 2010 transliteration (word-initial є/ї/й/ю/я → Ye/Yi/Y/Yu/Ya, «зг» → «zgh», apostrophe and ь dropped)."""
    out, prev_letter = [], False
    low = s.lower()
    for i, ch in enumerate(s):
        lc = low[i]
        if lc == "г" and i > 0 and low[i - 1] == "з":
            t = "gh"
        elif lc in _KMU:
            t = _KMU_FIRST[lc] if (lc in _KMU_FIRST and not prev_letter) else _KMU[lc]
        else:
            out.append(ch)
            prev_letter = ch.isalpha()
            continue
        if ch != lc and t:  # keep the capital
            t = t[0].upper() + t[1:]
        out.append(t)
        prev_letter = lc not in ("'", "’", "ʼ") or prev_letter
    return "".join(out)


# generic words in place names that are translated, not transliterated (TERMS-EN §4/§8)
_NAME_WORDS = {"район": "District", "мікрорайон": "microdistrict", "мікрорайони": "microdistricts", "ліс": "Forest",
               "увесь": "All of", "котеджне": "Cottage", "містечко": "town", "область": "Oblast", "км": "km",
               "і": "and", "старий": "Old"}
_ORD = re.compile(r"^(\d+)-й$")


def _ordinal(n: int) -> str:
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def place_name_en(name: str | None) -> str | None:
    """«Деснянський район (Київ)» → «Desnianskyi District (Kyiv)», «Позняки (≈1 км)» → «Pozniaky (≈1 km)»."""
    if not name:
        return name
    def word(m: re.Match) -> str:
        w = m.group(0)
        if (o := _ORD.match(w)):
            return _ordinal(int(o.group(1)))
        tr = _NAME_WORDS.get(w.lower())
        if tr is not None:
            return tr[0].upper() + tr[1:] if w[:1].isupper() else tr
        return romanize(w)
    return re.sub(r"[\w’'ʼ-]+", word, name)


# ------------------------------------------------------------------ texts

def _num(s: str) -> str:
    return s.replace(",", ".")


EXACT: dict[str, str] = {
    # overview reasons
    "немає супутникової температури поверхні (прогалина в продукті USGS)":
        "no satellite surface temperature (a gap in the USGS product)",
    "немає даних про температуру поверхні за ці роки": "no surface temperature data for these years",
    "замало літніх сезонів із даними, щоб оцінити тренд": "too few summer seasons with data to estimate a trend",
    "не вдалося порахувати": "could not be computed",
    # hotspot land classes
    "забудова": "built-up", "поле": "field", "зелень": "greenery", "вода": "water",
    "голий ґрунт / інше": "bare ground / other", "немає даних": "no data",
    # climate
    "Прогноз приземної температури повітря (на висоті 2 м; CMIP6, комірка сітки ≈25 км), а не поверхні. "
    "Медіана 12 моделей, діапазон 10–90 %; 20-річні вікна, база 1995–2014.":
        "Outlook for near-surface air temperature (at 2 m; CMIP6, ≈25 km grid cell), not the surface. "
        "Median of 12 models, 10–90% range; 20-year windows, baseline 1995–2014.",
    "денний максимум приземної температури повітря (на висоті 2 м), не температура поверхні":
        "daily maximum near-surface air temperature (at 2 m), not surface temperature",
    "Це прогноз приземної температури повітря (на висоті 2 м), а не температури поверхні з Landsat.":
        "This is an outlook for near-surface air temperature (at 2 m), not the Landsat surface temperature.",
    # meta / layers
    "Приглушити не-забудову": "Fade non-built-up land",
    "Приглушено все, що в цей рік не забудова (класи Esri/IO + екстраполяція 2013–2016 і 2024–2025, як в аналізі); "
    "на дрібних масштабах — пропорційно частці забудови.":
        "Everything that is not built-up in that year is faded (Esri/IO classes, estimated for 2013–2016 and 2024–2025 as "
        "in the analysis); at small scales, in proportion to the built-up share.",
    "Поблизу Києва/Харкова/Львова — еталон міста (як у звітах); деінде — згладжене поле стабільного лісу навколо "
    "(σ≈10 км). Див. METHOD.md.":
        "Near Kyiv/Kharkiv/Lviv: the city's reference forest (as in the reports); elsewhere: a smoothed field of the "
        "stable forest around (σ≈10 km). See METHOD.md.",
    "заповнено з сусідніх років": "filled from neighbouring years",
    "LST — денна температура підстильної поверхні (близько 11:00 за місцевим сонячним часом), а не приземна "
    "температура повітря (2 м).":
        "LST is the daytime land surface temperature (image taken at about 11:00 local solar time), not the "
        "near-surface air temperature (2 m).",
    "Різниця з лісом навколо міста (LST зони − LST еталону)":
        "Surface heat gap with the forest around the city (area LST − reference forest LST)",
    "Денна температура поверхні (LST), медіана за літо": "Daytime surface temperature (LST), summer median",
    "Зелень (NDVI), медіана за літо": "Greenness (NDVI), summer median",
    "Зміна зелені (NDVI року − NDVI базового року)": "Change in greenness (NDVI of the year − NDVI of the base year)",
    # overlays (science / data files)
    "немає супутникової температури поверхні": "no satellite surface temperature",
    "замало безхмарних знімків цієї смуги в цьому році": "too few cloud-free images of this swath in this year",
    "Мінрозвитку України (наказ № 376 від 28.02.2025, zakon.rada.gov.ua); © OpenStreetMap contributors":
        "Ministry of Development of Ukraine (order No. 376 of 28.02.2025, zakon.rada.gov.ua); © OpenStreetMap contributors",
    # places
    "Обраний об'єкт — точка або дуже мала ділянка, тому аналізуємо коло радіусом ≈1 км навколо нього.":
        "The selected place is a point or a very small area, so we analyse a circle of ≈1 km radius around it.",
    "Колишні дачі забудовують щільніше — розрив із лісом росте.":
        "Former dachas are being built up more densely: the gap with the forest is growing.",
    "Великий ліс у місті: поводиться як природа — розриву майже немає.":
        "A large forest in the city: it behaves like nature, there is almost no gap.",
    "Щільні багатоповерхівки: найгарячіше місце, але розрив не росте.":
        "Dense high-rise blocks: the hottest place, but the gap is not growing.",
    "Котеджі, де підросли сади: зелені більшає, розрив зменшується.":
        "Cottages where gardens have grown: greenness is increasing, the gap is shrinking.",
}

_CITY_EN = {"Києва": "Kyiv", "Харкова": "Kharkiv", "Львова": "Lviv"}
N = r"[−-]?\d+(?:[.,]\d+)?"


def _compared_to(m: re.Match) -> str:
    n = int(m["n"])
    what = "built-up land" if m["what"] == "забудовою" else "land"
    city = _CITY_EN.get(m["city"], romanize(m["city"]))
    return f"compared with the {what} of {n} {'district' if n == 1 else 'districts'} of {city}"


_MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December")
_DMY = re.compile(r"(?P<d>\d{2})\.(?P<m>\d{2})\.(?P<y>\d{4})")
_DMY_EN = re.compile(r"\b(?P<d>\d{1,2}) (?P<mon>" + "|".join(_MONTHS_EN) + r") (?P<y>\d{4})\b")


def date_en(dmy: str) -> str:
    """«15.09.2026» → «15 September 2026» (TERMS-EN §10.4: the long form in English; Ukrainian keeps dd.mm.yyyy)."""
    m = _DMY.fullmatch(dmy)
    if not m or not 1 <= int(m["m"]) <= 12:
        return dmy
    return f"{int(m['d'])} {_MONTHS_EN[int(m['m']) - 1]} {m['y']}"


TEMPLATES: list[tuple[re.Pattern, Callable[[re.Match], str]]] = [
    (re.compile(r"порівняно із (?P<what>забудовою|територією) (?P<n>\d+) район\w* (?P<city>\S+)"), _compared_to),
    (re.compile(rf"Ділянка невелика \((?P<a>{N}) км² забудови\), а в районах — (?P<lo>{N})–(?P<hi>{N}) км²: щільний "
                r"квартал зазвичай гарячіший за середнє по цілому району\."),
     lambda m: f"The area is small ({_num(m['a'])} km² of built-up land) while the districts have {_num(m['lo'])}–"
               f"{_num(m['hi'])} km²: a dense block is usually hotter than the average of a whole district."),
    (re.compile(r"окуповано \(станом на (?P<d>[\d.]+), джерело: Мінрозвитку, наказ № (?P<n>\d+)\)"),
     lambda m: f"occupied (as of {date_en(m['d'])}, source: Ministry of Development of Ukraine, order No. {m['n']})"),
    (re.compile(r"Перелік ТОТ \(наказ Мінрозвитку № (?P<n>\d+), ред\. від (?P<d>[\d.]+)\) \+ межі громад OpenStreetMap"),
     lambda m: f"List of temporarily occupied territories (Ministry of Development of Ukraine order No. {m['n']}, as "
               f"amended on {date_en(m['d'])}) + OpenStreetMap hromada boundaries"),
    (re.compile(r"(?P<y>\d{4}): замало безхмарних знімків цієї смуги"),
     lambda m: f"{m['y']}: too few cloud-free images of this swath"),
]


def text_en(uk: str | None) -> str | None:
    """English for a backend Ukrainian text: exact entry, else a template; None when neither matches."""
    if uk is None:
        return None
    if uk in EXACT:
        return EXACT[uk]
    for rx, f in TEMPLATES:
        m = rx.fullmatch(uk)
        if m:
            return f(m)
    return None


# ------------------------------------------------------------------ the walker

_NAME_KEYS = ("name", "short_name")
_SOURCE_KEYS = ("source", "attribution", "rule")


def localize(obj: Any, extra: Callable[[str, dict], str | None] | None = None) -> Any:
    """Copy of ``obj`` with ``*_en`` siblings added (see module doc). ``extra(key, dict)`` may supply an English text
    for a ``*_uk`` key the tables do not know (e.g. science's war-zone caveat)."""
    if isinstance(obj, list):
        return [localize(v, extra) for v in obj]
    if not isinstance(obj, dict):
        return obj
    out = {k: localize(v, extra) for k, v in obj.items()}
    for k, v in obj.items():
        if k.endswith("_uk") and (v is None or isinstance(v, str)):
            ke = k[:-3] + "_en"
            if out.get(ke) is None:  # science may have set null (no template); a backend text may still match here
                en = text_en(v)
                if en is None and v is not None and extra is not None:
                    en = extra(k, obj)
                out[ke] = en
        elif k.endswith("_uk") and isinstance(v, dict) and k[:-3] + "_en" not in out:  # e.g. meta notes_uk
            out[k[:-3] + "_en"] = {kk: (text_en(vv) if isinstance(vv, str) else None) for kk, vv in v.items()}
        elif k in _NAME_KEYS and isinstance(v, str) and _CYR.search(v) and f"{k}_en" not in out:
            out[f"{k}_en"] = place_name_en(v)
        elif k in _SOURCE_KEYS and isinstance(v, str) and _CYR.search(v) and f"{k}_en" not in out:
            out[f"{k}_en"] = text_en(v)
    return out


def numbers(text: str | None) -> list[float]:
    """Multiset of the numbers in a text (decimal comma → point, «−» → «-»): the EN/UK identity test."""
    if not text:
        return []
    t = text.replace("−", "-").replace(" ", " ")
    # a date is the same date in both forms: «15.09.2026» (uk) = «15 September 2026» (en) → 15, 9, 2026
    t = _DMY.sub(lambda m: f"{int(m['d'])} {int(m['m'])} {m['y']}", t)
    t = _DMY_EN.sub(lambda m: f"{int(m['d'])} {_MONTHS_EN.index(m['mon']) + 1} {m['y']}", t)
    vals = []
    for m in re.finditer(r"-?\d+(?:[.,]\d+)?", t):
        vals.append(float(m.group(0).replace(",", ".")))
    return sorted(vals)


# ------------------------------------------------------------------ response helpers (routes)

def _war_extra(key: str, d: dict) -> str | None:
    """War-region overlay text = science's war_zone caveat → its English via science's report localiser."""
    if key != "text_uk" or "since" not in d:
        return None
    from uhd.services import science

    if not science.has_helper("localize_report"):
        return None
    try:
        rep = science.helper("localize_report", {"method_version": science.method_version(),
                                                 "caveats": [{"code": "war_zone", "text_uk": d[key]}]})
        return (rep.get("caveats") or [{}])[0].get("text_en")
    except Exception:  # noqa: BLE001 — null, never a guess
        return None


def localize_report(rep: dict) -> dict:
    """A report response (stored report + per-response context) with English siblings; numbers untouched."""
    from uhd.services import science

    if science.has_helper("localize_report"):
        try:
            name = (rep.get("zone") or {}).get("name")
            name_en = (rep.get("zone") or {}).get("name_en") or (place_name_en(name) if name else None)
            rep = science.helper("localize_report", rep, name_en=name_en)
        except Exception:  # noqa: BLE001 — science texts then stay without *_en
            import logging

            logging.getLogger(__name__).exception("localize_report failed", extra={"report_id": rep.get("report_id")})
    return localize(rep, _war_extra)


_bytes_cache: dict[str, tuple[bytes, str]] = {}


def localize_cached_json(body: bytes, etag: str) -> tuple[bytes, str]:
    """English variant of a cached JSON body (overview, overlays), memoised per source ETag."""
    import json

    hit = _bytes_cache.get(etag)
    if hit is None:
        d = localize(json.loads(body), _war_extra)
        hit = (json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode(), etag[:-1] + '-en"')
        if len(_bytes_cache) > 16:
            _bytes_cache.clear()
        _bytes_cache[etag] = hit
    return hit
