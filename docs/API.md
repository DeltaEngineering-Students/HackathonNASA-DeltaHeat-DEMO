# API — DELTAHEAT backend (owner: backend)

Base URL: `https://nasa-hackathon.hlushchenko.dev` — OpenAPI UI at `/api/docs`, schema at `/api/openapi.json`.
The same process serves the built frontend at `/` (SPA fallback to `index.html`) and the tiles at `/tiles/…`.

Contract: **v1** from `PLAN.md`. Additions (backwards-compatible) are marked **(+)**. Any breaking change is noted in the changelog at the bottom.

## Conventions
- JSON, UTF-8. Geometries are GeoJSON in WGS84 (lon, lat). A `Feature` or a one-feature `FeatureCollection` is accepted wherever a geometry is.
- Errors: `{"error": "<code>", "message": "<text>", "details"?: …}` with HTTP 404 (not found), 422 (bad input), 429 (rate limit), 502 (upstream geocoder/weather down), 503 (`science_not_ready`, `agent_not_configured`, `geocoder_busy`; may have `Retry-After`).
- Every response has `X-Request-Id` (echoes the request header if given). Logs are JSON lines (journald).
- CORS is open for `http://localhost:5173` (Vite dev). In production the frontend is same-origin.

## Endpoints

### `GET /api/health`
```json
{"ok": true, "data_version": "l8c2l2-60m-2013-2025/sci-v1", "api_version": "0.1.0", "science_ready": true, "raw_data": true}
```

### `GET /api/meta` (live format)
```jsonc
{
  "api_version": "0.1.0",
  "data_version": "l8c2l2-60m-2013-2025/sci-v2",
  "years": [2013, 2014, …, 2025],                 // array of ints (not {from,to})
  "default_years": [2013, 2025],
  "coverage": {"aoi": "ukraine", "bbox": [21.3406, 43.0521, 41.9249, 54.1805], "crs": "EPSG:3035", "res_m": 60},
  "cities": [{"id": "kyiv", "name": "Київ", "bbox": [29.8166, 49.9661, 31.2509, 50.8852], "place_id": "kyiv", "has_data": true}, …],
  "layers": {                                     // an OBJECT, not an array of layers
    "tile_url": "/tiles/{layer}/{year}/{z}/{x}/{y}.png?theme={theme}",
    "min_zoom": 3, "max_zoom": 16, "native_zoom": 11, "tile_size": 256,
    "ids": ["gap", "lst", "ndvi", "dndvi"], "dndvi_base_year": 2013,
    "gap_reference_uk": "Поблизу Києва/Харкова/Львова — еталон міста …",
    "scales": {
      "gap": {"title_uk": "Різниця з лісом навколо міста (LST зони − LST еталону)", "unit": "°C", "kind": "diverging",
              "domain": [-6, 12], "neutral": 0,
              "stops": {"light": [{"value": -6, "color": "#5C8C7A"}, {"value": -2, "color": "#CEDCD4"}, …],
                        "dark":  [{"value": -6, "color": "#326056"}, …]}},     // stops per theme, objects {value, color}
      "lst": {…, "kind": "sequential", "domain": [15, 50]}, "ndvi": {…, "domain": [0, 0.9]}, "dndvi": {…, "domain": [-0.3, 0.3], "neutral": 0}
    },
    "reference_color": {"light": "#1D3FBF", "dark": "#7F9BFF"},
    "no_data": "transparent"
  },
  "presets": [                                     // place summaries, no geometry; order: demo zones (science demos first), cities, districts, localities
    {"id": "demo-holosiivskyi-lis", "name": "Голосіївський ліс", "kind": "demo_zone", "city": "kyiv",
     "bbox": [30.49278, 50.36725, 30.51722, 50.38275], "area_km2": 1.96,
     "case": "control", "note_uk": "Великий ліс у місті: поводиться як природа — розриву майже немає."},
    {"id": "kyiv-pozniaky", "name": "Позняки (≈1 км)", "kind": "demo_zone", "city": "kyiv", "bbox": […], "area_km2": 3.14,
     "case": "hot_stable", "note_uk": "…", "aliases": ["demo-pozniaky"]}, …
  ],
  "limits": {"min_area_km2": 0.5, "max_area_km2": 5000.0, "max_vertices": 20000, "max_bbox_side_km_city": 150.0,
             "max_bbox_side_km": 72.0, "max_bbox_km2": 14400.0},
  "verdict_rule": {"p_lt": 0.05, "min_years": 8},
  "science_ready": true, "agent_configured": false,
  "notes_uk": {"lst": "LST — денна температура підстильної поверхні (близько 11:00 за місцевим сонячним часом), а не приземна температура повітря (2 м)."}
}
```

### Place object (presets, `/api/places`, `/api/places/{id}`)
`{id, name, kind, city, bbox: [w, s, e, n], area_km2, geometry?, case?, note_uk?, aliases?, source?}`
- `id` — always ASCII and stable. Science files with Cyrillic ids (`kyiv-оболонський-район`) are transliterated (`kyiv-obolonskyi`); the original id is kept in `aliases` and still resolves in `/api/places/{id}`. Each place is listed once: a science polygon with the same city + kind + name replaces the bundled geometry under the bundled id.
- `kind`: `demo_zone` (science demos `demo-*` and the bundled demo neighbourhoods; science `kind: "demo"` is normalised to `demo_zone`), `city`, `district`, `locality` (OSM named neighbourhoods from the science Overpass script).
- `case` (demo zones only): `densifying` (Нижні Сади — growing gap), `greening` (Деснянське), `control` (Голосіївський ліс), `hot_stable` (Позняки); `note_uk` — one-line story for the card.
- No `center` field: use the `bbox` centre.

### `GET /api/overview` (country map markers, MAP-TASKS 3)
Precomputed at deploy (`python -m uhd.services.overview --build --jobs 4`, after the rank tables) into
`{data_dir}/overview.json` (~60 kB), served from memory; `Cache-Control: public, max-age=86400`,
`ETag: "<data_version>|<method_version>|<generated_at>"` (`If-None-Match` → 304). `503 overview_not_ready` until the
first build. The numbers come from the same `analysis.analyze` call as `POST /api/analyze {place_id}` (same stored
report), so a marker equals the card headline.
```jsonc
{"version": "l8c2l2-60m-2013-2025/sci-v3", "method_version": "sci-v3.4", "generated_at": "2026-11-15T…Z",
 "years": [2013, 2025],
 "places": [{
   "place_id": "kyiv",                 // or "osm:R1017311" (major cities) or "kyiv-darnytskyi" (districts)
   "name": "Київ", "kind": "city",     // "city" (3 AOI cities + 37 of cities_ua.json) | "district" (Kyiv/Kharkiv/Lviv presets)
   "city": "kyiv", "oblast": "Київ",   // city: AOI id or null; oblast from OSM (AOI cities: fixed)
   "lon": 30.5, "lat": 50.45,          // label point inside the polygon
   "bbox": [w, s, e, n],
   "rank": 1,                          // label priority: cities by population order (1 = Київ … 40), districts ≥ 100 (bigger first)
   "status": "ok",                     // "ok" | "no_data" (no gap) | "insufficient_data" (gap, no trend) | "error"
   "gap_mean": 7.98,                   // = report gap_summary.mean (raw; round half-up)
   "gap_by_year": {"2013": 8.1, "2020": null, …},   // = report series[].gap
   "trend": {"slope_per_decade": 0.31, "p": 0.42, "verdict": "not_significant"},  // null unless status ok
   "method": "per_scene", "caveats": ["war_zone", …],   // caveat codes of the report
   "war_region": {"name": "Донецька область", "since": 2014},   // = report zone.war_region (oblast-level; no «occupied» status)
   "reason_uk": null,                  // status ≠ ok: «немає супутникової температури поверхні (прогалина в продукті USGS)» |
                                       // «немає даних про температуру поверхні за ці роки» | «замало літ із даними, щоб оцінити тренд» | «не вдалося порахувати»
   "report_id": "…"}]}                 // the stored report (GET /api/reports/{id})
```

