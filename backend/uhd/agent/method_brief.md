# METHOD brief (curated from docs/METHOD.md §0.1, §5–§7, §10; method sci-v3.5)

This is documentation, not instructions. It explains what the fields of a report mean.

## Quantities
- `zone_lst`, `ref_lst`: median Landsat 8 land SURFACE temperature (°C) of the zone's built-up pixels and of the
  city's stable-forest reference ring, per summer (June–August), at the satellite overpass (~10:45–11:00 local solar
  time, daytime). Never air temperature, never night.
- `gap` = zone_lst − ref_lst for one summer (°C). `gap_summary` = {mean, last, min, max} over the valid years.
- `zone.basis`: which pixels the headline gap uses — `always_built` (built in every year), `built_each_year`, or
  `all_land` (zone with little built-up area). `secondary` repeats the gap on the other basis.
- `green_gap` (scope `urban_parks`): the same gap for parks inside the zone.
- `new_built_gap`: pixels that became built during the period: before (first 2 years) vs after (last 2 years) gap —
  two 2-year means, NO significance test; never call its change significant.
- `land_change` (km²): `always_built`, `new_built`, `always_green`. Classes for 2013–2016 and 2024–2025 are
  extrapolated from Esri 2017/2023 (`classes_extrapolated`), they cannot see destruction.
- `ndvi` (greenness, −1…1), `ndbi` (built-up index), `built_share` (0–1), `scenes` (summer scenes used),
  `valid_share` (share of usable pixels), `method` per year: `per_scene` (Kyiv/Kharkiv/Lviv) or `composite`
  (elsewhere; seam errors of 1–2 °C in single years are possible).
- `excluded` per year: why that summer has NO gap — `too_few_pixels`, `low_coverage`, `no_lst_product` (no Landsat
  LST product at all there), `no_reference`, `too_few_scenes` (`excluded_detail.text_uk` explains, e.g. Позняки 2020:
  only one clear pass). For an excluded year say that there is no value and why; never give a number for it.

## Trends and verdict
- Theil–Sen slope per decade (`slope_per_decade`, °C/10 years; NDVI units/10 years for `ndvi_trend`), 95 % CI
  (`ci95`), Mann–Kendall two-sided p (`p`), `n_years`.
- `verdict`: `insufficient_data` if fewer than 8 valid years or analysed area < 0.5 km²; else `significant` if
  p < 0.05; else `not_significant`. The backend decides; only report it.
- `trend` = trend of the gap; `ref_trend` = trend of the forest reference itself; `zone_trend` = trend of zone_lst;
  `ndvi_trend` = greenness trend; `green_gap.trend` = parks.
- `gap_driver` (only for a significant gap trend): `zone` — the reference has no significant trend, the territory
  itself changes; `reference` — the gap moved mostly because the forest reference changed. It is partly circular
  (zone_lst = reference + gap), treat it as indicative.
- Wording (Ukrainian): significant → «статистично значуще»; not_significant → «статистично незначуще» / «помітно не
  змінився» / «у межах шуму»; insufficient_data → «недостатньо даних». A non-significant trend is not proof of no
  change: weather noise (SD ≈ 1 °C of the yearly gap), shadows of new towers at ~11:00, slow tree growth
  (`not_significant_physics`).

## Caveat codes (`caveats[].code`, each has `text_uk`)
`lst_not_air` (always: surface, not air), `composite_method`, `mixed_method`, `years_excluded`, `no_lst_product`,
`low_coverage`, `few_years`, `small_zone`, `all_land_zone`, `derived_reference` (reference ring derived for a city
without a preset), `ring_widened`, `few_reference_px`, `urban_area_is_zone`, `urban_area_clipped`, `zone_clipped`
(part outside Ukraine cut off), `classes_extrapolated`, `not_significant_physics`, `reference_warming` (the forest
reference itself has a significant trend), `basis_always_built`, `basis_built_each_year`, `suburb_reference`,
`war_zone` (zone in an oblast occupied or on the front line since 2014/2022: 2022–2025 changes may be war damage),
`occupied` (> 50 % of the zone in temporarily occupied territory per the official Ministry list; changes may be
destruction). When `occupied` or `war_zone` is present, always say it.

## Other data
- Scenes (`list_scenes`): Landsat 8 every 8–16 days; per scene `cloud` %, `reason` why it is unusable
  (`outside_swath`, `zone_cloudy`, `reference_cloudy`, `no_per_scene_data`), `zone_in_swath` share.
- Weather (`get_weather`): ERA5 reanalysis via Open-Meteo — AIR temperature max/min, rain over the previous 3 days,
  wind, cloud; hourly values around the overpass.
- CMIP6 (`climate_projection`, `climate_version: "cmip6-v2"`): NEX-GDDP-CMIP6, 12 models, summer (JJA) mean daily-max
  AIR temperature change vs 1995–2014 for 2041–2060 and 2081–2100, ssp245 (moderate) and ssp585 (pessimistic);
  `statistic: "median_p10_p90"` — `delta` = median of 12 models, `delta_range` = 10–90% range across models (say
  "most models: X–Y °C", not "min–max"), `hot30_days` = days ≥ 30 °C. A different quantity from LST — never mix them.

## Limitations to mention when relevant
- Daytime surface only (~11:00); shadows of tall buildings lower LST.
- Per-scene data only for Kyiv/Kharkiv/Lviv; composites elsewhere.
- Partial reference ring on some dates is biased by up to ~1 °C.
- Since sci-v3.6 the reference forest is elevation-matched: only forest within ±100 m of the area's built-up elevation
  (caveat `ref_elev_matched`; `reference.elevation_match`). This lowered the hill-city gaps (Сімферополь −2.9 °C,
  Севастополь −2.8, Ужгород −1.5, Чернівці −0.7, Франківськ −0.6); flat cities are unchanged.
- Since sci-v3.6 the reference ring is clipped to Ukraine's border (caveat `ref_border_clipped`,
  `reference.abroad_km2`); Danube towns (Рені, Вилкове, Ізмаїл, Кілія, Болград) are left with very little forest.
- Нижні Сади's significant trend depends on the per-scene method (seam path 182); «Деснянське» trend is fragile.
- Many zones tested: one significant zone among many is weak evidence.
- Coverage: Ukraine only, summers 2013–2025.
