"""Board item 29 «Експорт»: GET /api/reports/{id}/export?format=csv|xlsx|json|pdf.

Built from the stored report only (no analysis is re-run, old ids keep working): the same labelling as
GET /api/reports/{id} (name from ``?name=``), never the per-response context. File names
«deltaheat_<slug>_<report_id>.<ext>».
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from uhd.services import analysis, reports

FORMATS = {"csv": "text/csv; charset=utf-8", "json": "application/json",
           "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "pdf": "application/pdf"}
CSV_DELIMITER = ";"

_TRANSLIT = dict(zip("абвгґдезийклмнопрстуфхцчшщьюяієїыэё",
                     ["a", "b", "v", "h", "g", "d", "e", "z", "y", "i", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                      "u", "f", "kh", "ts", "ch", "sh", "shch", "", "iu", "ia", "i", "ie", "i", "y", "e", "io"]))
_TRANSLIT["ж"] = "zh"

VERDICT_UK = {"significant": "Суттєво (статистично значущо)", "not_significant": "Поки несуттєво (статистично незначущо)",
              "insufficient_data": "замало даних"}
BASIS_UK = {"always_built": "забудова в усі роки періоду", "built_each_year": "забудова кожного року",
            "all_land": "уся поверхня зони"}
METHOD_UK = {"per_scene": "окремі знімки", "composite": "середнє за літо", "mixed": "змішано"}
EXCLUDED_UK = {"no_lst_product": "немає продукту температури (USGS)", "low_coverage": "хмари: мало чистих пікселів",
               "too_few_pixels": "замало пікселів забудови", "no_reference": "немає даних для лісу-еталону",
               "too_few_scenes": "замало чистих знімків"}
SERIES_COLUMNS = [  # (key, Ukrainian column name, number format for xlsx)
    ("year", "Рік", "0"), ("zone_lst", "LST зони, °C", "0.0"), ("ref_lst", "LST лісу-еталону, °C", "0.0"),
    ("gap", "Розрив, °C", "0.0"), ("ndvi", "NDVI", "0.00"), ("built_share", "Частка забудови", "0%"),
    ("scenes", "Знімків", "0"), ("method", "Метод", "@"), ("excluded", "Причина виключення", "@")]

# ?lang=en (item 32, TERMS-EN): the same rows and numbers, English labels; stored reports are never changed.
VERDICT_EN = {"significant": "Significant (statistically significant)",
              "not_significant": "Not significant yet (statistically not significant)",
              "insufficient_data": "not enough data"}
BASIS_EN = {"always_built": "built-up in every year of the period", "built_each_year": "built-up in each year",
            "all_land": "the whole surface of the zone"}
METHOD_EN = {"per_scene": "individual scenes", "composite": "summer mean", "mixed": "mixed"}
EXCLUDED_EN = {"no_lst_product": "no temperature product (USGS)", "low_coverage": "clouds: too few clear pixels",
               "too_few_pixels": "too few built-up pixels", "no_reference": "no data for the reference forest",
               "too_few_scenes": "too few clear scenes"}
SERIES_COLUMNS_EN = ["Year", "Zone LST, °C", "Reference forest LST, °C", "Gap, °C", "NDVI", "Built-up share",
                     "Scenes", "Method", "Exclusion reason"]
CSV_DELIMITER_EN = ","


def slug(text: str | None) -> str:
    s = "".join(_TRANSLIT.get(ch, ch) for ch in (text or "").lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60].strip("-") or "zona"


def filename(rep: dict, ext: str, lang: str | None = None) -> str:
    """``lang`` only when the caller asked for one explicitly (``-en`` / ``-uk``): default names are unchanged."""
    z = rep.get("zone") or {}
    pid = (rep.get("params") or {}).get("place_id")
    return f"deltaheat_{slug(z.get('name') or pid)}_{rep['report_id']}{'-' + lang if lang else ''}.{ext}"


def _ring(geom: dict) -> list | None:
    c = geom.get("coordinates")
    if geom.get("type") == "Polygon" and c:
        return c[0]
    if geom.get("type") == "MultiPolygon" and c:
        return max((p[0] for p in c), key=len)
    return None


def report_link(rep: dict, base: str) -> str:
    """The app URL for this zone (the frontend's ?zone= / ?area= state), else the API report URL."""
    base = base.rstrip("/")
    p = rep.get("params") or {}
    if p.get("place_id"):
        return f"{base}/?zone={p['place_id']}"
    ring = _ring(p.get("geometry") or {})
    if ring and len(ring) <= 200:
        pts = ring[:-1] if ring[0] == ring[-1] else ring
        return f"{base}/?area=" + ";".join(f"{x:.5f},{y:.5f}" for x, y in pts)
    return f"{base}/api/reports/{rep['report_id']}"


_PLACE_ID = re.compile(r"[A-Za-z0-9:._-]{1,64}")


def load(report_id: str, name: str | None, place_id: str | None = None) -> dict:
    """Stored reports are name- and place-free; the caller's ``name`` / ``place_id`` label this export only."""
    rep = reports.require(report_id)
    pid = place_id if place_id and _PLACE_ID.fullmatch(place_id) else (rep.get("params") or {}).get("place_id")
    return analysis.label(rep, name, pid)


def _num(v: Any, nd: int = 2) -> Any:
    return round(v, nd) if isinstance(v, float) else v


def summary_rows(rep: dict, link: str, lang: str = "uk") -> list[tuple[str, Any]]:
    if lang == "en":
        return _summary_rows_en(rep, link)
    z, r = rep.get("zone") or {}, rep.get("reference") or {}
    gs, tr = rep.get("gap_summary") or {}, rep.get("trend") or {}
    ci = tr.get("ci95") or [None, None]
    years = rep.get("years") or (rep.get("params") or {}).get("years") or [None, None]
    ref = ("ліс навколо міста" if r.get("kind") == "preset" else "стабільний ліс навколо зони") + \
        (f", кільце {r['ring_km'][0]:g}–{r['ring_km'][1]:g} км від межі міста" if r.get("ring_km") else "")
    return [
        ("Зона", z.get("name") or (rep.get("params") or {}).get("place_id") or "намальована ділянка"),
        ("Площа зони, км²", _num(z.get("area_km2"), 3)),
        ("Проаналізовано, км²", _num(z.get("analysed_area_km2"), 3)),
        ("Основа", BASIS_UK.get(z.get("basis"), z.get("basis"))),
        ("Еталон", ref),
        ("Площа еталону, км²", r.get("area_km2")),
        ("Літні сезони", f"{years[0]}–{years[1]}" if years[0] else None),
        ("Середній розрив, °C", _num(gs.get("mean"))),
        ("Тренд, °C за 10 років", _num(tr.get("slope_per_decade"))),
        ("95 % інтервал тренду, °C/10 р.", f"{_num(ci[0])} … {_num(ci[1])}" if ci[0] is not None else None),
        ("p", _num(tr.get("p"), 3)),
        ("Літніх сезонів із даними", tr.get("n_years")),
        ("Висновок", VERDICT_UK.get(tr.get("verdict"), tr.get("verdict"))),
        ("Текст", rep.get("verdict_text_uk")),
        ("Метод", METHOD_UK.get(rep.get("method"), rep.get("method"))),
        ("method_version", rep.get("method_version")),
        ("data_version", rep.get("data_version")),
        ("report_id", rep.get("report_id")),
        ("Посилання", link),
    ]


def _summary_rows_en(rep: dict, link: str) -> list[tuple[str, Any]]:
    z, r = rep.get("zone") or {}, rep.get("reference") or {}
    gs, tr = rep.get("gap_summary") or {}, rep.get("trend") or {}
    ci = tr.get("ci95") or [None, None]
    years = rep.get("years") or (rep.get("params") or {}).get("years") or [None, None]
    ref = ("forest around the city" if r.get("kind") == "preset" else "stable forest around the zone") + \
        (f", ring {r['ring_km'][0]:g}–{r['ring_km'][1]:g} km from the city boundary" if r.get("ring_km") else "")
    text = rep.get("verdict_text_en")
    return [
        ("Zone", z.get("name_en") or z.get("name") or (rep.get("params") or {}).get("place_id") or "drawn area"),
        ("Zone area, km²", _num(z.get("area_km2"), 3)),
        ("Analysed, km²", _num(z.get("analysed_area_km2"), 3)),
        ("Basis", BASIS_EN.get(z.get("basis"), z.get("basis"))),
        ("Reference", ref),
        ("Reference area, km²", r.get("area_km2")),
        ("Summers", f"{years[0]}–{years[1]}" if years[0] else None),
        ("Mean gap, °C", _num(gs.get("mean"))),
        ("Trend, °C per 10 years", _num(tr.get("slope_per_decade"))),
        ("Trend 95 % interval, °C/10 yr", f"{_num(ci[0])} … {_num(ci[1])}" if ci[0] is not None else None),
        ("p", _num(tr.get("p"), 3)),
        ("Summers with data", tr.get("n_years")),
        ("Verdict", VERDICT_EN.get(tr.get("verdict"), tr.get("verdict"))),
        ("Text", text),
        ("Method", METHOD_EN.get(rep.get("method"), rep.get("method"))),
        ("method_version", rep.get("method_version")),
        ("data_version", rep.get("data_version")),
        ("report_id", rep.get("report_id")),
        ("Link", link),
    ]


def series_rows(rep: dict, lang: str = "uk") -> list[list[Any]]:
    en = lang == "en"
    out = []
    for s in rep.get("series") or []:
        row = []
        for k, _, _ in SERIES_COLUMNS:
            v = s.get(k)
            if k == "method":
                v = (METHOD_EN if en else METHOD_UK).get(v, v)
            elif k == "excluded":
                v = (EXCLUDED_EN if en else EXCLUDED_UK).get(v, v) if v else None
            row.append(_num(v, 3))
        out.append(row)
    return out


def series_header(lang: str = "uk") -> list[str]:
    return SERIES_COLUMNS_EN if lang == "en" else [c for _, c, _ in SERIES_COLUMNS]


def to_csv(rep: dict, link: str, lang: str = "uk") -> bytes:
    """uk: ``;`` (Excel with a Ukrainian locale); en: ``,``. Numbers are written the same way in both (``.``)."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=CSV_DELIMITER_EN if lang == "en" else CSV_DELIMITER, lineterminator="\r\n")
    for k, v in summary_rows(rep, link, lang):
        w.writerow([k, "" if v is None else v])
    w.writerow([])
    w.writerow(series_header(lang))
    for row in series_rows(rep, lang):
        w.writerow(["" if v is None else v for v in row])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def to_json(rep: dict, link: str) -> bytes:
    return json.dumps({**rep, "link": link}, ensure_ascii=False, indent=1).encode()


METHOD_TEXT_UK = [
    "Розрив — різниця денної температури поверхні (LST, Landsat 8 Collection 2 Level-2, знімок близько 11:00 за місцевим сонячним часом) між "
    "забудовою зони і стабільним лісом навколо міста, літо (червень–серпень) кожного року 2013–2025.",
    "Забудова — карта Esri/IO LULC 10 м (2017–2023; інші роки оцінено за знімками), еталон — ліс, стабільний усі роки.",
    "Тренд — нахил лінійної регресії розриву за роками; статистично значущо лише коли p < 0,05 і є ≥ 8 літніх сезонів із даними.",
    "Це температура поверхні, а не повітря.",
]
SOURCES_UK = [
    ("Landsat 8 Collection 2 Level-2", "USGS / NASA, суспільне надбання"),
    ("Esri / Impact Observatory LULC 10 m", "CC BY 4.0"),
    ("Межі OpenStreetMap", "© OpenStreetMap contributors, ODbL 1.0"),
    ("Перелік ТОТ (наказ Мінрозвитку № 376)", "офіційний документ"),
]
METHOD_TEXT_EN = [
    "Gap — the difference in daytime land surface temperature (LST, Landsat 8 Collection 2 Level-2, overpass around "
    "11:00 local solar time) between the zone's built-up area and stable forest around the city, summer (June–August) "
    "of each year 2013–2025.",
    "Built-up — the Esri/IO LULC 10 m map (2017–2023; other years estimated from imagery); reference — forest that is "
    "stable in all years.",
    "Trend — the slope of a linear regression of the gap over the years; statistically significant only when p < 0.05 "
    "and there are ≥ 8 summers with data.",
    "This is surface temperature, not air temperature.",
]
SOURCES_EN = [
    ("Landsat 8 Collection 2 Level-2", "USGS / NASA, public domain"),
    ("Esri / Impact Observatory LULC 10 m", "CC BY 4.0"),
    ("OpenStreetMap boundaries", "© OpenStreetMap contributors, ODbL 1.0"),
    ("List of temporarily occupied territories (Ministry of Development order No. 376)", "official document"),
]


def method_texts(lang: str = "uk") -> list[str]:
    return METHOD_TEXT_EN if lang == "en" else METHOD_TEXT_UK


def sources(lang: str = "uk") -> list[tuple[str, str]]:
    return SOURCES_EN if lang == "en" else SOURCES_UK


_XLSX_EN = {"Підсумок": "Summary", "Показник": "Item", "Значення": "Value", "Застереження": "Caveats",
            "За роками": "By year", "Про метод": "About the method", "Джерело": "Source", "Ліцензія": "Licence",
            "Посилання": "Link", "DELTAHEAT": "DELTAHEAT"}


def to_xlsx(rep: dict, link: str, lang: str = "uk") -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    en = lang == "en"

    def L(uk: str) -> str:
        return _XLSX_EN.get(uk, uk) if en else uk

    wb = Workbook()
    ws = wb.active
    ws.title = L("Підсумок")
    bold = Font(bold=True)
    ws.append([L("Показник"), L("Значення")])
    for k, v in summary_rows(rep, link, lang):
        ws.append([k, v])
    ws.append([])
    ws.append([L("Застереження")])
    ws.cell(ws.max_row, 1).font = bold
    for c in rep.get("caveats") or []:
        ws.append([c.get("code"), (c.get("text_en") if en else None) or c.get("text_uk")])
    for row in ws.iter_rows(min_row=2):
        row[1].alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 90
    for c in ws[1]:
        c.font = bold
    ws.freeze_panes = "A2"

    ys = wb.create_sheet(L("За роками"))
    ys.append(series_header(lang))
    for row in series_rows(rep, lang):
        ys.append(row)
    for j, (name, (_, _, fmt)) in enumerate(zip(series_header(lang), SERIES_COLUMNS), start=1):
        ys.cell(1, j).font = bold
        letter = ys.cell(1, j).column_letter
        ys.column_dimensions[letter].width = max(10, len(name) + 2)
        for i in range(2, ys.max_row + 1):
            ys.cell(i, j).number_format = fmt
    ys.freeze_panes = "A2"

    ms = wb.create_sheet(L("Про метод"))
    ms.append([L("Про метод")])
    ms.cell(1, 1).font = bold
    for t in method_texts(lang):
        ms.append([t])
    ms.append([])
    ms.append([L("Джерело"), L("Ліцензія")])
    for c in ms[ms.max_row]:
        c.font = bold
    for s in sources(lang):
        ms.append(list(s))
    ms.append([])
    ms.append(["method_version", rep.get("method_version")])
    ms.append(["data_version", rep.get("data_version")])
    ms.append([L("Посилання"), link])
    ms.column_dimensions["A"].width = 60
    ms.column_dimensions["B"].width = 50
    for row in ms.iter_rows():
        row[0].alignment = Alignment(wrap_text=True, vertical="top")
    ms.freeze_panes = "A2"
    wb.properties.title = f"{L('DELTAHEAT')} — {rep['report_id']}"
    wb.properties.creator = "DELTAHEAT"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def render(report_id: str, fmt: str, name: str | None, base: str, place_id: str | None = None,
           lang: str | None = None) -> tuple[bytes, str, str]:
    """(body, media type, file name). ``lang=None`` is the Ukrainian default, byte-identical to before item 32;
    ``"en"`` adds the *_en siblings (as GET /api/reports/{id}?lang=en) and English labels — numbers unchanged."""
    rep = load(report_id, name, place_id)
    link = report_link(rep, base)
    if lang:
        link += ("&" if "?" in link else "?") + f"lang={lang}"
    lg = lang or "uk"
    if lg == "en":
        from uhd.services import i18n

        rep = i18n.localize_report(rep)
    if fmt == "csv":
        body = to_csv(rep, link, lg)
    elif fmt == "json":
        body = to_json(rep, link)
    elif fmt == "xlsx":
        body = to_xlsx(rep, link, lg)
    elif fmt == "pdf":
        from uhd.services import export_pdf

        body = export_pdf.get(rep, link, lg)
    else:  # validated by the route
        raise ValueError(fmt)
    return body, FORMATS[fmt], filename(rep, fmt, lang)


_HOST = re.compile(r"[A-Za-z0-9.-]{1,253}(:[0-9]{1,5})?")


def public_base(headers, base_url: str) -> str:
    """App origin for links / QR: X-Forwarded-Proto/Host from the public mirror (validated), else the Host the request
    came in on, else UHD_PUBLIC_BASE_URL."""
    from uhd.config import get_settings

    fh = (headers.get("x-forwarded-host") or "").split(",")[0].strip()
    fp = (headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    if fh and _HOST.fullmatch(fh):
        return f"{fp if fp in ('http', 'https') else 'https'}://{fh}/"
    host = (headers.get("host") or "").strip()
    if host and _HOST.fullmatch(host):
        return base_url
    return (get_settings().public_base_url or base_url).rstrip("/") + "/"