### `GET /api/overlays` (veil, border, no-data hatch, war outline — MAP-TASKS 2/4)
Built in memory on first request (rebuilt when the science mask file changes); same cache headers (ETag = content hash).
```jsonc
{"version": "<data_version>",
 "ukraine": {"bbox": [22.14, 44.39, 40.23, 52.38], "geometry": {"type": "MultiPolygon", …}},  // /srv/landsat/aoi/Ukraine.geojson, simplified 0.005°
 "war_regions": {"type": "FeatureCollection", "features": [   // backend/data/places/war_oblasts.geojson, simplified 0.005°
    {"type": "Feature", "properties": {"name": "Донецька область", "since": 2014, "text_uk": "<war_zone caveat text>"}, "geometry": …}]},
 "occupied": {"type": "FeatureCollection",          // backend/data/places/occupied.geojson (science, PM 4b), simplified 0.005°
    "properties": {"label_uk": "окуповано (станом на 15.09.2026, джерело: Мінрозвитку, наказ № 376)",
                   "attribution": "Мінрозвитку України (наказ № 376 від 28.02.2025, zakon.rada.gov.ua); © OpenStreetMap contributors",
                   "source": …, "source_url": "https://zakon.rada.gov.ua/laws/show/z0380-25", "snapshot_date": "2026-09-15", "licence": …},
    "features": [{"properties": {"oblast": "Донецька", "whole_unit": false, "label_uk": "<same label>"}, "geometry": …}]},  // 7, one per oblast
 "no_scenes": {"type": "FeatureCollection",        // science (c4f077c): {data_dir}/overlays/no_scenes.geojson, served as-is
    "properties": {"rule": "lst_n == 0 and ndvi_n < 3 on land; ~1 km blocks …; simplified 500 m; one feature per year",
                   "label_uk": "замало безхмарних знімків цієї смуги в цьому році"},
    "features": [{"properties": {"year": 2022, "area_km2": 13519.0, "label_uk": "2022: замало безхмарних знімків цієї смуги"},
                  "geometry": {"type": "MultiPolygon", …}}, …]},   // one per year that has such swaths; filter by year client-side
 "no_lst": {"type": "FeatureCollection", "properties": {"rule": …, "data_version": …, "area_km2": …},   // science mask
    "features": [{"properties": {"years": [2013, …], "share_years": 1.0, "area_km2": 812.4,
                                 "label_uk": "немає супутникової температури поверхні"}, "geometry": …}]}}
```
`occupied` must be shown with its `properties.attribution` (ODbL, derived OSM database — terms in backend/data/places/README.md); `war_regions` stays «зона бойових дій». Reports (sci-v3.5): caveat code `"occupied"` replaces `war_zone` where it applies, and `zone.occupied = {snapshot_date, source, source_url} | null` (also per place in `/api/overview`).
`no_scenes` (all years in one response, ≈ 95 kB) is an empty collection until science writes it; both science files are re-read when they change (no restart). `no_lst` is `{data_dir}/overlays/no_lst.geojson` written by `python -m uhd.science.nolst_mask` (science; run by the
deploy only when the file is missing); an empty collection until it exists.

### `GET /api/reports/{id}/export?format=csv|xlsx|json|pdf[&name=&place_id=&lang=]` (board item 29 «Експорт»)
The stored report only — nothing is re-analysed, so every old id (incl. the mentor-PDF ids) exports as it was computed.
`name` / `place_id` = what the page shows (stored reports are name- and place-free): they label the file, its zone
row and the link (`{origin}/?zone=<place_id>`, else `{origin}/?area=lon,lat;…` for a drawn ring ≤ 200 points, else
`{origin}/api/reports/{id}`). `Content-Disposition: attachment; filename="deltaheat_<slug>_<id>.<ext>"` (slug =
transliterated name / place id, else `zona`); `Cache-Control: public, max-age=86400`; `HEAD` supported (feature probe).
422 `invalid_format` / bad id, 404 unknown id.
- **csv** — UTF-8 **with BOM**, delimiter **`;`** (Excel in the Ukrainian locale), decimal **point**, CRLF. A header block
  of `key;value` rows (Зона, Площа зони, Проаналізовано, Основа, Еталон, Площа еталону, Роки, Середній розрив, Тренд,
  95 % інтервал, p, Літ із даними, Висновок, Текст, Метод, method_version, data_version, report_id, Посилання), an empty
  row, then the series: `Рік;LST зони, °C;LST лісу-еталону, °C;Розрив, °C;NDVI;Частка забудови;Знімків;Метод;Причина виключення`.
- **xlsx** — sheets «Підсумок» (the same header block + caveats), «За роками» (series with number formats), «Про метод»
  (short method, sources and licences, versions, link); header rows frozen. (A scenes sheet is left out: it needs the
  scene list, i.e. a recompute.)
- **json** — the labelled stored report (as `GET /api/reports/{id}` without the per-response `context`) + `link`.
- **pdf** — 1–2 A4 pages in Ukrainian (fpdf2, pure Python; no system packages): title, map snapshot (our own `gap` tiles of
  the latest summer with data + the zone outline (`zone_outline` when cut) + numbered hotspots, Pillow; no external
  tiles), headline sentence, three big numbers (mean gap, trend with 95 % CI, verdict with p), the two-line chart (zone vs
  forest LST), the year table, hotspots, caveats, method + versions, data credits, the link + QR (segno). App palette
  (F7 light) and Onest 400/600, decimal commas, «−». Cached in `{cache_dir}/export/{id}.<key>.pdf` (key = report, name,
  link, method/hotspots version), LRU by mtime, ≤ 200 MB. Render ≈ 1–2 s cold (tiles), instant when cached.
  Fonts: `backend/uhd/resources/fonts/Onest-{400,600}.ttf` — static instances of Onest[wght] (google/fonts, © The Onest
  Project Authors), SIL Open Font License 1.1 (`OFL.txt` next to them); embedded (subset) in every PDF.

### `GET /api/reports/{id}/reference` (board item 20 D: reference-forest outline for the map)
GeoJSON Feature (< 100 kB, `Cache-Control: public, max-age=86400`, ETag): the report's reference forest, rebuilt from the
stored geometry with the current science reference code, simplified from 30 m upward (30/60/120/240/480 m) until it fits.
Cached on disk (`{cache_dir}/reference/{id}.ref1.json`); the report and its id are not changed. 422 bad id, 404 unknown id.
**(+) sci-v3.6:** when the report's `reference.elevation_match.applied` is true the outline is the elevation-matched forest
(the forest the report used); `properties.elevation_matched` says which. Older reports keep the whole ring.
```jsonc
{"type": "Feature", "geometry": {"type": "MultiPolygon", …},
 "properties": {"report_id": "…", "label_uk": "ліс-еталон", "city": "kyiv" | "derived", "kind": "preset" | "derived",
                "ring_km": [2, 15], "area_km2": 210.0, "simplify_m": 30, "report_method_version": "sci-v3.4.1",
                "method_version": "sci-v3.6", "elevation_matched": false, "schema": "ref1"}}
```

