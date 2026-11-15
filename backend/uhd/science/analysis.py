"""Per-year series for a zone: zone LST, reference LST, gap, NDVI/NDBI, built share, coverage.

Two LST methods (METHOD.md §5):
* per_scene  — preset cities: for every acquisition date, gap_d = mean LST(zone built px) − reference_d
               (reference_d = climatology-adjusted mean of the visible forest-ring pixels of that date);
               summer gap = median of gap_d over dates with zone coverage ≥ 50 % and ≥ MIN_REF_PX_DATE
               visible forest pixels. Removes the Landsat path seam (different dates on either side).
* composite  — elsewhere / fallback: gap = mean(lst_med over zone built px) − mean(lst_med over reference).
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np

from . import classes as C
from . import data as D
from . import elevmatch as EM
from .stats import rnd
from . import reference as R
from . import scenes as SC
from ._lru import LRU
from .geometry import Zone, make_zone

MIN_ZONE_KM2 = 0.5             # analysed (built or land) area needed for a verdict
MIN_YEAR_PX = 70               # ~0.25 km² of analysed pixels in a given year
MIN_VALID_SHARE = 0.5          # year dropped below this share of analysed px with any clear summer obs
LOW_VALID_SHARE = 0.8          # caveat below this
MIN_ZONE_COVER_DATE = 0.5      # per-scene: zone coverage needed on a date
MIN_REF_PX_DATE = 2000         # per-scene: visible reference forest px on a date (~7 km²)
MIN_DATES = 2                  # per-scene: dates needed per summer, else composite for that year
MIN_COMPOSITE_OBS = 2          # composite: median clear summer observations per analysed px, else year dropped
GREEN_MODE_BUILT_SHARE = 0.2   # zones with less built-up than this are analysed as a whole ("all_land")


def _f(v, nd=2):
    return rnd(v, nd)


@dataclass
class Context:
    zone: Zone
    city: str | None
    ref: R.Reference
    years: list[int]
    cls: np.ndarray                    # (n_years, h, w) classes on the zone window, for `years`
    mode: str = "built"                # built | all_land
    basis: str = "built_each_year"     # always_built | built_each_year | all_land | new_built (pixels analysed)
    notes: list[str] = field(default_factory=list)
    elev: EM.Match | None = None       # sci-v3.6 elevation match of the reference (ref is already the matched one)

    def basis_mask(self, basis: str) -> np.ndarray | None:
        """Fixed (all-years) mask for the fixed-pixel bases, None for per-year bases."""
        if basis in ("always_built", "new_built"):
            return C.land_change_masks(self.cls)[basis] & self.zone.mask
        return None

    def year_mask(self, i: int) -> np.ndarray:
        fixed = self.basis_mask(self.basis)
        if fixed is not None:
            return fixed
        c = self.cls[i]
        if self.basis == "built_each_year":
            return self.zone.mask & (c == C.BUILT)
        return self.zone.mask & (c != C.WATER) & (c != C.NONE)

    def land_mask(self, i: int) -> np.ndarray:
        c = self.cls[i]
        return self.zone.mask & (c != C.WATER) & (c != C.NONE)


def norm_years(years) -> list[int]:
    if not years:
        return list(D.YEARS)
    y0, y1 = int(years[0]), int(years[1])
    y0, y1 = max(min(y0, y1), D.YEARS[0]), min(max(y0, y1), D.YEARS[-1])
    return list(range(y0, y1 + 1))


def reference_for_zone(zone: Zone, city: str | None) -> R.Reference:
    if city is not None:
        return R.preset(city)
    return R.derive_cached(zone)


def build_context(geometry: dict, years=None) -> Context:
    zone, city = make_zone(geometry)
    ref = reference_for_zone(zone, city)
    ys = norm_years(years)
    cls = R.read_classes(zone.aoi, zone.win, ys)
    ctx = Context(zone=zone, city=city, ref=ref, years=ys, cls=cls)
    built_km2 = [float((zone.mask & (c == C.BUILT)).sum()) * D.PX_KM2 for c in cls]
    land_km2 = [float(ctx.land_mask(i).sum()) * D.PX_KM2 for i in range(len(ys))]
    share = np.median([b / l if l else 0 for b, l in zip(built_km2, land_km2)])
    if max(built_km2) < MIN_ZONE_KM2 or share < GREEN_MODE_BUILT_SHARE:
        ctx.mode = ctx.basis = "all_land"
    elif float(ctx.basis_mask("always_built").sum()) * D.PX_KM2 >= MIN_ZONE_KM2:
        ctx.basis = "always_built"      # concept #15: the headline follows the same pixels every year
    ctx.elev = EM.for_context(ctx)      # sci-v3.6: forest within ±100 m of the built basis' median elevation
    if ctx.elev.applied:
        ctx.ref = EM.matched_reference(ref, ctx.elev)
    return ctx


def ref_stats(ref: R.Reference) -> dict:
    """refstats of a preset reference — of its elevation-matched forest when the match is applied."""
    if ref.elev_band is not None:
        return EM.matched_stats(ref.city, tuple(ref.elev_band))
    return R.preset_stats(ref.city)


def series_basis(ctx: Context, basis: str) -> list[dict]:
    saved = ctx.basis
    try:
        ctx.basis = basis
        return series(ctx)
    finally:
        ctx.basis = saved


def city_reference_line(city: "str | R.Reference", year: int) -> float | None:
    """One reference line per preset city (sci-v3.3): median of the per-date reference (climatology-adjusted forest
    ring LST) over all usable acquisitions of the summer — the same for every zone of the city, so the chart's forest
    line and `ref_trend` no longer depend on which dates a zone happened to use. Zone line = this + gap.
    sci-v3.6: given a Reference, the line of its (possibly elevation-matched) forest."""
    st = (ref_stats(city) if isinstance(city, R.Reference) else R.preset_stats(city))["dates"].get(str(year)) or []
    v = [d["ref_lst_adj"] for d in st if d["ref_lst_adj"] is not None and d["ref_valid_px"] >= MIN_REF_PX_DATE]
    if len(v) < MIN_DATES:
        return None
    return float(np.median(v))


def ref_composite(ref: R.Reference, year: int) -> tuple[float | None, float | None]:
    """(reference LST, in-city green LST) from summer composites."""
    if ref.kind == "preset":
        st = ref_stats(ref)["composite"][str(year)]
        return st["ref_lst"], st["green_lst"]
    return _derived_ref_values(ref.key, ref, year)


_DERIVED_CACHE = LRU(4096)


def _derived_ref_values(key, ref: R.Reference, year: int):
    k = (key, year)
    v = _DERIVED_CACHE.get(k)
    if v is None:
        r, _ = R.composite_mean(ref.aoi, year, ref.win, ref.ref)
        g, _ = R.composite_mean(ref.aoi, year, ref.win, ref.green) if ref.green.sum() >= MIN_YEAR_PX else (None, 0)
        v = (r, g)
        _DERIVED_CACHE.put(k, v)
    return v


_FOOTPRINTS = LRU(48)


def footprints(aoi: str, year: int) -> dict[str, tuple]:
    """STAC scene footprints (EPSG:3035) and scene cloud % per scene id, from the raw items file."""
    k = (aoi, year)
    v = _FOOTPRINTS.get(k)
    if v is None:
        import json

        import shapely.geometry as sg

        from .geometry import to_3035

        p = D.RAW / aoi / "items" / f"{year}.json"
        v = {}
        if p.exists():
            for d in json.load(open(p)):
                if d.get("geometry"):
                    v[d["id"]] = (to_3035(sg.shape(d["geometry"])), d["properties"].get("eo:cloud_cover"))
        _FOOTPRINTS.put(k, v)
    return v


def pass_footprint(zone_m, aoi: str, year: int, ids: list[str]) -> tuple[float | None, float | None]:
    """(share of the zone inside the pass's footprint, scene cloud % weighted by each row's overlap with the zone).
    Same-date rows of one pass are merged; the zone usually lies in one of them, so its cloud is what matters
    (the plain mean mixed in the neighbouring row: 13.8 vs 2.4 % for Позняки 2020-06-13, INVESTIGATION-2020).
    STAC footprints are the corner polygon of the data area and slightly conservative (≈0.1 of a small zone)."""
    fps = footprints(aoi, year)
    parts = [fps[i] for i in ids if i in fps]
    if not parts or zone_m.area <= 0:
        return None, None
    ov = [g.intersection(zone_m).area for g, _ in parts]
    from shapely.ops import unary_union

    share = unary_union([g for g, _ in parts]).intersection(zone_m).area / zone_m.area
    cl = [(o, c) for o, (_, c) in zip(ov, parts) if c is not None]
    if not cl:
        return share, None
    w = sum(o for o, _ in cl)
    cloud = sum(o * c for o, c in cl) / w if w > 0 else float(np.mean([c for _, c in cl]))
    return float(share), float(cloud)


def classify_pass(row: dict) -> str | None:
    """Why a pass did not enter the per-scene gap: outside_swath (even if clear, < 50 % of the zone could be seen:
    the zone is outside or on the edge of the scene), zone_cloudy, reference_cloudy; None if used."""
    if row["used"]:
        return None
    seen = max(row.get("zone_in_swath") or 0.0, row["zone_cover"])   # clear share is a hard lower bound
    if seen < MIN_ZONE_COVER_DATE:
        return "outside_swath"
    if row["zone_cover"] < MIN_ZONE_COVER_DATE:
        return "zone_cloudy"
    return "reference_cloudy"


def _ddmm(date: str) -> str:
    return f"{date[8:10]}.{date[5:7]}"


def scenes_detail(rows: list[dict] | None, n_passes_items: int | None = None, n_outside_items: int | None = None) -> dict:
    """Structured reason for a `too_few_scenes` year (+ ready Ukrainian text), from the per-pass rows."""
    if rows is None:   # composite-only zone: no per-pass clear shares, only the footprints
        n, o = n_passes_items or 0, n_outside_items or 0
        txt = (f"Замало чистих знімків: менше двох чистих спостережень ділянки за літо (з {n} прольотів над нею"
               + (f", у {o} ділянка поза смугою знімання або на її краю" if o else "") + ").")
        return dict(usable_dates=None, n_passes_total=n, n_outside_swath=o, n_cloudy=None,
                    n_reference_cloudy=None, text_uk=txt)
    reasons = [classify_pass(r) for r in rows]
    usable = [r["date"] for r, why in zip(rows, reasons) if why is None]
    n_out, n_cl, n_ref = (sum(w == k for w in reasons) for k in ("outside_swath", "zone_cloudy", "reference_cloudy"))
    if not usable:
        lead = "Жодного чистого прольоту над ділянкою"
    elif len(usable) == 1:
        lead = f"Лише один чистий проліт над ділянкою ({_ddmm(usable[0])})"
    else:
        lead = f"Лише {len(usable)} чисті прольоти над ділянкою ({', '.join(_ddmm(d) for d in usable)})"
    parts = []
    if n_cl:
        parts.append(f"{n_cl} — хмарні над ділянкою")
    if n_out:
        parts.append(f"у {n_out} ділянка поза смугою знімання або на її краю")
    if n_ref:
        parts.append(f"{n_ref} — хмарно над лісом-еталоном")
    txt = lead + "." + (f" З {len(rows)} прольотів за літо {', '.join(parts)}." if parts else "") + \
        f" Для річного значення потрібно щонайменше {MIN_DATES}."
    return dict(usable_dates=usable, n_passes_total=len(rows), n_outside_swath=n_out, n_cloudy=n_cl,
                n_reference_cloudy=n_ref, text_uk=txt)


def per_scene_year(ctx: Context, i: int, year: int, mask: np.ndarray) -> dict | None:
    """Per-acquisition gaps for one summer; None if per-scene data are not available/usable."""
    if ctx.city is None or not SC.has_stack(ctx.city, year):
        return None
    stats = ref_stats(ctx.ref)
    st = stats["dates"].get(str(year))
    if not st:
        return None
    a = SC.window_lst(ctx.city, year, ctx.zone.win)
    r0, c0, h, w = ctx.zone.win
    zm, zs = SC.masked_means_adjusted(a, mask, np.asarray(SC.clim(ctx.city)[r0:r0 + h, c0:c0 + w]))
    rows = []
    ids = {x["date"]: x["ids"] for x in SC.dates(ctx.city, year)}
    for k, d in enumerate(st):
        ok = (zs[k] >= MIN_ZONE_COVER_DATE and d["ref_valid_px"] >= MIN_REF_PX_DATE
              and d["ref_lst_adj"] is not None and np.isfinite(zm[k]))
        g = d["green_lst_adj"] if (d["green_lst_adj"] is not None and d["green_valid_share"] and
                                   d["green_valid_share"] * stats["green_px"] >= 500) else None
        sw, cl = pass_footprint(ctx.zone.shape_m, ctx.city, year, ids.get(d["date"], []))
        rows.append(dict(date=d["date"], zone=zm[k], zone_cover=zs[k], ref=d["ref_lst_adj"],
                         ref_px=d["ref_valid_px"], green=g, used=bool(ok), zone_in_swath=sw, cloud_zone=cl))
    used = [r for r in rows if r["used"]]
    if len(used) < MIN_DATES:
        return dict(rows=rows, n_used=len(used), usable=False)
    gaps = [r["zone"] - r["ref"] for r in used]
    ggaps = [r["zone"] - r["green"] for r in used if r["green"] is not None]
    gap = float(np.median(gaps))
    ref_lst = float(np.median([r["ref"] for r in used]))
    # lines shown in the UI must satisfy zone_lst − ref_lst == gap: reference line = median reference over the
    # used (matched) dates, zone line = reference line + per-scene gap
    return dict(rows=rows, n_used=len(used), usable=True, gap=gap, zone_lst=ref_lst + gap, ref_lst=ref_lst,
                green_gap=float(np.median(ggaps)) if len(ggaps) >= MIN_DATES else None)


def no_lst_product(aoi: str, year: int, win, mask: np.ndarray, lst_n: np.ndarray) -> bool:
    """True if most of the zone had clear views (NDVI from >= 3 scenes) but never an LST value.

    Landsat C2 L2 has no surface temperature where its ASTER GED emissivity input is missing (emis = -9999 while
    qa_pixel says clear and the TOA thermal radiance exists) — fixed patches, the same in every year, mostly in the
    east (QA SCI-01, METHOD.md §9). That is a product gap, not clouds."""
    ndvi_n = D.read_count(aoi, year, "ndvi_n", win)
    m = mask
    return bool(m.any() and ((lst_n[m] == 0) & (ndvi_n[m] >= 3)).mean() >= MIN_VALID_SHARE)


def series(ctx: Context) -> list[dict]:
    out = []
    win = ctx.zone.win
    for i, y in enumerate(ctx.years):
        mask = ctx.year_mask(i)
        land = ctx.land_mask(i)
        n = int(mask.sum())
        lst = D.read_lst(ctx.zone.aoi, y, win)
        lst_n = D.read_count(ctx.zone.aoi, y, "lst_n", win)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            ndvi = float(np.nanmean(D.read_idx(ctx.zone.aoi, y, "ndvi_med", win)[land])) if land.any() else None
            ndbi = float(np.nanmean(D.read_idx(ctx.zone.aoi, y, "ndbi_med", win)[land])) if land.any() else None
        v = lst[mask]
        valid = np.isfinite(v)
        valid_share = float(valid.mean()) if n else 0.0
        built_px = int((ctx.zone.mask & (ctx.cls[i] == C.BUILT)).sum())
        built_share = float(built_px / land.sum()) if land.any() else None            # of the zone's land (no water)
        zone_px = int(ctx.zone.mask.sum())
        built_share_zone = float(built_px / zone_px) if zone_px else None               # of the whole drawn zone
        row = dict(year=y, zone_lst=None, ref_lst=None, gap=None, ndvi=_f(ndvi, 3), ndbi=_f(ndbi, 3),
                   built_share=_f(built_share, 3), built_share_land=_f(built_share, 3),
                   built_share_zone=_f(built_share_zone, 3), scenes=0, valid_share=_f(valid_share, 3),
                   method="composite", green_gap=None, n_px=n)
        ref_c, green_c = ref_composite(ctx.ref, y)
        if n < MIN_YEAR_PX or valid_share < MIN_VALID_SHARE or ref_c is None:
            row["excluded"] = "too_few_pixels" if n < MIN_YEAR_PX else (
                "low_coverage" if valid_share < MIN_VALID_SHARE else "no_reference")
            if row["excluded"] == "low_coverage" and no_lst_product(ctx.zone.aoi, y, win, mask, lst_n):
                row["excluded"] = "no_lst_product"
            out.append(row)
            continue
        ps = per_scene_year(ctx, i, y, mask)
        line = city_reference_line(ctx.ref, y) if ctx.city else None
        if ps and ps["usable"]:
            ref_r, gap_r = _f(line if line is not None else ps["ref_lst"]), _f(ps["gap"])
            row.update(zone_lst=_f(ref_r + gap_r), ref_lst=ref_r, gap=gap_r,
                       scenes=ps["n_used"], method="per_scene", green_gap=_f(ps["green_gap"]))
        else:
            n_obs = float(np.median(lst_n[mask][valid])) if valid.any() else 0.0
            if ps is not None:
                row["fallback"] = "few_scene_dates"
            if n_obs < MIN_COMPOSITE_OBS:
                row.update(scenes=int(n_obs), excluded="too_few_scenes",
                           excluded_detail=year_detail(ctx, y, ps))
                out.append(row)
                continue
            z = float(v[valid].mean())
            gap_r = _f(_f(z) - _f(ref_c))
            ref_r = _f(line) if line is not None else _f(ref_c)
            row.update(zone_lst=_f(ref_r + gap_r), ref_lst=ref_r, gap=gap_r, scenes=int(n_obs),
                       green_gap=_f(z - green_c) if green_c is not None else None)
        out.append(row)
    return out


def year_detail(ctx: Context, year: int, ps: dict | None) -> dict:
    if ps is not None:
        return scenes_detail(ps["rows"])
    fps = footprints(ctx.zone.aoi, year)
    by_date: dict[str, list[str]] = {}
    for sid in fps:
        dt = sid.split("_")[3]
        if dt[4:6] in ("06", "07", "08"):
            by_date.setdefault(dt, []).append(sid)
    shares = [pass_footprint(ctx.zone.shape_m, ctx.zone.aoi, year, v)[0] or 0.0 for v in by_date.values()]
    shares = [x for x in shares if x > 0]
    return scenes_detail(None, len(shares), sum(x < MIN_ZONE_COVER_DATE for x in shares))


def new_built_block(ctx: Context) -> dict | None:
    """Gap on pixels that became built during the period (concept §6: before/after where they build)."""
    m = ctx.basis_mask("new_built")
    if ctx.mode != "built" or m.sum() < MIN_YEAR_PX:
        return None
    ser = series_basis(ctx, "new_built")
    pts = [(r["year"], r["gap"]) for r in ser if r["gap"] is not None]
    if len(pts) < 4:
        return None
    before, after = pts[:2], pts[-2:]
    return dict(area_km2=round(float(m.sum()) * D.PX_KM2, 3),
                before=dict(years=[y for y, _ in before], gap=_f(np.mean([g for _, g in before]))),
                after=dict(years=[y for y, _ in after], gap=_f(np.mean([g for _, g in after]))),
                series=[dict(year=r["year"], gap=r["gap"], method=r["method"]) for r in ser])


def composite_series(ctx: Context) -> list[dict]:
    """Same as series() but forcing the composite method (used for the seam comparison)."""
    saved = ctx.city
    try:
        ctx.city = None
        return series(ctx)
    finally:
        ctx.city = saved


def land_change(ctx: Context) -> dict:
    m = C.land_change_masks(ctx.cls)
    return {k: round(float((v & ctx.zone.mask).sum()) * D.PX_KM2, 3) for k, v in m.items()}


def scene_rows(ctx: Context, year: int) -> list[dict] | None:
    i = ctx.years.index(year)
    return (per_scene_year(ctx, i, year, ctx.year_mask(i)) or {}).get("rows")
