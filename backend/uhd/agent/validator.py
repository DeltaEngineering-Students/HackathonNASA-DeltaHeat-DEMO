"""Number validator: every number in the analyst's answer must come from tool results (decisions #18/#19).

Sources are collected *with their JSON path* (``trend.slope_per_decade``, ``series[3].gap``, ``valid_share`` …), so an
answer number is matched only against source values of a compatible kind:

* precision: ``|src − ans| ≤ ½ unit of the last written digit`` (``6,2`` matches 6.23; ``6`` matches 6.23);
* unit: ``°C`` → temperature-like paths; ``%`` → ``*_share`` paths ×100 or percent fields (cloud, humidity);
  ``км²`` → area paths; numbers without a unit → any path (but never ×100);
* «розрив» in the same clause → only gap paths (gap, gap_summary, green_gap, the gap trend);
* ``p = …`` → only ``p`` fields;
* sign: must match, unless the clause says the value is lower/cooler/decreasing («прохолодн…», «менш…», «зменш…»);
* small integers (≤ 12) are skipped only when they carry no unit («3 причини»); «5 °C» is checked;
* dates (YYYY-MM-DD / DD.MM.YYYY) must appear in the sources; years (1950–2100) must appear as some value.
Numbers from the user's question and a short allow-list of fixed facts (system prompt) count as sourced.
Ignored: list markers («1.»), URLs, inline code, identifiers (LC08…, ssp245, report ids).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

_URL = re.compile(r"https?://\S+|\]\([^)]*\)")
_CODE = re.compile(r"`[^`]*`")
_SSP = re.compile(r"\bSSP\s?\d[\-‑–]?\d[.,]\d\b|\bssp\d{3}\b|\bRCP\s?\d[.,]\d\b", re.I)  # scenario names, not numbers
_DATE_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_DATE_UA = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4})(?![\d])")
# «23 серпня», «9 June»: the day of a written date is not a measured number (the year next to it is still checked)
_DAY_MONTH = re.compile(r"(?<![\d.,])\d{1,2}(?=(?:\s*[-–]\s*\d{1,2})?\s+(?:січня|лютого|березня|квітня|травня|червня|"
                        r"липня|серпня|вересня|жовтня|листопада|грудня|january|february|march|april|may|june|july|"
                        r"august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
                        r"\b)", re.I)
_LIST_MARK = re.compile(r"(?m)^\s*\d{1,2}[.)]\s")
_NUM = re.compile(r"(?<![\w.,])([-−–+]?)(\d{1,3}(?:[   ]\d{3})+|\d+)(?:[.,](\d+))?(?![\w])")
_UNIT = re.compile(r"^\s*(°\s*[CС]?|градус\w*|%|відсот\w*|км²|км2|кв\.?\s*км|km²)", re.I)
_CLAUSE_END = re.compile(r"[.;!?\n]\s|[;!?\n]")
_P_BEFORE = re.compile(r"\bp\s*(?:-value\s*)?[=<>≈≤≥]\s*$", re.I)
_DOWN_WORDS = re.compile(r"прохолод|холодн|менш|зменш|нижч|знизи|впа|спад|cooler|lower|decreas", re.I)
_TREND_DOWN = re.compile(r"зменш|знижу|знизи|впа[вл]|спада|скороч|охолод|холоднішає|decreas|declin|fall|cool", re.I)
_TREND_UP = re.compile(r"зрост|зріс|вирос|виріс|збільш|підвищ|посил|нагрів|нагріл|теплішає|increas|grow|rise|rose|warm",
                       re.I)
_SURFACE_WORD = re.compile(r"поверхн|територі|зона|зони|surface", re.I)
_NEW_BUILT_WORD = re.compile(r"нов[аоуі]\w* забудов|з’явил|з'явил|new[- ]built|new construction", re.I)
_GAP_WORD = re.compile(r"розрив|gap", re.I)
_GREEN_WORD = re.compile(r"парк|сквер|зелен|green|park", re.I)
_CI_WORD = re.compile(r"інтервал|довір|\bci\b|ci95|межа|межі|від .* до", re.I)
_NDVI_WORD = re.compile(r"ndvi|зелен|green", re.I)
_REF_WORD = re.compile(r"еталон|сам ліс|reference", re.I)

TEMP_PATH = re.compile(r"lst|gap|temperature|tasmax|jja|delta|slope|ci95|mean|last|min|max|value")
NOT_TEMP_PATH = re.compile(r"ndvi|ndbi|hot\d|days|share|area|km2|precip|wind|humid|cloud|radiation|_px|soil|n_years|"
                           r"scenes$|count|sun_|year")  # «scenes» only as a leaf (a count): list_scenes keeps LSTs under scenes[i]
AREA_PATH = re.compile(r"area|km2|always_built|new_built|always_green|value")
PCT_RAW_PATH = re.compile(r"cloud|humid")
GAP_PATH = re.compile(r"gap|(?<![a-z_])trend\.(slope_per_decade|ci95)|value")

# Fixed facts the analyst may state without a tool (system prompt): thresholds, resolution, overpass time, CI level.
DEFAULT_ALLOWED = (8, 10.5, 30, 60, 95, 0.05, 100)
SMALL_INT_MAX = 12


@dataclass
class NumberCheck:
    text: str
    value: float
    decimals: int
    sourced: bool
    kind: str = "number"


@dataclass
class ValidationResult:
    ok: bool
    checked: list[NumberCheck] = field(default_factory=list)

    @property
    def unsourced(self) -> list[NumberCheck]:
        return [c for c in self.checked if not c.sourced]

    def to_dict(self) -> dict:
        return {"ok": self.ok, "n_checked": len(self.checked),
                "unsourced": [{"text": c.text, "value": c.value, "kind": c.kind} for c in self.unsourced]}


Source = tuple[float, str]  # (value, json path); path "*" = matches any kind (question / allow-list)


def _strip(text: str) -> str:
    text = _URL.sub(" ", text)
    text = _CODE.sub(" ", text)
    text = _SSP.sub(" ", text)
    return _LIST_MARK.sub(" ", text)


def _parse(m: re.Match) -> tuple[float, int]:
    sign, intpart, frac = m.group(1), m.group(2), m.group(3)
    v = float(f"{re.sub(r'[   ]', '', intpart)}.{frac}" if frac else re.sub(r"[   ]", "", intpart))
    return (-v if sign in "-−–" and sign else v), (len(frac) if frac else 0)


def extract_numbers(text: str) -> list[tuple[str, float, int]]:
    """(raw text, value, decimals) for each number in free text (Ukrainian/English formats)."""
    return [(m.group(0), *_parse(m)) for m in _NUM.finditer(text)]


def extract_dates(text: str) -> list[tuple[str, str]]:
    out = [(m.group(0), m.group(0)) for m in _DATE_ISO.finditer(text)]
    out += [(m.group(0), f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}") for m in _DATE_UA.finditer(text)]
    return out


def collect_sources(obj: Any, path: str = "", acc: list[Source] | None = None,
                    dates: set[str] | None = None) -> tuple[list[Source], set[str]]:
    """All numbers with their JSON path (numbers inside strings get ``<path>.text``) and all ISO dates."""
    acc = [] if acc is None else acc
    dates = set() if dates is None else dates
    if isinstance(obj, bool) or obj is None:
        pass
    elif isinstance(obj, (int, float)):
        if math.isfinite(obj):
            acc.append((float(obj), path))
    elif isinstance(obj, str):
        for m in re.finditer(r"\d{4}-\d{2}-\d{2}", obj):
            dates.add(m.group(0))
        for _, iso in extract_dates(obj):
            dates.add(iso)
        for _, v, _ in extract_numbers(obj):
            acc.append((v, f"{path}.text"))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            # period keys («2041-2060» in climate projections) are years the answer may name
            for y in re.findall(r"(?<!\d)(\d{4})(?!\d)", str(k)):
                if 1950 <= int(y) <= 2100:
                    acc.append((float(y), f"{path}.{k}.key" if path else f"{k}.key"))
            collect_sources(v, f"{path}.{k}" if path else str(k), acc, dates)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            collect_sources(v, f"{path}[{i}]", acc, dates)
    return acc, dates


def collect_numbers(obj: Any) -> tuple[set[float], set[str]]:
    src, dates = collect_sources(obj)
    return {v for v, _ in src}, dates


def _leaf(path: str) -> str:
    return re.split(r"[.\[]", path.rstrip("]"))[-1] if path else ""


@dataclass(frozen=True)
class _Ctx:
    """What the clause around a number talks about (SCI-04: tie numbers to their semantic field)."""
    unit: str | None
    gap: bool
    p: bool
    green: bool
    ci: bool
    ndvi: bool
    ref: bool
    surface: bool = False
    new_built: bool = False


_TOP_TREND = re.compile(r"(^|[.\]])(trend|secondary\.trend)\.")


def _semantic_ok(lp: str, c: _Ctx) -> bool:
    if "ci95" in lp and not c.ci:  # a CI bound is not the value itself
        return False
    if "new_built_gap" in lp and not c.new_built:  # the gap on new construction only in a new-construction clause
        return False
    if "green_gap" in lp and not c.green:  # the parks gap is not the forest gap
        return False
    if c.green and "gap" in lp and "green_gap" not in lp and c.unit == "temp" and not c.p:
        return False  # «зелень/парки на X °C прохолодніші» → only the parks gap
    if c.p:  # p of the trend the clause names
        if c.ndvi:
            return "ndvi_trend" in lp or "green_gap" in lp
        if c.ref:
            return "ref_trend" in lp
        if c.gap:
            return bool(_TOP_TREND.search(lp)) and "ref_trend" not in lp and "ndvi_trend" not in lp
    return True


def _kind_ok(path: str, unit: str | None, gap_ctx: bool, p_ctx: bool, ctx: _Ctx | None = None) -> tuple[bool, bool]:
    """(path allowed, ×100 allowed) for an answer number with this unit/context."""
    if path == "*":
        return True, False
    lp = path.lower()
    if ctx is not None and not _semantic_ok(lp, ctx):
        return False, False
    if lp.endswith(".text"):  # a number quoted inside a source sentence: usable as-is, never as gap / p / share
        return not (p_ctx or gap_ctx or unit == "pct"), False
    if p_ctx:
        return _leaf(lp) == "p", False
    if unit == "pct":
        if _leaf(lp).endswith("share"):
            return True, True
        return bool(PCT_RAW_PATH.search(lp)), False
    if unit == "temp":
        ok = bool(TEMP_PATH.search(lp)) and not NOT_TEMP_PATH.search(lp)
        if gap_ctx and not (ctx is not None and ((ctx.ref and "ref_trend" in lp)
                                                  or (ctx.surface and "zone_trend" in lp))):
            ok = ok and bool(GAP_PATH.search(lp))
        return ok, False
    if unit == "area":
        return bool(AREA_PATH.search(lp)), False
    if gap_ctx:
        if ctx is not None and ((ctx.ref and "ref_trend" in lp) or (ctx.surface and "zone_trend" in lp)):
            return True, False  # «розрив зріс через ліс-еталон (−0,5 °C), а поверхня (+0,2 °C)»
        return bool(GAP_PATH.search(lp)) and not NOT_TEMP_PATH.search(lp), False
    return True, False


def _unit(after: str) -> str | None:
    m = _UNIT.match(after)
    if not m:
        return None
    u = m.group(1).lower()
    if u.startswith("°") or u.startswith("градус"):
        return "temp"
    if u.startswith("%") or u.startswith("відсот"):
        return "pct"
    return "area"


def _matches(v: float, d: int, sources: Iterable[Source], unit: str | None, gap_ctx: bool, p_ctx: bool,
             allow_flip: bool, ctx: _Ctx | None = None, explicit: bool = True, direction: int = 0) -> bool:
    tol = 0.5 * 10 ** (-d) + 1e-9
    for s, path in sources:
        ok, pct = _kind_ok(path, unit, gap_ctx, p_ctx, ctx)
        if not ok:
            continue
        if "slope" in path and path != "*":
            # a trend: the stated direction must agree with the sign («зменшився на 0,4» ≠ +0,4)
            stated = v if explicit else (direction * abs(v) if direction else v)
            if abs(s - stated) <= tol:
                return True
            continue
        for c in ((s, s * 100) if pct else (s,)):
            if abs(c - v) <= tol:
                return True
            # opposite sign is fine only when the clause says the value is lower/cooler/decreasing
            if allow_flip and abs(abs(c) - abs(v)) <= tol:
                return True
    return False


def _strings(obj: Any, out: list[str]) -> list[str]:
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _strings(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _strings(v, out)
    return out


def _drop_quoted(answer: str, tool_results: list) -> str:
    """Sentences copied verbatim from a tool result (the report's verdict or a caveat) are sourced as a whole."""
    src = " ".join(_strings(tool_results, []))
    if not src:
        return answer
    norm = lambda t: re.sub(r"\s+", " ", t).strip()  # noqa: E731
    srcn = norm(src)
    parts = re.split(r"(?<=[.!?])\s+", answer)
    return " ".join(p for p in parts if not (len(norm(p)) > 25 and norm(p) in srcn))


def validate(answer: str, tool_results: Iterable[Any], question: str = "",
             allowed: Iterable[float] = DEFAULT_ALLOWED) -> ValidationResult:
    tool_results = list(tool_results)
    sources, dates = collect_sources(tool_results)
    qn, qd = collect_numbers(question)
    sources += [(v, "*") for v in qn] + [(float(a), "*") for a in allowed]
    dates |= qd
    years = {v for v, _ in sources if v.is_integer() and 1950 <= v <= 2100}
    text = _strip(_drop_quoted(answer, tool_results))
    checks: list[NumberCheck] = []
    for raw, iso in extract_dates(text):
        checks.append(NumberCheck(raw, float(iso[:4]), 0, iso in dates, "date"))
    text = _DATE_ISO.sub(" ", _DATE_UA.sub(" ", text))
    text = _DAY_MONTH.sub(lambda m: " " * len(m.group(0)), text)
    for m in _NUM.finditer(text):
        v, d = _parse(m)
        before = text[: m.start()]
        after = text[m.end(): m.end() + 40]
        unit = _unit(after)
        cl_start = max((x.end() for x in _CLAUSE_END.finditer(before)), default=0)
        cl_end_m = _CLAUSE_END.search(after)
        clause = before[cl_start:] + m.group(0) + (after[: cl_end_m.start()] if cl_end_m else after)
        if d == 0 and 0 <= abs(v) <= SMALL_INT_MAX and unit is None:
            continue
        if d == 0 and unit is None and 1950 <= v <= 2100:
            checks.append(NumberCheck(m.group(0), v, 0, v in years, "year"))
            continue
        p_ctx = bool(_P_BEFORE.search(before[-20:]))
        # «розрив» binds the numbers of its own comma part only: in «зона 37,48 °C, ліс 26,53 °C, а розрив — 10,95 °C»
        # the first two are temperatures, not gaps
        head = before[cl_start:]
        tail = clause[len(head) + len(m.group(0)):]
        sub = head.rsplit(", ", 1)[-1] + m.group(0) + tail.split(", ", 1)[0]
        # «NDVI (0,366) і один з найбільших розривів»: a unitless number right after NDVI is NDVI, not a gap
        gap_ctx = bool(_GAP_WORD.search(sub)) and not (unit is None and _NDVI_WORD.search(before[-24:]))
        flip = bool(_DOWN_WORDS.search(clause))
        ctx = _Ctx(unit, gap_ctx, p_ctx, bool(_GREEN_WORD.search(clause)), bool(_CI_WORD.search(clause)),
                   bool(_NDVI_WORD.search(clause)), bool(_REF_WORD.search(clause)),
                   bool(_SURFACE_WORD.search(clause)), bool(_NEW_BUILT_WORD.search(clause)))
        # the direction word must be close to the number («зменшився на 0,4»), not anywhere in a long sentence
        near = before[-32:] + m.group(0) + after[:16]
        down, up = bool(_TREND_DOWN.search(near)), bool(_TREND_UP.search(near))
        direction = -1 if down and not up else (1 if up and not down else 0)
        ok = _matches(v, d, sources, unit, gap_ctx, p_ctx, flip, ctx, explicit=m.group(1) != "",
                      direction=direction)
        checks.append(NumberCheck(m.group(0), v, d, ok, {"temp": "°C", "pct": "%", "area": "km²"}.get(unit, "number")))
    return ValidationResult(all(c.sourced for c in checks), checks)


def dumps_for_sources(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
