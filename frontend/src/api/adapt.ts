// Normalise live backend responses (uhd/backend, api_version 0.1.x) into the frontend types.
// Kept tolerant: accepts both the shapes assumed in API contract v1 and the richer live shapes.
import type { Climate, ColorStop, Hotspot, LayerMeta, Meta, PlaceHit, PresetMeta, Report } from './types';

type Raw = Record<string, unknown>;
const isObj = (x: unknown): x is Raw => typeof x === 'object' && x !== null && !Array.isArray(x);

const LAYER_UK: Record<string, { name: string; lo: string; hi: string }> = {
  gap: { name: 'Розрив з лісом', lo: 'прохолодніше', hi: 'гарячіше' },
  lst: { name: 'Температура поверхні', lo: 'прохолодніше', hi: 'гарячіше' },
  ndvi: { name: 'Зелень (NDVI)', lo: 'мало', hi: 'багато' },
  dndvi: { name: 'Зміна зелені', lo: 'поменшало', hi: 'побільшало' },
};

const stops = (x: unknown): ColorStop[] =>
  Array.isArray(x)
    ? x.map((s) => (Array.isArray(s) ? (s as ColorStop) : [Number((s as Raw).value), String((s as Raw).color)] as ColorStop))
    : [];

/** Genitive for «ліс навколо …». */
export const CITY_GEN: Record<string, string> = { kyiv: 'Києва', kharkiv: 'Харкова', lviv: 'Львова' };

/** City id → display name, filled from the last /api/meta. */
export const cityNames = new Map<string, string>([['kyiv', 'Київ'], ['kharkiv', 'Харків'], ['lviv', 'Львів']]);
/** City id → English name (item 32: /api/meta?lang=en adds `name_en`). */
export const cityNamesEn = new Map<string, string>([['kyiv', 'Kyiv'], ['kharkiv', 'Kharkiv'], ['lviv', 'Lviv']]);

/** City id → Ukrainian label; never shows raw enum values like "derived". */
export function cityLabel(id: string | undefined | null): string {
  if (!id) return '';
  const n = cityNames.get(id);
  if (n) return n;
  if (id === 'derived' || /^[a-z0-9_-]+$/.test(id)) return '';
  return id;
}

export function adaptMeta(raw: Raw): Meta {
  const cities = (raw.cities as Meta['cities']) ?? [];
  for (const c of cities) {
    cityNames.set(c.id, c.name);
    const en = (c as { name_en?: unknown }).name_en;
    if (typeof en === 'string' && en) cityNamesEn.set(c.id, en);
  }
  let layers: LayerMeta[];
  let tile: Meta['tiles'] | undefined;
  let fill: Meta['fill'] = null;
  let nonbuilt: Meta['nonbuilt'] = null;
  if (Array.isArray(raw.layers)) layers = raw.layers as LayerMeta[];
  else {
    const L = (raw.layers ?? {}) as Raw;
    const scales = (L.scales ?? {}) as Record<string, Raw>;
    const fillMeta = isObj(L.fill) ? (L.fill as { gap?: string; lst?: string; label_uk?: string }) : null;
    fill = fillMeta;
    const ov = isObj(L.overlays) ? (L.overlays as Record<string, unknown>) : null;
    nonbuilt = ov && isObj(ov.nonbuilt) ? (ov.nonbuilt as NonNullable<Meta['nonbuilt']>) : null;
    // fill layers are drawn under their main layer, never offered as a layer of their own
    const fillIds = new Set([fillMeta?.gap, fillMeta?.lst, 'nonbuilt'].filter(Boolean));
    const ids = ((L.ids as string[] | undefined) ?? Object.keys(scales)).filter((id) => !fillIds.has(id) && !id.endsWith('_fill'));
    layers = ids.map((id) => {
      const sc = scales[id] ?? {};
      const st = sc.stops;
      const uk = LAYER_UK[id];
      return {
        id,
        name_uk: uk ? uk.name.replace('{base}', String(L.dndvi_base_year ?? 2013)) : String(sc.title_uk ?? id),
        kind: sc.kind as string | undefined,
        title_uk: sc.title_uk as string | undefined,
        units: String(sc.unit ?? ''),
        stops: isObj(st) ? stops(st.light) : stops(st),
        stops_dark: isObj(st) ? stops(st.dark) : undefined,
        legend_lo_uk: uk?.lo,
        legend_hi_uk: uk?.hi,
      };
    });
    tile = {
      url: L.tile_url as string | undefined,
      minzoom: L.min_zoom as number | undefined,
      maxzoom: (L.native_zoom ?? L.max_zoom) as number | undefined,
      tileSize: L.tile_size as number | undefined,
      version: L.tiles_version as string | undefined,
    };
  }
  return {
    data_version: raw.data_version as string | undefined,
    years: (raw.years as number[]) ?? [],
    cities,
    layers,
    presets: ((raw.presets as PresetMeta[]) ?? []).map((p) => ({ ...p })),
    tiles: tile,
    fill,
    nonbuilt,
    limits: raw.limits as Meta['limits'],
    agent_configured: raw.agent_configured as boolean | undefined,
  };
}

