// Typed fixtures matching API contract v1, used while the backend is not reachable
// (VITE_API_MODE=fixtures, or auto-fallback). Numbers for Kyiv zones come from the
// team's first Kyiv check (context/results/2026-11-14-*, design F7 stats): summer LST
// composites 2013–2025, forest reference in a 2–15 km ring. Kharkiv/Lviv numbers and
// all preset polygons are approximate placeholders — the backend supplies real ones.
import type { Feature, FeatureCollection, Polygon } from 'geojson';
import type { Climate, Meta, Place, PlaceHit, Report, SeriesPoint, Trend, ZoneGeometry } from '../api/types';
import kyivFc from './geo/kyiv.geojson?raw';
import kharkivFc from './geo/kharkiv.geojson?raw';
import lvivFc from './geo/lviv.geojson?raw';

export const YEARS = [2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025];

const cityGeom = (raw: string): ZoneGeometry =>
  ((JSON.parse(raw) as FeatureCollection).features[0] as Feature<Polygon>).geometry;

const poly = (pts: [number, number][]): Polygon => ({
  type: 'Polygon',
  coordinates: [[...pts, pts[0]!]],
});

export const GAP_STOPS_LIGHT: [number, string][] = [
  [-6, '#5C8C7A'], [-2, '#CEDCD4'], [0, '#F0EFEC'], [2, '#FAE0C8'], [5, '#FCAA70'], [8, '#EA548C'], [12, '#801260'],
];
export const GAP_STOPS_DARK: [number, string][] = [
  [-6, '#326056'], [-2, '#1E2E3A'], [0, '#1A2034'], [2, '#4E2E30'], [5, '#C45C2C'], [8, '#D63A80'], [12, '#F078BA'],
];

export const META: Meta = {
  data_version: 'fixtures-2026-11-15',
  years: YEARS,
  cities: [
    { id: 'kyiv', name: 'Київ', bbox: [30.2361, 50.2132, 30.8264, 50.5908] },
    { id: 'kharkiv', name: 'Харків', bbox: [36.1056, 49.8785, 36.4555, 50.1048] },
    { id: 'lviv', name: 'Львів', bbox: [23.898, 49.7682, 24.1334, 49.9037] },
  ],
  layers: [
    { id: 'gap', name_uk: 'Розрив з лісом', units: '°C', kind: 'diverging', stops: GAP_STOPS_LIGHT, stops_dark: GAP_STOPS_DARK, legend_lo_uk: 'прохолодніше', legend_hi_uk: 'гарячіше' },
    { id: 'lst', name_uk: 'Температура поверхні', units: '°C', stops: [[20, '#2B4C7E'], [30, '#F0EFEC'], [38, '#FCAA70'], [44, '#EA548C'], [50, '#801260']], legend_lo_uk: 'прохолодніше', legend_hi_uk: 'гарячіше' },
    { id: 'ndvi', name_uk: 'Зелень (NDVI)', units: '', stops: [[0, '#E8E2D0'], [0.4, '#A9C79A'], [0.8, '#2F6B4F']], legend_lo_uk: 'мало', legend_hi_uk: 'багато' },
    { id: 'dndvi', name_uk: 'Зміна зелені', units: '', kind: 'diverging', stops: [[-0.3, '#B5562B'], [0, '#F0EFEC'], [0.3, '#2F6B4F']], legend_lo_uk: 'поменшало', legend_hi_uk: 'побільшало' },
    // item 17 C: internal layers as an older meta could deliver them — they must never reach the UI
    { id: 'gap_fill', name_uk: 'gap_fill', units: '°C', stops: [] },
    { id: 'nonbuilt', name_uk: 'nonbuilt', units: '', stops: [] },
  ],
  presets: [
    { id: 'kyiv-pozniaky', name: 'Позняки', kind: 'demo_zone', city: 'kyiv', case: 'hot_stable', note_uk: 'Щільні багатоповерхівки: найгарячіше місце, але розрив стабільний; тут проходить стик смуг Landsat.' },
    { id: 'kyiv-obolon', name: 'Оболонь', kind: 'demo_zone', city: 'kyiv' },
    { id: 'kyiv-teremky', name: 'Теремки', kind: 'demo_zone', city: 'kyiv' },
    { id: 'kyiv-hatne', name: 'Гатне', kind: 'demo_zone', city: 'kyiv' },
    { id: 'kyiv', name: 'Увесь Київ', kind: 'city', city: 'kyiv' },
    { id: 'kharkiv', name: 'Увесь Харків', kind: 'city', city: 'kharkiv' },
    { id: 'lviv', name: 'Увесь Львів', kind: 'city', city: 'lviv' },
  ],
};

