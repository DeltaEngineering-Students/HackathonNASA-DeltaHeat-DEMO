"""analyze(): the full report for POST /api/analyze (minus report_id), Ukrainian texts."""
from __future__ import annotations

import copy
import logging

from . import analysis as A
from . import data as D
from . import stats as ST
from ._lru import LRU
from .geometry import geometry_hash

log = logging.getLogger("uhd.science.report")

METHOD_VERSION = "sci-v3.6"  # bump with any change of report numbers/texts (backend keys reports by it)
TILES_VERSION = "tiles-v2"   # bump whenever gap/lst/ndvi tile values change
# Backend keys tiles AND reports by DATA_VERSION: change it only when derived rasters/tile values change.
DATA_VERSION = "l8c2l2-60m-2013-2025/sci-v3"

CAVEATS_UK = {
    "basis_always_built": "Головний розрив рахуємо на ділянках, забудованих в усі роки періоду ({km2} км²): так "
                          "поява нової забудови не створює хибного тренду. Варіант «забудова кожного року» — у деталях.",
    "basis_built_each_year": "Постійно забудованої площі замало (< 0,5 км²), тому розрив рахуємо по забудові кожного "
                             "року — тренд може відображати й саму появу нової забудови.",
    "suburb_reference": "Ділянка за межею міста, але в його приміській смузі (до 15 км) — порівнюємо з тим самим "
                        "лісом-еталоном, що й райони {city}, щоб цифри можна було ставити поруч.",
    "lst_not_air": "Це денна температура підстильної поверхні (знімок близько 11:00 за місцевим сонячним часом), а не приземна температура повітря (на висоті 2 м). Розрив між поверхнями зазвичай більший, ніж між температурами приземного повітря.",
    "composite_method": "Для цієї території немає окремих знімків по датах, тому використано середнє за літо. На стиках знімків Landsat в окремі роки можлива похибка розриву 1–2 °C.",
    "mixed_method": "У {years} р. для зони замало чистих знімків, тому для цих років використано середнє за літо замість порівняння в межах одного знімка.",
    "low_coverage": "У {years} р. чисті знімки покривають лише частину зони — ці роки менш надійні.",
    "years_excluded": "{years} р. виключено: замало даних (замало чистих знімків або замало забудови в зоні).",
    "no_lst_product": "{years} р.: для цієї ділянки Landsat не дає температури поверхні — у продукті USGS тут "
                      "прогалина (бракує даних про випромінювальну здатність поверхні). Це не хмари: знімки чисті, "
                      "але температуру з них не розраховано.",
    "zone_clipped": "Частина території (≈{km2} км²) лежить за кордоном України — її не аналізуємо.",
    "war_zone": "Територія в регіоні, де з {since} р. тривають окупація або бойові дії ({region}). Зміни 2022–2025 р. "
                "можуть бути наслідком війни і руйнувань, а карти забудови після 2023 р. екстрапольовані й "
                "руйнувань не бачать.",
    "occupied": "Окупована територія (станом на {date}, джерело: {source}). Зміни 2022–2025 р. можуть бути наслідком "
                "війни і руйнувань, а карти забудови після 2023 р. екстрапольовані й руйнувань не бачать.",
    "few_years": "Для висновку про тренд потрібно щонайменше 8 років з даними — зараз {n}.",
    "small_zone": "На ділянці замало забудови (< 0,5 км²) — результат нерепрезентативний.",
    "all_land_zone": "На ділянці майже немає забудови, тому з лісом-еталоном порівнюємо всю її поверхню (як контроль).",
    "derived_reference": "Межу міста визначено автоматично за картою забудови; еталон — стабільний ліс у кільці "
                         "{r0}–{r1} км від межі міста (забудованої території), не від центру.",
    "ref_higher": "Ліс-еталон лежить у середньому на {dz} м вище за забудову, а вище поверхня прохолодніша, тож розрив "
                  "може бути завищеним.",
    "ref_match_fallback": "Лісу на тій самій висоті (±100 м), що й забудова, замало ({km2} км²), тому еталоном "
                          "лишається весь ліс кільця.",
    "ref_elev_matched": "Ліс-еталон підібрано на тій самій висоті (±100 м), що й забудова: {km2} км² із {km2_all} км² "
                        "лісу кільця.",
    "ref_weak": "Ліс-еталон тут малий або подрібнений ({km2} км² лісосмуг і гаїв) і тепліший за великі ліси, "
                "тож розрив може бути заниженим.",
    "urban_area_is_zone": "Поруч немає суцільної забудови — кільце лісу-еталона побудовано навколо самої ділянки.",
    "ring_widened": "Біля міста замало стабільного лісу, тому кільце лісу-еталона розширено до {r1} км.",
    "urban_area_clipped": "Агломерація дуже велика — межу міста обрізано в радіусі ~60 км від зони.",
    "few_reference_px": "Навколо ділянки збереглося мало лісу ({km2} км²), показник розриву може бути неточним.",
    "ref_border_clipped": "Частина лісу в кільці лежить за кордоном України ({km2} км²) — її не беремо, еталон лише "
                          "з лісу в Україні.",
    "classes_extrapolated": "Щорічні карти забудови є лише за 2017–2023; для {years} їх оцінено за зеленню і «бетонним» індексом знімків відносно найближчого року. Руйнування ці оцінки не бачать.",
    "not_significant_physics": "«Поки несуттєво» не означає «нічого не змінилось»: за 10–13 літніх сезонів розрив з лісом між окремими літніми сезонами коливається приблизно на 1 °C, а тінь нових висоток зранку і повільний ріст дерев приховують зміну. Подивіться також, як змінилися зелень і забудова.",
    "reference_warming": "Сам ліс-еталон помітно змінюється ({slope} °C за 10 років) — частина зміни розриву пов'язана з погодою регіону, а не з містом.",
}


