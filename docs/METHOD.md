# METHOD — science package `uhd.science` (owner: data science)

## 0. Interface for the backend (v1, stable — changes are announced here)

Pure Python package `backend/uhd/science/` (numpy, scipy, rasterio, shapely, pyproj; no FastAPI).
Paths come from env (same names as `uhd/config.py`): `UHD_LANDSAT_DIR` (default `/srv/landsat`, read-only), `UHD_DATA_DIR` (default `/root/uhd/data`, precomputed by `scripts/precompute_*.py`).
All functions are synchronous, thread-safe for reads, and return JSON-serialisable dicts/lists (floats rounded, `None` for missing).
Geometries are GeoJSON **geometry or Feature** dicts in WGS84 (lon, lat); Polygon or MultiPolygon.

```python
from uhd import science as S

S.DATA_VERSION                      # "l8c2l2-60m-2013-2025/sci-v3" — store with every report
S.METHOD_VERSION                    # "sci-v3.2" — key cached reports by it (bumped with any change of report numbers/texts)
S.TILES_VERSION                     # "tiles-v2" — key cached tiles by it (bumped when tile values change)
S.YEARS                             # (2013, 2025)
S.grid_info(aoi="ukraine")          # {aoi, crs:"EPSG:3035", res:60.0, x0, y1, width, height, transform:[6], bbox_wgs84:[w,s,e,n]}
S.cities()                          # [{id:"kyiv", name_uk:"Київ", bbox_wgs84, center:[lon,lat]}, ...] (kyiv, kharkiv, lviv)

S.analyze(geometry, years=None, name=None) -> dict          # the /api/analyze report (minus report_id), see §0.1;
                                                             # cached (thread-safe LRU 128) WITHOUT the name: `name` only
                                                             # sets zone.name and the start of verdict_text_uk
S.reference_for(city_or_geometry) -> dict                   # {city, kind:"preset"|"derived", ring_km:[2,15], area_km2, forest_px,
                                                             #  urban_area_km2, ring_geometry (GeoJSON WGS84, simplified)}
S.zone_timeseries(geometry, years=None) -> list[dict]       # == report["series"]
S.list_scenes(geometry, year) -> list[dict]                 # summer acquisitions: [{id, ids, date, path, row, rows, cloud,
                                                             #   used, reason, zone_lst, ref_lst, gap, zone_valid_share,
                                                             #   ref_valid_px}]; zone/ref/gap/used = null where no per-scene
                                                             #   data exist (reason "no_per_scene_data")
S.land_change(geometry, years=None) -> dict                 # {always_built, new_built, always_green (km²), classes_source:{year: "esri"|"esri+landsat"}}
S.climate_projection(lat, lon) -> dict                      # CMIP6 tasmax summary, see §0.2
S.gap_raster(aoi, year, window=None, per_scene=True) -> (np.ndarray float32 [°C, NaN], affine.Affine, "EPSG:3035")
                                                             # LST − reference LST for tiles; aoi in kyiv|kharkiv|lviv|ukraine;
                                                             # window = rasterio Window or (row_off, col_off, h, w) on that aoi grid
S.layer_raster(aoi, layer, year, window=None) -> same       # layer in lst|ndvi|ndbi|dndvi (dndvi = ndvi_med(year) − ndvi_med(first year))
S.classes_raster(aoi, year, window=None) -> (uint8, T, crs) # 0 none, 1 built, 2 field, 3 nature, 4 water, 5 other/bare
```

Errors: `S.ScienceError(code, message_uk)` (codes: `outside_coverage`, `bad_geometry`, `too_large`) — map to HTTP 422.
Too-small zones are **not** errors: they return a report with `trend.verdict = "insufficient_data"` and a caveat.

