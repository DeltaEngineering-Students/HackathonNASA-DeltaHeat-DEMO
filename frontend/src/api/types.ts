// Types for API contract v1 (uhd/docs/PLAN.md). Backend owns the contract;
// fields marked "frontend assumption" are not fixed in v1 and are listed in uhd/docs/QUESTIONS.md.
import type { Feature, FeatureCollection, MultiPolygon, Polygon } from 'geojson';

export type ZoneGeometry = Polygon | MultiPolygon;
export type Verdict = 'significant' | 'not_significant' | 'insufficient_data';

export interface Health {
  ok: boolean;
  data_version: string;
}

/** [value, '#rrggbb'] */
export type ColorStop = [number, string];

export interface LayerMeta {
  id: 'gap' | 'lst' | 'ndvi' | 'dndvi' | string;
  name_uk: string;
  units: string;
  /** diverging | sequential */
  kind?: string;
  /** frontend assumption: stops for the light theme; `stops_dark` optional. */
  stops: ColorStop[];
  stops_dark?: ColorStop[];
  /** long title from the backend, e.g. «Різниця з лісом навколо міста (LST зони − LST еталону)» */
  title_uk?: string;
  /** frontend assumption: short legend ends, e.g. «прохолодніше» / «гарячіше». */
  legend_lo_uk?: string;
  legend_hi_uk?: string;
}

export interface CityMeta {
  id: string;
  name: string;
  /** [west, south, east, north] WGS84 */
  bbox: [number, number, number, number];
}

export interface PresetMeta {
  id: string;
  name_en?: string;
  /** 'city' | 'district' | 'demo_zone' | 'locality' */
  kind: string;
  name: string;
  city?: string;
  bbox?: [number, number, number, number];
  area_km2?: number;
  /** demo presets: story type ('control' | 'greening' | 'densifying' | 'hot_stable') and a one-line note */
  case?: string;
  note_uk?: string;
}

export interface Meta {
  data_version?: string;
  years: number[];
  cities: CityMeta[];
  layers: LayerMeta[];
  presets: PresetMeta[];
  /** live backend: tile URL template with {layer},{year},{theme},{z},{x},{y} */
  tiles?: { url?: string; minzoom?: number; maxzoom?: number; tileSize?: number; version?: string };
  /** display-only fill tiles (item 9, API v2.3): layer id per main layer + the legend note; null without science fill */
  fill?: { gap?: string; lst?: string; label_uk?: string } | null;
  /** item 13 (API v2.4): «Лише забудова» overlay drawn over gap/lst; null without the backend's classes */
  nonbuilt?: { url?: string; label_uk?: string; default_strength?: number; applies_to?: string[] } | null;
  limits?: { min_area_km2: number; max_area_km2: number; max_vertices?: number };
  agent_configured?: boolean;
}

export interface PlaceHit {
  id: string;
  name: string;
  /** 'preset' | 'district' | 'city' | 'geocoder' … */
  kind: string;
  /** geocoder only: city, town, village, building … */
  osm_type?: string;
  city?: string;
  /** frontend assumption: secondary line, e.g. «Київ» or Nominatim display name */
  subtitle?: string;
  /** frontend assumption: optional point for fly-to before geometry arrives */
  center?: [number, number];
  note_uk?: string;
  /** item 32: English siblings (`/api/places?lang=en`), absent on fixtures and older backends */
  name_en?: string;
  subtitle_en?: string;
  note_en?: string;
}

export interface Place {
  id: string;
  name: string;
  name_en?: string;
  display_name_en?: string;
  kind: string;
  display_name?: string;
  geometry: ZoneGeometry;
}