def _caveat(code: str, **kw) -> dict:
    return dict(code=code, text_uk=CAVEATS_UK[code].format(**kw))


def _years_str(ys: list[int]) -> str:
    """[2013, 2014, 2015, 2020] -> "2013–2015, 2020"."""
    parts, ys = [], sorted(ys)
    i = 0
    while i < len(ys):
        j = i
        while j + 1 < len(ys) and ys[j + 1] == ys[j] + 1:
            j += 1
        parts.append(str(ys[i]) if j == i else (f"{ys[i]}, {ys[j]}" if j == i + 1 else f"{ys[i]}–{ys[j]}"))
        i = j + 1
    return ", ".join(parts)


def _uk_num(v: float, nd: int = 1) -> str:
    r = ST.rnd(v, nd)
    return f"{r:.{nd}f}".replace(".", ",").replace("-", "−")


def _lit(n: int) -> str:
    """«літній сезон» after a number (mentor wording, item 31): 1 літній сезон, 2–4 літні сезони, 5+ літніх сезонів."""
    if n % 10 == 1 and n % 100 != 11:
        return "літній сезон"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "літні сезони"
    return "літніх сезонів"


def driver(tr: dict, zone_tr: dict, ref_tr: dict) -> str | None:
    """Which side moves the gap: "reference" when the forest line explains most of a significant gap change
    (opposite sign and at least as large as the zone's own change), "zone" otherwise, None if not significant."""
    if tr["verdict"] != "significant" or zone_tr["slope_per_decade"] is None or ref_tr["slope_per_decade"] is None:
        return None
    g, z, r = tr["slope_per_decade"], zone_tr["slope_per_decade"], ref_tr["slope_per_decade"]
    if (g > 0 > r or g < 0 < r) and abs(r) >= abs(z):
        return "reference"
    return "zone"


