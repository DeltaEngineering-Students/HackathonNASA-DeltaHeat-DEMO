"""Rule-based check of required caveats in the analyst's answer (CLAUDE-API-PLAN §4.2).

``check_caveats(answer, sources)`` returns the missing / violated rules; the loop feeds them, together with the
number validator's unsourced numbers, into ONE repair turn. The rules are deliberately simple regexes over
Ukrainian (and English) wording — the system prompt states each rule, this only catches misses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

_TEMP_NUM = re.compile(r"\d\s*°\s*[CС]?|\d\s*градус", re.I)
_SURFACE = re.compile(r"поверхн|surface", re.I)
_AIR = re.compile(r"повітр|\bair\b", re.I)
_AIR_NEG = re.compile(r"не\s+(?:про\s+|температур\w*\s+)?повітр|а\s+не\s+повітр|not\s+(?:the\s+)?air", re.I)
_TREND_TALK = re.compile(r"тренд|зріс|зрост|зменш|змінив|змінюв|за 10 рок|за десятил|на рік|теплішає|росте|trend",
                         re.I)
_NOT_SIGNIF = re.compile(r"не\s*значущ|незначущ|помітно не змін|у межах шуму|не можна стверджувати|"
                         r"(?:not|n['’]t)\s+(?:statistically\s+)?significant|відсутн\w*\s+(?:статистично\s+)?значущ|без\s+значущ|"
                         r"non[-\s]?significant|no\s+(?:statistically\s+)?significant|lack of (?:a\s+)?significan", re.I)
_SIGNIF_CLAIM = re.compile(r"(?<![\wʼ'’])(?<!не)(?<!не\s)(?<!не )значущ\w*|(?<!not )(?<!in)significant", re.I)
_INSUFF = re.compile(r"недостатньо даних|замало|мало (?:років|сцен|знімків|даних)|insufficient", re.I)
_WAR = re.compile(r"окупов|війн|воєн|бойов|руйнув|фронт|occupied|\bwar\b", re.I)
_EXCL_WORDS = re.compile(r"немає|нема\b|відсутн|виключ|не вистач|недостатньо|без даних|без значення|не рахува|"
                         r"хмар|не порахува|пропущ|no value|excluded|missing", re.I)
_CAUSAL = re.compile(r"через|спричин|внаслідок|обумовл|завдяки|due to|caused", re.I)
_CAUSE_OBJ = re.compile(r"забудов|ЖК|будин|будів|зелен|дерев|асфальт|construction|building", re.I)
_PCT = re.compile(r"\d\s*(?:%|відсот)", re.I)
_REF_WORDS = re.compile(r"еталон|ліс|reference|forest", re.I)
_NEW_BUILT = re.compile(r"нов\w*\s+забудов|new[- ]built|new construction", re.I)
_SENT = re.compile(r"(?<=[.!?\n])\s+")
_YEAR = re.compile(r"(?<!\d)(20[12]\d)(?!\d)")


@dataclass(frozen=True)
class Missing:
    code: str
    message: str  # instruction for the repair turn (English, model-facing)

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


def _walk(obj: Any, path: str, out: list[tuple[str, Any]]) -> None:
    if isinstance(obj, dict):
        out.append((path, obj))
        for k, v in obj.items():
            _walk(v, f"{path}.{k}" if path else str(k), out)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _walk(v, f"{path}[{i}]", out)


@dataclass
class _Facts:
    lst: bool = False            # an LST / gap number exists in the sources
    climate: bool = False        # a CMIP6 projection was fetched
    weather: bool = False        # ERA5 weather was fetched
    war: bool = False            # occupied / war_zone caveat
    driver_reference: bool = False
    verdicts: tuple = ()         # verdicts of the main gap trends
    excluded_years: frozenset = frozenset()


def _facts(sources: Iterable[Any]) -> _Facts:
    nodes: list[tuple[str, Any]] = []
    for s in sources:
        if isinstance(s, (dict, list)):
            _walk(s, "", nodes)
    f = _Facts()
    verdicts: list[str] = []
    excl: set[int] = set()
    for path, d in nodes:
        keys = set(d)
        if keys & {"gap_summary", "zone_lst", "ref_lst", "gap", "zone_lst_c", "zone"} and (
                "gap_summary" in keys or "zone_lst" in keys or "gap" in keys):
            f.lst = True
        if "ssp245" in keys or "ssp585" in keys or (d.get("variable") == "tasmax" and "delta" in keys):
            # a projection, or the report's context.climate note (one scenario/period)
            f.climate = True
        if "overpass_hours_local" in keys or "previous_days" in keys:
            f.weather = True
        if d.get("gap_driver") == "reference":
            f.driver_reference = True
        cv = d.get("caveats")
        if isinstance(cv, list):
            for c in cv:
                code = c.get("code") if isinstance(c, dict) else c
                if code in ("occupied", "war_zone"):
                    f.war = True
        if isinstance(d.get("occupied"), dict) or isinstance(d.get("war_region"), dict):
            f.war = True
        tr = d.get("trend")
        last = path.rsplit(".", 1)[-1]
        if isinstance(tr, dict) and isinstance(tr.get("verdict"), str) and last not in ("green_gap", "secondary"):
            verdicts.append(tr["verdict"])
        if "rank" in keys and isinstance(d.get("verdict"), str):
            verdicts.append(d["verdict"])
        if "year" in keys and d.get("excluded") and isinstance(d.get("year"), int):
            excl.add(d["year"])
    f.verdicts = tuple(verdicts)
    f.excluded_years = frozenset(excl)
    return f


def _web_split(answer: str) -> str:
    """Only the data part is checked: text under «Гіпотези з інтернету» is the model's labelled web part."""
    m = re.search(r"гіпотези з інтернету|hypotheses from the web", answer, re.I)
    return answer[: m.start()] if m else answer