const bboxCenter = (b: unknown): [number, number] | undefined =>
  Array.isArray(b) && b.length === 4 ? [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2] : undefined;

/**
 * Nominatim names a building by its house number only («22»). Use «Хрещатик, 22» from display_name
 * («22, вулиця Хрещатик, Центр, …»); a trailing «(≈1 км навколо)» is kept (QA R3-7).
 */
export function addressName(name: string, displayName?: string | null): string {
  const m = name.match(/^(\S+?)(\s*\(.*\))?$/);
  const num = m?.[1] ?? '';
  if (!displayName || !/^\d+[\p{L}]?([/-]\d*[\p{L}]?)?$/u.test(num)) return name;
  const parts = displayName.split(',').map((x) => x.trim());
  if (parts[0] !== num || !parts[1]) return name;
  const street = parts[1].replace(/^вулиця\s+/u, '');
  return `${street}, ${num}${m?.[2] ?? ''}`;
}

const str = <K extends string>(k: K, v: unknown): Partial<Record<K, string>> =>
  (typeof v === 'string' && v ? { [k]: v } as Record<K, string> : {});

export function adaptPlaces(raw: unknown): PlaceHit[] {
  if (Array.isArray(raw)) return raw as PlaceHit[];
  if (!isObj(raw)) return [];
  const presets = ((raw.presets as Raw[]) ?? []).map((p) => ({
    id: String(p.id),
    name: String(p.name),
    kind: String(p.kind ?? 'preset'),
    city: p.city as string | undefined,
    // major cities from OSM (API v1.9) have no `city`, but an oblast
    subtitle: p.city ? cityNames.get(String(p.city)) ?? String(p.city) : typeof p.oblast === 'string' ? p.oblast : undefined,
    center: bboxCenter(p.bbox),
    note_uk: p.note_uk as string | undefined,
    // item 32: English siblings from /api/places?lang=en (Search shows them in EN, the Ukrainian text otherwise)
    ...str('name_en', p.name_en), ...str('note_en', p.note_en),
    ...str('subtitle_en', p.city ? cityNamesEn.get(String(p.city)) : p.oblast_en),
  }));
  const geo = ((raw.geocoder as Raw[]) ?? []).map((g) => ({
    id: String(g.id),
    name: addressName(String(g.name), g.display_name as string | undefined),
    kind: 'geocoder',
    osm_type: g.osm_type as string | undefined,
    subtitle: String(g.display_name ?? '').split(', ').slice(1).join(', ') || undefined,
    ...str('name_en', typeof g.name_en === 'string' ? addressName(g.name_en, g.display_name_en as string | undefined) : undefined),
    ...str('subtitle_en', typeof g.display_name_en === 'string' ? g.display_name_en.split(', ').slice(1).join(', ') : undefined),
    center: (g.center as [number, number] | undefined) ?? bboxCenter(g.bbox),
  }));
  return [...presets, ...geo];
}