def verdict_text(name: str | None, city_gen: str, mode: str, gs: dict, tr: dict, ref_tr: dict,
                 ndvi_tr: dict, green: dict | None, zone_tr: dict | None = None, new_built: dict | None = None) -> str:
    """Lead answers both halves of the question (hotter? getting worse?) and says *surface* (QA-UX C1/C2/C10/C12)."""
    pre = f"{name}: " if name else ""
    if gs["mean"] is None:
        return f"{pre}недостатньо даних для висновку." if name else "Недостатньо даних для висновку."
    subj = "поверхня забудови" if mode == "built" else "поверхня тут"
    mean = gs["mean"]
    if abs(mean) < 0.5:
        s1 = f"{subj} влітку вдень майже така ж тепла, як ліс навколо {city_gen} (різниця {_uk_num(abs(mean))} °C)"
    else:
        word = "гарячіша" if mean > 0 else "прохолодніша"
        s1 = f"{subj} влітку вдень у середньому на {_uk_num(abs(mean))} °C {word}, ніж ліс навколо {city_gen}"
    v, n = tr["verdict"], tr["n_years"]
    if v == "insufficient_data":
        s2 = ", але даних замало, щоб сказати, чи цей розрив змінюється."
    elif v == "significant":
        sl = tr["slope_per_decade"]
        s2 = f", і за {n} {_lit(n)} цей розрив {'зріс' if sl > 0 else 'зменшився'} — приблизно на " \
             f"{_uk_num(abs(sl))} °C за 10 років (статистично значуще, p = {_uk_num(tr['p'], 3)})."
    else:
        s2 = f", і за {n} {_lit(n)} цей розрив помітно не змінився (статистично незначуще, p = {_uk_num(tr['p'], 2)})."
    lead = pre + s1 + s2
    if not name:
        lead = lead[0].upper() + lead[1:]
    parts = [lead]
    d = driver(tr, zone_tr or {"slope_per_decade": None}, ref_tr)
    if d == "reference":
        what = "зріс" if tr["slope_per_decade"] > 0 else "зменшився"
        parts.append(f"Розрив {what} здебільшого через ліс-еталон: у ці літні сезони він був "
                     f"{'прохолоднішим' if ref_tr['slope_per_decade'] < 0 else 'теплішим'} "
                     f"({_uk_num(ref_tr['slope_per_decade'])} °C за 10 років), а сама поверхня тут змінилась менше "
                     f"({_uk_num(zone_tr['slope_per_decade'])} °C за 10 років).")
    elif d == "zone" and zone_tr and zone_tr["verdict"] == "significant":
        w = "нагрівається" if zone_tr["slope_per_decade"] > 0 else "охолоджується"
        num = f"її поверхня {w} на {_uk_num(abs(zone_tr['slope_per_decade']))} °C за 10 років."
        if ref_tr.get("verdict") == "significant":     # the forest moves too: keep the plain statement
            parts.append(f"Змінюється саме ця територія: {num}")
        else:                                          # M4: a flat forest trend does not prove the forest is stable
            parts.append(f"Ліс-еталон не має статистично значущого тренду, тож зміна йде від самої території: {num}")
    nb = new_built_sentence(new_built)
    if nb:
        parts.append(nb)
    if ndvi_tr["verdict"] == "significant":
        parts.append("Зелені на ділянці статистично значуще " + ("більшає." if ndvi_tr["slope_per_decade"] > 0 else "меншає."))
    if green and green.get("mean") is not None and mode == "built" and green["mean"] > 0:
        parts.append(f"Парки й сквери всередині міста на {_uk_num(green['mean'])} °C прохолодніші за цю забудову.")
    return " ".join(parts)


def sealed_share_ghsl(zone) -> dict | None:
    """GHSL GHS-BUILT-S sealed surface (roofs + paving) as a share of the zone area, {"2015": .., "2020": .., "2025": ..}.
    Independent of the Esri "built" class, which is urban fabric incl. yards, parks and dachas (INVESTIGATION-BUILT-SHARE)."""
    import shapely.geometry as sg

    from . import ghsl_built
    try:
        km2 = ghsl_built(sg.mapping(zone.shape_ll))
    except Exception:  # noqa: BLE001 — optional evidence, never fails a report
        return None
    a = zone.area_km2
    if not a or all(v is None for v in km2.values()):
        return None
    return {y: (None if v is None else round(min(v / a, 1.0), 3)) for y, v in km2.items()}