export const PLACES: Record<string, Place & { subtitle: string; center: [number, number] }> = {
  'kyiv-pozniaky': {
    id: 'kyiv-pozniaky', name: 'Позняки', kind: 'district', subtitle: 'Київ · Дарницький р-н', center: [30.628, 50.397],
    geometry: poly([[30.601, 50.404], [30.616, 50.412], [30.641, 50.413], [30.659, 50.404], [30.655, 50.389], [30.636, 50.381], [30.612, 50.384], [30.602, 50.392]]),
  },
  'kyiv-obolon': {
    id: 'kyiv-obolon', name: 'Оболонь', kind: 'district', subtitle: 'Київ · Оболонський р-н', center: [30.498, 50.507],
    geometry: poly([[30.47, 50.522], [30.494, 50.53], [30.52, 50.524], [30.526, 50.505], [30.512, 50.488], [30.484, 50.489], [30.468, 50.503]]),
  },
  'kyiv-teremky': {
    id: 'kyiv-teremky', name: 'Теремки', kind: 'district', subtitle: 'Київ · Голосіївський р-н', center: [30.457, 50.369],
    geometry: poly([[30.438, 50.382], [30.466, 50.385], [30.479, 50.368], [30.466, 50.353], [30.443, 50.356], [30.434, 50.369]]),
  },
  'kyiv-hatne': {
    id: 'kyiv-hatne', name: 'Гатне', kind: 'district', subtitle: 'Київська обл. · передмістя', center: [30.428, 50.355],
    geometry: poly([[30.41, 50.364], [30.43, 50.368], [30.447, 50.358], [30.441, 50.345], [30.42, 50.343], [30.408, 50.352]]),
  },
  kyiv: { id: 'kyiv', name: 'Увесь Київ', kind: 'city', subtitle: 'місто', center: [30.523, 50.45], geometry: cityGeom(kyivFc) },
  kharkiv: { id: 'kharkiv', name: 'Увесь Харків', kind: 'city', subtitle: 'місто', center: [36.25, 49.99], geometry: cityGeom(kharkivFc) },
  lviv: { id: 'lviv', name: 'Увесь Львів', kind: 'city', subtitle: 'місто', center: [24.03, 49.84], geometry: cityGeom(lvivFc) },
};