export interface SeriesPoint {
  year: number;
  zone_lst: number | null;
  ref_lst: number | null;
  gap: number | null;
  ndvi: number | null;
  ndbi: number | null;
  built_share: number | null;
  scenes: number;
  valid_share: number;
  /** null for excluded years (sci-v3.2) */
  method: 'per_scene' | 'composite' | null;
  /** sci-v3.2: null, or why the year is left out (too_few_pixels | low_coverage | no_reference | too_few_scenes) */
  excluded?: string | null;
  /** sci-v3.4: why a too_few_scenes year was dropped, with a ready sentence (`text_uk`) */
  excluded_detail?: { text_uk?: string; usable_dates?: string[] | null; n_passes_total?: number; n_outside_swath?: number; n_cloudy?: number | null; n_reference_cloudy?: number | null } | null;
}

export interface Trend {
  slope_per_decade: number | null;
  ci95: [number, number] | null;
  p: number | null;
  n_years: number;
  verdict: Verdict;
}

export interface Hotspot {
  center: [number, number]; gap: number; area_km2?: number; years?: number[];
  /** pending backend redesign: gap above the zone mean, the hot area's outline, a land-cover label */
  delta_vs_zone?: number; polygon?: import('geojson').Polygon | import('geojson').MultiPolygon; type_uk?: string;
}

export interface Caveat {
  code: string;
  text_uk: string;
}

export interface Report {
  report_id: string;
  /** API v2.9 (MAP-TASKS 24): the zone clipped to Ukraine, WGS84; null when nothing was clipped */
  zone_outline?: ZoneGeometry | null;
  zone: {
    name?: string; area_km2: number; built_area_km2: number; city?: string;
    /** built | all_land */
    analysed?: string;
    /** always_built | built_each_year | all_land */
    basis?: string;
    analysed_area_km2?: number;
    /** sci-v3.3: part of the drawn area outside the data, km² */
    clipped_km2?: number | null;
    war_region?: boolean | string | null;
  };
  reference: {
    city: string; ring_km: [number, number] | number; area_km2: number; forest_px: number;
    /** frontend: «ліс навколо Києва» / «ліс навколо міста» (derived: said in Details) */
    forest_uk?: string;
    kind?: string;
  };
  series: SeriesPoint[];
  gap_summary: { mean: number | null; last: number | null; min: number | null; max: number | null };
  trend: Trend;
  ref_trend?: Trend;
  /** own LST trend of the zone (science, planned; accepted as `zone_trend` or `zone_lst_trend`) */
  zone_trend?: Trend | null;
  /** sci-v3.3: what mainly drives the gap trend */
  gap_driver?: 'zone' | 'reference' | null;
  /** hottest spots inside the zone (backend field, pending): centre + mean gap there */
  hotspots?: Hotspot[];
  /** per-request context from the backend (API v1.8), never stored */
  context?: ReportContext;
  ndvi_trend?: Trend;
  land_change?: { always_built: number; new_built: number; always_green: number };
  green_gap?: number | null;
  /** urban_parks (sci-v3.2) | urban_area */
  green_scope?: string;
  /** the same gap on the other pixel basis («забудова кожного року») */
  secondary?: { basis: string; gap_summary: { mean: number | null }; trend: Trend } | null;
  /** gap on pixels built during the period: before (first 2 years) vs after (last 2) */
  new_built_gap?: { area_km2: number; before: { years: number[]; gap: number | null }; after: { years: number[]; gap: number | null }; series?: { year: number; gap: number | null }[] } | null;
  caveats: Caveat[];
  verdict_text_uk: string;
}

export interface AnalyzeRequest {
  /** always kept for fixtures / map; sent only when there is no place_id */
  geometry: ZoneGeometry;
  /** presets and city places: the backend knows the place (district rank excludes itself, R4-2) */
  place_id?: string;
  years?: [number, number];
}

/** Send `place_id` for presets and cities; geometry only for drawn areas and geocoder addresses (QA R4-2). */
export const sendsPlaceId = (id: string | undefined, kind?: string) => !!id && !(kind ?? '').startsWith('geocoder') && (!id.startsWith('osm:') || kind === 'city');