def reference_quality_caveats(ctx) -> list[dict]:
    """INVESTIGATION-REGIONAL-GAP: the elevation match (sci-v3.6, fix 3: ref_elev_matched) and caveats 1 and 2
    (text only): reference forest much higher than the zone's built surface (ref_higher, + ref_match_fallback when
    too little forest lies at the built-up elevation) / small, fragmented or riparian reference (ref_weak)."""
    from . import elevmatch as EM
    from . import refquality as Q

    out = []
    em = ctx.elev
    if em is not None and em.applied:
        if EM.shown(em):        # Київ drops 0.2 % with Δz unchanged: no line (noise on the demo city)
            out.append(_caveat("ref_elev_matched", km2=_uk_num(em.px_kept * D.PX_KM2),
                               km2_all=_uk_num(em.px_total * D.PX_KM2)))
    basis = EM.basis_pixels(ctx)
    try:
        if em is not None and em.dz_after_m is not None:
            dz = em.dz_after_m                  # 60 m DEM, the reference actually used
        else:
            dz = Q.elevation_diff(ctx.ref, ctx.zone.aoi, ctx.zone.win, basis)
        if dz is not None and dz >= Q.HIGHER_M:
            out.append(_caveat("ref_higher", dz=int(round(dz, -1))))
            if em is not None and em.status == "fallback":
                out.append(_caveat("ref_match_fallback", km2=_uk_num(em.px_kept * D.PX_KM2)))
        q = Q.quality(ctx.ref)
        if Q.is_weak(q) and q["forest_km2"] >= 5:      # < 5 km² already says few_reference_px
            out.append(_caveat("ref_weak", km2=_uk_num(q["forest_km2"])))
    except Exception:  # noqa: BLE001 — a caveat never breaks a report
        log.exception("reference quality caveats failed")
    return out


def _uk_date(iso: str | None) -> str:
    if not iso:
        return "дату переліку"
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


NEW_BUILT_MIN_KM2 = 0.2
NEW_BUILT_MIN_JUMP = 1.0


def new_built_sentence(nb: dict | None) -> str | None:
    """Concept §6 (before/after where they build): said only for a clear jump on a real area of new construction.
    A before/after of two 2-year means, not a trend test — the text gives the numbers, not a significance claim."""
    if not nb or nb["area_km2"] < NEW_BUILT_MIN_KM2 or nb["before"]["gap"] is None or nb["after"]["gap"] is None:
        return None
    b, a = nb["before"]["gap"], nb["after"]["gap"]
    if abs(a - b) < NEW_BUILT_MIN_JUMP:
        return None
    yb, ya = nb["before"]["years"], nb["after"]["years"]
    return (f"Там, де за ці роки з’явилась нова забудова (≈{_uk_num(nb['area_km2'])} км²), поверхня стала "
            f"{'гарячішою' if a > b else 'прохолоднішою'}: розрив із лісом був {_uk_num(b)} °C у {yb[0]}–{yb[-1]} р., "
            f"а став {_uk_num(a)} °C у {ya[0]}–{ya[-1]} р.")


_CACHE = LRU(128)


def analyze(geometry: dict, years=None, name: str | None = None) -> dict:
    """Report for a zone. Computed and cached without the name; ``name`` only labels the copy returned."""
    key = (geometry_hash(geometry, years), METHOD_VERSION)
    hit = _CACHE.get(key)
    if hit is None:
        hit = _analyze(geometry, years)
        _CACHE.put(key, hit)
    rep, vargs = hit
    out = copy.deepcopy(rep)
    out["zone"]["name"] = name
    out["verdict_text_uk"] = verdict_text(name, *vargs)
    return out