// ---- per-zone raw numbers -----------------------------------------------------------
interface Raw {
  lst: number[];
  ref: number[];
  ndvi: number[];
  built: number;
  trend: { s: number; lo: number; hi: number; p: number };
  ndviTrend: { s: number; lo: number; hi: number; p: number };
  area: number;
  builtArea: number;
  city: string;
  validDip?: Record<number, number>;
}
const KYIV_FOREST = [31.52, 30.57, 31.55, 33.1, 32.4, 30.84, 31.09, 29.94, 31.92, 32.17, 31.13, 32.46, 29.24];
const RAW: Record<string, Raw> = {
  'kyiv-pozniaky': {
    lst: [38.6, 43.2, 40.3, 43.88, 41.78, 39.97, 36.3, 37.46, 40.21, 44.65, 42.66, 41.42, 34.14], ref: KYIV_FOREST,
    ndvi: [0.28, 0.34, 0.26, 0.28, 0.27, 0.31, 0.33, 0.3, 0.35, 0.32, 0.38, 0.34, 0.36], built: 0.968,
    trend: { s: -1.0, lo: -6.53, hi: 3.6, p: 0.59 }, ndviTrend: { s: 0.08, lo: 0.03, hi: 0.13, p: 0.01 },
    area: 6.4, builtArea: 5.7, city: 'Київ', validDip: { 2020: 0.58 },
  },
  'kyiv-obolon': {
    lst: [41.61, 38.89, 38.23, 40.91, 39.2, 39.5, 36.76, 40.32, 42.19, 36.81, 39.11, 41.97, 35.59], ref: KYIV_FOREST,
    ndvi: [0.37, 0.44, 0.35, 0.41, 0.36, 0.42, 0.4, 0.4, 0.44, 0.42, 0.45, 0.39, 0.45], built: 0.958,
    trend: { s: -0.83, lo: -5.08, hi: 3.14, p: 0.675 }, ndviTrend: { s: 0.05, lo: -0.02, hi: 0.1, p: 0.085 },
    area: 9.8, builtArea: 7.2, city: 'Київ',
  },
  'kyiv-teremky': {
    lst: [39.81, 38.1, 35.93, 40.92, 38.79, 38.1, 35.02, 39.11, 39.0, 37.94, 37.48, 39.5, 37.71], ref: KYIV_FOREST,
    ndvi: [0.44, 0.48, 0.43, 0.48, 0.46, 0.48, 0.46, 0.46, 0.45, 0.45, 0.5, 0.46, 0.48], built: 0.92,
    trend: { s: -0.43, lo: -2.11, hi: 3.37, p: 0.765 }, ndviTrend: { s: -0.0, lo: -0.03, hi: 0.04, p: 0.487 },
    area: 5.1, builtArea: 3.1, city: 'Київ',
  },
  'kyiv-hatne': {
    lst: [36.17, 33.64, 34.09, 37.62, 36.58, 35.32, 33.02, 35.96, 37.13, 36.6, 34.44, 37.8, 33.16], ref: KYIV_FOREST,
    ndvi: [0.61, 0.62, 0.56, 0.59, 0.56, 0.6, 0.58, 0.59, 0.6, 0.59, 0.62, 0.59, 0.61], built: 0.9,
    trend: { s: 0.56, lo: -1.52, hi: 3.06, p: 0.765 }, ndviTrend: { s: 0.01, lo: -0.03, hi: 0.05, p: 0.532 },
    area: 4.2, builtArea: 1.7, city: 'Київ',
  },
  kyiv: {
    lst: [39.77, 38.34, 36.65, 40.4, 38.6, 38.17, 35.22, 37.82, 39.6, 39.09, 38.05, 39.81, 35.45], ref: KYIV_FOREST,
    ndvi: [0.69, 0.7, 0.65, 0.67, 0.64, 0.68, 0.67, 0.66, 0.7, 0.68, 0.68, 0.68, 0.72].map((v) => v - 0.25), built: 0.62,
    trend: { s: -0.77, lo: -2.35, hi: 1.44, p: 0.435 }, ndviTrend: { s: 0.02, lo: -0.01, hi: 0.05, p: 0.21 },
    area: 839, builtArea: 412, city: 'Київ',
  },
  // Placeholder numbers (not computed) — only so the UI can be exercised for other cities.
  kharkiv: {
    lst: [40.1, 39.0, 37.9, 41.2, 39.4, 39.8, 36.9, 38.7, 40.3, 40.9, 39.2, 41.0, 37.6],
    ref: [33.0, 32.1, 32.4, 34.2, 33.0, 32.9, 32.0, 31.8, 33.1, 33.9, 32.5, 33.8, 31.6],
    ndvi: [0.41, 0.42, 0.39, 0.4, 0.38, 0.41, 0.4, 0.4, 0.42, 0.4, 0.41, 0.41, 0.43], built: 0.66,
    trend: { s: 0.12, lo: -1.4, hi: 1.7, p: 0.82 }, ndviTrend: { s: 0.01, lo: -0.02, hi: 0.04, p: 0.48 },
    area: 350, builtArea: 205, city: 'Харків',
  },
  lviv: {
    lst: [35.2, 34.1, 33.0, 36.1, 34.8, 34.4, 32.6, 33.9, 35.2, 35.6, 34.3, 35.9, 33.1],
    ref: [29.6, 28.9, 28.7, 30.4, 29.6, 29.2, 28.4, 28.6, 29.7, 30.0, 29.0, 30.1, 28.5],
    ndvi: [0.45, 0.46, 0.44, 0.45, 0.43, 0.45, 0.44, 0.45, 0.46, 0.44, 0.45, 0.45, 0.47], built: 0.64,
    trend: { s: -0.2, lo: -1.6, hi: 1.3, p: 0.71 }, ndviTrend: { s: 0.01, lo: -0.02, hi: 0.03, p: 0.55 },
    area: 182, builtArea: 98, city: 'Львів',
  },
};