### 0.1 Report shape (`analyze`)
Exactly the `POST /api/analyze` shape from PLAN.md (minus `report_id`) plus informational keys:
top-level `method`, `years`, `data_version`, `method_version`; `zone.analysed` ("built" | "all_land"),
`zone.basis` ("always_built" | "built_each_year" | "all_land": which pixels the headline gap uses, §5),
`zone.analysed_area_km2`, `zone.city` (preset id or null); every `series` row has `excluded` (null or the reason the
year has no gap: `too_few_pixels` | `low_coverage` | `no_lst_product` | `no_reference` | `too_few_scenes`; then
`method` is null too — an excluded year is never "from the composite"); `green_gap.scope = "urban_parks"`; `secondary` (when basis = always_built: the same gap on
"built in each year" pixels: `{basis, gap_summary, trend, series[{year, gap}]}`, else null); `new_built_gap`
(pixels that became built in the period, ≥ 0.25 km²: `{area_km2, before{years, gap}, after{years, gap},
series[{year, gap, method}]}`, else null);
`reference.kind` ("preset" | "derived"), `reference.urban_area_km2`. `zone.name` is the `name` argument (may be null).
sci-v3.6: `reference.elevation_match` = `{applied, status, tolerance_m: 100, min_px: 200, zone_elev_m, dz_before_m,
dz_after_m, px_kept, px_total}` (§4.1); `reference.area_km2` / `forest_px` are those of the forest actually used
(the matched one when `applied`).
sci-v3.3: `zone_trend` (trend of the zone's own LST line, same keys as `trend`), `gap_driver` ("zone" | "reference" |
null, §6), `zone.clipped_km2` (area cut off outside Ukraine's border, else null; `zone.area_km2` is then the clipped
area), `zone.war_region` (`{name, since}` of the occupied / front-line region, else null). `zone.analysed_area_km2` and
`zone.built_area_km2` (pixel counts) are capped at `zone.area_km2` (a pixel edge used to make them exceed it, QA SCI-07).
sci-v3.4: every `series` row has `excluded_detail` — null, or for `too_few_scenes` years
`{usable_dates: ["2020-08-16"], n_passes_total, n_outside_swath, n_cloudy, n_reference_cloudy, text_uk}`
(composite-only zones: `usable_dates`/`n_cloudy`/`n_reference_cloudy` null, counts from scene footprints), e.g.
Позняки 2020: «Лише один чистий проліт над ділянкою (16.08). З 12 прольотів за літо 4 — хмарні над ділянкою, у 7 зона поза
смугою знімання або на її краю. Для річного значення потрібно щонайменше 2.» `list_scenes` rows: `reason` ∈ null |
`outside_swath` | `zone_cloudy` | `reference_cloudy` | `no_per_scene_data`, new `zone_in_swath` (share of the zone
inside the pass's STAC footprint), and `cloud` = scene cloud % weighted by each merged row's overlap with the zone.

Size limits (all errors are `ScienceError(code, message_uk)` with a Ukrainian message): polygon area ≤ 5000 km²
(`too_large`); bounding box ≤ 2500 px = **150 km** per side in the preset cities' grids and ≤ 1200 px = **72 km**
elsewhere (derived reference reads the bbox + 30–60 km), and ≤ 4 Mpx in total (`too_large`, «Територія надто
розкидана: … (максимум N км)»); no part inside Ukraine → `outside_coverage`. The backend's own 150 km bbox check is
therefore the binding limit only inside Kyiv/Kharkiv/Lviv; elsewhere 72 km applies (QA SCI-09).

```jsonc
{
  // sci-v3.4 shape (abridged)
  "zone": {"name": "Позняки", "area_km2": 3.1, "built_area_km2": 2.2, "analysed": "built", "basis": "always_built",
           "analysed_area_km2": 3.0, "city": "kyiv", "clipped_km2": null, "war_region": null},
  "reference": {"city": "kyiv" | "derived", "ring_km": [2, 15], "area_km2": 354.0, "forest_px": 98333, ...},
  "series": [{"year": 2013, "zone_lst": 39.1, "ref_lst": 30.2, "gap": 8.9, "ndvi": 0.31, "ndbi": -0.03,
              "built_share": 0.71, "scenes": 9, "valid_share": 0.98, "method": "per_scene",
              "excluded": null, "excluded_detail": null}, ...],
  "gap_summary": {"mean": 8.7, "last": 8.1, "min": 6.0, "max": 10.4},
  "trend":     {"slope_per_decade": 0.4, "ci95": [-1.1, 1.9], "p": 0.62, "n_years": 13, "verdict": "not_significant"},
  "ref_trend": {...same keys...},           // trend of the city reference line (°C / decade)
  "zone_trend": {...same keys...},          // trend of zone_lst = reference line + gap
  "gap_driver": "zone" | "reference" | null,
  "ndvi_trend": {...same keys...},          // NDVI units / decade
  "land_change": {"always_built": 1.6, "new_built": 0.4, "always_green": 0.3},
  "green_gap": {"mean": 6.9, "last": 7.0, "scope": "urban_parks", "trend": {...}},  // or null
  "secondary": {...} | null, "new_built_gap": {...} | null,
  "caveats": [{"code": "lst_not_air", "text_uk": "..."}],
  "verdict_text_uk": "...",
  "method": "per_scene" | "composite" | "mixed",
  "years": [2013, 2025],
  "data_version": "...", "method_version": "sci-v3.4"
}
```
Verdict rule (all trends): `insufficient_data` if fewer than 8 valid years (or zone too small); else
`significant` if the **reported** (3-decimal) Mann–Kendall p < 0.05; else `not_significant`.
Rounding: all numbers are rounded half-up on their decimal value (`stats.rnd`: 11.25 → 11.3) and the Ukrainian texts
format the same rounded values, so text and numbers always agree.

### 0.2 Climate (`climate_projection`)
`{lat, lon, cell:[lat,lon], variable:"tasmax", unit:"°C", label_uk, baseline:{period:[2005,2014], jja_mean},
  ssp245:{"2041-2050":{delta, delta_range:[min,max], hot30_days}, "2071-2080":{...}}, ssp585:{...}, models:[...]}`
Deltas are multi-model means of summer (JJA) mean daily-max **air** temperature vs 2005–2014.
(Only these decades exist on disk; PLAN's 2041–2060/2081–2100 vs 1995–2014 is not available — see QUESTIONS.)


## 1. Data on disk (inspected 2026-11-14)

All rasters: GeoTIFF, EPSG:3035, 60 m, tiled 512, zstd. Grids are **aligned**: every city grid is a sub-window of the
Ukraine grid (`offset = ((y1_ukr − y1_city)/60, (x0_city − x0_ukr)/60)`).

| AOI | x0 | y1 | W × H |
|---|---|---|---|
| ukraine | 5 195 100 | 3 534 420 | 21 783 × 15 227 |
| kyiv | 5 717 100 | 3 280 020 | 1 361 × 1 389 |
| kharkiv | 6 127 740 | 3 353 220 | 1 108 × 1 075 |
| lviv | 5 293 560 | 3 092 160 | 962 × 904 |

City grids = OSM admin boundary (`aoi/<city>.geojson`) + 20 km buffer.

- `<aoi>/composites/<year>/` (2013–2025, all AOIs): `lst_med` int16 0.01 °C (nodata −32768) — per-pixel median of
  clear summer (Jun–Aug) LST, same-date scenes merged first; `lst_n` uint8 number of clear summer dates;
  `ndvi_med`, `ndbi_med`, `mndwi_med` int8 ×100 (nodata −128, summer medians); `ndvi_max` int8 ×100 (Apr–Oct max),
  `ndvi_n` uint8. `info.json` = `{year, scenes, grid{x0,y1,W,H}, crs, res}`. LST = ST_B10 × 0.00341802 + 149 − 273.15,
  QA_PIXEL clear bit set and bits 0–5 (fill, dilated cloud, cirrus, cloud, shadow, snow) unset.
- `<aoi>/scenes/<year>/<id>.json` = `{id, date, summer, n_clear, row_off, col_off, h, w}` (window on the AOI grid);
  `<id>.idx.tif` int8×100 bands ndvi[, ndbi, mndwi] (3 bands in summer); `<id>.lst.tif` int16 0.01 °C (summer only).
  Complete for kyiv/kharkiv/lviv (11–19 summer scenes per year, 3 WRS paths over Kyiv: 180, 181, 182).
  Ukraine: only 2013–2017 kept (318–342 summer LST scenes/yr); 2018–2025 deleted for disk.
- `<aoi>/items/<year>.json` — STAC items (Planetary Computer `landsat-c2-l2`, L8 only, Apr–Oct, cloud < 70 %):
  `eo:cloud_cover`, `landsat:wrs_path/row`, `datetime`, `bbox`, ….
- `<aoi>/maps/` uint8 (nodata 0), mode-resampled to 60 m: `worldcover2021.tif` (ESA WorldCover v200: 10 trees,
  20 shrub, 30 grass, 40 crop, 50 built, 60 bare, 80 water, 90 wetland), `esri_2017..2023.tif` (Esri/IO LULC v02:
  1 water, 2 trees, 4 flooded veg., 5 crops, 7 built, 8 bare, 11 rangeland; from the 20 m overview),
  `osm_farmland.tif` (0/1, cities only).
- `aoi/{Ukraine,kyiv,kharkiv,lviv}.geojson` — Nominatim/OSM boundaries (FeatureCollection, 1 feature).
- `extra/cmip6/<model>_<scen>_<year>.npz` — `tasmax_mjjas` int16 0.01 °C (153 days May–Sep, lat, lon),
  `jja_mean` float32 °C, `hot30`, `hot35` uint8 days, `lat` (152, 34.125…71.875), `lon` (280, −24.875…44.875).
  Models (`models.json`): ACCESS-CM2, MPI-ESM1-2-HR, EC-Earth3, MRI-ESM2-0, CNRM-ESM2-1. Years: historical
  2005–2014; ssp245/ssp585 2041–2050 and 2071–2080.
- `extra/ghsl/` GHS-BUILT-S 2015/2020/2025 (uint16 m² per 100 m cell, nodata 65535) and GHS-BUILT-H 2018 (float32 m),
  ESRI:54009 Mollweide 100 m, global. Not used in v1 (Esri per-year built-up is on our grid already).
- `extra/lcz/lcz_filter_v3.tif` — global LCZ map (Demuzere et al. 2022), EPSG:4326 ~100 m, uint8. Not used in v1.

## 2. Precomputed data (`/root/uhd/data`, scripts in `backend/scripts/`)

Run order (all idempotent, `--force` to redo, logs in `/root/uhd/data/logs/`), with the science venv
(`/root/uhd/venv-sci`, or the backend env) and `PYTHONPATH=uhd/backend`:

| script | output | time |
|---|---|---|
| `precompute_masks.py kyiv kharkiv lviv ukraine` | `<aoi>/classes.tif` (13 bands = 2013…2025), `<aoi>/forest.tif` | 5 s cities, 35 s Ukraine |
| `precompute_cities.py` | `<city>/ref_masks.npz`, `<city>/scenes/<year>.npy` (+ `.json`), `<city>/refstats.json`, `<city>/clim.npy` | 15 s |
| `python -m uhd.science.refquality --dem60` | `ukraine/dem60.tif` (Copernicus GLO-90, bilinear on the 60 m grid, int16 m, 119 MB) | 3 min, ~1 GB download |
| `precompute_refbins.py` | `<city>/refbins.npz` (per-metre elevation sums of the preset reference, §4.1; ~0.25 MB each) | 5 s |
| `precompute_reffield.py` | `ukraine/reffield.npz` (gap-tile reference field) | 1.5 min |
| `precompute_gapmaps.py` | `<city>/gapmap.npz` (per-scene-matched gap tiles + blend weight, §4) | 50 s |
| `precompute_climate.py` | `climate/cmip6_summary.npz` | 1 s |
| `precompute_places.py [--repo-copy backend/data/places]` | `places/<city>.geojson` (OSM raions + named localities) | network |
| `precompute_validation.py kyiv kharkiv lviv` | `validation/<city>.json` (seam + demo scan, §8–9) | ~5 min/city |

Disk: ~1.1 GB (per-scene stacks 610 MB Kyiv, 260 MB Kharkiv, 166 MB Lviv; Ukraine classes ~0.3 GB).

## 3. Land-cover classes per year (`classes.py`)

Classes: 1 built, 2 field, 3 nature (trees, shrub, grass/rangeland, wetland, flooded veg.), 4 water, 5 other (bare).
- 2017–2023: Esri of that year; Esri nodata → WorldCover 2021; OSM farmland turns nature into field (cities).
- 2013–2016 (anchor Esri 2017): built pixel becomes nature (field on farmland/WC cropland) if
  `ndvi_max_y − ndvi_max_2017 ≥ 0.20` and `ndvi_max_y ≥ 0.60` (it was clearly vegetated before construction).
- 2024–2025 (anchor Esri 2023): non-built, non-water pixel becomes built if `Δndvi_max ≤ −0.25`,
  `ndvi_max_y < 0.45` and `ndbi_y − ndbi_2023 ≥ 0.05`; built becomes nature if `Δndvi_max ≥ +0.25` and `ndvi_max_y ≥ 0.60`.
  Construction sites/sand stay "built" (no reliable spectral separation; NDBI of Kyiv concrete is ≈ −0.04).
- Kyiv built-up area 2013 → 2025 (grid incl. 20 km buffer): 1382 → 1495 km² (smooth across the 2016/2017 and
  2023/2024 joins: 1402 → 1412, 1488 → 1494).
- Stable masks: **stable forest** = WorldCover trees ∧ Esri trees in all 2017–2023 ∧ not OSM farmland ∧ summer NDVI
  ≥ 0.4 in every year (drops later clear-cuts/burns) ∧ eroded by 1 px (60 m; thermal band is 100 m, so edge pixels
  mix with fields/roads). **Stable nature** (in-city green) = class nature in all 13 years, eroded 1 px.
- Zone land change (for the selected years): always-built = built every year; new-built = not built in the first two
  years and built in the last two; always-green = nature every year (km²).
- **What "built" means** (board item 14, `INVESTIGATION-BUILT-SHARE.md`): Esri «Built area» is urban *fabric*, not
  sealed surface — it includes yards, gardens, tree-lined streets, dacha plots and much of the urban parks (median
  summer NDVI of our "built" pixels 0.55–0.64 in Франківськ, Стрийський парк, Гідропарк, Нижні Сади; WorldCover built
  is 2–6× and GHSL sealed surface 3–7× lower there). The report therefore gives three shares (sci-v3.5.1, numbers
  unchanged): `series[].built_share_land` = Esri built / non-water land of the zone (the old `built_share`, kept for
  compatibility, same value; this is the share the mode decision uses), `series[].built_share_zone` = Esri built / all
  pixels of the drawn zone (water included), and `zone.sealed_share_ghsl` = GHSL GHS-BUILT-S R2023A roofs + paving
  (100 m) / zone area for 2015, 2020, 2025 (null if GHSL is unavailable). Франківськ lake + park circle (750 m):
  land 0.92, zone 0.73, GHSL sealed 0.13–0.14. A park veto on the Esri class (OSM `leisure=park`) would change the
  gap and is pending sign-off.

## 4. Reference (`reference.py`)

- One reference per city (decision #6): **stable forest in a ring 2–15 km outside the urban area**.
- Urban area: Kyiv/Kharkiv/Lviv = OSM admin boundary. A zone belongs to a preset city if its representative point
  is inside the boundary or > 50 % of its area is.
- Any other place (Ukraine grid): urban area = connected built-up patches (2021 classes) that touch the zone, after a
  morphological closing with a 300 m (5 px) structuring radius so blocks split by streets/parks/rivers merge.
  Search window = zone bbox + 30 km (60 km if the patch touches the edge; beyond that `urban_area_clipped`).
  If that patch is < 0.1 km² (village, open land) the urban area is the zone itself (`urban_area_is_zone`).
  If the 2–15 km ring has < 500 forest px (1.8 km²), the ring is widened to 2–30 km (`ring_widened`).
- Sizes: Kyiv 354 km² of reference forest (98 333 px), Kharkiv 275 km², Lviv 256 km²; derived examples:
  Vinnytsia 192 km², Bila Tserkva 78 km², Dnipro 34 km², Odesa 7.5 km² (steppe; flagged when < 5 km²).
- **Suburbs** (sci-v3.2): a zone outside the admin boundary whose representative point is within 15 km of it (inside
  the city's own reference ring — Гатне, Бровари, Ірпінь, Вишневе …) uses that city's reference and per-scene data
  (caveat `suburb_reference`), so it can be compared with the city's districts (concept: one reference per city).
  Examples (1.2 km boxes): Гатне 5.6 °C, Бровари 6.8, Ірпінь 6.9, all trends n.s.
- **In-city green** (for `green_gap`, sci-v3.2): "urban parks" = connected patches of stable nature inside the urban
  area no larger than 5 km² (parks, squares, green yards, small groves). Large forests inside the admin boundary
  (Kyiv: Pushcha 152 km², Holosiiv/Bykivnia 105 and 46 km²) are excluded — with them the in-city green was the forest
  reference again (QA-22: green gap = forest gap ± 0.1 °C). Kyiv parks: 25 km² (7 061 px), climatology 31.2 °C vs
  29.8 °C for the reference forest; Kharkiv 20 km², Lviv 15 km². Demo green gaps: Позняки 9.7 °C (forest gap 11.4),
  Нижні Сади 3.6 (5.1), «Деснянське» 6.7 (8.5). The text says «Парки й сквери … прохолодніші» only when positive.
- Tiles (`gap_raster`, layer `gap`):
  - **Preset cities** (city AOIs, and the same pixels on the Ukraine AOI): per-scene-matched gap map
    (`precompute_gapmaps.py`): `gap_y(px) = (clim(px) − clim_ref) + G_σ[median_d A_d](px)`, where
    `A_d = (LST_d − clim) − (ref_d − clim_ref)` over usable dates d (≥ 2000 visible reference px), σ = 1.5 km,
    `clim` = per-pixel median of the 13 composites. Pixel detail comes from the multi-year climatology, the yearly
    change from same-date comparisons. On the Ukraine AOI it is blended into the composite gap between 15 and 20 km
    from the city boundary.
    Agreement with reports (zone mean of tile vs report gap, 13 years): Pozniaky max |Δ| 1.6 °C, trend +0.23 vs
    report +0.40 °C/10 yr (plain composite tiles: 3.6 °C and −1.35); Obolon 1.6 (3.2); Nyzhni Sady 1.5 (3.8).
    Remaining differences: per-pixel date sets (clouds) and the 1.5 km smoothing of the yearly anomaly.
    Compare like with like: the report uses the zone's analysed (always-built) pixels. Теремки: tile mean over those
    pixels − report = −0.11 °C on average (max 1.48); over *all* zone pixels (incl. its many green ones, as the QA
    colour-decoding script does) −0.62 (max 1.79) — the QA-06 residual is this pixel-set difference, not a bug.
  - **Elsewhere**: composite LST minus a smooth regional reference field — stable-forest LST averaged on 1.2 km
    cells, Gaussian σ = 10 km (σ = 30 km, then σ = 100 km, then the nearest value fill gaps — before 15.11 the last two
    steps were missing, 14.7 % of the grid had no field and northern Crimea, Kerch and Syvash showed transparent
    "lenses"; values that were already defined did not change); within 15 km of a preset city it equals the city reference and
    is blended linearly into the regional field over 15–25 km (no step at the ring edge). Composite → path seams of
    1–3 °C are possible on the map; the UI should say so (map ≠ per-scene report outside the three cities).

### 4.0 Reference ring clipped to Ukraine (sci-v3.6)

INVESTIGATION-FOREIGN-REFERENCE, signed off by the owner 15.11. The ukraine grid extends ≥ 20 km past the border and
`forest.tif` / the composites have values there, so border towns used to compare with Romanian, Moldovan, Slovak,
Hungarian, Polish, Belarusian or Russian forest (Рені 97 %, Вилкове 91 %, Ізмаїл 80 %, Чоп 60 %, Ужгород 24 % of the
reference abroad).

- **Rule.** `derive()`: ring forest = `ring ∩ stable forest ∩ Ukraine` (the same Ukraine polygon the zones are clipped
  to; it includes coastal waters), **before** the `MIN_REF_PX` (500 px) test, so the existing widening to 2–30 km applies
  when too little forest is left in Ukraine. `build_city_masks()` does the same (a no-op for Kyiv, Kharkiv, Lviv: no
  forest abroad; `ref_masks.npz` unchanged).
- **Caveat** `ref_border_clipped` («Частина лісу в кільці лежить за кордоном України ({km2} км²) — її не беремо, еталон
  лише з лісу в Україні.») when ≥ 10 % of the ring's forest was dropped; `reference.abroad_km2` = the dropped area
  (0 when nothing). `few_reference_px` (< 5 km²) and `ref_weak` (< 20 km²) then judge the clipped reference.
- **Order with the elevation match (§4.1): border clip first, then ±100 m.** The 200 px fallback of §4.1 is evaluated
  after both (on the forest that is in Ukraine *and* in the band); if it falls back, the whole *Ukrainian* ring forest is
  used.
- **Gap tiles**: `precompute_reffield.py` sums only Ukrainian stable forest into the 1.2 km cells before smoothing, so
  the regional field near the border is no longer pulled by foreign forest (`ukraine/reffield.npz` rebuilt; the tile
  version follows the file's identity, old gap pyramids are evicted).

### 4.1 Elevation-matched reference (sci-v3.6)

INVESTIGATION-REGIONAL-GAP fix 3 («C»), signed off by the owner 15.11. Mountain forest is cooler than the valley a city
lies in, so where the ring climbs into the hills the gap was overstated (Ужгород, Сімферополь, Севастополь, Чернівці,
Івано-Франківськ).

- **Rule.** The reference keeps only the stable-forest pixels whose elevation is within **±100 m** of the median
  elevation of the zone's built basis (always-built pixels; else built in the last year; else the whole zone, ≥ 50 px —
  the same pixels as `ref_higher`). If fewer than **200 px** (0.72 km²) remain, the whole forest is kept (fallback).
- **DEM.** Copernicus DEM GLO-90, read once from the public COGs and resampled bilinearly onto the 60 m Ukraine grid
  (`ukraine/dem60.tif`, int16 m; city grids are aligned with it). The band is in whole metres: `[⌈z − 100⌉, ⌊z + 100⌋]`.
- **Applied everywhere, both methods.** Derived references (composite): the matched mask simply replaces the ring forest
  (new cache key). Preset cities (per-scene): the per-date reference is summed from `<city>/refbins.npz` — per metre of
  elevation, the pixel counts and sums of the climatology, the yearly composite LST and every acquisition's LST and
  LST − climatology over the reference forest — so any band reproduces `refstats.json` exactly (full band: max
  |Δ| 0.001 °C = the rounding). The city reference line is then the line of the matched forest.
- **`reference.elevation_match.status`**: `matched` (some forest dropped, ≥ 200 px left: used, `applied` = true,
  caveat `ref_elev_matched` only when ≥ 5 % of the ring forest is dropped or |dz_before − dz_after| ≥ 20 m — not in
  Київ, which drops 0.2 % with Δz unchanged; the `elevation_match` fields are in every report), `all_within` (every forest pixel already in the band: nothing changes), `fallback`
  (< 200 px in the band: whole forest; with `ref_higher` when it is still ≥ 100 m higher, plus `ref_match_fallback`),
  `unavailable` (no DEM / refbins, or no basis elevation: not evaluated). The band is applied to the forest left
  after the border clip (§4.0). `dz_before_m` / `dz_after_m` = median forest
  minus median basis elevation, whole forest / forest used. `ref_higher` is evaluated on the forest used (60 m DEM), so
  it no longer fires once the match is applied.
- **Map outline** (`GET /api/reports/{id}/reference`): the matched forest when the report's `elevation_match.applied`;
  reports before sci-v3.6 keep the whole ring, as they were computed.
- **Effect**: §4.2.
- **Limits.** ±100 m is a tolerance, not a lapse-rate correction: within it a 6.5 °C/km gradient is still up to
  ±0.65 °C. The matched forest can be much smaller (Севастополь 14 km², `few_reference_px` / `ref_weak` then say so).
  The band is applied after the border clip (§4.0).

### 4.2 Effect of sci-v3.6 (border clip + elevation match)

Full re-run on the VM (read-only, live data, 15.11): the 65 `/api/overview` places, the 4
demo zones and 20 border towns (OSM boundaries of INVESTIGATION-FOREIGN-REFERENCE), mean gap over all summers, °C.
"border clip only" = sci-v3.6 with the elevation match switched off.

| place | sci-v3.5.4 | border clip only | **sci-v3.6** | Δ | elevation fix C estimate | forest km² before → after | abroad km² | Δz before → after, m | status |
|---|---|---|---|---|---|---|---|---|---|
| Сімферополь | 10.72 | 10.72 | **7.79** | -2.93 | -2.74 | 472.8 → 53.4 | 0.0 | +292 → +61 | matched |
| Севастополь | 8.07 | 8.07 | **5.32** | -2.75 | -2.83 | 184.1 → 14.4 | 0.0 | +254 → +76 | matched |
| Ужгород | 10.08 | 10.06 | **8.60** | -1.48 | -1.16 | 356.6 → 62.3 | 85.0 | +227 → -1 | matched |
| Чернівці | 7.01 | 7.03 | **6.32** | -0.69 | -0.42 | 398.1 → 80.1 | 51.0 | +167 → +64 | matched |
| Івано-Франківськ | 9.99 | 9.99 | **9.38** | -0.61 | -0.56 | 442.9 → 194.1 | 0.0 | +113 → +61 | matched |
| Слов’янськ | 6.98 | 6.98 | **6.55** | -0.43 | -0.3 | 138.9 → 91.4 | 0.0 | +75 → +23 | matched |
| Краматорськ | 8.30 | 8.30 | **8.09** | -0.21 | -0.17 | 138.2 → 114.0 | 0.0 | +52 → +25 | matched |
| Рені | 8.02 | 7.69 | **7.69** | -0.33 |  | 3.0 → 0.4 (ring 30 km) | 171.9 | -11 → -11 | all_within |
| Вилкове | 4.05 | 6.96 | **6.96** | +2.91 |  | 3.7 → 0.5 (ring 30 km) | 4.2 | +6 → +6 | all_within |
| Болград | 6.08 | 5.02 | **5.02** | -1.06 |  | 2.7 → 0.8 (ring 30 km) | 11.1 | -7 → -7 | all_within |
| Ізмаїл | 10.22 | 9.56 | **9.56** | -0.66 |  | 15.4 → 3.0 | 12.3 | -18 → -18 | all_within |
| Кілія | 8.71 | 7.66 | **7.66** | -1.05 |  | 9.5 → 3.0 | 6.5 | +3 → +3 | all_within |
| Чоп | 8.82 | 9.05 | **9.05** | +0.23 |  | 90.6 → 35.6 | 54.1 | +5 → +5 | matched |
| Могилів-Подільський | 6.88 | 6.92 | **6.44** | -0.44 |  | 101.3 → 23.6 | 39.0 | +117 → +73 | matched |
| Берегове | 7.87 | 7.91 | **7.89** | +0.02 |  | 122.1 → 85.0 | 33.5 | +13 → +12 | matched |
| Хуст | 9.17 | 9.23 | **7.68** | -1.49 |  | 384.9 → 75.6 | 47.8 | +184 → +52 | matched |
| Виноградів | 9.25 | 9.34 | **8.25** | -1.00 |  | 261.4 → 98.8 | 47.6 | +117 → +21 | matched |
| Київ | 7.98 | 7.98 | **7.98** | +0.00 |  | 354.0 → 353.4 | 0.0 | +35 → +35 | matched |
| Львів | 8.82 | 8.82 | **8.82** | +0.00 |  | 255.5 → 255.5 | 0.0 | +19 → +19 | matched |
| Одеса | 5.64 | 5.64 | **5.64** | +0.00 |  | 7.5 → 7.5 | 0.0 | +11 → +11 | all_within |
| Харків | 8.44 | 8.44 | **8.44** | +0.00 |  | 274.8 → 274.8 | 0.0 | +45 → +45 | all_within |
| Позняки | 11.41 | 11.41 | **11.40** | -0.01 |  | 354.0 → 348.7 | 0.0 | +47 → +46 | matched |
| Котеджне містечко «Деснянське» (Троєщина) | 8.48 | 8.48 | **8.46** | -0.02 |  | 354.0 → 347.2 | 0.0 | +49 → +48 | matched |
| Нижні Сади (Осокорки) | 5.13 | 5.13 | **5.12** | -0.01 |  | 354.0 → 343.7 | 0.0 | +53 → +52 | matched |
| Голосіївський ліс | -0.15 | -0.15 | **-0.15** | +0.00 |  | 354.0 → 354.0 | 0.0 | -8 → -8 | all_within |

- Every other overview place moves by ≤ 0.03 °C (Черкаси, Личаківський −0.03; Сихівський +0.02; Луганськ −0.08 from
  6 km² of Russian forest). Київ, Львів, Одеса, Харків and the demo zones: ≤ 0.02.
- The elevation fix gives somewhat larger drops than the investigation's estimate (Ужгород −1.48 vs −1.16, Чернівці
  −0.69 vs −0.42, Слов’янськ −0.43 vs −0.30): the estimate took the *median* of a 13-summer mean LST and applied it as a
  difference; the report averages the forest pixels per year (the cold mountain tail weighs more), and in Ужгород /
  Чернівці the clip removes lowland forest abroad first, so the band keeps less (and more similar) forest. Same sign
  and ranking everywhere.
- Border clip alone: −0.02 Ужгород and +0.02 Чернівці, as the foreign-reference VM run predicted (Ужгород −0.02). The
  Danube towns change most (Вилкове +2.91, Болград −1.06, Кілія −1.05, Ізмаїл −0.66, Рені −0.33): their reference was
  mostly Romanian / Moldovan riparian forest; what is left in Ukraine is 0.4–3 km² (`few_reference_px`), often after
  widening to 30 km. The investigation's Δgap for them (e.g. Рені −2.9) assumed the same ring, so it differs.
- Exact foreign shares from `foreign_ref.py --source vm` with the sci-v3.5.4 code: Рені 97.1 %, Вилкове 91.0, Болград
  88.6, Ізмаїл 80.2, Кілія 68.3 (2–30 km), Чоп 59.6, Могилів-Подільський 38.5, Берегове 27.5, Ужгород 23.8 (Чернівці
  12.7 % in the proxy run; its city boundary is outside the script's 25 km screen).

## 5. LST per year and the gap (`analysis.py`)

Analysed pixels (`zone.basis`, concept decision #15):
- **always_built** (default): zone pixels built in every year of the selected period — the same pixels every year, so
  new construction cannot create or hide a trend by changing the composition (caveat `basis_always_built`).
- **built_each_year** (fallback when always-built < 0.5 km²): pixels built in that year (caveat
  `basis_built_each_year`). For always-built zones this variant is reported as `secondary`.
- **all_land**: if the zone's max built-up area < 0.5 km² or its median built share < 20 %, all non-water pixels
  (caveat `all_land_zone`; parks/forests as controls).
- `new_built_gap`: the gap on pixels that became built (not built in the first two years, built in the last two),
  as a before (first two valid years) / after (last two) pair plus the series — "how heat changes where they build".
Effect of the basis on the demo zones is small (they are almost fully built every year): Pozniaky 11.41 vs 11.32 °C,
trend +0.40 vs +0.34; Nyzhni Sady +1.85 vs +1.80; «Деснянське» −2.59 (p 0.033) vs −2.45 (p 0.024).

**Per-scene method** (preset cities, all years) — removes the Landsat path seam:
1. Same-date scenes (adjacent WRS rows) are mosaicked into one acquisition (`scenes/<year>.npy`).
2. For acquisition d: `zone_d = mean_zone(clim) + mean_visible(LST_d − clim)` over the analysed pixels (same
   climatology adjustment as the reference, so a partly cloudy zone is not biased towards its visible part);
   zone coverage share = visible / analysed pixels.
3. `ref_d` = climatology-adjusted mean of visible reference pixels:
   `ref_d = mean_ring(clim) + mean_visible(LST_d − clim)`, `clim` = per-pixel median of the 13 summer composites.
   (Neighbouring paths see only part of the 2–15 km ring; without this, *which* forests are visible would bias ref_d.)
4. Date used if zone coverage ≥ 50 % and ≥ 2000 visible reference px (~7 km²).
5. Summer gap = **median over used dates of (zone_d − ref_d)**. Lines shown in the chart (sci-v3.3): `ref_lst` = the
   **city reference line** — median of ref_d over *all* dates of that summer with ≥ 2000 visible reference px, the
   same for every zone of the city — and `zone_lst` = `ref_lst + gap` (so `zone_lst − ref_lst == gap` exactly, ±0.01
   rounding). Up to sci-v3.2 `ref_lst` was the median over the dates *used for that zone* (zone ≥ 50 % clear), so
   each zone had its own reference line and `ref_trend` (QA UX-04: Нижні Сади −1.5 °C/10 yr vs Позняки +0.3): which
   summer days happen to be clear over a small zone changes the median by 1–2 °C in single years. The gap itself is
   unchanged (it is matched per date); only the decomposition into "zone" and "reference" lines is now common.
   `scenes` = number of used dates. Fewer than 2 used dates → that year falls back to the composite (`method`
   per row; report `method = "mixed"`, caveat `mixed_method`).

**Composite method** (elsewhere): `gap = mean(lst_med over analysed px) − mean(lst_med over reference px)`;
`scenes` = median `lst_n` over the analysed pixels; caveat `composite_method`. A composite year whose analysed
pixels have a median of < 2 clear acquisitions is dropped (`years_excluded`; one cloud-edge scene gave −10 °C outliers).

Per year also: `ndvi`, `ndbi` = mean summer median over the zone's land (non-water) pixels; `built_share` = built /
land pixels; `valid_share` = share of analysed pixels with ≥ 1 clear summer observation. A year is excluded
(gap = null) if analysed px < 70 (0.25 km²) or valid_share < 0.5; caveat `low_coverage` if < 0.8.

A year with low coverage is marked `no_lst_product` instead of `low_coverage` when ≥ 50 % of the analysed pixels
had NDVI from ≥ 3 clear scenes but never an LST value. Cause (checked on the raw assets, QA SCI-01): Landsat C2 L2
has no surface temperature where its ASTER GED emissivity input is missing — e.g. central Маріуполь, scene
LC08_L2SP_175027_20160820: `qa_pixel` = 21824 (clear), TOA thermal radiance `trad` present, but `emis` = `emsd` =
`qa` (ST_QA) = −9999 and `lwir11` = 0 (fill). Fixed patches, identical in every year (QA: ≈ 11 300 km² of land), mostly in
the east (Kharkiv/Luhansk/Donetsk oblasts, Маріуполь) — a product gap, not clouds and not our ingest. Fix (data
side): compute LST there from `trad`, `urad`, `drad`, `atran` with an NDVI-based emissivity (single-channel
inversion of the band-10 Planck function, K1 = 774.8853, K2 = 1321.0789); this needs those four assets for the
affected summer scenes.

**Why a pass is not used** (sci-v3.4, `analysis.classify_pass`, docs/INVESTIGATION-2020.md): `seen` =
max(share of the zone inside the pass's STAC footprint, zone clear share) — the footprint is the corner polygon of the
data area and ≈0.1 conservative for a small zone (Позняки 08-16: 0.63 vs 0.74 measured from `qa_pixel` fill), the clear
share is a hard lower bound. `seen` < 0.5 → `outside_swath` (even a clear sky could not have given 50 % of the zone:
the zone is outside or on the edge of that track), else zone clear share < 0.5 → `zone_cloudy`, else
`reference_cloudy`. Same-date rows of one pass are merged; their scene cloud % is weighted by each row's overlap
with the zone (06-13: 2.4 % for row 25 that holds Позняки, not the 13.8 % mean with row 24). Nothing in the method
changed: 2020 stays excluded for Позняки (one usable pass, path 181 cloudy on all four dates, paths 180/182 miss the
zone).

**No-LST map mask** (MAP-TASKS #4, `uhd.science.nolst_mask`, `python -m uhd.science.nolst_mask [--out] [--force]`,
default `$UHD_DATA_DIR/overlays/no_lst.geojson`, served by the backend in `GET /api/overlays`). The same rule as
`no_lst_product`, applied to the whole `ukraine` grid: a pixel qualifies in a summer if `lst_n == 0` and
`ndvi_n ≥ 3`, and counts if it qualifies in ≥ 7 of the 13 summers. It is aggregated to 16 × 16 px (≈ 1 km) blocks; a block is no-LST if
≥ 50 % of its land pixels (2021 classes ≠ water) count and ≥ 25 % of it is land. One-block closing, vectorised,
clipped to Ukraine, holes and polygons < 4 km² dropped, simplified to 500 m, WGS84, 4-decimal coordinates. Properties:
`years` (summers in which ≥ 50 % of the feature's blocks are no-LST), `share_years` (mean share of summers without
LST over its blocks), `area_km2`, `label_uk` «немає супутникової температури поверхні»; the collection carries
`rule`, `data_version` and the total `area_km2`. Result (15.11): 100 polygons, 12 661 km² (QA SCI-01 measured
≈ 11 300 km² per pixel; closing adds the block edges), 68 kB; mostly Donetsk/Luhansk/Kharkiv oblasts plus swath-shaped
stripes in the centre and west, the same in all 13 summers — the stripes are the same emissivity gap, not narrower ST swath edges: at 25.57 E, 50.35 N and 33.17 E, 47.30 N, clear
pixels (`qa_pixel` 21824) in scenes from two different paths each (184/185 and 178/179, 18–52 km inside the scene)
have `trad` but `emis` = `qa` = −9999 and `lwir11` = 0. The gap is fixed on the ground, i.e. holes in the ASTER GED
emissivity map itself, whose shape follows ASTER's own narrow, tilted swaths (`share_years` 0.7–0.96 for the largest). Checks: Маріуполь
(37.55 E, 47.10 N) inside; Київ, Харків, Львів outside; 11 of 12 sample 1.4 km boxes at feature representative points
give `no_lst_product` in `analyze()` (the 12th lies at a polygon edge that the closing filled). Strip-wise reads, ~75 s,
~0.6 GB peak RSS; read-only on /srv/landsat.

**Per-year "too few clear scenes" overlay** (QA chat-review re-test; `uhd.science.noscene_mask`, `python -m
uhd.science.noscene_mask [--force]` → `$UHD_DATA_DIR/overlays/no_scenes.geojson`, 95 kB, 56 s). Cause of the 2022
transparent swath Знам'янка–Олександрія–Глобине (≈ 32.6–33.6 E, 47.3–49.7 N): the Landsat 8 C2 L2 catalogue has a
single summer-2022 scene of path 179 over rows 26/27 (2022-06-30, 48 % cloud), so the path-179 interior has no LST
and < 3 clear NDVI observations (2021: 23 scenes, 2023: 29 over the same pixel). It is a source gap, not the ASTER-GED
product gap — so the display fill, which only fills clear-but-no-LST pixels, correctly leaves it empty (filling 13 500 km²
from 2021/2023 would hide that 2022 was not observed). Landsat 9 has four clear path-179 scenes (07-08, 08-09, 08-25)
— the post-pitch fix (A3). The overlay hatches, per year, ~1 km blocks where ≥ 50 % of the land has `lst_n == 0` and
`ndvi_n < 3` (closed, clipped, < 25 km² dropped, 500 m simplified); features carry `year`, `area_km2`, `label_uk`
«{Y}: замало безхмарних знімків цієї смуги». Areas: 2022 13 519 km², 2013 3 897, 2023 1 384, 2020 1 103, others
< 750 km². Display only: the analysis already excludes such zone-years (`too_few_scenes` / `low_coverage`).

**Sea mask for tiles** (`uhd.science.sea_mask`, `python -m uhd.science.sea_mask [--force]` →
`$UHD_DATA_DIR/ukraine/sea_mask.tif`, uint8 on the ukraine grid, 1 = sea; the backend clips tiles by it because the
Ukraine outline includes the 12-nm territorial sea). Sea = 2021 class water (4) or no-product (0, open sea beyond the
Esri/WorldCover coastal strip, ~30 km offshore) connected to seeds in the Black and Azov seas through water ≥ ~2.4 km
wide (water eroded by 1.2 km, seed components kept and grown back inside the water). Bays, the Дніпровсько-Бузький
лиман and the Azov coast are sea; the Dnipro, its reservoirs, lakes and lagoons behind narrow inlets (Дністровський
лиман) stay land; Сиваш is mapped as field/salt flat (class 2) and stays land. 143 856 km² of sea in the grid, 15 s.
Not used by any analysis number.

**Inland water in the ΔNDVI tiles** (backend `uhd.tiles.render`, tag `dndvi-w2`): the `dndvi` layer is transparent
where `classes.tif` says water (class 4) in *both* the shown year and the base year (coarse zooms: ≥ 50 % water in the
pyramid cell in both; uint8 `water@<classes tag>` pyramid like `nonbuilt`), so the Dnipro, reservoirs and lakes no
longer show a "greenness change" (NDVI of water is noise around/below 0). Water in only one of the two years is a real
change and stays visible (new ponds, drained land). Kakhovka exemption: `classes.tif` 2024–2025 inherit Esri 2023,
which still maps about half of the drained bed as water, so inside the box 33.30–35.15° E, 46.72–47.80° N and for
shown years ≥ 2023 a "water" pixel is masked only if its NDVI that year is < 0.2 — the greened bed (NDVI ≈ 0.6–0.7)
is shown, the remaining Dnipro channel stays masked (z12 tile at 34.25° E 47.52° N, 2025 vs 2013: 98 % shown, mean ΔNDVI
+0.47; the Dnipro tile at Kyiv stays 15 % masked).
(`dndvi-w1`, the first version, masked water in either year and hid the Kakhovka bed.)
Display only: the zone NDVI series and `ndvi_trend` already average land pixels only (classes ≠ water/none), so no
report number, METHOD_VERSION or TILES_VERSION changes; the `gap`/`lst`/`ndvi` tiles are untouched.

**Display-only fill of year-specific holes** (PM item 9, Volyn/Rivne; `uhd.science.gapfill`, tile layers
`gap_fill` / `lst_fill` from `layer_raster`). A pixel of summer Y is a hole if `lst_n == 0` and `ndvi_n ≥ 3` (clear,
but no LST — the emissivity gap, which in some summers covers extra patches: Volyn–Rivne 2022 7.5 %, Ukraine 2018
2.0 %, 2022 4.3 %). Persistent holes (≥ 7 of 13 summers, the no-LST mask rule) are never filled; they stay
transparent under the `no_lst` hatch. Other holes get the median of the same pixel's `gap` (or `lst`) in Y±1, and if
neither has a value, Y±2. The fill layers hold values only on filled pixels (NaN elsewhere), so `gap`/`lst` tiles are
unchanged; the renderer draws the fill with its own alpha and the legend note «заповнено з сусідніх років». **No report
number, trend or verdict reads it** (test `test_gapfill_layers_are_not_used_by_analysis`). Per-pixel hole counts:
`python -m uhd.science.gapfill [--force]` → `$UHD_DATA_DIR/ukraine/nolst_years.tif` (uint8, 5.2 MB, 34 s, 0.27 GB
RSS; without it the counts are read on the fly). Rivne 2022, 1024² px window: 12.6 % holes, 12.1 % filled, 0.5 %
persistent left; ~10 s per full-width 1024-row strip (≈ 2.5 min per year for the pyramid).

`green_gap` (built mode only) = zone LST − urban-parks LST (§4). In a per-scene year it is the median over used
dates with ≥ 500 visible park px, and **null if fewer than 2 such dates** (QA method review C7). The composite park gap
is used only when the whole year falls back to the composite. Summary + trend over the non-null years.

## 6. Trends and verdict (`stats.py`)

- Theil–Sen slope (scipy `theilslopes`, 95 % CI of the slope from Sen's rank method), reported per decade.
- Mann–Kendall two-sided test with tie correction (normal approximation with continuity correction).
- Verdict: `insufficient_data` if < 8 valid years or the analysed area < 0.5 km²; else `significant` if p < 0.05;
  else `not_significant`. Same rule for `trend` (gap), `ref_trend` (reference LST), `ndvi_trend`, `green_gap.trend`.
- Validation: false-positive rate of MK on white noise (n = 13, 2000 runs) is within 2–8 % (unit test).
- `zone_trend` = trend of `zone_lst` (= city reference line + gap), so `trend` ≈ `zone_trend` − `ref_trend`.
  `gap_driver` (only if the gap trend is significant): "reference" when the reference trend has the opposite sign
  to the gap trend and is at least as large as the zone's own trend (the gap moved mostly because the forest
  changed), else "zone".
- Verdict text (QA-UX C1/C2): one lead sentence that answers both halves and says *surface* — «{name}: поверхня
  забудови влітку вдень у середньому на X °C гарячіша, ніж ліс навколо Києва, і за N літніх сезонів цей розрив зріс / зменшився
  — приблизно на Y °C за 10 років (статистично значуще, p = …)» or «… помітно не змінився (статистично незначуще, p = …)»; |gap| < 0.5 °C
  → «майже така ж тепла, як ліс». Then: the driver sentence («Ліс-еталон не має статистично значущого тренду, тож зміна йде від самої території: її поверхня
  нагрівається на … °C за 10 років» — sci-v3.4.1, method review M4: a non-significant forest trend is not proof of a
  stable forest; «Змінюється саме ця територія: …» only when the forest trend is itself significant — or «Розрив зріс здебільшого через ліс-еталон …»), the new-construction sentence when the
  `new_built_gap` area ≥ 0.2 km² and |after − before| ≥ 1 °C («Там, де за ці роки з’явилась нова забудова (≈A км²),
  поверхня стала гарячішою: розрив із лісом був B °C у 2013–2014 р., а став C °C у 2024–2025 р.» — two 2-year means,
  no significance claim), «Зелені на ділянці статистично значуще більшає / меншає», and the urban-parks comparison.
- Honest text (decision #17): a non-significant LST trend comes with `not_significant_physics` — weather noise
  (SD ≈ 1 °C of the yearly gap), late-morning (~11:00 local solar time) shadows of new towers and slow tree growth; NDVI trend is shown as the early
  "suspect" signal.

## 7. Caveat codes (`report.py`, texts in Ukrainian)

`lst_not_air` (always), `composite_method`, `mixed_method`, `years_excluded`, `low_coverage`, `few_years`,
`small_zone`, `all_land_zone`, `derived_reference`, `urban_area_is_zone`, `ring_widened`, `urban_area_clipped`,
`few_reference_px` (< 5 km² forest), `classes_extrapolated` (years outside 2017–2023), `not_significant_physics`,
`reference_warming` (reference trend significant), `basis_always_built`, `basis_built_each_year`, `suburb_reference`,
sci-v3.3: `no_lst_product` (years without any Landsat LST, §5 — `years_excluded` no longer lists them and no longer
mentions clouds), `zone_clipped` (part of the zone outside Ukraine's border was cut off), `war_zone` (QA SCI-03: the
zone lies in a region occupied or on the front line since 2014/2022 — АР Крим, Севастополь, Донецька, Луганська,
Запорізька, Херсонська області; whole oblasts from OSM, `scripts/precompute_war_areas.py` →
`backend/data/places/war_oblasts.geojson`, because no offline front-line dataset is available; the text says
"the region", never that the place itself is occupied, and that 2022–2025 changes may be war damage). The analysis is
kept. `classes_extrapolated` now also says that the extrapolated class maps cannot see destruction.
sci-v3.5 (PM 4b, QUESTIONS M1): `occupied` — more than 50 % of the zone lies in temporarily occupied territory per the
official list (наказ Мінрозвитку № 376 від 28.02.2025, consolidated to 15.09.2026; settlement rows with status
«Тимчасово окупована …» and no end date), drawn at hromada level on OSM hromada boundaries (`katotth`; a hromada if ≥ 50 %
of its listed settlements are occupied and, when only partly, its centre is; АР Крим and Севастополь whole) —
`scripts/precompute_occupied.py` → `backend/data/places/occupied.geojson` (7 features, 41 kB; sources, terms and refresh
in `backend/data/places/README.md`). Text «Окупована територія (станом на 15.09.2026, джерело: Мінрозвитку, наказ
№ 376). Зміни 2022–2025 р. можуть бути наслідком війни …»; it replaces `war_zone`, which stays for the rest of the war
oblasts (e.g. Краматорськ). `zone.occupied` = {snapshot_date, source, source_url} or null. Hromada-level: coarse by
about one hromada at the front; Кінбурн (Очаківська громада, free centre) is not drawn.

sci-v3.6 (§4.0): `ref_border_clipped` (≥ 10 % of the ring forest lay abroad and was dropped); `few_reference_px` reworded
(Лідія): «Навколо ділянки збереглося мало лісу ({km2} км²), показник розриву може бути неточним.»
sci-v3.6 (§4.1): `ref_elev_matched` — «Ліс-еталон підібрано на тій самій висоті (±100 м), що й забудова: {km2} км² із
{km2_all} км² лісу кільця.» when the elevation match is applied and matters (≥ 5 % dropped or Δz moved ≥ 20 m); `ref_match_fallback` — «Лісу на тій самій висоті
(±100 м), що й забудова, замало ({km2} км²), тому еталоном лишається весь ліс кільця.» after `ref_higher` when the match
fell back to the whole forest. `ref_higher` now uses the 60 m DEM and the forest actually used.

## 8. Validation (real data; `scripts/precompute_validation.py` → `/root/uhd/data/validation/<city>.json`)

**Legacy ballpark reproduced** (composites, WorldCover-2021 built inside the boundary minus the ring, 13 summers):

| | WC trees ring (old method) | WC nature ring (first check) | our stable forest ring |
|---|---|---|---|
| Kyiv | **6.72 °C** (expected ≈ 6.8) | 5.57 (first check: 5.59) | 8.62 |
| Pozniaky 1 km circle | **8.88 °C** (expected ≈ 9.0) | 7.72 | 10.78 |
| Kharkiv | 7.54 | 6.48 | 9.77 |
| Lviv | 8.81 | 7.80 | 10.24 |

How the new method moves the Kyiv number (whole city, 2013–2025, sci-v3): old 6.72 → stricter reference (stable
interior forest, +1.90) 8.62 → Esri always-built mask instead of WC-2021 built (−1.24) 7.38 (composite) → per-scene
method (+0.60) **7.98 °C** (Kharkiv 8.44, Lviv 8.82). The per-scene gap is higher on average (+0.49 °C over 178 Kyiv
cells; ≈0 in Kharkiv/Lviv): it
uses dates where zone and ring are both largely clear, i.e. sunny days with stronger heating contrast, while
per-pixel composite medians also take partially cloudy dates.

**Landsat path seam.** Kyiv is covered by WRS paths 180/181/182 on different dates. The eastern swath edge of path 182
runs at kyiv-grid columns ≈ 788–817, i.e. through/just west of Pozniaky (centre col 812), so a composite pixel west of
it is a median of 181+182 dates and east of it mostly 181 dates — a different weather mix on each side. Effect on the
yearly gap:

| zone | per-scene: mean / inter-annual SD | composite: mean / SD | mean abs(per-scene − composite) per year |
|---|---|---|---|
| Pozniaky circle | 11.41 / **0.93 °C** | 10.92 / **2.29 °C** | 1.39 °C (e.g. 2025 and 2013: composite 3.7 / 2.1 °C lower) |
| Kyiv, 178 cells of 1.5 km (median) | SD 0.91 | SD 1.39 | 0.96 (p90 1.36); per-scene SD smaller in 98 % of cells |
| Kharkiv, 122 cells | SD 1.07 | SD 1.42 | 0.84; smaller in 91 % |
| Lviv, 45 cells | SD 0.97 | SD 1.27 | 0.62; smaller in 91 % |
| whole Kyiv | 7.98 / 1.05 | 7.38 / 0.98 | 0.75 (city-wide averaging already mixes paths) |

Consequence for trends: significant gap trends among Kyiv cells 14/178 (7.9 %) per-scene vs 0–1 (≤ 0.6 %) with
composites (noise halved → power up); Kharkiv 0/122 (composite 2), Lviv 0/45 (composite 1). 14/178 is above the ~9 expected by
chance only modestly, but the significant cells are spatially clustered (Nyzhni Sady/Osokorky, §9), not scattered.
Pixel-level tiles: a per-pixel median of per-scene gaps does *not* remove the seam on the map (median column step
across the band 2.34 → 2.22 °C) because clouds give each pixel its own date mix. sci-v3 tiles therefore use the
climatology + smoothed date-matched anomaly construction of §4 (max step 2.0–2.3 vs 1.8–3.1 °C composite; the
remaining ~2 °C steps are real urban structure, the same every year).
Pozniaky 2020: only one usable acquisition and a one-scene composite → year excluded (was 8.59 °C, the low outlier).

Tests: `tests/science/test_stats.py`, `test_masks.py` (synthetic, run anywhere) and `test_real_data.py`
(`pytest -m server_data`, on the server): 58 pass (sci-v3.4). Speed: district report 0.25–0.45 s, whole Kyiv ~2 s (per-scene
stacks over the full city), derived places 0.5–1.1 s; cached repeats ~0 s.

## 9. Demo cases (concept §9; presets in `places/demo.geojson`, reports in `validation/demo_cases.json`)

sci-v3.3: notes rewritten without jargon (QA-UX Q1–Q3), «Позняки» without «(≈1 км)». With the city reference line
(§5) Нижні Сади now reads consistently: gap +1.85/10 yr (p 0.002), **zone itself +2.35/10 yr (p 0.004)**, reference
+0.13 (n.s.) → `gap_driver` "zone" (in sci-v3.2 the zone-matched reference showed −1.5, QA UX-04). «Деснянське»: gap
−2.59 (p 0.033), zone −1.85 (p 0.033), driver "zone". Позняки 11.41, +0.40 (p 0.37). Голосіївський ліс −0.15, +0.32
(p 0.50).

Densification re-scan (sci-v3.3, `/root/uhd/data/validation/scan_demo.json`: 721 boxes of 1.5 and 3 km with ≥ 80 %
urban area in Kyiv/Kharkiv/Lviv). Boxes with a significant *and* zone-driven warming: 13, all but one in the
Осокорки/Нижні Сади cluster — so Нижні Сади stays the "zone warms" demo. Where new construction is visible
(`new_built_gap`), the gap trend is not significant, but the before/after on the newly built pixels is clear:

| candidate (3×3 km box) | gap mean, trend (p) | new built area | gap on new-built px 2013–14 → 2024–25 | GHSL built km² 2015 → 2025 |
|---|---|---|---|---|
| **Виноградар (ЖК «Варшавський»)**, Kyiv, 30.398–30.451 E, 50.482–50.515 N (kyiv px r 575–625, c 500–550) | 7.6 °C, +0.55 (0.30) | 1.22 km² | **5.7 → 7.2 °C** | 1.60 → 1.81 (+13 %) |
| **North of Шевченківський р-н, Lviv**, 23.998–24.047 E, 49.859–49.891 N (lviv px r 350–400, c 450–500) | 8.2 °C, +0.94 (0.08) | 0.81 km² | **2.5 → 5.1 °C** | 1.07 → 1.16 (+8 %) |
| Жуляни — Джигирівщина, Kyiv (r 750–800, c 575–625) | 6.5 °C, +0.22 (0.63) | 0.89 km² | 4.9 → 7.1 °C | 1.25 → 1.39 |

Earlier selection — picked from the 1.5 km cell scan, verified with full sci-v3 reports (per-scene method, always-built pixels, 13 summers,
reference = Kyiv forest ring):

| case | zone | gap mean | gap trend / 10 yr (95 % CI, p) | NDVI trend / 10 yr (p) | other evidence |
|---|---|---|---|---|---|
| 1. densifying | **Нижні Сади (Осокорки)**, 3×3 km box (30.608 E, 50.367 N; kyiv px r 750–800, c 775–825) | 5.1 °C (4.0 → 6.1) | **+1.85 (1.40…2.69), p = 0.002, significant** | +0.010 (0.33) | built share ≈ 0.98 all years (dacha plots count as built), but GHSL built-up surface 1.15 → 1.44 km² (+25 %, 2015→2020): ущільнення |
| 2. greening | **Котеджне містечко «Деснянське» (Троєщина)**, 1.5 km box (30.584 E, 50.532 N; r 475–500, c 675–700) | 8.5 °C (11.7 in 2013 → 6.3 in 2025) | **−2.59 (−4.58…−0.24), p = 0.033, significant** | **+0.109 (p = 0.003)** | built share 0.56 stable, GHSL flat (0.21 → 0.22 km²): gardens/trees grew in a finished cottage town. At 3×3 km the same trend is −1.6, p = 0.11 (diluted). |
| 3. control | **Голосіївський ліс**, 1.4 km square (30.505 E, 50.375 N) | **−0.15 °C** (−1.3…+0.6) | +0.32 (−0.70…1.34), p = 0.50 | +0.026 (0.007) | analysed as "all_land"; behaves like the reference |
| hot but stable | **Позняки (≈1 км)** circle (30.633 E, 50.397 N) | **11.4 °C** | +0.40 (−1.03…2.12), p = 0.37, not significant | +0.059 (p = 0.024) | the hottest demo zone; greening yards, gap flat; seam case |

District / locality presets (`scripts/precompute_places.py --check`): OSM polygons ≥ 0.5 km² (the analysis minimum;
smaller ones such as «ЖК Патріотика» 0.30 km² could never get a report) that `analyze()` accepts; adjacent too-small
neighbourhoods may be merged (`MERGES`: «Виноградар (1-й і 2-й мікрорайони)», 0.73 km²).

Other controls: Bykivnia forest −1.9 °C (n.s.). Non-preset examples (composite + derived reference): Vinnytsia centre
8.3 °C, Bila Tserkva 9.1, Dnipro 7.4, Odesa 6.7 (only 7.5 km² of forest in the ring), all trends n.s.
Pozniaky polygon: OSM has no neighbourhood polygon for «Позняки» (only small complexes such as «ЖК Позняки-4А»,
«ЖБ №1 (Позняки-2)», the park and the lake), so the preset is the 1 km circle around the old demo point (QUESTIONS #2).

## 9b. CMIP6 v2 (active since 15.11 ~16:10 Kyiv, user's decision; mentor review 15.11)

**Active.** `tasmax`, **12 models**, baseline **1995–2014**, futures **2041–2060** / **2081–2100**, median across models
with the **P10–P90** range; every answer carries `climate_version = "cmip6-v2"` and `statistic = "median_p10_p90"`.
Summary built on the homelab from the complete `uhd-dl-cmip6tx` tasmax download (12 × 100 yearly files; 3 failed
downloads were retried, every model/window complete), file `climate/cmip6_summary.npz` (1.5 MB, sha256 `1e9c50d8…`);
the previous v1 file is kept as `climate/cmip6_summary_v1.npz`. Climate values are not stored in reports (the card's
`context.climate` and `/api/climate` are computed per request), so old report ids are unchanged and serve v2 after a
worker restart. Final numbers (change of the summer mean of the daily maximum 2 m air temperature, °C, median
[P10; P90]):

| place | scenario | v1 (5 models, 2005–14 → 2041–50 / 2071–80, mean [min; max]) | v2 (12 models, 1995–2014 → 2041–60 / 2081–2100) |
|---|---|---|---|
| Київ / Нижні Сади | SSP2-4.5 | +2.0 [1.3; 3.1] / +2.1 [1.0; 4.3] | +2.2 [1.4; 3.6] / +3.5 [1.8; 4.9] |
| Київ / Нижні Сади | SSP5-8.5 | +2.7 [1.0; 4.0] / +4.3 [2.1; 6.2] | +3.2 [2.1; 4.1] / +6.8 [4.3; 9.6] |
| Сарни | SSP2-4.5 | +1.7 [0.6; 2.8] / +1.8 [0.6; 4.3] | +2.1 [1.1; 3.3] / +3.3 [1.5; 4.8] |
| Сарни | SSP5-8.5 | +2.3 [0.3; 3.0] / +3.9 [1.6; 6.2] | +3.0 [2.1; 3.9] / +6.5 [4.6; 9.4] |
| Одеса | SSP2-4.5 | +2.3 [1.3; 3.4] / +2.6 [1.4; 4.2] | +2.2 [1.5; 3.6] / +3.5 [2.2; 4.8] |
| Одеса | SSP5-8.5 | +2.8 [1.6; 3.6] / +4.7 [3.0; 5.9] | +3.2 [2.3; 4.0] / +6.7 [5.6; 9.1] |

Baseline summer mean of the daily maximum (1995–2014, median of 12): Київ 25.9 °C, Сарни 24.6 °C, Одеса 27.0 °C; days
> 30 °C per summer 17.0 / 11.8 / 19.7 (SSP5-8.5 2081–2100: 77 / 63 / 91). With 5 models (same windows) the medians
differ by ≤ 0.8 °C; the 12-model P10–P90 is wider and more honest.

The text below is the proposal as written before the decision (kept for the record).


Mentor (climatologist): 20-year windows instead of 10; more than 5 models; median and P10–P90 across models instead of
the ensemble mean; Landsat 5/7 must not extend the LST series (long-term context = air temperature only; QUESTIONS A4
answered: no L5/L7 in the app's LST).

**Proposal.** Variable unchanged: summer (June–August) mean of the daily maximum 2 m air temperature (`tasmax`),
NEX-GDDP-CMIP6 0.25°, nearest cell (as now; a 3 × 3-cell mean is an option, not yet evaluated). Baseline
**1995–2014**, futures **2041–2060** and **2081–2100**, SSP2-4.5 and SSP5-8.5; per model the window means, change =
future − baseline; shown: **median across models with the P10–P90 range** (no ensemble mean as the headline);
`n_models` reported; a model counts only with ≥ 80 % of the years of both windows. Target ≥ 10 models (the 12 of
`cmip6_ext.py`: ACCESS-CM2, MPI-ESM1-2-HR, EC-Earth3, MRI-ESM2-0, CNRM-ESM2-1, NorESM2-MM, GFDL-ESM4, INM-CM5-0, MIROC6,
CanESM5, UKESM1-0-LL, IPSL-CM6A-LR). Hot days > 30 °C follow the same windows and statistics.

**Data on 15.11 ~12:45 (Kyiv).** VM: `tasmax`, 5 models, 2005–2014 / 2041–2050 / 2071–2080 (the current block).
Homelab `extra/cmip6/tas`: 5 models × 1995–2014, 2041–2060, 2081–2100, both SSPs — complete but 2 files (497/500);
`tasmax`: 12 files (NorESM2-MM historical 1995–2006). `tasmax` for the new windows is **not** available for any model.
Download rate ≈ 175 files/h with full-file fallback (the homelab venv lacks `fsspec`, so the HTTP-range reader fails);
10–12 models × 100 files = 1 000–1 200 files ≈ 6–7 h → not by 16:30 as is.

**Preview numbers** (`docs/cmip6-v2/cmip6_v2.py`, raw rows in `docs/cmip6-v2/*.jsonl`; change of the summer mean, °C;
v2 shown with `tas`, the only variable available for the new windows, 5 models — so P10–P90 is still close to min–max).
Kyiv and Нижні Сади share one 0.25° cell.

| place | scenario | current (tasmax, 2005–14 → 2041–50 / 2071–80, mean [min; max], 5 models) | v2 preview (tas, 1995–2014 → 2041–60 / 2081–2100, median [P10; P90], 5 models) |
|---|---|---|---|
| Київ / Нижні Сади | SSP2-4.5 | +2.0 [1.3; 3.1] / +2.1 [1.0; 4.3] | +2.2 [1.5; 2.9] / +2.9 [1.8; 4.1] |
| Київ / Нижні Сади | SSP5-8.5 | +2.7 [1.0; 4.0] / +4.3 [2.1; 6.2] | +3.2 [1.8; 3.6] / +6.7 [4.5; 8.2] |
| Сарни | SSP2-4.5 | +1.7 [0.6; 2.8] / +1.8 [0.6; 4.3] | +1.9 [1.2; 2.7] / +2.9 [1.5; 4.0] |
| Сарни | SSP5-8.5 | +2.3 [0.3; 3.0] / +3.9 [1.6; 6.2] | +2.6 [1.5; 3.2] / +6.3 [4.0; 7.7] |
| Одеса | SSP2-4.5 | +2.3 [1.3; 3.4] / +2.6 [1.4; 4.2] | +2.1 [2.1; 3.0] / +3.1 [2.3; 4.1] |
| Одеса | SSP5-8.5 | +2.8 [1.6; 3.6] / +4.7 [3.0; 5.9] | +3.0 [2.4; 3.6] / +6.9 [5.7; 7.8] |

Why v2 is larger: the earlier baseline (1995–2014 is ~0.3–0.5 °C cooler than 2005–2014) and the later end window
(2081–2100 vs 2071–2080, +1.5–2.5 °C under SSP5-8.5). Variable effect, same 5 models and old windows: `tas` change is
0.1–0.3 °C smaller than `tasmax` (Kyiv SSP2-4.5 2041–50: 1.79 vs 2.00), so the `tas` preview slightly *understates*
the final `tasmax` v2. Cost of the change: climate block numbers and card wording («медіана моделей, діапазон 10–90 %»,
«1995–2014 → 2041–2060 / 2081–2100»), mentor PDF §4.11/§7, a new precompute of `cmip6_summary.npz` (~1 GB of
yearly files to the VM). LST, gap and all report numbers are unaffected.

**Implementation (ready, inactive).** `climate.build_summary_v2(raw_dir)` /
`scripts/precompute_climate.py --v2 RAW_DIR --out PATH` build the v2 summary (per model and window means of
`jja_mean`, `hot30`, `hot35`; a model/window needs ≥ 80 % of its years; ~0.3 MB) and stamp it `version = v2`;
`climate_projection` then answers with `statistic = "median_p10_p90"`, baseline `[1995, 2014]`, periods `2041-2060` /
`2081-2100`, and per period `delta` = median, `delta_range` = [P10, P90], `delta_stat`, `n_models` (same keys as now, so
the API shape is unchanged; the frontend takes period keys from the response). Activation = putting the v2 file in
place of `$UHD_DATA_DIR/climate/cmip6_summary.npz` — only after the user's decision. Download (homelab unit
`uhd-dl-cmip6tx`, 15.11): tasmax stage 0 (5 base models, 500 files) ≈ 375 files/h with ranged reads → ~14:10 Kyiv;
stage 3 (7 more models, 700 files) → ~16:00.

**Card / i18n wording for v2** (replaces «N моделей: від X до Y»):
- main: «Прогноз: до 2060 денний максимум приземної температури повітря (на висоті 2 м) зросте приблизно на
  X °C (порівняно з 1995–2014)» — X = median.
- sub: «Помірний сценарій (SSP2‑4.5), медіана N моделей; у 8 з 10 моделей — від A до B °C. Повітря, не поверхня.»
  (A–B = P10–P90; «8 з 10» is the plain reading of the 10–90 % range — alternative wording «діапазон 10–90 %: від A до
  B °C»).
- climate panel/table headers: «2041–2060», «2081–2100», «базовий період 1995–2014», «медіана (10–90 %)».
- glossary «Розкид моделей»: «Кожна кліматична модель дає своє значення. Показуємо медіану (половина моделей дає
  більше, половина — менше) і діапазон, у який потрапляють 80 % моделей (від 10-го до 90-го процентиля). Середнє по
  моделях не показуємо: при великому розкиді воно вводить в оману.»
- remove the backend `short_baseline` caveat (10-year baseline) — baseline is now 20 years.

**Mentor PDF changes for v2:** §4.11 — periods 1995–2014 → 2041–2060 / 2081–2100 (were 2005–2014 → 2041–2050 /
2071–2080), N models (list), statistic = median with P10–P90 (was ensemble mean with min–max), same variable/cell; the
results table for the demo places with the new numbers; §7 — remove «10-year windows are noisy» from limitations and
the CMIP6 open question (answered: 20-year windows, more models), keep «air, not surface»; question 14 → answered;
A4 → answered: no Landsat 5/7 in the LST series (long-term context only for air temperature).

## 10. Limitations

- LST is late-morning (~10:45–11:00 local mean solar time over Kyiv; nominal 10:00–10:15 equator crossing) daytime surface temperature (not air, not night); shadows of tall buildings lower it.
- Classes for 2013–2016 and 2024–2025 are extrapolated from Esri 2017/2023 with simple NDVI/NDBI rules;
  Esri itself flickers between built/rangeland in sparse areas. Construction sand counts as built.
- Per-scene data only for Kyiv/Kharkiv/Lviv; elsewhere composites (seam errors of 1–2 °C in single years possible).
- Per-scene reference uses the visible part of the ring with a climatology correction, but a partial ring is still
  biased (method review M5). On the 8 Kyiv dates with ≥ 95 % of the ring clear, estimating it from one half against the
  full ring gave: west half +0.29 °C (SD 0.32, max 0.80), east half −0.44 (SD 0.48, **max 1.22**), north/south
  +0.27 / −0.44 (max 1.06). The error is systematic. Path-182 dates see mostly the west half, and dates are accepted
  with only ≥ 2000 visible px (≈ 2 % of the ring). The earlier "0.1–0.5 °C" was not measured.
- Pixel mixing at 60 m (review M7): the ingest reads Landsat overview level 0. Its `qa_pixel` is nearest-sampled
  (one 30 m child pixel) while `lwir11` is averaged over four, so a 60 m LST value can include a cloudy or edge
  30 m pixel that the QA test did not see. The dilated-cloud bit mitigates this only partly. Nearest-neighbour
  reprojection does not undo it.
- Seam sensitivity (review M2): Нижні Сади also straddles the path-182 edge. Its trend is significant with the
  per-scene method (+1.85 °C/10 yr, p 0.002; robust: every leave-one-year-out p ≤ 0.005) but not with composites
  (+1.06, p 0.43). The per-scene method is the one designed for the seam, but the result depends on it.
- Fragile trends (review M3): «Деснянське» −2.59, p 0.033 loses significance when any one of 2013, 2014, 2015, 2022
  or 2025 is dropped (leave-one-year-out p 0.06–0.115); composites −1.60, p 0.077. Treat it as suggestive.
- `gap_driver` is partly circular (review M4): `zone_lst` = reference line + gap, so `zone_trend` ≈ gap trend +
  reference trend by construction, and the driver compares point slopes only. "zone" means "the reference line has
  no significant trend". It does not exclude a forest cooling inside the reference CI (Нижні Сади: −1.27…+2.06 °C/10 yr).
- Trends are computed on the reported 2-decimal yearly values. The effect is ≤ 0.01 in slope and ≤ 0.05 in CI
  bounds (Нижні Сади unrounded +1.84 [1.45; 2.69]), and the shown p is exactly reproducible from the shown series.
- The derived urban area for arbitrary places depends on the 300 m closing; large agglomerations are clipped at ~60 km.
- Steppe cities (Odesa, Mykolaiv, Zaporizhzhia) have little stable forest; the reference is small or widened.
- Many tests on many cells: a single significant cell is weak evidence; prefer zones chosen in advance.
- No LST at all in ASTER-GED gaps (§5, `no_lst_product`) until the data side computes LST from radiance there.
- Post-pitch option (PM item 9, not now): compute LST from TOA radiance (`trad`) with land-cover-based emissivity in the
  ASTER-GED gaps — a new product, to be validated against C2 ST where both exist; until then the gaps are hatched
  (persistent) or display-filled from neighbouring summers (year-specific). Landsat 9 merging is the real fix for the
  2022 holes but is a method change (QUESTIONS A3), post-pitch.
- **L8 vs L9 offset (QUESTIONS A3, validation only — nothing merged)**: Landsat 9 flies 8 days out of phase with
  Landsat 8, so over Ukraine adjacent-path sidelaps are seen by the two sensors **1 day apart** (no same-day pairs in
  summer). Summers 2022–2023, all L9 scenes × L8 scenes with |Δd| ≤ 1 overlapping by ≥ 20 000 clear px (homelab
  per-scene ST, `docs/investigation-a3/a3_offset.py`): **1 800 pairs** (median overlap 585 000 px).
  L9 − L8 surface temperature: median **+0.07 °C**, mean +0.10 ± 0.09 (IQR −1.9…+1.9: day-to-day weather). Gap
  (median built − median stable forest inside the same overlap, 1 185 pairs with ≥ 2 000 px of each): median
  **+0.11 °C**, mean +0.15 ± 0.04 (IQR −0.5…+0.8); 2022 +0.14, 2023 +0.09. The gap offset depends on the side of
  the swath (L9 one day later: +0.29; one day earlier: −0.07) — view-geometry, not a sensor bias. Conclusion: L9 C2 ST
  is interchangeable with L8 for the gap to ≈ 0.15 °C (well below the 1–2 °C year-to-year noise), so a merge needs no
  cross-calibration beyond an optional −0.1 °C; it still needs the user's decision (A3) and a version bump.
- War: 2022–2025 changes in occupied / front-line regions may be destruction; classes after 2023 are extrapolated and
  do not see ruins (`occupied`, `war_zone`, `classes_extrapolated`). Occupation is per hromada from the official list
  (dated snapshot), the rest of the war oblasts per oblast; neither is a front line.
- Zones are clipped to Ukraine's land border (`zone_clipped`); the border polygon includes coastal waters, so sea is
  not clipped (water pixels are excluded by the classes anyway).
- Future work (not done, INVESTIGATION-2020): (a) show a single usable pass as an *indicative* point outside the
  series and trend (Позняки 2020-08-16: +11.4 °C); (b) add Landsat 7 (2020-08-17 is 98 % clear over Позняки) — a
  method change (sensor cross-calibration, SLC-off stripes) that must be validated over all years, not patched into
  one. Lowering the per-date coverage threshold is *not* an option: it would admit cloud-contaminated partial scenes.
- CMIP6 block: 5 models, 0.25° cells, decades 2041–2050/2071–2080 vs 2005–2014 only.

## 11. Data versions

Versions: sci-v1 (first release), sci-v2 (chart lines `zone_lst = ref_lst + gap`), **sci-v3** (always-built
headline, zone climatology adjustment, per-scene gap tiles, blended reference field, pixel budget, name-free cache), sci-v3.1 (METHOD_VERSION only: half-up rounding, verdict on the shown p — tiles unchanged),
sci-v3.2 (METHOD_VERSION only: urban-parks green, suburbs use the city reference, explicit excluded years),
sci-v3.3 (METHOD_VERSION only: common city reference line, `zone_trend`/`gap_driver`, new verdict copy and
new-construction sentence, `no_lst_product`/`war_zone`/`zone_clipped`, border clipping, area cap — tiles unchanged),
sci-v3.4 (METHOD_VERSION only: `excluded_detail` for `too_few_scenes` years; scenes `outside_swath` /
`zone_in_swath` / zone-weighted cloud — numbers unchanged), sci-v3.4.1 (driver sentence wording, review M4), sci-v3.5 (`occupied` caveat and `zone.occupied` — numbers
unchanged), sci-v3.5.1 (`built_share_land` / `built_share_zone` / `zone.sealed_share_ghsl` — numbers unchanged), sci-v3.5.2 (`derived_reference` text: the ring is measured from the built-up city edge, not the centre), sci-v3.5.3 (text only: caveats `ref_higher` — reference forest ≥ 100 m above the zone's built pixels, median
elevations from `ukraine/dem600.tif` (Copernicus DEM GLO-90, 600 m, `python -m uhd.science.refquality`), and `ref_weak` —
reference < 20 km², median patch < 1 km² or > 10 % within 300 m of water, from INVESTIGATION-REGIONAL-GAP; item 31 wording
«N літніх сезонів», «поки несуттєво», «приземна температура повітря (2 м)»). Copernicus DEM: © DLR e.V. 2010–2014 and ©
Airbus Defence and Space GmbH 2014–2018 provided under COPERNICUS by the European Union and ESA. sci-v3.5.4 (text only, TERMS-UK.md: «статистично значуще / незначуще» next to p, «ділянка», «ліс-еталон», «підстильна поверхня, близько 11:00 за місцевим сонячним часом», «приземна температура повітря (на висоті 2 м)», «поза межами даних»). **sci-v3.6** (numbers change, owner sign-off
15.11): reference ring clipped to Ukraine before the minimum-forest check (§4.0, caveat `ref_border_clipped`,
`reference.abroad_km2`, gap-tile reference field rebuilt on Ukrainian forest only); `few_reference_px` reworded; elevation-matched reference forest (§4.1) — forest within ±100 m of the zone's median built elevation (60 m
Copernicus DEM `ukraine/dem60.tif`), fallback to the whole forest below 200 px; `reference.elevation_match`; caveats
`ref_elev_matched`, `ref_match_fallback`; preset cities via `<city>/refbins.npz`. Gaps (§4.2): Сімферополь −2.93 °C,
Севастополь −2.75, Ужгород −1.48, Чернівці −0.69, Франківськ −0.61, Слов’янськ −0.43, Краматорськ −0.21; Danube
towns −1.06…+2.91; Київ, Львів, Одеса and the demo zones ≤ 0.02. DATA_VERSION unchanged; gap tiles change near the
border through the rebuilt `reffield.npz`.

Memory per API worker (QA RB-01): derived references are cropped to the bbox of their masks and cached in an LRU of
≤ 64 entries and ≤ 160 MB (`reference.DERIVE_CACHE_BYTES`; typical entry 2–7 MB, was up to ~30 MB uncropped);
reports: LRU 128 (tens of KB each); derived reference values: LRU 4096 float pairs. Tile inputs (`gapmap.npz` 25–53
MB per city, `reffield.npz` 43 MB) are extracted once to `<file>.npz.d/*.npy` and opened as read-only memmaps, so the
workers share the page cache instead of holding private copies; per-scene stacks and `clim.npy` were memmaps already.
All other module caches are keyed by a fixed small set (cities, years) and bounded.
`DATA_VERSION = "l8c2l2-60m-2013-2025/sci-v3"` (bump only when rasters/tile values change: the backend keys tiles by it),
`METHOD_VERSION = "sci-v3.4"`, `TILES_VERSION = "tiles-v2"`: Landsat 8 Collection 2 Level 2 (Planetary Computer), summers 2013–2025,
60 m EPSG:3035 grid; ESA WorldCover v200 (2021); Esri/IO LULC v02 2017–2023; OSM farmland and boundaries (Nov 2026);
GHSL R2023A; NEX-GDDP-CMIP6 (5 models). Bump the version when classes, masks or thresholds change (reports store it).