def _analyze(geometry: dict, years) -> tuple[dict, tuple]:
    ctx = A.build_context(geometry, years)
    ser = A.series(ctx)
    ys = [r["year"] for r in ser]
    gaps = [r["gap"] for r in ser]
    caveats = [_caveat("lst_not_air")]

    built_px_max = max(int(((ctx.cls == 1) & ctx.zone.mask).sum(axis=(1, 2)).max()), 0)
    analysed_km2 = max(r["n_px"] for r in ser) * D.PX_KM2
    too_small = analysed_km2 < A.MIN_ZONE_KM2

    tr = ST.trend(ys, gaps)
    if too_small:
        tr["verdict"] = "insufficient_data"
        caveats.append(_caveat("small_zone"))
    ref_tr = ST.trend(ys, [r["ref_lst"] for r in ser])
    zone_tr = ST.trend(ys, [r["zone_lst"] for r in ser])
    ndvi_tr = ST.trend(ys, [r["ndvi"] for r in ser], nd=3)
    green_vals = [r["green_gap"] for r in ser]
    green = None
    if any(v is not None for v in green_vals) and ctx.mode == "built":
        gsum = ST.summary(green_vals)
        green = dict(mean=gsum["mean"], last=gsum["last"], scope="urban_parks", trend=ST.trend(ys, green_vals))

    secondary = None
    if ctx.basis == "always_built":
        caveats.append(_caveat("basis_always_built", km2=_uk_num(analysed_km2, 2)))
        s2 = A.series_basis(ctx, "built_each_year")
        g2 = [r["gap"] for r in s2]
        secondary = dict(basis="built_each_year", gap_summary=ST.summary(g2), trend=ST.trend(ys, g2),
                         series=[dict(year=r["year"], gap=r["gap"]) for r in s2])
    elif ctx.basis == "built_each_year" and not too_small:
        caveats.append(_caveat("basis_built_each_year"))
    new_built = A.new_built_block(ctx)

    methods = {r["method"] for r in ser if r["gap"] is not None}
    method = "per_scene" if methods == {"per_scene"} else ("composite" if methods <= {"composite"} else "mixed")
    if method == "composite":
        caveats.append(_caveat("composite_method"))
    elif method == "mixed":
        caveats.append(_caveat("mixed_method", years=_years_str(
            [r["year"] for r in ser if r["gap"] is not None and r["method"] == "composite"])))
    nolst = [r["year"] for r in ser if r.get("excluded") == "no_lst_product"]
    if nolst:
        caveats.append(_caveat("no_lst_product", years=_years_str(nolst)))
    excl = [r["year"] for r in ser if r["gap"] is None and r.get("excluded") != "no_lst_product"]
    if excl and not too_small:
        caveats.append(_caveat("years_excluded", years=_years_str(excl)))
    low = [r["year"] for r in ser if r["gap"] is not None and (r["valid_share"] or 0) < A.LOW_VALID_SHARE]
    if low:
        caveats.append(_caveat("low_coverage", years=_years_str(low)))
    if tr["verdict"] == "insufficient_data" and not too_small:
        caveats.append(_caveat("few_years", n=tr["n_years"]))
    if ctx.mode == "all_land":
        caveats.append(_caveat("all_land_zone"))
    ref = ctx.ref
    if ctx.zone.clipped_km2:
        caveats.append(_caveat("zone_clipped", km2=_uk_num(ctx.zone.clipped_km2)))
    if ctx.zone.occupied:
        caveats.append(_caveat("occupied", date=_uk_date(ctx.zone.occupied["snapshot_date"]),
                               source="Мінрозвитку, наказ № 376"))
    elif ctx.zone.war_region:
        caveats.append(_caveat("war_zone", since=ctx.zone.war_region["since"], region=ctx.zone.war_region["name"]))
    if ctx.zone.suburb:
        caveats.append(_caveat("suburb_reference", city=D.CITY_GEN_UK[ctx.city]))
    if ref.kind == "derived":
        caveats.append(_caveat("derived_reference", r0=int(ref.ring_km[0]), r1=int(ref.ring_km[1])))
        for n in ref.notes:
            if n == "ring_widened":
                caveats.append(_caveat(n, r1=int(ref.ring_km[1])))
            elif n == "ref_border_clipped":
                caveats.append(_caveat(n, km2=_uk_num(ref.abroad_px * D.PX_KM2)))
            else:
                caveats.append(_caveat(n))
    if ref.forest_px * D.PX_KM2 < 5:
        caveats.append(_caveat("few_reference_px", km2=_uk_num(ref.forest_px * D.PX_KM2)))
    caveats += reference_quality_caveats(ctx)
    extrap = [y for y in ys if y < D.ESRI_YEARS[0] or y > D.ESRI_YEARS[-1]]
    if extrap:
        caveats.append(_caveat("classes_extrapolated", years=_years_str(extrap)))
    if tr["verdict"] == "not_significant":
        caveats.append(_caveat("not_significant_physics"))
    if ref_tr["verdict"] == "significant":
        caveats.append(_caveat("reference_warming", slope=_uk_num(ref_tr["slope_per_decade"])))

    gs = ST.summary(gaps)
    city_gen = D.CITY_GEN_UK.get(ctx.city, "міста") if ref.kind == "preset" else "міста"
    # excluded years: no gap, method null, `excluded` = reason (too_few_pixels | low_coverage | no_lst_product |
    # no_reference | too_few_scenes) so the UI never presents them as "from the composite" or uses their coverage
    public_series = [{k: r[k] for k in ("year", "zone_lst", "ref_lst", "gap", "ndvi", "ndbi", "built_share",
                                         "built_share_land", "built_share_zone", "scenes", "valid_share", "method")} | {"excluded": r.get("excluded"),
                                                                                "excluded_detail": r.get("excluded_detail")}
                     for r in ser]
    for r in public_series:
        if r["gap"] is None:
            r["method"] = None
    rep = dict(
        zone=dict(name=None, area_km2=round(ctx.zone.area_km2, 3),
                  # pixel counts can exceed the polygon area by a pixel edge (SCI-07): capped at the zone area
                  built_area_km2=round(min(built_px_max * D.PX_KM2, ctx.zone.area_km2), 3), analysed=ctx.mode,
                  basis=ctx.basis, analysed_area_km2=round(min(analysed_km2, ctx.zone.area_km2), 3),
                  clipped_km2=round(ctx.zone.clipped_km2, 3) if ctx.zone.clipped_km2 else None,
                  war_region=ctx.zone.war_region, occupied=ctx.zone.occupied,
                  sealed_share_ghsl=sealed_share_ghsl(ctx.zone),
                  city=ctx.city),
        reference=dict(city=ref.city if ref.kind == "preset" else "derived", ring_km=list(ref.ring_km),
                       area_km2=round(ref.forest_px * D.PX_KM2, 1), forest_px=ref.forest_px, kind=ref.kind,
                       urban_area_km2=round(float(ref.urban.sum()) * D.PX_KM2, 1),
                       elevation_match=ctx.elev.info() if ctx.elev is not None else None,
                       abroad_km2=round(ref.abroad_px * D.PX_KM2, 1)),
        series=public_series,
        gap_summary=gs,
        trend=tr,
        ref_trend=ref_tr,
        zone_trend=zone_tr,
        gap_driver=driver(tr, zone_tr, ref_tr),
        ndvi_trend=ndvi_tr,
        land_change=A.land_change(ctx),
        green_gap=green,
        secondary=secondary,
        new_built_gap=new_built,
        caveats=caveats,
        verdict_text_uk=None,
        method=method,
        years=[ys[0], ys[-1]],
        data_version=DATA_VERSION,
        method_version=METHOD_VERSION,
    )
    return rep, (city_gen, ctx.mode, gs, tr, ref_tr, ndvi_tr, green, zone_tr, new_built)