/** `hotspots` (API v1.8): [{lon, lat, gap, gap_peak_px, area_km2, years}], tolerant of center/gap_c/mean. */
export function adaptHotspots(x: unknown): Hotspot[] {
  if (!Array.isArray(x)) return [];
  return x.flatMap((h) => {
    if (!isObj(h)) return [];
    const c = Array.isArray(h.center) ? h.center : [h.lon, h.lat];
    const gap = [h.gap, h.gap_c, h.mean].find((v) => typeof v === 'number') as number | undefined;
    if (typeof c[0] !== 'number' || typeof c[1] !== 'number' || gap == null) return [];
    const years = Array.isArray(h.years) ? (h.years as unknown[]).filter((y): y is number => typeof y === 'number') : undefined;
    const poly = [h.polygon, h.geometry, h.outline].find((g) => isObj(g) && (g.type === 'Polygon' || g.type === 'MultiPolygon'));
    const lc = isObj(h.land_class) ? h.land_class.label_uk : undefined; // API v2.0
    const typeUk = [lc, h.type_uk, h.kind_uk, h.class_uk].find((t) => typeof t === 'string');
    return [{
      center: [c[0], c[1]] as [number, number], gap, area_km2: typeof h.area_km2 === 'number' ? h.area_km2 : undefined,
      ...(years?.length ? { years } : {}),
      ...(typeof h.delta_vs_zone === 'number' ? { delta_vs_zone: h.delta_vs_zone } : {}),
      ...(poly ? { polygon: poly as unknown as NonNullable<Hotspot['polygon']> } : {}),
      ...(typeUk ? { type_uk: typeUk as string } : {}),
    }];
  }).sort((a, b) => b.gap - a.gap).slice(0, 3);
}

export function adaptReport(raw: Raw): Report {
  const r = raw as unknown as Omit<Report, 'green_gap'> & { green_gap?: unknown };
  const gg = r.green_gap;
  const green = typeof gg === 'number' ? gg : isObj(gg) && typeof gg.mean === 'number' ? gg.mean : null;
  const city = cityLabel(r.reference?.city);
  const gen = CITY_GEN[r.reference?.city ?? ''];
  // human label for the reference forest; derived references never show the raw id (QA round 3)
  const ref = { ...r.reference, city, forest_uk: gen ? `ліс навколо ${gen}` : 'ліс навколо міста' }; // Роман P1-3: «підібрано автоматично» lives in Details
  const scope = isObj(gg) && typeof gg.scope === 'string' ? gg.scope : undefined;
  const series = (r.series ?? []).map((s) => (s.gap == null ? { ...s, method: null } : s));
  const zt = (raw.zone_trend ?? raw.zone_lst_trend) as Report['zone_trend'];
  const hotspots = adaptHotspots(raw.hotspots);
  return { ...r, hotspots, zone_trend: zt ?? null, series, reference: ref, green_gap: green, green_scope: scope, caveats: r.caveats ?? [] };
}

const dash = (s: string) => s.replace('-', '–');

export function adaptClimate(raw: Raw): Climate {
  if (Array.isArray(raw.projections)) return raw as unknown as Climate;
  const projections: Climate['projections'] = [];
  for (const scen of ['ssp245', 'ssp585', 'ssp126', 'ssp370']) {
    const byPeriod = raw[scen];
    if (!isObj(byPeriod)) continue;
    for (const [period, v] of Object.entries(byPeriod)) {
      if (!isObj(v) || typeof v.delta !== 'number') continue;
      const range = v.delta_range as [number, number] | undefined;
      projections.push({ scenario: scen, period: dash(period), delta: v.delta, lo: range?.[0], hi: range?.[1] });
    }
  }
  const base = raw.baseline;
  const baseline = isObj(base) && Array.isArray(base.period) ? `${base.period[0]}–${base.period[1]}` : typeof base === 'string' ? base : undefined;
  return {
    variable: raw.variable as string | undefined,
    baseline,
    models: raw.models as string[] | undefined,
    label_uk: raw.label_uk as string | undefined,
    projections,
  };
}

/** First sentence of the backend verdict, without the "Зона: " prefix (the card already shows the name). */
export function leadSentence(text: string, zoneName?: string): string {
  let t = text.trim();
  const m = /^(.+?[.!?])(?=\s+[А-ЯІЇЄҐA-Z«(]|\s*$)/u.exec(t);
  if (m) t = m[1]!;
  const prefix = zoneName && t.startsWith(`${zoneName}:`) ? zoneName.length + 1 : (/^[^:.\d]{1,40}:\s+/u.exec(t)?.[0].length ?? 0);
  if (prefix) {
    t = t.slice(prefix).trim();
    t = t.charAt(0).toUpperCase() + t.slice(1);
  }
  return t;
}