/** frontend assumption — /api/climate shape not fixed in v1. */
export interface ClimateProjection {
  scenario: string; // 'ssp245' | 'ssp585'
  period: string; // '2041–2050'
  delta: number; // °C, multi-model median
  lo?: number;
  hi?: number;
}
export interface Climate {
  variable?: string; // 'tasmax'
  baseline?: string; // '2005–2014'
  models?: string[];
  label_uk?: string;
  projections: ClimateProjection[];
}

export interface ApiError {
  error: string;
  detail?: string;
}

/** Agent chat (decision #19). */
export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}
export interface AgentStep {
  id?: string;
  tool: string;
  status: 'running' | 'done' | 'error';
  summary?: string;
}

/** API v1.8 `context.rank`: the zone's mean gap among the city's preset districts (rank 1 = hottest; `of` includes the zone). */
export interface ContextRank {
  rank: number; of: number; percentile?: number; city: string; metric?: string; compared_with?: string;
  is_district?: boolean; district_gap_range?: [number, number];
  /** API v1.9 */
  basis?: string; compared_to_uk?: string; zone_analysed_km2?: number; district_analysed_km2_range?: [number, number];
  like_for_like?: boolean; note_uk?: string | null;
  district_extremes?: { hottest?: DistrictRef; coolest?: DistrictRef };
}
/** API v1.8 `context.climate`: CMIP6 air temperature (tasmax), nearest period, moderate scenario. */
export interface ContextClimate {
  scenario: string; period: string; variable?: string; unit?: string; delta: number; delta_range?: [number, number];
  baseline_period?: string | [number, number]; note_uk?: string; source?: string;
}
export interface ReportContext { rank?: ContextRank | null; climate?: ContextClimate | null }

export interface DistrictRef { id: string; name?: string; short_name?: string; gap: number }

// ---- country map (MAP-TASKS 2–4, API v2.1) ----
export interface Overlays {
  version?: string;
  ukraine: { bbox: [number, number, number, number]; geometry: Polygon | MultiPolygon };
  war_regions: FeatureCollection<Polygon | MultiPolygon, { name: string; since: number; text_uk: string }>;
  no_lst: FeatureCollection<Polygon | MultiPolygon, { label_uk?: string; share_years?: number }>;
  /** per-year swaths without enough clear scenes (one feature per year; «2022: замало безхмарних знімків цієї смуги») */
  no_scenes?: FeatureCollection<Polygon | MultiPolygon, { year: number; area_km2?: number; label_uk?: string }>;
  /** optional: occupied territory (neutral hatch) with its source; absent/empty = nothing drawn */
  occupied?: FeatureCollection<Polygon | MultiPolygon, { label_uk?: string; source?: string }> & { source?: string; attribution?: string };
}
export interface OverviewPlace {
  place_id: string;
  name_en?: string;
  name: string;
  kind: 'city' | 'district';
  city: string | null;
  oblast?: string | null;
  lon: number;
  lat: number;
  bbox: [number, number, number, number];
  rank: number;
  status: 'ok' | 'no_data' | 'insufficient_data' | 'error';
  gap_mean: number | null;
  gap_by_year?: Record<string, number | null>;
  trend?: { slope_per_decade: number; p: number; verdict: string } | null;
  war_region: { name: string; since: number } | null;
  /** temporarily occupied (official list, dated) — preferred over the oblast-level war caveat */
  occupied?: { snapshot_date: string; source: string; source_url?: string } | null;
  /** mean summer daytime surface temperature of the built-up area, °C (MAP-TASKS 21 H; when the backend adds it) */
  lst_mean?: number | null;
  reason_uk: string | null;
  report_id?: string | null;
}
export interface Overview {
  version?: string;
  method_version?: string;
  years?: [number, number];
  places: OverviewPlace[];
}

/** GET /api/reports/{id}/reference (API v2.7, MAP-TASKS 20 D): the report's reference forest, simplified */
export type ReferenceOutline = Feature<Polygon | MultiPolygon, {
  report_id: string; label_uk?: string; city?: string; kind?: 'preset' | 'derived' | string;
  ring_km?: [number, number]; area_km2?: number; simplify_m?: number;
}>;