const r2 = (x: number) => Math.round(x * 100) / 100;
const mean = (a: number[]) => a.reduce((s, v) => s + v, 0) / a.length;
const trendOf = (t: Raw['trend'], n: number): Trend => ({
  slope_per_decade: t.s, ci95: [t.lo, t.hi], p: t.p, n_years: n,
  verdict: n < 8 ? 'insufficient_data' : t.p < 0.05 ? 'significant' : 'not_significant',
});

const GEN: Record<string, string> = { 'Київ': 'Києва', 'Харків': 'Харкова', 'Львів': 'Львова' };
const c1 = (x: number) => x.toFixed(1).replace('.', ',').replace('-', '−');

/** Mirrors the backend's verdict_text_uk style (first sentence = the card lead). */
function verdictText(name: string, city: string, gapMean: number, t: Trend): string {
  const head = `${name}: забудова влітку вдень у середньому на ${c1(gapMean)} °C гарячіша за ліс навколо ${GEN[city] ?? city}.`;
  if (t.verdict === 'insufficient_data') return `${head} Літніх сезонів із чистими знімками замало, щоб оцінити, чи змінюється розрив.`;
  const p = (t.p ?? 1).toFixed(2).replace('.', ',');
  if (t.verdict === 'significant')
    return `${head} Розрив ${(t.slope_per_decade ?? 0) > 0 ? 'росте' : 'меншає'} на ${c1(Math.abs(t.slope_per_decade ?? 0))} °C/10 р., і це статистично значуща зміна (p = ${p}).`;
  return `${head} Тренд розриву ${c1(t.slope_per_decade ?? 0)} °C/10 р. статистично незначущий (p = ${p}) — розрив стабільний або змінюється повільніше, ніж «шумить» погода.`;
}

export function buildReport(id: string, raw: Raw, name: string): Report {
  const series: SeriesPoint[] = YEARS.map((year, i) => {
    const zone = raw.lst[i]!;
    const ref = raw.ref[i]!;
    const valid = raw.validDip?.[year] ?? 0.9 + ((i * 7) % 9) / 100;
    return {
      year, zone_lst: zone, ref_lst: ref, gap: r2(zone - ref), ndvi: raw.ndvi[i]!, ndbi: r2(0.12 - raw.ndvi[i]! * 0.2),
      built_share: r2(raw.built - i * 0.0004), scenes: 3 + ((i * 5) % 6), valid_share: valid,
      method: year === 2020 && raw.validDip ? 'composite' : 'per_scene',
    };
  });
  const gaps = series.map((s) => s.gap!);
  const trend = trendOf(raw.trend, YEARS.length);
  const caveats = [
    { code: 'lst_surface', text_uk: 'Це температура поверхні (дахи, асфальт, крони) близько 11:00 за сонцем, а не приземна температура повітря (2 м).' },
  ];
  if (id === 'kyiv-pozniaky')
    caveats.push({ code: 'landsat_seam', text_uk: 'За 0,75 км на захід від центру Позняків проходить шов між смугами знімків Landsat; розрив рахуємо по кожному знімку окремо, але 2025 рік може бути зміщений.' });
  if (raw.validDip)
    caveats.push({ code: 'low_valid_share', text_uk: '2020: є ділянки без даних (покрито 58 % території), рік пораховано з композиту.' });
  if (!id.startsWith('kyiv'))
    caveats.push({ code: 'fixture_placeholder', text_uk: 'Демо-цифри для інтерфейсу: справжній розрахунок для цього міста ще не підключено.' });
  const ref_trend = trendOf(id.startsWith('kyiv') ? { s: -0.42, lo: -2.36, hi: 1.89, p: 0.952 } : { s: 0.1, lo: -1, hi: 1.2, p: 0.8 }, YEARS.length);
  const ndvi_trend = trendOf(raw.ndviTrend, YEARS.length);
  return {
    report_id: `fx-${id}`,
    zone: { name, area_km2: raw.area, built_area_km2: raw.builtArea },
    reference: { city: raw.city, ring_km: [2, 15], area_km2: 214, forest_px: 59400 },
    series,
    gap_summary: { mean: r2(mean(gaps)), last: gaps[gaps.length - 1]!, min: Math.min(...gaps), max: Math.max(...gaps) },
    trend,
    ref_trend,
    ndvi_trend,
    land_change: { always_built: r2(raw.builtArea * 0.93), new_built: r2(raw.builtArea * 0.07), always_green: r2((raw.area - raw.builtArea) * 0.6) },
    green_gap: r2(mean(gaps) * 0.38),
    caveats,
    verdict_text_uk: verdictText(name === 'Ваша ділянка' ? 'Ваша ділянка' : name.replace('Увесь ', ''), raw.city, mean(gaps), trend),
  };
}

