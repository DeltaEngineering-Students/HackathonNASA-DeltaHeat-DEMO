"""Board item 29 «Експорт» — PDF (fpdf2 + Onest, pure Python; main/PM option C).

1–2 A4 pages in Ukrainian, built from the stored report only: title, map snapshot (our own gap tiles of the latest
summer + the zone outline + hotspots, composited with Pillow — no external tiles), headline sentence, big numbers,
the two-line chart (zone vs forest LST), the year table, hotspots, caveats, method/versions, data credits, the link
and a QR code. App palette (F7 light) and typography (Onest 400/600, OFL), decimal commas, «−» minus.
Cached per report + label in {cache_dir}/export (LRU, ≤ CACHE_MAX_BYTES).
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Any

from uhd.config import get_settings

log = logging.getLogger(__name__)
_LANG: "contextvars.ContextVar[str]" = __import__("contextvars").ContextVar("pdf_lang", default="uk")


def t(uk: str) -> str:
    """The English template label for ``uk`` when this PDF is English (item 32), else ``uk``."""
    return EN.get(uk, uk) if _LANG.get() == "en" else uk

def _template_hash() -> str:
    """Hash of the code that draws the PDF (this module + export.py's method texts / sources): any template change gets
    new cache keys, so files cached by an older build are never served again (they age out of the LRU)."""
    h = hashlib.sha256()
    for f in (Path(__file__), Path(__file__).with_name("export.py")):
        try:
            h.update(f.read_bytes())
        except OSError:
            h.update(f.name.encode())
    return h.hexdigest()[:8]


# pdf1 was never bumped, so PDFs cached by the first build (rows «літа …», plain «Гарячі точки») outlived 4f9cae5 and
# 44fea5e on the VM; the key now follows the template code itself.
SCHEMA = "pdf2-" + _template_hash()
CACHE_MAX_BYTES = 200 * 2**20
FONT_DIR = Path(__file__).resolve().parents[1] / "resources" / "fonts"
MAP_W, MAP_H = 1200, 600          # px of the map snapshot (drawn at 178 × 89 mm)
MAP_MAX_TILES = 40
INK, INK2, RULE, SURF2 = (13, 18, 32), (90, 98, 117), (231, 233, 238), (244, 245, 248)
HEAT, HEAT2, HEAT_L, REF, OK = (200, 22, 106), (217, 72, 15), (249, 227, 238), (29, 63, 191), (47, 107, 79)
_lock = threading.Lock()

# TERMS-UK (item 31): card labels + the statistical wording under them; applied to old stored reports too
CARD_LABEL_UK = {"significant": "Суттєво", "not_significant": "Поки несуттєво", "insufficient_data": "Замало даних"}
STAT_UK = {"significant": "статистично значущо", "not_significant": "статистично незначущо"}


def seasons_uk(n: int) -> str:
    """«1 літній сезон», «3 літні сезони», «12 літніх сезонів» (EN: «1 summer season», «12 summer seasons»)."""
    n = int(n or 0)
    if _LANG.get() == "en":
        return f"{n} summer season" + ("" if n == 1 else "s")
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} літній сезон"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} літні сезони"
    return f"{n} літніх сезонів"


def wrap_link(text: str, width_of, max_w: float) -> list[str]:
    """Lines of ``text`` no wider than ``max_w``, broken only after «?», «&», «;» or «,» (never inside a number)."""
    import re

    parts = re.findall(r"[^?&;,]*[?&;,]?", text)
    lines, cur = [], ""
    for t in (x for x in parts if x):
        if cur and width_of(cur + t) > max_w:
            lines.append(cur)
            cur = t
        else:
            cur += t
    return lines + ([cur] if cur else [])


# ------------------------------------------------------------------ number formatting (uk)

def fnum(v: Any, nd: int = 1, sign: bool = False) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    from uhd.services.num import rnd

    x = rnd(float(v), nd)
    s = f"{abs(x):.{nd}f}"
    if _LANG.get() != "en":
        s = s.replace(".", ",")
    if x < 0:
        return "−" + s
    return ("+" + s) if sign and x > 0 else s


# ------------------------------------------------------------------ map snapshot

def _merc(lon: float, lat: float, z: int) -> tuple[float, float]:
    n = 256 * (1 << z)
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def _rings(geom: dict) -> list[list]:
    t, c = geom.get("type"), geom.get("coordinates") or []
    if t == "Polygon":
        return [r for r in c]
    if t == "MultiPolygon":
        return [r for p in c for r in p]
    return []


def map_snapshot(rep: dict, year: int | None):
    """PIL image (RGB) of the gap layer for ``year`` around the zone, or None when it cannot be drawn."""
    from PIL import Image, ImageDraw, ImageFont

    from uhd.tiles import render

    geom = rep.get("zone_outline") or (rep.get("params") or {}).get("geometry") or {}
    pts = [p for r in _rings(geom) for p in r]
    if not pts or year is None:
        return None
    lons, lats = [p[0] for p in pts], [p[1] for p in pts]
    lo0, lo1, la0, la1 = min(lons), max(lons), min(lats), max(lats)
    z = 15
    while z > render.MIN_Z:
        x0, y1 = _merc(lo0, la0, z)
        x1, y0 = _merc(lo1, la1, z)
        if (x1 - x0) * 1.5 <= MAP_W and (y1 - y0) * 1.5 <= MAP_H:
            break
        z -= 1
    z = min(z, 14)
    x0, y1 = _merc(lo0, la0, z)
    x1, y0 = _merc(lo1, la1, z)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    left, top = cx - MAP_W / 2, cy - MAP_H / 2
    tx0, ty0 = int(left // 256), int(top // 256)
    tx1, ty1 = int((left + MAP_W) // 256), int((top + MAP_H) // 256)
    if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) > MAP_MAX_TILES:
        return None
    img = Image.new("RGBA", (MAP_W, MAP_H), (246, 246, 243, 255))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            if not (0 <= ty < (1 << z)):
                continue
            try:
                png = render.tile_png("gap", year, z, tx % (1 << z), ty, "light")
                t = Image.open(io.BytesIO(png)).convert("RGBA")
            except Exception:  # noqa: BLE001 — a missing tile leaves the background
                continue
            img.alpha_composite(t, (int(tx * 256 - left), int(ty * 256 - top)))
    d = ImageDraw.Draw(img)
    for r in _rings(geom):
        xy = [(_merc(lo, la, z)[0] - left, _merc(lo, la, z)[1] - top) for lo, la in r]
        if len(xy) > 1:
            d.line(xy + [xy[0]], fill=(255, 255, 255, 255), width=7, joint="curve")
            d.line(xy + [xy[0]], fill=INK + (255,), width=3, joint="curve")
    try:
        font = ImageFont.truetype(str(FONT_DIR / "Onest-600.ttf"), 22)
    except OSError:
        font = None
    for i, h in enumerate(rep.get("hotspots") or [], start=1):
        x, y = _merc(h["lon"], h["lat"], z)
        x, y = x - left, y - top
        d.ellipse([x - 16, y - 16, x + 16, y + 16], fill=HEAT + (255,), outline=(255, 255, 255, 255), width=3)
        if font:
            d.text((x, y), str(i), fill=(255, 255, 255, 255), font=font, anchor="mm")
    _scale_and_north(d, z, (la0 + la1) / 2)
    return img.convert("RGB")


SCALE_STEPS_M = (50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 20000, 50000)


def scale_bar(z: int, lat: float, max_px: float) -> tuple[int, float]:
    """(metres, pixels) of the longest round scale-bar length that fits ``max_px`` at zoom ``z`` / latitude ``lat``."""
    m_per_px = 156543.03392 * math.cos(math.radians(lat)) / (1 << z)
    best = SCALE_STEPS_M[0]
    for m in SCALE_STEPS_M:
        if m / m_per_px <= max_px:
            best = m
    return best, best / m_per_px


def _scale_and_north(d, z: int, lat: float) -> None:
    from PIL import ImageFont

    try:
        font = ImageFont.truetype(str(FONT_DIR / "Onest-600.ttf"), 20)
    except OSError:
        font = None
    m, px = scale_bar(z, lat, MAP_W / 5)
    km, mm = t("км"), t("м")
    label = f"{m // 1000} {km}" if m >= 1000 and m % 1000 == 0 else (f"{fnum(m / 1000, 1)} {km}" if m >= 1000 else f"{m} {mm}")
    x0, y0 = 24, MAP_H - 44
    d.rounded_rectangle([x0 - 10, y0 - 12, x0 + px + 90, y0 + 26], radius=8, fill=(255, 255, 255, 220))
    d.rectangle([x0, y0 + 6, x0 + px, y0 + 12], fill=INK + (255,))
    d.rectangle([x0, y0, x0 + 3, y0 + 18], fill=INK + (255,))
    d.rectangle([x0 + px - 3, y0, x0 + px, y0 + 18], fill=INK + (255,))
    if font:
        d.text((x0 + px + 12, y0 + 9), label, fill=INK + (255,), font=font, anchor="lm")
    # north arrow (Web Mercator: north is up)
    cx, cy = MAP_W - 40, 44
    d.ellipse([cx - 26, cy - 30, cx + 26, cy + 30], fill=(255, 255, 255, 220))
    d.polygon([(cx, cy - 22), (cx - 11, cy + 4), (cx, cy - 2), (cx + 11, cy + 4)], fill=INK + (255,))
    if font:
        d.text((cx, cy + 16), t("Пн"), fill=INK + (255,), font=font, anchor="mm")


# ------------------------------------------------------------------ the document

class _Doc:
    def __init__(self):
        from fpdf import FPDF

        self.pdf = p = FPDF(format="A4", unit="mm")
        p.set_auto_page_break(True, margin=16)
        p.set_margins(16, 14, 16)
        p.add_font("Onest", "", str(FONT_DIR / "Onest-400.ttf"))
        p.add_font("Onest", "B", str(FONT_DIR / "Onest-600.ttf"))
        p.set_creator("DELTAHEAT")

    def font(self, size: float, bold: bool = False, color=INK):
        self.pdf.set_font("Onest", "B" if bold else "", size)
        self.pdf.set_text_color(*color)

    def text(self, s: str, size=9.5, bold=False, color=INK, h=None, w=0, align="L"):
        self.font(size, bold, color)
        self.pdf.multi_cell(w, h or size * 0.48, s, align=align, new_x="LMARGIN", new_y="NEXT")

    def heading(self, s: str):
        p = self.pdf
        if p.get_y() > p.h - 40:
            p.add_page()
        p.ln(3)
        self.text(s, 11.5, True)
        p.ln(1)


def _year_of_map(rep: dict) -> int | None:
    ys = [s["year"] for s in rep.get("series") or [] if s.get("gap") is not None]
    return ys[-1] if ys else None


def _big_numbers(doc: _Doc, rep: dict):
    p = doc.pdf
    gs, tr = rep.get("gap_summary") or {}, rep.get("trend") or {}
    ci = tr.get("ci95") or [None, None]
    boxes = [
        (t("Розрив із лісом, середнє"), f"{fnum(gs.get('mean'), 1, True)} °C",
         t("останнє літо {v} °C").format(v=fnum(gs.get('last'), 1, True)), HEAT),
        (t("Тренд розриву"), f"{fnum(tr.get('slope_per_decade'), 1, True)} °C / {t('10 р.')}",
         f"95 %: {fnum(ci[0], 1, True)} … {fnum(ci[1], 1, True)}", INK),
        (t("Висновок"), t(CARD_LABEL_UK.get(tr.get("verdict"), "—")),
         ((f"{t(STAT_UK[tr['verdict']])}, p = {fnum(tr.get('p'), 2)}\n") if tr.get("verdict") in STAT_UK else "")
         + t("{n} із даними").format(n=seasons_uk(tr.get('n_years') or 0)),
         OK if tr.get("verdict") == "significant" else INK2),
    ]
    w, gap_, y = (p.w - 32 - 8) / 3, 4, p.get_y()
    for i, (lab, big, small, col) in enumerate(boxes):
        x = 16 + i * (w + gap_)
        p.set_fill_color(*SURF2)
        p.rect(x, y, w, 27, style="F", round_corners=True, corner_radius=3)
        p.set_xy(x + 4, y + 3)
        doc.font(7.5, False, INK2)
        p.cell(w - 8, 4, lab)
        p.set_xy(x + 4, y + 8.5)
        doc.font(15 if i < 2 else 12.5, True, col)
        p.cell(w - 8, 7, big)
        doc.font(7.5, False, INK2)
        for k, line in enumerate(small.split("\n")):  # ≤ 2 short lines, each fits the box
            p.set_xy(x + 4, y + 17 + k * 3.8)
            p.cell(w - 8, 4, line)
    p.set_y(y + 31)


def _chart(doc: _Doc, rep: dict, h: float = 52):
    """Zone LST vs forest LST by summer (the app's two-line chart); gaps in the series stay gaps."""
    p = doc.pdf
    ser = [s for s in rep.get("series") or []]
    vals = [v for s in ser for v in (s.get("zone_lst"), s.get("ref_lst")) if v is not None]
    if not vals:
        return
    x0, y0, w = 26, p.get_y() + 2, p.w - 16 - 26
    lo, hi = math.floor(min(vals) - 1), math.ceil(max(vals) + 1)
    ys = [s["year"] for s in ser]
    yr0, yr1 = min(ys), max(ys)

    def X(yr):
        return x0 + (yr - yr0) / max(1, yr1 - yr0) * w

    def Y(v):
        return y0 + h - (v - lo) / max(1e-9, hi - lo) * h

    p.set_draw_color(*RULE)
    p.set_line_width(0.2)
    step = 2 if hi - lo <= 14 else 5
    doc.font(7, False, INK2)
    for v in range(int(lo), int(hi) + 1):
        if v % step:
            continue
        p.line(x0, Y(v), x0 + w, Y(v))
        p.set_xy(x0 - 11, Y(v) - 2)
        p.cell(9, 4, f"{fnum(v, 0)}°", align="R")
    for yr in ys:
        p.set_xy(X(yr) - 5, y0 + h + 1)
        p.cell(10, 4, str(yr)[2:] if len(ys) > 8 else str(yr), align="C")
    for key, col in (("zone_lst", HEAT), ("ref_lst", REF)):
        p.set_draw_color(*col)
        p.set_fill_color(*col)
        p.set_line_width(0.6)
        prev = None
        for s in ser:
            v = s.get(key) if s.get("gap") is not None else None
            if v is None:
                prev = None
                continue
            pt = (X(s["year"]), Y(v))
            if prev:
                p.line(*prev, *pt)
            p.ellipse(pt[0] - 0.8, pt[1] - 0.8, 1.6, 1.6, style="F")
            prev = pt
    # legend
    lx = x0
    for col, lab in ((HEAT, t("забудова зони (LST, °C)")), (REF, t("ліс-еталон (LST, °C)"))):
        p.set_fill_color(*col)
        p.rect(lx, y0 + h + 7, 4, 1.6, style="F")
        p.set_xy(lx + 5, y0 + h + 5.8)
        doc.font(7.5, False, INK2)
        p.cell(50, 4, lab)
        lx += 52
    p.set_y(y0 + h + 12)


def _table(doc: _Doc, rep: dict):
    from uhd.services.export import EXCLUDED_UK, METHOD_UK

    p = doc.pdf
    cols = [(t("Рік"), 12, "C"), (t("LST зони"), 20, "R"), (t("LST лісу"), 20, "R"), (t("Розрив"), 18, "R"),
            ("NDVI", 15, "R"), (t("Забудова"), 18, "R"), (t("Знімків"), 15, "R"), (t("Метод / причина"), 0, "L")]
    rest = p.w - 32 - sum(c[1] for c in cols)
    cols[-1] = (cols[-1][0], rest, "L")
    doc.font(7.5, True, INK2)
    p.set_fill_color(*SURF2)
    for name, w, al in cols:
        p.cell(w, 6, name, align=al, fill=True)
    p.ln(6)
    doc.font(8, False, INK)
    for s in rep.get("series") or []:
        bs = s.get("built_share")
        why = t(EXCLUDED_UK.get(s.get("excluded"), s.get("excluded"))) if s.get("excluded") else \
            t(METHOD_UK.get(s.get("method"), s.get("method") or ""))
        row = [str(s["year"]), fnum(s.get("zone_lst")), fnum(s.get("ref_lst")), fnum(s.get("gap"), 1, True),
               fnum(s.get("ndvi"), 2), (fnum(bs * 100, 0) + " %") if bs is not None else "—",
               str(s.get("scenes") if s.get("scenes") is not None else "—"), why or ""]
        base = INK2 if s.get("gap") is None else INK
        for (name, w, al), v in zip(cols, row):
            if name == t("Розрив") and s.get("gap") is not None:
                doc.font(8, True, HEAT)
            else:
                doc.font(8, False, base)
            p.cell(w, 5.2, v, align=al)
        p.ln(5.2)
        p.set_draw_color(*RULE)
        p.set_line_width(0.15)
        p.line(16, p.get_y(), p.w - 16, p.get_y())


def years_span(ys: list[int]) -> str:
    """«2023–2025» for consecutive summers, else «2019, 2021, 2024»."""
    ys = sorted(ys or [])
    if not ys:
        return "—"
    if len(ys) > 1 and ys == list(range(ys[0], ys[-1] + 1)):
        return f"{ys[0]}–{ys[-1]}"
    return ", ".join(map(str, ys))


def _hotspot_table(doc: _Doc, hs: list[dict]):
    p = doc.pdf
    cols = [("№", 8, "C"), (t("Розрив з лісом"), 26, "R"), (t("Понад забудову зони"), 33, "R"), (t("Площа"), 20, "R"),
            (t("Тип"), 24, "L"), (t("Координати (пн. ш. / сх. д.)"), 0, "L"), (t("Літні сезони"), 24, "L")]
    rest = p.w - 32 - sum(c[1] for c in cols)
    cols[5] = (cols[5][0], rest, "L")
    doc.font(7.5, True, INK2)
    p.set_fill_color(*SURF2)
    for name, w, al in cols:
        p.cell(w, 6, name, align=al, fill=True)
    p.ln(6)
    for i, h in enumerate(hs, start=1):
        lc = h.get("land_class") or {}
        land = (lc.get("label_en") if _LANG.get() == "en" else None) or t(lc.get("label_uk") or "—")
        row = [str(i), f"{fnum(h.get('gap'), 1, True)} °C", f"{fnum(h.get('delta_vs_zone'), 1, True)} °C",
               f"{fnum(h.get('area_km2'), 2)} {t('км²')}", land, f"{fnum(h['lat'], 4)}° / {fnum(h['lon'], 4)}°",
               years_span(h.get("years") or [])]
        for (name, w, al), v in zip(cols, row):
            if name in ("№", t("Розрив з лісом")):
                doc.font(8, True, HEAT)
            else:
                doc.font(8, False, INK)
            p.cell(w, 5.2, v, align=al)
        p.ln(5.2)
        p.set_draw_color(*RULE)
        p.set_line_width(0.15)
        p.line(16, p.get_y(), p.w - 16, p.get_y())
    p.ln(1)
    doc.text(t("Номери — як на карті; «понад забудову зони» — наскільки точка гарячіша за середню забудову цієї ділянки."),
             7, False, INK2)


def build(rep: dict, link: str, lang: str = "uk") -> bytes:
    tok = _LANG.set("en" if lang == "en" else "uk")
    try:
        return _build(rep, link)
    finally:
        _LANG.reset(tok)


def _verdict_fallback_en(rep: dict) -> str:
    """When science has no English template for this report: the numbers only, no paraphrase of the uk sentence."""
    gs, tr = rep.get("gap_summary") or {}, rep.get("trend") or {}
    out = f"Mean surface heat gap with the forest: {fnum(gs.get('mean'), 1, True)} °C."
    if tr.get("slope_per_decade") is not None:
        out += f" Trend: {fnum(tr.get('slope_per_decade'), 1, True)} °C per 10 years (p = {fnum(tr.get('p'), 2)})."
    return out


def _build(rep: dict, link: str) -> bytes:
    from uhd.services.export import method_texts, sources

    en = _LANG.get() == "en"
    doc = _Doc()
    p = doc.pdf
    p.add_page()
    z = rep.get("zone") or {}
    name = z.get("name") or (rep.get("params") or {}).get("place_id") or t("Намальована ділянка")
    if _LANG.get() == "en" and name and z.get("name"):
        from uhd.services.i18n import place_name_en

        name = place_name_en(name)
    years = rep.get("years") or (rep.get("params") or {}).get("years") or [None, None]
    p.set_title(t("DELTAHEAT — {name}").format(name=name))
    doc.text(t("DELTAHEAT · Детектор міського тепла"), 7.5, True, HEAT)
    p.ln(0.5)
    doc.text(name, 20, True, INK, h=9)
    sub = t("Літні сезони {a}–{b} · площа {s} км²").format(a=years[0], b=years[1], s=fnum(z.get('area_km2'), 2))
    if z.get("analysed_area_km2") is not None:
        sub += t(" · проаналізовано {s} км²").format(s=fnum(z.get('analysed_area_km2'), 2))
    doc.text(sub, 9, False, INK2)
    p.ln(2)
    vt = (rep.get("verdict_text_en") or (_verdict_fallback_en(rep) if rep.get("verdict_text_uk") else None)) if en \
        else rep.get("verdict_text_uk")
    if vt:
        doc.text(vt, 11, False, INK, h=5.6)
        p.ln(2)
    _big_numbers(doc, rep)
    yr = _year_of_map(rep)
    try:
        img = map_snapshot(rep, yr)
    except Exception:  # noqa: BLE001 — the PDF never fails because of the picture
        log.exception("pdf map failed", extra={"report_id": rep.get("report_id")})
        img = None
    if img is not None:
        w = p.w - 32
        hmm = w * MAP_H / MAP_W
        if p.get_y() + hmm > p.h - 20:
            p.add_page()
        y = p.get_y()
        p.image(img, x=16, y=y, w=w, h=hmm)
        p.set_draw_color(*RULE)
        p.rect(16, y, w, hmm)
        p.set_y(y + hmm + 1)
        doc.text(t("Розрив із лісом (°C), літо {yr}: від шавлієвого (прохолодніше за ліс) до малинового (гарячіше). "
                   "Чорна лінія — ділянка; кружки — гарячі точки (номери — як у таблиці). Карта: Landsat 8, власні тайли.")
                 .format(yr=yr), 7, False, INK2)
    doc.heading(t("Температура поверхні по роках"))
    _chart(doc, rep)
    doc.heading(t("По роках"))
    _table(doc, rep)
    hs = rep.get("hotspots") or []
    if hs:
        ys = sorted({y for h in hs for y in (h.get("years") or [])})
        doc.heading(f"{t('Гарячі точки')} ({years_span(ys)})" if ys else t("Гарячі точки"))
        doc.text(t("найгарячіші місця забудови за останні 3 літні сезони з даними (середнє за ці сезони); ≥ 1 °C "
                   "гарячіші за решту забудови ділянки; до 3 точок, ≥ 500 м одна від одної"), 8, False, INK2, h=4)
        p.ln(1)
        _hotspot_table(doc, hs)
    cav = rep.get("caveats") or []
    if cav:
        doc.heading(t("Застереження"))
        for c in cav:
            txt = (c.get("text_en") if en else None) or c.get("text_uk") or c.get("code") or ""
            doc.text("• " + txt, 8.2, h=4.1)  # no English template → the Ukrainian original, never a guess
            p.ln(0.6)
    doc.heading(t("Про метод"))
    for line in method_texts("en" if en else "uk"):
        doc.text(line, 8.2, h=4.1)
        p.ln(0.4)
    doc.text(t("Версія методу {mv} · дані {dv} · звіт {rid}").format(
        mv=rep.get('method_version') or '—', dv=rep.get('data_version') or '—', rid=rep.get('report_id')), 7.5, False, INK2)
    doc.heading(t("Дані"))
    doc.text(" · ".join(f"{a} ({b})" for a, b in sources("en" if en else "uk")) + " · " + t("шрифт Onest (SIL OFL 1.1)"), 7.5, False, INK2)
    # link + QR
    if p.get_y() > p.h - 44:
        p.add_page()
    p.ln(3)
    y = p.get_y()
    try:
        import segno

        q = segno.make(link, error="m")
        buf = io.BytesIO()
        q.save(buf, kind="png", scale=8, border=1, dark="#0d1220")
        buf.seek(0)
        p.image(buf, x=p.w - 16 - 26, y=y, w=26, h=26)
    except Exception:  # noqa: BLE001 — QR is optional
        log.exception("pdf qr failed")
    p.set_xy(16, y + 2)
    doc.font(8, True, INK)
    p.cell(0, 5, t("Відкрити цей звіт на сайті:"))
    p.set_xy(16, y + 8)
    doc.font(8, False, REF)
    for i, line in enumerate(wrap_link(link, p.get_string_width, p.w - 32 - 34)):
        p.set_xy(16, y + 8 + i * 4.2)
        p.cell(p.w - 32 - 34, 4.2, line, link=link)
    p.set_xy(16, max(p.get_y() + 5, y + 20))
    doc.font(7, False, INK2)
    p.cell(0, 4, t("Створено {d} · LST — температура поверхні, не повітря").format(d=time.strftime('%d.%m.%Y', time.gmtime())))
    out = p.output()
    return bytes(out)


# ------------------------------------------------------------------ cache

def _dir() -> Path:
    return get_settings().cache_dir / "export"


def _trim(d: Path) -> None:
    files = sorted((f for f in d.glob("*.pdf")), key=lambda f: f.stat().st_mtime)
    total = sum(f.stat().st_size for f in files)
    while files and total > CACHE_MAX_BYTES:
        f = files.pop(0)
        try:
            total -= f.stat().st_size
            f.unlink()
        except OSError:
            pass


def get(rep: dict, link: str, lang: str = "uk") -> bytes:
    parts = [SCHEMA, *(["en"] if lang == "en" else []), rep["report_id"], str(rep.get("method_version")), str((rep.get("zone") or {}).get("name")),
             link, str(rep.get("hotspots_version"))]
    if lang == "en":  # science's English templates may arrive later than the cached file
        parts.append(json.dumps([rep.get("verdict_text_en"), [c.get("text_en") for c in rep.get("caveats") or []]],
                                ensure_ascii=False))
    key = hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]
    d = _dir()
    f = d / f"{rep['report_id']}.{key}.pdf"
    try:
        body = f.read_bytes()
        os.utime(f)  # LRU by mtime
        return body
    except FileNotFoundError:
        pass
    body = build(rep, link, lang)
    with _lock:
        try:
            d.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            tmp.write_bytes(body)
            tmp.replace(f)
            _trim(d)
        except OSError as e:
            log.warning("pdf cache not written", extra={"err": str(e)})
    return body


# ------------------------------------------------------------------ English template labels (item 32, TERMS-EN)

EN: dict[str, str] = {
    "км": "km", "м": "m", "км²": "km²", "Пн": "N", "10 р.": "10 yr",
    "Розрив із лісом, середнє": "Gap with the forest, mean", "останнє літо {v} °C": "last summer {v} °C",
    "Тренд розриву": "Gap trend", "Висновок": "Verdict", "{n} із даними": "{n} with data",
    "Суттєво": "Significant", "Поки несуттєво": "Not yet significant", "Замало даних": "Too little data for a trend",
    "статистично значущо": "statistically significant", "статистично незначущо": "not statistically significant",
    "забудова зони (LST, °C)": "built-up land of the area (LST, °C)", "ліс-еталон (LST, °C)": "reference forest (LST, °C)",
    "Рік": "Year", "LST зони": "Area LST", "LST лісу": "Forest LST", "Розрив": "Gap", "Забудова": "Built-up",
    "Знімків": "Images", "Метод / причина": "Method / reason",
    "Розрив з лісом": "Gap with the forest", "Понад забудову зони": "Above the area's built-up land", "Площа": "Area",
    "Тип": "Type", "Координати (пн. ш. / сх. д.)": "Coordinates (N / E)", "Літні сезони": "Summer seasons",
    "Номери — як на карті; «понад забудову зони» — наскільки точка гарячіша за середню забудову цієї ділянки.":
        "Numbers as on the map; «above the area's built-up land» is how much hotter the spot is than the mean "
        "built-up land of this area.",
    "Намальована ділянка": "Drawn area", "DELTAHEAT · Детектор міського тепла": "DELTAHEAT · URBAN HEAT DETECTIVE",
    "Літні сезони {a}–{b} · площа {s} км²": "Summer seasons {a}–{b} · area {s} km²",
    " · проаналізовано {s} км²": " · analysed {s} km²",
    "Розрив із лісом (°C), літо {yr}: від шавлієвого (прохолодніше за ліс) до малинового (гарячіше). "
    "Чорна лінія — ділянка; кружки — гарячі точки (номери — як у таблиці). Карта: Landsat 8, власні тайли.":
        "Gap with the forest (°C), summer {yr}: from sage (cooler than the forest) to crimson (hotter). Black line: the "
        "area; circles: hot spots (numbers as in the table). Map: Landsat 8, our own tiles.",
    "Температура поверхні по роках": "Surface temperature by year", "По роках": "By year",
    "Гарячі точки": "Hot spots",
    "найгарячіші місця забудови за останні 3 літні сезони з даними (середнє за ці сезони); ≥ 1 °C "
    "гарячіші за решту забудови ділянки; до 3 точок, ≥ 500 м одна від одної":
        "the hottest built-up places over the last 3 summer seasons with data (mean over these seasons); ≥ 1 °C hotter "
        "than the rest of the area's built-up land; up to 3 spots, ≥ 500 m apart",
    "Застереження": "Caveats", "Про метод": "About the method", "Дані": "Data",
    "Версія методу {mv} · дані {dv} · звіт {rid}": "Method version {mv} · data {dv} · report {rid}",
    "шрифт Onest (SIL OFL 1.1)": "Onest font (SIL OFL 1.1)",
    "Відкрити цей звіт на сайті:": "Open this report on the website:",
    "Створено {d} · LST — температура поверхні, не повітря": "Created {d} · LST is surface temperature, not air",
    # values shared with export.py
    "окремі знімки": "individual images", "середнє за літо": "summer mean", "змішано": "mixed",
    "немає продукту температури (USGS)": "no temperature product (USGS)",
    "хмари: мало чистих пікселів": "clouds: too few clear pixels", "замало пікселів забудови": "too few built-up pixels",
    "немає даних для лісу-еталону": "no data for the reference forest", "замало чистих знімків": "too few clear images",
}