def check_caveats(answer: str, sources: Iterable[Any]) -> list[Missing]:
    sources = list(sources)
    f = _facts(sources)
    text = _web_split(answer)
    sentences = [s for s in _SENT.split(text) if s.strip()]
    out: list[Missing] = []
    has_temp = bool(_TEMP_NUM.search(text))

    if f.lst and has_temp and not _SURFACE.search(text) and not (f.climate and not _surface_numbers(sentences)):
        out.append(Missing("lst_not_air", "Say that the temperatures/gap are land SURFACE temperature "
                                          "(«температура поверхні»), not air temperature."))
    if f.lst and not (f.climate or f.weather):
        for s in sentences:
            if _AIR.search(s) and _TEMP_NUM.search(s) and not _AIR_NEG.search(s):
                out.append(Missing("air_claim", "Our numbers are surface temperature; do not describe them as air "
                                                "temperature (write «поверхня, не повітря»)."))
                break
    talks_trend = bool(_TREND_TALK.search(text))
    if f.verdicts and talks_trend:
        if all(v == "not_significant" for v in f.verdicts) and not _NOT_SIGNIF.search(text):
            out.append(Missing("significance_wording", "The gap trend is not_significant: say «статистично "
                                                       "незначуще» / «помітно не змінився»."))
        if "significant" not in f.verdicts and any(_SIGNIF_CLAIM.search(s) and not _NOT_SIGNIF.search(s)
                                                   for s in sentences):
            out.append(Missing("significance_claim", "No trend here is significant; do not call it «значущий»."))
        if all(v == "insufficient_data" for v in f.verdicts) and not _INSUFF.search(text):
            out.append(Missing("insufficient_data", "The trend verdict is insufficient_data: say «недостатньо "
                                                    "даних» and do not present the slope as a finding."))
    if f.war and not _WAR.search(answer):
        out.append(Missing("war_zone", "The zone is in an occupied / war region: say so, and that 2022–2025 "
                                       "changes may be destruction."))
    for y in sorted(f.excluded_years):
        for s in sentences:
            if re.search(rf"(?<!\d){y}(?!\d)", s) and not re.search(rf"{y}\s*[–—-]\s*20\d\d|20\d\d\s*[–—-]\s*{y}", s) \
                    and not _EXCL_WORDS.search(s) and re.search(r"\d[.,]\d", _YEAR.sub("", s)):
                out.append(Missing("excluded_year", f"{y} has no gap value in the series (excluded); say that and "
                                                     "why instead of giving a number for it."))
                break
        else:
            continue
        break
    if f.climate:
        if not _AIR.search(text) and has_temp:
            out.append(Missing("cmip6_air", "CMIP6 projections are AIR temperature («температура повітря»)."))
    for s in sentences:
        if _PCT.search(s) and _CAUSAL.search(s) and _CAUSE_OBJ.search(s) and not re.search(r"хмар|cloud", s, re.I):
            out.append(Missing("causal_share", "Do not state a causal share («X % через забудову»); show the "
                                               "association without a percentage of cause."))
            break
    if f.driver_reference and talks_trend and not _REF_WORDS.search(text):
        out.append(Missing("gap_driver_reference", "The gap changed mostly because the forest reference changed "
                                                   "(gap_driver = reference); say so."))
    for s in sentences:
        if _NEW_BUILT.search(s) and _SIGNIF_CLAIM.search(s) and not _NOT_SIGNIF.search(s):
            out.append(Missing("new_built_significance", "The new-construction before/after gap has no "
                                                         "significance test; do not call it significant."))
            break
    return out


def _surface_numbers(sentences: list[str]) -> bool:
    return any(_TEMP_NUM.search(s) and re.search(r"розрив|lst|gap|поверхн|забудов|ліс", s, re.I) for s in sentences)