### `?lang=en` (item 32, I18N.md §6) — English on read
`lang` = `uk` (default; missing → today's bytes, unchanged) | `en`, on `POST /api/analyze`, `GET /api/reports/{id}`,
`/api/overview`, `/api/overlays`, `/api/places`, `/api/places/{id}`, `/api/climate`, `/api/meta`; anything else → 422.
`en` **adds** siblings and changes nothing else (no number, no `*_uk`, stored reports untouched, old ids → 200):
- every `X_uk` string → `X_en` (a dict such as `notes_uk` → `notes_en` with the same keys); every Cyrillic `name` /
  `short_name` → `name_en` / `short_name_en` (KMU 2010 romanisation; generic words translated: район → District,
  ліс → Forest, мікрорайон → microdistrict, Увесь → All of: «Desnianskyi District (Kyiv)», «Pozniaky (≈1 km)»);
  Cyrillic `source` / `attribution` / `rule` → `*_en`.
- report texts from science (`verdict_text_en`, `caveats[].text_en`, `series[].excluded_detail.text_en`) via
  `uhd.science.localize_report`, per the report's `method_version`.
- A text with no exact entry or template is `"…_en": null` — show the `_uk` text then. Numbers in an `_en` text are the
  `_uk` ones (decimal point; tested: same number multiset).
- `/api/overview` and `/api/overlays` with `lang=en` have their own ETag (`"<etag>-en"`).
- OSM/Nominatim hits on `/api/places` and `/api/places/{id}` have provider-supplied `name_en` and
  `display_name_en` when `lang=en` (see below); preset names continue using the existing local dictionary/romanisation.
- `GET /api/reports/{id}/export?lang=en` (piece 3): the same file, same rows and numbers, in English —
  csv delimiter **`,`** (decimal point as before), header block Zone, Zone area, Analysed, Basis, Reference,
  Reference area, Summers, Mean gap, Trend, Trend 95 % interval, p, Summers with data, Verdict, Text, Method,
  method_version, data_version, report_id, Link; series `Year,Zone LST, °C,Reference forest LST, °C,Gap, °C,NDVI,
  Built-up share,Scenes,Method,Exclusion reason`; xlsx sheets «Summary», «By year», «About the method»; json = the
  `?lang=en` report + `link`; pdf with TERMS-EN labels and decimal points (no science English verdict → a numbers-only
  sentence). An explicit `lang` adds `-en` / `-uk` to the file name and `&lang=…` to the link; `Cache-Control` for `en`
  is `max-age=3600`. No `lang` → the Ukrainian bytes as before.

### `GET /api/places?q=&limit=10&geocoder=true`
Presets first (text folded for case, diacritics and apostrophes — «Соломянський» = «Солом’янський»; ranked: exact name/id/alias › every query word is a whole word of the name («Київ» → «Увесь Київ») › prefix › word prefix › substring, then by kind; empty `q` → all presets in the order above), then — if fewer than `limit` presets match and `q` has ≥ 3 chars — Nominatim results restricted to Ukraine (cached 30 days on disk, generic User-Agent, no user data forwarded). Rate limit: ≤ 1 request/1.1 s **across all workers** (a `flock`'d slot file in the cache dir); a search waits for at most one slot (≤ 1.2 s) — if the geocoder is busy or down, `geocoder` is `[]` (no error) and `geocoder_status` says why: `"ok" | "geocoder_busy" | "geocoder_unavailable" | null` (null = geocoder not asked). The response is an **object**, not an array:
```bash
curl -G $H/api/places --data-urlencode q=Тер
```
```json
{"query": "Тер",
 "presets": [{"id": "kyiv-teremky", "name": "Теремки", "kind": "demo_zone", "city": "kyiv", "bbox": [30.43841, 50.36323, 30.46667, 50.38111], "area_km2": 3.14}],
 "geocoder_status": "ok",
 "geocoder": [{"id": "osm:R72525", "name": "Тернопільська область", "display_name": "Тернопільська область, Україна", "kind": "geocoder",
               "osm_class": "boundary", "osm_type": "state", "center": [25.616752, 49.663], "bbox": [24.716, 48.507, 26.444, 50.267]}],
 "attribution": "Geocoding © OpenStreetMap contributors (Nominatim)"}
```
Preset sources (merged in order): bundled `backend/uhd/resources/presets.geojson` (OSM boundaries of the three cities and their districts; demo circles), then science files `backend/data/places/*.geojson` (`demo.geojson`, `kyiv.geojson`, `kharkiv.geojson`) and `$UHD_DATA_DIR/places/*.geojson`.

With `lang=en`, the native `accept-language=uk` search still determines the hits, their ordering, identities and
coordinates. One optional second search with `accept-language=en,uk` supplies `name_en` / `display_name_en`, matched
by OSM type + id, never by response position. The native `name` / `display_name` and all other canonical fields stay
unchanged. If the English response is busy, unavailable or omits a native hit, that hit's English siblings explicitly
fall back to its native labels; the successful native search stays `geocoder_status: "ok"`. No LLM is used.
Both language responses are cached independently for 30 days using the existing Nominatim cache and global limiter.
A cold English search can therefore make **two** upstream calls and wait for an additional ~1.1 s time slot (plus
HTTP latency); UK/default requests never make the English request. Cached responses require no additional HTTP call.

Major cities without a bundled preset (Дніпро, Одеса, Запоріжжя, Маріуполь, … 37, `uhd/resources/cities_ua.json`) are
returned among `presets` for a matching query (Ukrainian name, Russian/Latin aliases) as `{"id": "osm:R1017311",
"name": "Дніпро", "kind": "city", "source": "osm", "center", "bbox", "oblast", "aliases"}` — no `area_km2`; the
boundary is fetched from OSM when opened (`/api/places/{id}`, `/api/analyze {place_id}`, kind `city`). They rank like
presets: exact/prefix name of a city before districts that only contain the query («Дніпро» → Дніпро, then
«Дніпровський район (Київ)»), and are not in `/api/meta → presets` (the default list) nor repeated under `geocoder`.

Rounding: every displayed number (stored values and `*_uk` texts) is rounded **half-up on the decimal value**
(7.55 → 7,6; ties away from zero: −0.05 → −0.1), not JS `toFixed`/Python `round` on the binary value (7.55 → 7.5).
Clients should format with the same rule, e.g. `Math.sign(v) * Number(Math.round(Number(Math.abs(v) + "e1")) + "e-1")`
for one decimal.

### `GET /api/places/{id}`
Place object with `geometry`. Geocoder ids (`osm:R1929810`) are resolved through Nominatim `lookup`; a point, line or polygon smaller than 0.5 km² becomes a ≈1 km-radius circle (`kind: "geocoder_circle"`, name «… (≈1 км навколо)», `note_uk`; `/api/analyze` with that `place_id` adds caveat `geocoder_circle` first). Malformed osm ids (not `osm:` + N/W/R + ≤ 16 digits) → 422 `invalid_place_id` without asking Nominatim. Unknown id → 404 `place_not_found`; geocoder queue longer than 2 s → 503 `geocoder_busy` (retry).

For `lang=en`, an optional, separately cached `lookup` with `accept-language=en,uk` and `polygon_geojson=0` adds only
the English labels; geometry/bbox/area and native fields still come exclusively from the Ukrainian lookup. English
circle names end in ` (≈1 km around)`; the native suffix remains ` (≈1 км навколо)`. Matching and fallback rules are
the same as for search, and a failure of this optional label request never turns a successful native lookup into an
error. Internal `places.get_place()` calls keep the default Ukrainian mode unless English is explicitly requested.

### `POST /api/analyze`
Body: `{geometry?: GeoJSON, place_id?: string, years?: [from, to], name?: string}` — `geometry` **or** `place_id` **(+)**. With `place_id` the zone name defaults to the place name.
Validation (422): `missing_geometry`, `invalid_geometry` (not Polygon/MultiPolygon, unparsable, not lon/lat; self-intersections are repaired), `too_many_vertices`, `outside_coverage`, `area_too_small` (< **0.5 km²**, same as the frontend), `area_too_large` (> 5000 km²), `bbox_too_large` (bounding box > 14 400 km², or a side > 150 km inside the Kyiv/Kharkiv/Lviv areas / > 72 km elsewhere — the same limits as science's `too_large` — e.g. two far-apart small squares, a long sliver; `details` has the bbox size), `invalid_years` (outside 2013–2025 or from > to), plus science errors (`bad_geometry`, `too_large`, …). All geometry messages are in Ukrainian; the limits are science's own (5000 km², 150 km per side inside the Kyiv/Kharkiv/Lviv areas, 72 km elsewhere), checked in the backend first.
Zones too small in *built-up* area are not errors: the report says `trend.verdict = "insufficient_data"` with a caveat.

Caching: `report_id = sha256(geometry_hash | years | data_version | method_version)[:16]`, where `geometry_hash` is computed on the normalised geometry (orientation and ~0.1 m noise do not matter). Stored reports are **name-free** (`zone.name`, `params.place_id` are `null` in the store): the response is labelled per request — `zone.name` = request `name` › place name › `null`, `params.place_id` only if the geometry is that place's, and the verdict sentence starts with that name (without a name it is a neutral sentence: «Забудова влітку вдень …»). So the same zone returns the stored report instantly and nobody can plant a name into somebody else's report; a new `data_version` gives a new id. Measured on the VM: districts 0.4–0.7 s on first computation, whole Kyiv ≈ 1.5 s, cached ≈ 5 ms server-side.

Report (live format; example values are illustrative and change with `data_version`):
```jsonc
{
  "report_id": "58a0715a439acc39",
  "zone": {"name": "Нижні Сади (Осокорки)", "area_km2": 9.0, "built_area_km2": 7.758,
           "analysed": "built",            // science: "built" (built-up pixels) | "all_land" (zone < 20 % built: parks, forests)
           "basis": "always_built",        // pixels behind the headline gap: "always_built" (built in every year of the
                                           //   period, ≥ 0.5 km²) | "built_each_year" (each year's own built-up) | "all_land"
           "analysed_area_km2": 7.459,     // area of those pixels (≤ area_km2)
           "clipped_km2": null,            // km² of the drawn zone outside Ukraine that was cut off (caveat zone_clipped)
           "war_region": null,             // {"name": "Херсонська область", "since": 2022, …} in occupied/front-line
                                           //   oblasts (caveat war_zone), else null
           "city": "kyiv"},                // science: preset city the zone belongs to (also suburbs ≤ 15 km outside it), or null
  "reference": {"city": "kyiv",            // city ID (not display name; map via meta.cities)
                "ring_km": [2.0, 15.0], "area_km2": 354.0, "forest_px": 98333,
                "kind": "preset",          // science: "preset" (Kyiv/Kharkiv/Lviv) | "derived" (urban area derived from built-up data)
                "urban_area_km2": 827.9,
                // (+) sci-v3.6: forest kept only within ±100 m of the zone's median built elevation (METHOD.md §4.1).
                // area_km2 / forest_px above are those of the forest actually used. null in older reports.
                "elevation_match": {"applied": true,          // the matched forest is used (status "matched")
                                    "status": "matched",      // matched | all_within (no-op) | fallback (< 200 px: whole
                                                              //   forest) | unavailable (no DEM: not evaluated)
                                    "tolerance_m": 100, "min_px": 200,
                                    "zone_elev_m": 118.0,     // median elevation of the zone's built basis, m
                                    "dz_before_m": 232.0,     // median forest − basis elevation, whole forest, m
                                    "dz_after_m": -6.0,       // the same for the forest used, m
                                    "px_kept": 24721, "px_total": 99060},
                // (+) sci-v3.6: ring forest outside Ukraine, dropped (the ring is clipped to the border); 0 = none
                "abroad_km2": 85.0},
  "series": [{"year": 2025, "zone_lst": 29.48, "ref_lst": 23.41, "gap": 6.07, "ndvi": 0.63, "ndbi": -0.213, "built_share": 0.983,
              "scenes": 5, "valid_share": 1.0, "method": "per_scene", "excluded": null}, …],
              // excluded year: gap/zone_lst/ref_lst null, method null, "excluded" = reason:
              //   "too_few_pixels" | "low_coverage" | "no_reference" | "too_few_scenes" |
              //   "no_lst_product" (USGS has no surface temperature there — emissivity gap, not clouds) — never show as data
  "gap_summary": {"mean": 5.03, "last": 6.07, "min": 3.74, "max": 6.07},
  "trend":      {"slope_per_decade": 1.8, "ci95": [1.5, 2.56], "p": 0.001, "n_years": 13, "verdict": "significant"},
  "ref_trend":  {… same keys …},          // reference forest LST, °C/decade
  "zone_trend": {… same keys …},          // the zone's own surface LST, °C/decade (zone line = reference + gap)
  "gap_driver": "zone",                   // what moved the gap: "zone" | "reference" | null (no clear change)
  "ndvi_trend": {… same keys …},          // NDVI units/decade
  "land_change": {"always_built": 7.459, "new_built": 0.058, "always_green": 0.108},   // km²
  "green_gap": {"mean": 5.01, "last": 6.01, "scope": "urban_parks", "trend": {…}},   // an OBJECT (or null), not a number;
              // zone built-up vs in-city green patches ≤ 5 km² (parks, not big forests); null for "all_land" zones
  "secondary": {"basis": "built_each_year",          // only when zone.basis = "always_built": the same gap on each year's
                "gap_summary": {…}, "trend": {…},    //   built-up (includes new construction) — «Варіант» in details
                "series": [{"year": 2013, "gap": 4.9}, …]},   // or null
  "new_built_gap": {"area_km2": 0.058,               // pixels that became built during the period (or null if too few)
                    "before": {"years": [2013, 2014], "gap": 1.2}, "after": {"years": [2024, 2025], "gap": 5.6},
                    "series": [{"year": 2013, "gap": 1.1, "method": "per_scene"}, …]},
  "caveats": [{"code": "lst_not_air", "text_uk": "…"}, …],
  "hotspots": [                           // (+) v2 (hotspots_version "hs4": searched in the zone as analysed, i.e. cut at Ukraine's border; outline clipped to it): up to 3 compact hot places, hottest first
    {"lon": 30.63603, "lat": 50.38996,    //   marker = the cluster's hottest smoothed pixel, inside the zone, ≥ 1 px from its edge
     "gap": 15.6,                         //   mean 3-summer gap over the cluster's pixels, °C
     "gap_peak_px": 20.7,                 //   hottest single 60 m pixel of THIS cluster, °C
     "delta_vs_zone": 4.4,                //   gap − zone_built_mean_gap (≥ 1.0 by construction)
     "zone_built_mean_gap": 11.2,         //   mean gap of the zone's built pixels, same summers, same raster
     "area_km2": 0.241,                   //   cluster area (≤ cap, see below)
     "land_class": {"class": "built", "label_uk": "забудова", "share": 1.0,
                    "source": "Esri/IO LULC (+ Landsat extrapolation)"},   // dominant class over the cluster and years
                                          //   (candidates are built pixels, so this is «built» unless classes are mixed; null without class maps)
     "years": [2023, 2024, 2025],         //   the summers averaged (last 3 with data)
     "scale": "local",                    //   "local" (zone ≤ 30 km²) | "district" (bigger zones and whole cities)
     "polygon": {"type": "Polygon", "coordinates": [...]}}, …],   // simplified cluster outline (WGS84), for an outline on the map
  //   Definition: per-pixel mean gap of the last 3 summers, smoothed (σ 120 m local / 300 m district, built pixels
  //   only); candidates = built pixels in the zone's top 10 % AND ≥ 1 °C above the zone's built mean; clusters =
  //   connected candidates, each capped around its peak at 0.25 km² and 10 % of the zone (local) or 1 km²
  //   (district/city); clusters < 3 px dropped; markers ≥ 500 m apart. [] = no place distinctly hotter than the zone;
  //   null = not computable (zone bigger than the window budget). Stored with the report; reports stored with an older
  //   hotspots_version are recomputed on the next request (all presets at deploy).
  "zone_outline": null,                   // (+) hs4 (24/28): the zone AS ANALYSED (WGS84, 5 decimals) when it was cut at Ukraine's
                                          //   border (same rule as science: > 1 % outside → zone.clipped_km2 > 0); null = nothing cut,
                                          //   draw params.geometry. When not null, draw this outline (and optionally params.geometry
                                          //   dashed/faint) — the numbers, hotspots and per-pixel stats refer to it. Example (Ужгород
                                          //   triangle ?area=22.25766,48.64753;22.22363,48.65641;22.25054,48.62557, ≈ 40 % in Ukraine):
                                          //   {"type": "Polygon", "coordinates": [[[22.25766, 48.64753], …]]}  (the triangle minus its Slovak tip)
                                          //   Stored with hotspots (same version gate); old reports get it on their next request.
  "context": {                            // (+) computed per response, never stored
    "rank": {"rank": 2, "of": 10, "percentile": 89, "city": "kyiv", "metric": "gap_mean",
             "compared_with": "districts", "is_district": true, "district_gap_range": [5.1, 9.4],
             "basis": "always_built",     // zone and every compared district on the same basis (built-up pixels only,
                                          // same city forest reference); districts on another basis are never mixed in
             "compared_to_uk": "порівняно із забудовою 9 районів Києва",   // ready-to-show label (n = other districts)
             "district_extremes": {           // hottest / coolest compared district (same basis; may be the zone itself)
               "hottest": {"id": "kyiv-dniprovskyi", "name": "Дніпровський район (Київ)", "short_name": "Дніпровський район", "gap": 9.4},
               "coolest": {"id": "kyiv-holosiivskyi", "name": "Голосіївський район (Київ)", "short_name": "Голосіївський район", "gap": 5.1}},
             "zone_analysed_km2": 2.891, "district_analysed_km2_range": [12.4, 319.1],
             "like_for_like": false,      // false when the zone's analysed built-up area < 25 % of the smallest district's
             "note_uk": "Зона невелика (2,9 км² забудови), а в районах — 12–319 км²: щільний квартал зазвичай гарячіший за середнє по цілому району."},  // null when like_for_like
             // mean gap vs the city's preset districts: rank 1 = hottest; `of` counts the zone itself; percentile =
             // share of the other districts that are cooler. null: no city (derived reference), a whole-city preset, an all-land zone, or the
             // district table is still being built (first request after a data/method change; retry later)
             // a geometry sent without place_id that equals a preset district (IoU ≥ 0.98) counts as that district
             // (is_district: true, excluded from the compared set) — share links / old clients
    "climate": {"scenario": "ssp245", "period": "2041-2060", "variable": "tasmax", "unit": "°C", "delta": …,
                "delta_range": [p10, p90], "baseline_period": [1995, 2014], "note_uk": "…повітря…",
                "source": "/api/climate?lat=50.4&lon=30.63"}   // nearest CMIP6 period (v2: 2041–2060; per response,
                                                               // not stored — old ids show the current climate data)
  },
  "verdict_text_uk": "…",
  "method": "per_scene",                  // science: "per_scene" | "composite" | "mixed"
  "years": [2013, 2025],                  // science: requested range
  "data_version": "l8c2l2-60m-2013-2025/sci-v3",
  "method_version": "sci-v3.2",           // science: bump with any change of report numbers/texts (part of report_id)
  "params": {"geometry": {…}, "geometry_hash": "736099a137b64598", "years": [2013, 2025], "place_id": "demo-nyzhni-sady",
             "data_version": "…", "method_version": "…", "api_version": "0.1.0"},     // (+) reproducibility
  "created_at": "2026-11-15T00:13:10Z", "compute_s": 0.372                             // (+)
}
```
Caveat codes (`caveats[].code`; `text_uk` is ready to show): `no_lst_product`, `zone_clipped`, `war_zone`, `geocoder_circle`, `basis_always_built`, `basis_built_each_year`, `suburb_reference` (zone outside the city but within its 15 km suburban belt — compared with the same city reference), `lst_not_air`, `composite_method`, `mixed_method`, `low_coverage`, `years_excluded`, `few_years`, `small_zone`, `all_land_zone`, `derived_reference`, `urban_area_is_zone`, `ring_widened`, `urban_area_clipped`, `few_reference_px`, `classes_extrapolated`, `not_significant_physics`, `reference_warming`, `ref_higher`, `ref_weak`, (+) sci-v3.6: `ref_elev_matched` («Ліс-еталон підібрано на тій самій висоті (±100 м), що й забудова: …» — shown when `reference.elevation_match.applied` and ≥ 5 % of the ring forest is dropped or |dz_before_m − dz_after_m| ≥ 20 m), `ref_match_fallback` (after `ref_higher` when too little forest lies at the built-up elevation). `ref_border_clipped` (≥ 10 % of the ring forest lay outside Ukraine and was left out). sci-v3.6 rewords `few_reference_px` («Навколо ділянки збереглося мало лісу ({km2} км²), показник розриву може бути неточним.»). Unknown codes may appear — show `text_uk`.

`verdict` (for `trend`, `ref_trend`, `ndvi_trend`, `green_gap.trend`, `secondary.trend`) follows the rule: `insufficient_data` if `n_years < 8` (or no p), else `significant` iff `p < 0.05`, else `not_significant`; the backend enforces it for the three top-level trends.

### `GET /api/reports` **(+)** and `GET /api/reports/{id}`
List (most recent first, summaries: `report_id, name, place_id, created_at, years, area_km2, gap_last, gap_mean, slope_per_decade, p, verdict, data_version`) and the stored report (same body as `/api/analyze`). Bad id → 422 `invalid_report_id`; unknown → 404 `report_not_found`. Since reports are name-free, `name`/`place_id` in the list are `null` and `GET /api/reports/{id}` returns the neutral wording; pass `?name=` to label that response.

### `GET /api/scenes?report_id=|place_id=|geometry=<urlencoded GeoJSON>&year=&summer_only=true`
Summer (Jun–Aug) Landsat 8 acquisitions over the zone. `year` optional (all years if omitted). For preset cities the science package returns per-scene zone/reference LST:
```json
{"aoi": "kyiv", "year": 2021, "summer_only": true, "source": "science", "count": 15,
 "scenes": [{"year": 2021, "id": "LC08_L2SP_181025_20210609_02_T1", "ids": ["LC08_L2SP_181025_20210609_02_T1"], "date": "2021-06-09",
             "path": 181, "row": 25, "rows": [25], "cloud": 12.5, "used": true, "reason": null,
             "zone_lst": 35.85, "ref_lst": 26.53, "gap": 9.32, "zone_valid_share": 1.0, "ref_valid_px": 74588,
             "datetime": "2021-06-09T08:48:59.488681Z", "cloud_cover_land": 12.5, "sun_elevation": 59.68, "covers_zone_fully": true}],
 "note": "Landsat 8 overpass ≈10:45–11:00 local mean solar time; dates are UTC acquisition dates. used = the date entered the per-scene gap median."}
```
Elsewhere (no per-scene files) `zone_lst/ref_lst/gap` are `null` and `reason: "no_per_scene_data"`.

### `GET /api/scenes/{scene_id}?report_id=|place_id=|geometry=` **(+)**
One acquisition over a zone (the science row for that date + STAC metadata). Used by the analyst tool `get_scene_stats`.

### `GET /api/climate?lat=&lon=` (live format)
CMIP6 (NASA NEX-GDDP-CMIP6, 12 models since `climate_version: "cmip6-v2"`) summer **air** temperature (tasmax) at the nearest 0.25° cell, from the science package (METHOD.md §0.2). Scenarios are top-level keys, periods are `"YYYY-YYYY"` keys (not a `projections` array):
```json
{"lat": 50.45, "lon": 30.52, "cell": [50.375, 30.625], "variable": "tasmax", "unit": "°C",
 "label_uk": "Прогноз кліматичних моделей CMIP6 (NASA NEX-GDDP): середня денна максимальна температура ПОВІТРЯ влітку …",
 "models": ["…12 model names…"], "climate_version": "cmip6-v2", "statistic": "median_p10_p90",
 "baseline": {"period": [1995, 2014], "jja_mean": …, "hot30_days": …},
 "ssp245": {"2041-2060": {"delta": …, "delta_range": [p10, p90], "delta_stat": "median_p10_p90", "jja_mean": …, "hot30_days": …, "n_models": 12},
            "2081-2100": {…}},
 "ssp585": {"2041-2060": {…}, "2081-2100": {…}},
 "caveats": [{"code": "air_not_surface", "text_uk": "Це прогноз температури повітря, а не температури поверхні з Landsat."}],
 "source_impl": "science"}
```
`delta` = median over 12 models of the change of the summer mean daily maximum vs 1995–2014; `delta_range` = [P10, P90] over models; `hot30_days` = days with tasmax > 30 °C (May–Sep); 20-year windows 2041–2060 and 2081–2100. (Before CMIP6 v2: 5 models, mean and [min, max], 2041–2050/2071–2080 vs 2005–2014.) (Only if the science package is missing does a backend fallback answer, with a different shape: `baseline.jja_tasmax`, `scenarios.{ssp}.{mid|late}`.)

### Drift vs contract v1 (what the frontend must adapt — see `frontend/src/api/adapt.ts`)
| endpoint | contract v1 / assumed | live |
|---|---|---|
| meta.layers | array of layers | object: `tile_url`, zooms, `ids`, `scales{id: {stops: {light, dark}}}` |
| colour stops | `[value, color]` pairs | `{value, color}` objects, per theme |
| places | array of hits | `{query, presets[], geocoder[], attribution}`; no `center` on presets (use bbox) |
| report.green_gap | number | object `{mean, last, scope, trend}` or null |
| report.reference.city | display name | city id (`kyiv`) |
| report extras | — | `method`, `years`, `data_version`, `zone.analysed`, `zone.city`, `reference.kind`, `reference.urban_area_km2`, `params`, `created_at`, `compute_s` |
| climate | — | scenario → period → `{delta, delta_range, jja_mean, hot30_days, n_models}` |

### `GET /api/weather?date=YYYY-MM-DD&lat=&lon=`
Open-Meteo historical archive (ERA5/ERA5-Land, CC BY 4.0) proxy, cached on disk (forever for dates > 60 days old). Returns the day, the 3 preceding days (rain before the scene matters), and hourly values at 10–12 h Kyiv time (around the Landsat overpass).
```json
{"date": "2021-07-10", "lat": 50.41, "lon": 30.63, "grid_lat": 50.439, "grid_lon": 30.635,
 "day": {"date": "2021-07-10", "temperature_2m_max": 31.1, "temperature_2m_min": 17.4, "precipitation_sum": 0.0, "wind_speed_10m_max": 13.5, …},
 "previous_days": [{"date": "2021-07-07", …}, …], "overpass_hours_local": [{"time": "2021-07-10T10:00", "temperature_2m": …}, …],
 "units": {…}, "timezone": "Europe/Kyiv", "source": "Open-Meteo …", "note": "Air temperature from reanalysis, not LST."}
```
Errors: `invalid_date` (not ISO, before 1950, or within the last 5 days), `outside_coverage` (422, point outside the Ukraine bbox 21.8–40.5 E, 43.9–52.6 N).
Every success has `"available": true`. **Weather not available** (since v2.22, was 502 `weather_unavailable`): when the
point/date is not in the local archive and the live API answers 429 (daily quota, shared with the homelab's jobs),
5xx, times out or is unreachable → **200**
`{"available": false, "reason": "quota" | "upstream", "text_uk": "Погода зараз недоступна: …", "text_en": "Weather is unavailable right now: …", "date", "lat", "lon"}`.
A 429 is remembered for 10 min per worker (no live request then; the local archive still answers). The analyst's
`get_weather` tool adds `agent_note` (continue without weather, ≤ 1 short sentence, no retry).

**Local archive first (item 34).** The team's Open-Meteo download (30 cities: the oblast centres incl. Kyiv, Sevastopol and
Simferopol, plus Kryvyi Rih, Kremenchuk, Bila Tserkva, Mariupol; May–Sep 2013–2025, some cities from 2003; same variables, Europe/Kyiv) is on the VM in
`{data_dir}/weather/openmeteo/<city>/<year>.json[.gz]` (read-only input, ≈ 22 MB gzipped) with the city points in
`cities.json` beside it — no city or year list in code; new files are used on the next request (copied by hand,
DEPLOY.md «Weather archive»). Order: local file → live API (disk-cached) → «not available». If the point is ≤ 25 km from one
of those city points and the date is in that file, the answer comes from the file (no live request; `previous_days`
may be shorter at the start of a season, e.g. 1 May). Same shape, plus:
`"source": "open-meteo-archive-local (ERA5)"`, `"attribution": "Open-Meteo Historical Weather API (ERA5 / ERA5-Land
reanalysis), https://open-meteo.com — CC BY 4.0"`, `"city": "kyiv"`, `"city_distance_km": 4.2`; `grid_lat/lon` are the
city point's ERA5 cell. Otherwise the live API as above (`source` unchanged, no `city`). The analyst's `get_weather` tool uses the same service.

### Tiles: `GET /tiles/{layer}/{year}/{z}/{x}/{y}.png?theme=light|dark[&base=2013][&v=<data_version>]`
XYZ WebMercator, 256 px, RGBA PNG, **no-data fully transparent**. `Cache-Control`: with `v` equal to the current `/api/meta → layers.tiles_version` → `public, max-age=31536000, immutable`; with another `v` → `max-age=60`; without `v` → `max-age=3600`. Zoom 3–16 (native ≈ z11; above it pixels are upscaled nearest-neighbour, below it a cached ×4/×16/×64 mean pyramid is used). Tiles outside the coverage return a shared empty PNG.

| layer | value | domain (clamped) | palette |
|---|---|---|---|
| `gap` | zone LST − reference forest LST, °C | −6 … +16, neutral 0 | F7: sage (cooler than forest) → off-white (0) → orange → magenta → plum (light); dark: orange → coral → magenta → pale pink, brightness rising with heat |
| `lst` | summer median daytime surface temperature, °C | 15 … 50 | same ramp, sequential |
| `ndvi` | summer median NDVI | 0 … 0.9 | off-white → sage → deep green |
| `dndvi` | NDVI(year) − NDVI(`base`, default 2013) | −0.3 … +0.3, neutral 0 | loss = orange/magenta, gain = green |

Exact stops for both themes are in `/api/meta → layers.scales` (gap stops are copied from the F7 generator `map.py`). The forest reference outline colour is `layers.reference_color` (ultramarine; not used in the rasters). The `gap` reference is the city reference near Kyiv/Kharkiv/Lviv and a smooth regional stable-forest field elsewhere (METHOD.md). **Tile values are not the report numbers**: tiles are a per-pixel *composite* (summer median LST − composite reference), reports use the median of *per-scene* gaps, so a district's mean tile gap can differ from its report gap by ~1–2 °C (REVIEW H2); show report numbers from `/api/analyze`, use tiles for the spatial pattern. Errors: 422 `invalid_layer|invalid_year|invalid_tile|invalid_theme`; 503 `science_not_ready` for `gap` if the science package is missing.
Typical latency on the VM: cached ~2 ms, fresh z12–z13 tile 25–60 ms; z5–z9 for all layers/years/themes are pre-rendered by `python -m uhd.tiles.warm`.

Browser caching: always append `&v=<layers.tiles_version>` from `/api/meta` (= `data_version` + science tile method + palette hash): it changes whenever tile pixels can change (data, method or colours), so tiles can be cached forever. `&v=<data_version>` still works but is cached for 60 s only. Server-side caches are keyed by `tiles_version` too.

MapLibre source example:
```js
map.addSource('gap', {type: 'raster', tileSize: 256, minzoom: 3, maxzoom: 16,
  tiles: [`/tiles/gap/${year}/{z}/{x}/{y}.png?theme=${theme}&v=${meta.layers.tiles_version}`]});
```

## AI analyst (decision #19)

### `GET /api/agent/tools`
`{configured, model: "claude-opus-5-5", team, public_enabled, effort, sandbox_enabled, server_tools, budget: {daily_usd, exhausted}, tools: [{name, description, input_schema, public, rest, enabled}]}` — `server_tools` lists the web tools only for the team tier (public: `[]`). With a valid `X-UHD-Team-Token` → `team: true` (the frontend uses this to check the key typed into «Командний режим»).
Tools (each calls the same service function as the REST endpoint in `rest`; the loop refuses — `tool_not_allowed` — any tool outside the caller's set, whatever the model asks for): `search_places`, `list_reports` (team), `get_report`, `list_scenes`, `get_scene_stats`, `zone_timeseries`, `land_change`, `rank_zones`, `climate_projection`, `get_weather`, `get_overview` (precomputed rankings), `create_report` (`place_id`, or `report_id` to re-run a report), `set_map_view`, `run_analysis` (team only, and only with `UHD_AGENT_SANDBOX_ENABLED=1`). All read-only except `create_report` / `rank_zones` (store reports).
Public tier limits per question: `create_report` ≤ 3, `get_scene_stats` ≤ 4, `rank_zones` ≤ 2 calls × ≤ 6 zones; new analyses only for preset places / city shortcuts or the user's current report (`context.report_id`), no custom geometry → tool error `presets_only` / `tool_limit` (returned to the model, not to the client).

### `POST /api/agent/chat`
Body: `{messages: [{role: "user"|"assistant", content: string}], context?: {report_id?, place_id?, layer?, year?, lang?: "en"|"uk"}}` (stateless: send the visible history; the server rebuilds a context card from `report_id` every request and the analyst answers in `lang`, default `uk`). Header `X-UHD-Team-Token` unlocks the team tier: full tool set, web search/fetch on allow-listed domains, effort `high`, no IP limit, own budget.
Before streaming:
- no `ANTHROPIC_API_KEY` → **503 `agent_not_configured`** (frontend: offline card; the card's `verdict_text_uk` keeps the story);
- `UHD_AGENT_PUBLIC_ENABLED=0` and no team token → **503 `agent_team_only`**;
- daily budget of the tier used up (UTC day; public $10, team $20 by default; spend in `cache_dir/agent_spend.json`) → **503 `agent_budget_exhausted`** with `Retry-After` until 00:00 UTC — the rest of the app works;
- public: > 30 requests/hour or > 8/minute per IP → **429 `rate_limited`** / **`rate_limited_burst`** (IP = socket peer, or `CF-Connecting-IP` / `X-Forwarded-For` when the peer is in `UHD_AGENT_TRUSTED_PROXIES`).
With a key → `text/event-stream`; events (`event:` = `data.type`):

| type | data |
|---|---|
| `text` | `{delta}` — answer text as it streams (a draft until `done`) |
| `thinking` | `{delta}` — summarised reasoning (UI: collapsed «Як міркував аналітик») |
| `tool_call` | `{id, name, input}` — show as an agent step |
| `tool_result` | `{id, name, is_error, result}` |
| `web` | `{name: "web_search"|"web_fetch"}` (team tier) |
| `map_view` | `{layer, year, place_ids, report_ids, bbox}` — apply to the map |
| `validation` | `{repairing: true, ok, n_checked, unsourced: [{text, value, kind}], caveats: [{code, message}]}` — unsourced numbers and/or missing required caveats; the model rewrites once |
| `text_reset` | discard the streamed text so far (a corrected answer follows) |
| `done` | `{answer, validation: {ok, n_checked, unsourced}, caveats: [...still missing], usage, cost_usd, tier, request_id}` |
| `error` | `{error, message}` — `rate_limited`, `upstream_error`, `upstream_overloaded`, `upstream_unreachable`, `refused`, `too_many_steps`, `too_expensive` (per-request cap $0.50 public / $2 team), `max_tokens`, `invalid_tool_json`. `message` is English for logs; the UI shows its own Ukrainian text per code |

Caveat checker (`uhd/agent/caveats.py`, rule-based, same single repair as the validator): LST/gap numbers need «поверхн…» and must not be called air; a `not_significant` trend needs «статистично незначуще» / «помітно не змінився» and no «значущий» claim; `insufficient_data` needs «недостатньо даних»; `occupied` / `war_zone` must be mentioned; an excluded year must not get a number; CMIP6 numbers need «повітря»; no causal percentages; `gap_driver = reference` names the forest reference; no significance claim on `new_built_gap`. Web results are a separate source class: their numbers count only under «Гіпотези з інтернету» in a paragraph with the https link.
Logging: `cache_dir/agent_log/<UTC-date>.jsonl` (14 days): tier, model, prompt version, tools, usage, cost, validation/caveats, error; question/answer text only for the team tier, public = SHA-256 prefix + length; no IPs.

Number validator (`uhd/agent/validator.py`): every number in the answer must equal, at its written precision, a number of a **compatible field** in the tool results (or the user's question / a short allow-list): `°C` → temperature fields (lst, gap, slope, delta, …), `%` → `*_share` fields ×100 (or raw cloud/humidity %), `км²` → area fields, «розрив» in the clause → gap fields only, `p = …` → `p` fields only. Sign must match unless the clause says lower/cooler/decreasing. Dates must appear in tool results; years must appear as some value; small counts ≤ 12 without a unit, list markers, ids and URLs are ignored. Semantic ties (SCI-04): a trend number must agree with the clause's direction («зменшився на 0,4» ≠ +0,4); `ci95` bounds count only next to «інтервал/довірчий/від … до»; the parks gap (`green_gap`) only with «парк/сквер/зелень» (and then the forest gap does not count); `p` must be the p of the trend the clause names (NDVI / еталон / розрив).

## Changelog
- sci-v3.6 (2026-11-15, METHOD_VERSION only; no API shape break): reference ring clipped to Ukraine (`reference.abroad_km2`
  (+), caveat `ref_border_clipped` (+); gap tiles: new `tiles_version` via the rebuilt reference field), `few_reference_px`
  reworded, `reference.elevation_match` (+), caveats `ref_elev_matched` / `ref_match_fallback` (+, with `text_en`), reference outline follows the match (`properties.elevation_matched`). New
  report ids (the id includes METHOD_VERSION); stored sci-v3.5.4 and older reports are served unchanged.
- v2.19 (2026-11-15, AI analyst P0/P1): per-tier parameters, daily/per-request spend caps (`agent_budget_exhausted`, `too_expensive`), `agent_team_only`, burst limit + trusted proxies, caveat checker + combined repair, web tools team-only with domain allow-list, web numbers not accepted as data, context card as a mid-conversation system message, `context.lang`, new tool `get_overview`, `create_report.report_id`, request log; `/api/agent/tools` gains `public_enabled`, `effort`, `budget`.
- v2.22 (2026-11-15): `/api/weather` never 502s: upstream 429 / 5xx / timeout → 200 `{available: false, reason, text_uk,
  text_en}` (429 remembered 10 min); successes carry `available: true`; archive cities from `cities.json`.
- v2.21 (2026-11-15): `/api/weather` answers from the local Open-Meteo archive copy (item 34) — `source`
  `"open-meteo-archive-local (ERA5)"`, `attribution`, `city`, `city_distance_km`; live API otherwise.
- v2.20 (2026-11-15): CMIP6 v2 (`climate_version: "cmip6-v2"`): 12-model median with P10–P90, 2041–2060/2081–2100 vs
  1995–2014; report `context.climate.note_uk` updated; the backend fallback no longer sends `short_baseline`.
- v2.19 (2026-11-15): `export?lang=en` (item 32 piece 3) — English csv/xlsx/json/pdf; science's `localize_report` gets
  `name_en` (KMU 2010) for named verdicts.
- v2.18 (2026-11-15): `?lang=en` (item 32) — `*_en` siblings on read; default unchanged.
- v2.17 (2026-11-15): PDF hotspot heading carries the seasons («Гарячі точки (2023–2025)») + one-line definition (CSV/XLSX have no hotspot section).
- v2.16 (2026-11-15): `/api/overlays.no_scenes` (per-year swaths without enough clear scenes, science c4f077c).
- v2.15 (2026-11-15): PDF map gets a scale bar (round length, Web-Mercator m/px at the zone's latitude) and a north arrow; hotspots as a table (№ | розрив з лісом | понад забудову зони | площа | тип | координати | літні сезони).
- v2.14 (2026-11-15): export links / QR use the public origin (`X-Forwarded-Host`/`-Proto` when valid, else the request host, else `UHD_PUBLIC_BASE_URL`; `Vary` set); PDF/CSV/XLSX template labels follow TERMS-UK («Літні сезони», «N літніх сезонів із даними», «Суттєво / Поки несуттєво» + «статистично (не)значущо»); long `?area=` links wrap at «;»/«,».
- v2.13 (2026-11-15): export `format=pdf` (fpdf2 + Onest, OFL).
- v2.12 (2026-11-15): `GET /api/reports/{id}/export?format=csv|xlsx|json` (item 29).
- v2.11 (2026-11-15): NDVI palette (item 29): grey-beige up to 0.3, green from 0.4, forest green at 0.8+ (light 0.3 #DED6C0, 0.4 #CCD4B0, 0.6 #96BA88, 0.8 #34704C, 0.9 #1C4C38; dark 0.3 #46423C, 0.4 #405442, 0.6 #467858, 0.8 #78BA80, 0.9 #A8D8A6) → new `tiles_version` (all layers re-render; pyramids unchanged). ΔNDVI unchanged.
- v2.10 (2026-11-15): hotspots `hs4` — searched in the zone cut at Ukraine's border (24/28: no hotspot abroad); new stored `zone_outline` (null = not cut). Report numbers unchanged (science already clipped), no METHOD_VERSION bump.
- v2.9 (2026-11-15): `layers.overlays.nonbuilt.applies_to = ["gap"]` (item 30: «Температура» shows the whole surface).
- v2.8 (2026-11-15): `/api/overview` places add `lst_mean` (°C, the zone's own summer surface temperature, mean over the years with a gap) and `lst_last {year, value}` (item 21 H: «сама поверхня ≈ 36 °C»); null when there is no LST.
- v2.7 (2026-11-15): `GET /api/reports/{id}/reference` (item 20 D).
- v2.6 (2026-11-15): `/api/meta → layers.internal = ["gap_fill", "nonbuilt"]` and `internal: true` on `layers.fill` / `layers.overlays.nonbuilt` (item 17: helpers, never a layer choice or a visible name); `/api/health` adds `method_version` and `build` (the deployed commit of that worker).
- v2.5 (2026-11-15): `/api/overlays.occupied` (official occupied list, PM 4b); report caveat `occupied` + `zone.occupied` (sci-v3.5); `/api/overview` places carry `occupied`.
- v2.4 (2026-11-15): «Лише забудова» overlay (item 13) `/tiles/nonbuilt/{year}/{z}/{x}/{y}.png?theme=` — the map's ground colour (dark #1C2438, light #F6F6F3) at alpha (1 − built share), 16 levels (baked at full strength; the frontend's slider «Приглушити не-забудову» 0–100 %, default 70 %, is the layer's raster-opacity); built = science `classes.tif` class 1 of that year (the analysis definition incl. the 2013–2016 / 2024–2025 extrapolation); field, nature, water, other are faded, class 0 (sea / no class) is transparent; at z ≤ 10 proportional to the built share of the cell (uint8 pyramid ×4/×16/×64, ≈ 22 MB per year). Draw it ON TOP of `gap` and `lst`; same clip / sea cut / `tiles_version` (now also hashes `classes.tif`). `/api/meta → layers.overlays.nonbuilt = {url, label_uk, alpha: 1.0, default_strength: 0.7, levels, applies_to: ["gap", "lst"], colors, rule_uk, warm_zooms}` (null without classes.tif). Warmed: country z9–10, cities z10–13; z11+ elsewhere on demand.
- v2.3 (2026-11-15): display-only fill layer `/tiles/gap_fill/{year}/{z}/{x}/{y}.png` (`lst_fill` exists in science but is not served for now — disk budget; `layers.fill.lst` = null) (science gapfill.py: year-specific LST holes filled with the median of the nearest valid summers Y±1/Y±2; persistent ASTER-GED holes stay empty under the no_lst hatch). Same palette as `gap`/`lst`, same clip/sea cut/`tiles_version` (`+fill1`); only the filled pixels are drawn — the frontend draws them at lower opacity under the label `layers.fill.label_uk` («заповнено з сусідніх років»). `/api/meta → layers.fill = {gap, lst, label_uk}` (null without the science fill), `layers.ids` lists them. No analysis/report number reads them. Gap pyramids are keyed by `reffield.npz` identity (`gap@<tag>`), so a rebuilt reference field also refreshes the low zooms; stale dirs are evicted.
- v2.2 (2026-11-15): tiles (all layers) clipped to the Ukraine outline (`/srv/landsat/aoi/Ukraine.geojson`, Crimea included, incl. the 12-nm territorial sea) + 1.5 km; tiles fully outside = the shared empty PNG (not cached); `tiles_version` gets `+ua1500`; open-sea pixels (science `{data_dir}/ukraine/sea_mask.tif`, lagoons joined to the sea included, lakes/reservoirs not) are transparent in every layer when the mask exists (`+sea1`); `+i<hash>` = size/mtime of science's `reffield.npz` and `sea_mask.tif`, so a rebuilt input gives new tile URLs even without a DATA/METHOD version bump.
- v2.1 (2026-11-15): `GET /api/overview`, `GET /api/overlays`; dark gap palette near 0 lifted (−2 #34465A, 0 #424A60, +1 #5A4A50, +2 #6A4E48; opaque) → new `tiles_version`.
- v2.0 (2026-11-15): hotspots v2 (compact clusters, marker at the peak inside the zone, per-cluster `gap_peak_px`, `delta_vs_zone`, `zone_built_mean_gap`, `land_class`, `scale`, `polygon`); `/api/scenes` `cloud_cover_land` of merged rows weighted by zone overlap (like science's `cloud`, sci-v3.4).
- v1.9 (2026-11-15): `context.rank.basis / compared_to_uk / like_for_like / note_uk / zone_analysed_km2 / district_analysed_km2_range`; major-city shortcuts (`osm:R…`, kind `city`, `source: osm`) in `/api/places`; half-up rounding for backend-computed numbers; RB-15 fixed geometry message; hotspots precomputed for all presets at deploy; a geometry equal to a district (IoU ≥ 0.98) ranks as that district (R4-2); `context.rank.district_extremes`.
- v1.8 (2026-11-15): `hotspots` (stored) and `context.rank` / `context.climate` (per response) in `/api/analyze` and `GET /api/reports/{id}`; the parks gap stays at `green_gap` (scope `urban_parks`).
- v1.7 (2026-11-15, science sci-v3.3): `zone_trend`, `gap_driver`, `zone.clipped_km2`, `zone.war_region`, excluded reason `no_lst_product`, caveats `no_lst_product`/`zone_clipped`/`war_zone`; limits = science's (5000 km², 150/72 km, 14 400 km² bbox) with Ukrainian messages, listed in `/api/meta → limits`; the number validator knows `zone_trend` and `new_built_gap` numbers.
- v1.6 (2026-11-15, robustness): request bodies > 2 MB → 413 `payload_too_large`; `X-Request-Id` echoed only if `[A-Za-z0-9._-]{1,64}`; security headers + CSP (self + OpenFreeMap); `GET /api/reports` (list) needs `X-UHD-Team-Token` → otherwise 403 `team_only` (single reports stay public by id); cold analyses limited per worker → 503 `busy` after 30 s queueing; `GET /api/health?deep=1` (data, cache/report writability, disk free; 503 when not ok); tiles are 128-colour palette PNGs (index 0 transparent, ~5× smaller); coordinates must be numbers and a hole equal to its outline → 422; agent `context` ≤ 4 KB, agent rate limit shared by all workers.
- v1.5 (2026-11-15): gap scale −6…+16 with new dark stops; `layers.tiles_version` for `&v=`; size limits as in science (72 km outside the cities); Ukrainian geometry error messages; `zone_timeseries` always returns `excluded`; `get_report` tool = `GET /api/reports/{id}` wording; merged scenes average `cloud_cover_land` like `cloud`; semantic number validator.
- v1.4 (2026-11-15): `geocoder_circle` for point-like geocoder results (no more `area_too_small` for squares/buildings), `invalid_place_id`, deep nesting → 422, NUL/junk SPA paths → 404.
- v1.3 (2026-11-15, science sci-v3.2): `zone.basis`, `zone.analysed_area_km2`, `series[].excluded`, `secondary`, `new_built_gap`, top-level `method_version`, `green_gap.scope = "urban_parks"`, caveats `basis_*` and `suburb_reference`.
- v1.2 (2026-11-15): `bbox_too_large`; reports stored name-free and labelled per response; `geocoder_status` + cross-worker geocoder limit (`geocoder_busy`); weather limited to Ukraine (`outside_coverage`); tile `&v=` controls caching; unit/field-aware number validator; sandbox runs in a fresh network namespace as `nobody` (`RLIMIT_NPROC`, process-group kill).
- v1.1 (2026-11-15): one ASCII id per place (`aliases` for science ids), science demo presets (`case`, `note_uk`), Kharkiv OSM districts/localities, `min_area_km2` 0.5, cached reports relabelled per request; live formats documented (drift table).
- v1.0 (2026-11-15): initial implementation of contract v1. Additions: `place_id` in analyze, `GET /api/reports`, `GET /api/scenes/{id}`, `params`/`created_at`/`compute_s` in reports, `theme`/`base` on tiles, `search_places` tool.