export const REPORTS: Record<string, Report> = Object.fromEntries(
  Object.entries(RAW).map(([id, raw]) => [id, buildReport(id, raw, PLACES[id]!.name)]),
);

/** A drawn area: demo report derived from the closest preset (clearly flagged). */
export function fixtureReportForCustom(nearestId: string, areaKm2: number): Report {
  const base = RAW[nearestId] ?? RAW['kyiv']!;
  const rep = buildReport(nearestId, { ...base, area: r2(areaKm2), builtArea: r2(areaKm2 * 0.7) }, 'Ваша ділянка');
  rep.report_id = `fx-custom-${Math.round(areaKm2 * 1000)}`;
  rep.caveats.push({ code: 'fixture_placeholder', text_uk: 'Демо-режим: для власної ділянки показано цифри найближчого району, доки сервер аналізу не підключено.' });
  return rep;
}

// CMIP6 v2 (science, item 33): Нижні Сади cell, median of 12 models with the 10–90 % range, base 1995–2014, 20-year windows
// (live /api/climate?lat=50.36&lon=30.61, adapted)
export const CLIMATE: Climate = {
  variable: 'tasmax',
  baseline: '1995–2014',
  models: ['ACCESS-CM2', 'CNRM-ESM2-1', 'CanESM5', 'EC-Earth3', 'GFDL-ESM4', 'INM-CM5-0', 'IPSL-CM6A-LR', 'MIROC6', 'MPI-ESM1-2-HR', 'MRI-ESM2-0', 'NorESM2-MM', 'UKESM1-0-LL'],
  projections: [
    { scenario: 'ssp245', period: '2041–2060', delta: 2.21, lo: 1.35, hi: 3.57 },
    { scenario: 'ssp585', period: '2041–2060', delta: 3.15, lo: 2.08, hi: 4.07 },
    { scenario: 'ssp245', period: '2081–2100', delta: 3.5, lo: 1.78, hi: 4.9 },
    { scenario: 'ssp585', period: '2081–2100', delta: 6.79, lo: 4.31, hi: 9.55 },
  ],
};

export function searchPresets(q: string): PlaceHit[] {
  const norm = q.trim().toLowerCase();
  return Object.values(PLACES)
    .filter((p) => !norm || p.name.toLowerCase().includes(norm) || p.subtitle.toLowerCase().includes(norm))
    .map((p) => ({ id: p.id, name: p.name, kind: p.kind === 'city' ? 'city' : 'demo_zone', subtitle: p.subtitle, center: p.center, note_uk: META.presets.find((m) => m.id === p.id)?.note_uk }));
}
