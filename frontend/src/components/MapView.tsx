import { useEffect, useMemo, useRef, useState, type MutableRefObject } from 'react';
import * as maplibregl from 'maplibre-gl';
import type { GeoJSONSource, LayerSpecification, Map as MlMap } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
// Bundle MapLibre's worker (and its shared chunk) through Vite; the default relative URL breaks under pre-bundling.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import type { Feature, FeatureCollection, MultiPolygon, Polygon, Position } from 'geojson';
import type { ColorStop, Overlays, Overview, OverviewPlace, ZoneGeometry } from '../api/types';
import { overviewFeatures } from '../lib/overview';
import { getOverlays, getReference, loadTile, retryingTileUrl, TILE_PROTOCOL, tileOptions, tileUrl } from '../api/client';
import { bbox, circlePolygon, haversineKm, maskPolygon, zoneShape } from '../lib/geo';
import { spotFactor } from '../lib/spot';
import { basemapNameEn } from '../i18n/placeNameExpr';
import { getMapUi, layerTransparency, muteApplies, REFERENCE_COLOR, setMapUi, useMapUi } from '../lib/mapUi';
import { minViewOf, panBounds, showAllUkraine, uaFeatures, unionBox, viewLimits } from '../lib/ukraine';
import { gloss } from '../lib/glossary';
import { SAT_TIMEOUT_MS, esriAttribution, esriLayerId, esriTiles, isSatLayerId, rememberSatFallback, satAttributionFor, satCaption, satErrorCounts, satLayerId, satLayerYear, satMaxzoom, satProviderOf, satShouldFallback, satTilesFor, type EsriShown, type SatProvider } from '../lib/satellite';
import { esriChoice, probeSatSite, tileCentre, tileOf, unprobe, type SatSite } from '../lib/wayback';
import { getLocale, tr, useLocale, type Locale } from '../i18n';
import { DISPUTED_LAYERS, undisputedBorder, withoutImposed } from '../lib/basemapPolicy';
import type { DrawMode } from '../state/store';
import { installLabelPick, type MapLabel } from '../lib/labelPick';

let protocolAdded = false;
function ensureTileProtocol() {
  if (protocolAdded) return;
  maplibregl.addProtocol(TILE_PROTOCOL, loadTile);
  protocolAdded = true;
}

type Theme = 'light' | 'dark';

/** Free vector basemaps without an API key (OpenFreeMap, OpenMapTiles schema, © OSM contributors). */
export const BASEMAP: Record<Theme, string> = {
  light: 'https://tiles.openfreemap.org/styles/positron',
  dark: 'https://tiles.openfreemap.org/styles/dark',
};
/**
 * Heat opacity by zoom: strong at city scale, lighter when zoomed in so streets and water under the 60 m pixels
 * stay visible («приближаєш … темно і не видно»).
 */
/** heat opacity scaled by the «Видимість тепла» slider (item 7b / 26); t = transparency 0..1 = 1 − visibility */
const heatOpacity = (t: number): maplibregl.ExpressionSpecification => ['interpolate', ['linear'], ['zoom'], 10, 0.88 * (1 - t), 13, 0.72 * (1 - t), 15, 0.6 * (1 - t)];
/** item 9: pixels filled from neighbouring summers — same palette, ≈ 0.45 of the heat opacity, so they read as estimated */
const fillOpacity = (t: number): maplibregl.ExpressionSpecification => ['interpolate', ['linear'], ['zoom'], 10, 0.4 * (1 - t), 13, 0.32 * (1 - t), 15, 0.27 * (1 - t)];
const MASK_OPACITY = 0.3;
/**
 * Роман (pre-pitch): the light wash read as milky fog. Light theme only: a third of it over the map, less over imagery,
 * none while the card is collapsed (the user is exploring). Dark unchanged.
 */
const washFactor = (o: { dark: boolean; sat: boolean; exploring: boolean }) => (o.dark ? 1 : o.exploring ? 0 : o.sat ? 0.15 : 0.33);
/** «Видимість тепла» drops the heat layers to 50 % over imagery; the green layers keep most of their colour (≥ 85 %) */
const layerT = layerTransparency;
/** MAP-TASKS 25: the light map a step below the page colour (#f6f6f3), and the rasters capped below pure white */
const LIGHT_GROUND = '#ebeae5';
const LIGHT_RASTER = { 'raster-brightness-max': 0.93 } as const;
/** the nonbuilt veil belongs to the heat picture: it fades with «Видимість тепла», so imagery shows through it too (item 26) */
const veilOpacity = (u: { mute: number; heatTransparency: number }) => u.mute * (1 - u.heatTransparency);
const LABEL_SIZE: Record<string, number> = { place_city_large: 15, place_city: 13, place_town: 12, place_state: 12, place_village: 11, place_suburb: 11, place_other: 11, water_name: 12 };

/** Soft diagonal hatch for «немає даних» (transparent tile pixels) — 16×16 at 2× pixel ratio. */
function hatchImage(dark: boolean): { width: number; height: number; data: Uint8Array } {
  const n = 16, data = new Uint8Array(n * n * 4);
  const [bg, fg] = dark ? [[30, 38, 58], [62, 72, 100]] : [[236, 236, 232], [205, 206, 210]];
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    const on = (x + y) % 8 < 2;
    const c = on ? fg! : bg!, i = (y * n + x) * 4;
    data[i] = c[0]!; data[i + 1] = c[1]!; data[i + 2] = c[2]!; data[i + 3] = 255;
  }
  return { width: n, height: n, data };
}

/** Generic diagonal hatch (transparent background): `dir` 1 = «/», −1 = «\\». */
/** cross-hatch for the per-year «too few clear scenes» swaths — distinguishable from the single-direction no-LST hatch */
function crossHatch(rgb: [number, number, number], alpha: number, n = 12): { width: number; height: number; data: Uint8Array } {
  const a = lineHatch(rgb, alpha, 1, n), b = lineHatch(rgb, alpha, -1, n);
  for (let i = 3; i < a.data.length; i += 4) a.data[i] = Math.max(a.data[i]!, b.data[i]!);
  return a;
}

function lineHatch(rgb: [number, number, number], alpha: number, dir: 1 | -1, n = 12): { width: number; height: number; data: Uint8Array } {
  const data = new Uint8Array(n * n * 4);
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    const on = ((dir > 0 ? x + y : x - y + n) % 6) < 1.5;
    const i = (y * n + x) * 4;
    data[i] = rgb[0]; data[i + 1] = rgb[1]; data[i + 2] = rgb[2]; data[i + 3] = on ? alpha : 0;
  }
  return { width: n, height: n, data };
}

/**
 * SDF pill for the country markers (`icon-halo` draws the war outline). Fixed size, wide enough for «+10,0°» at 13 px
 * (stretchable icons with `icon-text-fit` did not render in MapLibre 5 with an SDF image).
 */
function pillSdf(): { width: number; height: number; data: Uint8Array } {
  const W = 120, H = 44, R = 16, B = 6; // device px at pixelRatio 2 → 60×22 css px; B = SDF buffer around the shape
  const data = new Uint8Array(W * H * 4);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    // signed distance to a rounded rect inset by B
    const qx = Math.abs(x + 0.5 - W / 2) - (W / 2 - B - R), qy = Math.abs(y + 0.5 - H / 2) - (H / 2 - B - R);
    const d = Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - R;
    const i = (y * W + x) * 4;
    data.fill(255, i, i + 3); // white RGB: MapLibre reads SDF icons with RGB too
    data[i + 3] = Math.max(0, Math.min(255, 191 - d * 32));
  }
  return { width: W, height: H, data };
}

/**
 * MAP-TASKS 5: OpenFreeMap «dark» is near-black (#0c0c0c land, #1b1b1d water, #181818 roads). Recoloured in the
 * app's slate palette: land clearly above the page background, water a distinct blue, roads/rails/borders visible.
 * Роман P2-2 (15.11): one step brighter (land #1c2438 → #212a40) so the dark map reads better under the heat.
 */
const DARK_BASEMAP = { background: '#212a40' } as Record<string, string>;
const DARK_PAINT: Record<string, Record<string, string>> = {
  water: { 'fill-color': '#0e2742' },
  'ua-water': { 'fill-color': '#0e2742' },
  waterway: { 'line-color': '#1a3a5c' },
  landcover_wood: { 'fill-color': '#22313a' },
  landuse_park: { 'fill-color': '#22313a' },
  landuse_residential: { 'fill-color': '#273049' },
  building: { 'fill-color': '#2f3856', 'fill-outline-color': '#384263' },
  highway_path: { 'line-color': '#2d3650' },
  highway_minor: { 'line-color': '#38425f' },
  highway_major_casing: { 'line-color': 'rgba(120,132,170,0.55)' },
  highway_major_inner: { 'line-color': '#3d4866' },
  highway_major_subtle: { 'line-color': '#46526f' },
  highway_motorway_casing: { 'line-color': 'rgba(140,152,190,0.6)' },
  highway_motorway_subtle: { 'line-color': '#4f5b7a' },
  railway: { 'line-color': '#3b4562' },
  railway_minor: { 'line-color': '#343e59' },
  railway_transit: { 'line-color': '#343e59' },
  boundary_state: { 'line-color': '#4e5878' },
  'boundary_country_z0-4': { 'line-color': '#6a7596' },
  'boundary_country_z5-': { 'line-color': '#6a7596' },
  'aeroway-area': { 'fill-color': '#28314b' },
};

const OVERVIEW_Z = 9;
/** R-MAP-3: popup order when map areas overlap — occupied first, then no-LST, the year's no-scenes swath, the war oblast */
const AREA_ORDER = ['occ-fill', 'nolst-fill', 'noscn-fill', 'war-hit'];
/** glossary sentence for a map popup, only the first time per session per key (TOOLTIPS §3: «first marker hover») */
const seenTips = new Set<string>();
function firstTimeGlossary(k: 'countryMarkers' | 'markerNoData'): string | null {
  const key = `uhd-tip-${k}`;
  try { if (sessionStorage.getItem(key)) return null; } catch { /* private mode */ }
  if (seenTips.has(k)) return null;
  seenTips.add(k);
  try { sessionStorage.setItem(key, '1'); } catch { /* private mode */ }
  return gloss(k).short;
}
/** item 32 (2e-map): a server text in the UI language — `<base>_en` in English when the API sent it (overlays and
 * overview are fetched with ?lang=en, which keeps every *_uk), else the Ukrainian one */
const str = (v: unknown) => (typeof v === 'string' && v.trim() ? v : undefined);
const srv = (p: Record<string, unknown>, base: string, l: Locale) => (l === 'en' ? str(p[`${base}_en`]) : undefined) ?? str(p[`${base}_uk`]);
/** basemap place names: Ukrainian names in uk (as before); in en OSM `name:en`, else the Ukrainian name in KMU 2010 Latin —
 * never `name:latin` (Polish where OSM has `name:pl`) or raw Cyrillic (I18N.md §5.4) */
const NAME_EN = basemapNameEn();
const placeName = (l: Locale): maplibregl.ExpressionSpecification =>
  l === 'en' ? NAME_EN : ['coalesce', ['get', 'name:uk'], ['get', 'name']];
const nolstText = (l: Locale): maplibregl.ExpressionSpecification => ['coalesce', ['get', `label_${l}`], ['get', 'label_uk'], tr(l, 'map.noLst')];
const noscnText = (l: Locale): maplibregl.ExpressionSpecification => ['coalesce', ['get', `label_${l}`], ['get', 'label_uk'], tr(l, 'map.noScenes')];
const BASEMAP_LABEL = (id: string, m: MlMap) => !OVERLAY_IDS.has(id) && !isSatLayerId(id) && m.getLayer(id)?.type === 'symbol' && !!m.getLayoutProperty(id, 'text-field');

/** layers that only exist outside marker mode (their minzoom follows `overviewZoom`) */
const RASTER_IDS = ['heat', 'heat-fill', 'nonbuilt', 'ua-ground', 'ref-fill', 'ref-line'];
/**
 * R-MAP-1: marker mode starts below z9 — but with a zone open, only 1.5 zoom levels below the zone's own framing
 * (never above z9, never below z5), so a big city framed at z7–8 opens on its heat map, not on country markers.
 */
export function overviewZoom(frameZoom: number | null): number {
  return frameZoom == null ? OVERVIEW_Z : Math.min(OVERVIEW_Z, Math.max(5, frameZoom - 1.5));
}
/** a label under these is not picked: they have their own click, or it is outside Ukraine (veil) */
const LABEL_BLOCKERS: ReadonlySet<string> = new Set(['ov-city', 'ov-district', 'hot-dot', 'hot-num', 'draft-fill', 'draft-line', 'draft-pts', 'veil']);
const OVERLAY_IDS = new Set(['heat', 'heat-fill', 'mask', 'city', 'zone-halo', 'zone-line', 'draft-fill', 'draft-line', 'draft-pts', 'hot-dot', 'hot-num', 'hot-area', 'veil', 'ua-border', 'ua-ground', 'ua-water', 'ov-city', 'ov-district', 'nonbuilt', 'nolst-fill', 'nolst-label', 'war-line', 'war-hit', 'occ-fill', 'ref-fill', 'ref-line', 'noscn-fill', 'noscn-label']);
// ── Satellite basemap: one raster source + layer per imagery version (Esri Wayback: `sat-w<release>`, one per tile
// version at the place, so years with the same picture share a layer; EOX mosaic after a fallback: `sat-YYYY`), added
// lazily. A switch never blanks the map: the new layer goes UNDER the shown one, and the shown one fades out only once
// the new source has loaded its tiles in view (or after SAT_SWAP_MAX_MS). At most SAT_KEEP sources stay on the map.
const satWanted = new WeakMap<MlMap, string>();
const satProv = new WeakMap<MlMap, SatProvider>();
/** layer ids, most recently wanted last (pruning keeps the tail) */
const satRecent = new WeakMap<MlMap, string[]>();
const SAT_KEEP = 3;
const SAT_SWAP_MAX_MS = 8000;
const SAT_FADE_MS = 220;
const satIds = (m: MlMap) => m.getStyle().layers.map((l) => l.id).filter(isSatLayerId);
const satVisible = (m: MlMap, id: string) => m.getLayoutProperty(id, 'visibility') !== 'none';
/** the sat layer drawn on top that is not fading out (the one the user sees) */
const satTop = (m: MlMap) => satIds(m).filter((id) => satVisible(m, id) && m.getPaintProperty(id, 'raster-opacity') !== 0).pop();
function pruneSatellite(m: MlMap) {
  const keep = new Set((satRecent.get(m) ?? []).slice(-SAT_KEEP));
  for (const id of satIds(m)) {
    if (keep.has(id) || satVisible(m, id)) continue;
    m.removeLayer(id);
    if (m.getSource(id)) m.removeSource(id);
  }
}
/** the wanted layer has its tiles: fade out whatever is drawn above it, then hide everything else */
function settleSatellite(m: MlMap) {
  const want = satWanted.get(m);
  if (want == null || !m.getLayer(want)) return;
  const others = satIds(m).filter((id) => id !== want && satVisible(m, id));
  m.setPaintProperty(want, 'raster-opacity', 1);
  const above = others.filter((id) => satIds(m).indexOf(id) > satIds(m).indexOf(want));
  for (const id of others) if (!above.includes(id)) m.setLayoutProperty(id, 'visibility', 'none');
  if (!above.length) { pruneSatellite(m); return; }
  for (const id of above) {
    m.setPaintProperty(id, 'raster-opacity-transition', { duration: SAT_FADE_MS, delay: 0 });
    m.setPaintProperty(id, 'raster-opacity', 0);
  }
  window.setTimeout(() => {
    for (const id of above) {
      if (!m.getLayer(id) || satWanted.get(m) === id) continue;
      m.setLayoutProperty(id, 'visibility', 'none');
      m.setPaintProperty(id, 'raster-opacity-transition', { duration: 0, delay: 0 });
      m.setPaintProperty(id, 'raster-opacity', 1);
    }
    pruneSatellite(m);
  }, SAT_FADE_MS + 30);
}
/** call `done` once the source has the tiles of the current view (or after SAT_SWAP_MAX_MS), unless another version is wanted by then */
function whenSatLoaded(m: MlMap, id: string, done: () => void) {
  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    m.off('sourcedata', onData); m.off('idle', onIdle); window.clearTimeout(timer);
    if (satWanted.get(m) === id) done();
  };
  const check = () => { if (satWanted.get(m) !== id) finish(); else if (m.getSource(id) && m.isSourceLoaded(id)) finish(); };
  const onData = (e: { sourceId?: string; tile?: unknown }) => { if (e.sourceId === id && e.tile) check(); };
  const onIdle = () => check();
  m.on('sourcedata', onData);
  m.on('idle', onIdle);
  const timer = window.setTimeout(finish, SAT_SWAP_MAX_MS);
}
function clearSatellite(m: MlMap) {
  for (const id of satIds(m)) m.removeLayer(id);
  for (const id of Object.keys(m.getStyle().sources ?? {})) if (isSatLayerId(id)) m.removeSource(id);
  satRecent.set(m, []);
}
// Esri health: tile failures (not 404) and answers per map; falls back to EOX for the session (satShouldFallback).
// requests aborted by a page reload/navigation fail with no status: they are not an Esri outage
let unloading = false;
for (const ev of ['beforeunload', 'pagehide']) window.addEventListener(ev, () => { unloading = true; });
interface EsriWatch { errors: number; answered: number; t0: number; timer: number | undefined }
const esriWatch = new WeakMap<MlMap, EsriWatch>();
function stopEsriWatch(m: MlMap) {
  const w = esriWatch.get(m);
  if (w) { window.clearTimeout(w.timer); w.timer = undefined; }
}
function esriFailed(m: MlMap) {
  stopEsriWatch(m);
  rememberSatFallback();
  setMapUi({ satEox: true }); // the «Шари» effect re-runs showSatellite with the EOX provider
}
function watchEsri(m: MlMap) {
  let w = esriWatch.get(m);
  if (!w) {
    const ww: EsriWatch = { errors: 0, answered: 0, t0: Date.now(), timer: undefined };
    w = ww;
    esriWatch.set(m, ww);
    const check = () => { if (satProv.get(m) === 'esri' && satShouldFallback({ errors: ww.errors, answered: ww.answered, elapsedMs: Date.now() - ww.t0 })) esriFailed(m); };
    m.on('error', (ev) => {
      const e = ev as unknown as { sourceId?: string; error?: { status?: number } };
      if (unloading || satProv.get(m) !== 'esri' || !e.sourceId || !isSatLayerId(e.sourceId)) return;
      if (satErrorCounts(e.error?.status)) ww.errors++; else ww.answered++;
      check();
    });
    m.on('data', (ev) => {
      const e = ev as unknown as { dataType?: string; sourceId?: string; tile?: unknown };
      if (satProv.get(m) !== 'esri' || e.dataType !== 'source' || !e.tile || !e.sourceId || !isSatLayerId(e.sourceId)) return;
      ww.answered++;
      window.clearTimeout(ww.timer); // something came back: the timeout rule is moot
      ww.timer = undefined;
    });
  }
  if (w.answered === 0 && w.timer === undefined) {
    const ww = w;
    ww.t0 = Date.now();
    ww.timer = window.setTimeout(() => { ww.timer = undefined; if (satProv.get(m) === 'esri' && satShouldFallback({ errors: ww.errors, answered: ww.answered, elapsedMs: Date.now() - ww.t0 })) esriFailed(m); }, SAT_TIMEOUT_MS);
  }
}
/** one satellite layer to show: id, tiles and what the caption says */
interface SatSpec { prov: SatProvider; id: string; tiles: string; maxzoom: number; attribution: string; release?: number; shown: EsriShown | null }
/** `tz` = the tile zoom MapLibre draws at (256-px tiles: ≈ map zoom + 1) — below the dated imagery the caption says «zoom in» */
function satSpec(prov: SatProvider, year: number | null, site: SatSite | null, tz?: number): SatSpec {
  if (prov === 'eox') {
    const ly = satLayerYear('eox', year);
    return { prov, id: satLayerId(ly), tiles: satTilesFor('eox', ly), maxzoom: satMaxzoom('eox', ly), attribution: satAttributionFor('eox', ly), shown: null };
  }
  const c = esriChoice(year, site);
  return { prov, id: esriLayerId(c.release), tiles: esriTiles(c.release), maxzoom: c.maxzoom, attribution: esriAttribution(), release: c.release, shown: { date: c.date, captured: c.captured, nearest: c.nearest, zoomIn: !!c.captured && c.minzoom != null && tz != null && tz < c.minzoom } };
}
function showSatellite(m: MlMap, spec: SatSpec) {
  const { prov, id } = spec;
  if (satProv.get(m) !== prov) { clearSatellite(m); satProv.set(m, prov); }
  satWanted.set(m, id);
  satRecent.set(m, [...(satRecent.get(m) ?? []).filter((x) => x !== id), id]);
  const top = satTop(m);
  // fast clicking: layers still loading for an earlier click (visible, under the shown one) stop loading
  for (const x of satIds(m)) if (x !== top && x !== id && satVisible(m, x)) m.setLayoutProperty(x, 'visibility', 'none');
  if (!m.getSource(id)) m.addSource(id, { type: 'raster', tiles: [spec.tiles], tileSize: 256, maxzoom: spec.maxzoom, attribution: spec.attribution });
  if (!m.getLayer(id)) {
    const road = m.getStyle().layers.find((l) => !OVERLAY_IDS.has(l.id) && !isSatLayerId(l.id) && /^(aeroway|road_|highway|railway)/.test(l.id))?.id;
    m.addLayer({ id, type: 'raster', source: id, layout: { visibility: 'visible' }, paint: { 'raster-fade-duration': 0 } }, top ?? (m.getLayer('ua-ground') ? 'ua-ground' : road));
  } else {
    if (top && top !== id) m.moveLayer(id, top);
    m.setPaintProperty(id, 'raster-opacity-transition', { duration: 0, delay: 0 });
    m.setPaintProperty(id, 'raster-opacity', 1);
    m.setLayoutProperty(id, 'visibility', 'visible');
  }
  if (prov === 'esri') watchEsri(m);
  if (!top || top === id) { settleSatellite(m); return; } // nothing to cover: it simply draws in
  whenSatLoaded(m, id, () => settleSatellite(m));
}
function hideSatellite(m: MlMap) {
  satWanted.delete(m);
  stopEsriWatch(m);
  for (const id of satIds(m)) m.setLayoutProperty(id, 'visibility', 'none');
}
/** web-mercator tiles (256 px, as MapLibre asks for them at this map zoom) covering the view, at most `max` */
function viewTiles(m: MlMap, maxzoom: number, max: number): { z: number; x: number; y: number }[] | null {
  const z = Math.max(0, Math.min(maxzoom, Math.round(m.getZoom() + 1)));
  const b = m.getBounds();
  const a = tileOf(b.getWest(), b.getNorth(), z), c = tileOf(b.getEast(), b.getSouth(), z);
  const n = (c.x - a.x + 1) * (c.y - a.y + 1);
  if (n > max || n <= 0) return null;
  const out = [];
  for (let x = a.x; x <= c.x; x++) for (let y = a.y; y <= c.y; y++) out.push({ z, x, y });
  return out;
}
/**
 * Warm the HTTP cache (Wayback tiles: max-age 1 day) with the view's tiles of the neighbouring years' versions, so the
 * next year click swaps at once. Plain fetches (as MapLibre makes them), no extra raster sources on the map.
 */
const prefetched = new Set<string>();
function prefetchSat(m: MlMap, specs: SatSpec[], signal: AbortSignal) {
  for (const sp of specs) {
    const ts = viewTiles(m, sp.maxzoom, 60);
    if (!ts) continue;
    for (const t of ts) {
      const url = sp.tiles.replace('{z}', String(t.z)).replace('{y}', String(t.y)).replace('{x}', String(t.x));
      if (prefetched.has(url)) continue;
      prefetched.add(url);
      fetch(url, { signal }).then((r) => r.blob()).catch(() => prefetched.delete(url));
    }
  }
}
/** the «Супутник: Esri World Imagery, версія архіву 2019-09» line stacked above the attribution (bottom-right corner) */
class SatCaption implements maplibregl.IControl {
  el = document.createElement('div');
  onAdd() { this.el.className = 'maplibregl-ctrl sat-cap'; this.el.dataset.testid = 'sat-caption'; this.el.hidden = true; return this.el; }
  onRemove() { this.el.remove(); }
  set(text: string | null) { this.el.hidden = text == null; this.el.textContent = text ?? ''; }
}
const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] };
const KYIV: [number, number] = [30.6, 50.43];
maplibregl.setWorkerUrl(workerUrl);

const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888';
const fc = (g: ZoneGeometry | Polygon | null): FeatureCollection | Feature =>
  g ? { type: 'Feature', properties: {}, geometry: g } : EMPTY;

export interface MapHotspot { center: [number, number]; tip: string; polygon?: Polygon | MultiPolygon }

export interface MapViewProps {
  theme: Theme;
  geometry: ZoneGeometry | null;
  label: string | null;
  cityGeometry: ZoneGeometry | null;
  layer: string;
  year: number | null;
  tiles: boolean;
  leftInset: number;
  draw: DrawMode;
  onDrawn: (p: Polygon) => void;
  onDrawCancel: () => void;
  mapRef: MutableRefObject<MlMap | null>;
  /** hottest spots inside the zone (numbered like the card list), with their tooltip text and optional outline */
  hotspots?: MapHotspot[];
  /** dots only on the gap / temperature layers, not on greenery */
  showHotspots?: boolean;
  /** changes when the UI chrome over the map changes (strip shown / compact): re-fit the zoom-out limit */
  chrome?: string;
  /** the card is collapsed: the light-theme wash is off */
  exploring?: boolean;
  /** country markers (MAP-TASKS 3): places from /api/overview, the gap stops of the current theme, click → open */
  overview?: Overview | null;
  gapStops?: ColorStop[];
  onPickPlace?: (p: OverviewPlace) => void;
  /** true while the map is below z9 (markers instead of the raster) */
  onOverviewZoom?: (low: boolean) => void;
  /** item 9: the display-only fill layer for the current layer (`gap_fill` / `lst_fill`), or null */
  fillLayer?: string | null;
  /** Роман 15.11: a click on a basemap settlement / district name (not while drawing) */
  onPickLabel?: (l: MapLabel) => void;
}

export function MapView(props: MapViewProps) {
  const { theme, geometry, label, cityGeometry, layer, year, tiles, leftInset, draw, onDrawn, onDrawCancel, mapRef, hotspots, showHotspots = true, chrome, exploring = false, overview, gapStops, onPickPlace, onOverviewZoom, fillLayer, onPickLabel } = props;
  const el = useRef<HTMLDivElement>(null);
  const spot = useRef<HTMLDivElement>(null);
  const pin = useRef<maplibregl.Marker | null>(null);
  const hotPopup = useRef<maplibregl.Popup | null>(null);
  const cbs = useRef({ onDrawn, onDrawCancel });
  cbs.current = { onDrawn, onDrawCancel };
  const heatUrl = tiles && year ? tileUrl(layer, year, theme) : null;
  const fillUrl = tiles && year && fillLayer ? tileUrl(fillLayer, year, theme) : null;
  // item 13: «Лише забудова» overlay over gap/lst when meta has it
  const ui = useMapUi();
  const locale = useLocale();
  const nbMeta = tiles ? ui.nonbuilt : null;
  const nbUrl = nbMeta && year && muteApplies({ ...ui, nonbuilt: nbMeta, layer }) ? tileUrl('nonbuilt', year, theme) : null;
  useEffect(() => { setMapUi({ layer }); }, [layer]);
  // latest overlay data, re-installed after every basemap style swap
  const hotFc = (pts: MapHotspot[] | undefined): FeatureCollection => ({
    type: 'FeatureCollection',
    features: (pts ?? []).flatMap((h, i): Feature[] => [
      { type: 'Feature', properties: { n: String(i + 1), tip: h.tip }, geometry: { type: 'Point', coordinates: h.center } },
      ...(h.polygon ? [{ type: 'Feature' as const, properties: { n: String(i + 1), tip: h.tip }, geometry: h.polygon }] : []),
    ]),
  });
  const overlays = useRef<Overlays | null>(null);
  const satCap = useRef<SatCaption | null>(null);
  /** imagery versions + capture dates at the probed place (lib/wayback.ts); null until probed / on EOX */
  const [satSite, setSatSite] = useState<SatSite | null>(null);
  const satSiteRef = useRef<SatSite | null>(null);
  satSiteRef.current = satSite;
  /** where the imagery is dated: the zone centre, else (no zone) the map centre at z ≥ 12, snapped to a z14 tile */
  const [viewPoint, setViewPoint] = useState<[number, number] | null>(null);
  const [tileZoom, setTileZoom] = useState<number | undefined>(undefined);
  const yearRef = useRef(year);
  yearRef.current = year;
  /** marker mode below this zoom (R-MAP-1: lower while a big zone is open) */
  const ovZ = useRef(OVERVIEW_Z);
  /** item 20 D: the reference-forest outline of the current report (empty unless «Показати ліс-еталон») */
  const refFc = useRef<FeatureCollection>(EMPTY);
  // MAP-TASKS 24: the report's zone clipped to Ukraine replaces the drawn/preset shape for the outline and the wash
  const shape = useMemo(() => zoneShape(geometry, ui.zoneOutline), [geometry, ui.zoneOutline]);
  const data = useRef({ geometry, shape, cityGeometry, heatUrl, fillUrl, nbUrl, label, leftInset, hotspots, showHotspots, overview, gapStops, onPickPlace, onOverviewZoom, exploring, draw, onPickLabel });
  data.current = { geometry, shape, cityGeometry, heatUrl, fillUrl, nbUrl, label, leftInset, hotspots, showHotspots, overview, gapStops, onPickPlace, onOverviewZoom, exploring, draw, onPickLabel };
  const ovFc = () => {
    const d = data.current;
    return d.overview ? overviewFeatures(d.overview.places, d.gapStops ?? [], overlays.current, document.documentElement.dataset.theme === 'dark') : EMPTY;
  };

  /** Add our sources/layers on top of the basemap: heat + wash below labels, outlines above. */
  const installOverlay = (m: MlMap) => {
    applyOverviewZoom(m); // R-MAP-1: layers below are created with the open zone's switch zoom
    const d = data.current;
    // insert heat + wash right below the trailing block of label layers (all basemap fills/lines stay below)
    const layers = m.getStyle().layers.filter((l) => !OVERLAY_IDS.has(l.id) && !isSatLayerId(l.id));
    let cut = layers.length;
    while (cut > 0 && layers[cut - 1]!.type === 'symbol') cut -= 1;
    const firstSymbol = layers[cut]?.id;
    const add = (l: LayerSpecification, below?: string) => { if (!m.getLayer(l.id)) m.addLayer(l, below); };
    if (!m.getSource('zone')) m.addSource('zone', { type: 'geojson', data: fc(d.shape) });
    if (!m.getSource('mask')) m.addSource('mask', { type: 'geojson', data: fc(d.shape ? maskPolygon(d.shape) : null) });
    if (!m.getSource('city')) m.addSource('city', { type: 'geojson', data: fc(d.cityGeometry) });
    if (!m.getSource('draft')) m.addSource('draft', { type: 'geojson', data: EMPTY });
    if (d.heatUrl && !m.getSource('heat'))
      m.addSource('heat', { type: 'raster', tiles: [retryingTileUrl(d.heatUrl)], tileSize: tileOptions.tileSize, maxzoom: tileOptions.maxzoom }); // credit in Details › credits (map attribution keeps only the licence-required OSM/OpenFreeMap/EOX)
    // heat goes under the roads/rails (they are drawn over it, semi-transparent) so streets stay readable (MAP-TASKS 5)
    const firstRoad = layers.find((l) => /^(aeroway|road_|highway|railway)/.test(l.id))?.id ?? firstSymbol;
    // Ukraine «ground» under the heat: transparent tile pixels (= no data) show a soft hatch, not a black hole
    const dark = document.documentElement.dataset.theme === 'dark';
    if (!m.getSource('ua')) m.addSource('ua', { type: 'geojson', data: uaFeatures(overlays.current?.ukraine.geometry) });
    if (!m.hasImage('nodata-hatch')) m.addImage('nodata-hatch', hatchImage(dark), { pixelRatio: 2 });
    // item 7a: satellite imagery (Esri World Imagery Wayback; EOX Sentinel-2 cloudless as the fallback) over the basemap fills, under the hatch/heat/roads/labels;
    // the source is only added once satellite is switched on (no requests otherwise)
    const u = getMapUi();
    if (u.basemap === 'sat') showSatellite(m, satSpec(satProviderOf(u.satEox), yearRef.current, satSiteRef.current));
    add({ id: 'ua-ground', type: 'fill', source: 'ua', minzoom: ovZ.current, filter: ['has', 'border'], layout: { visibility: u.basemap === 'sat' ? 'none' : 'visible' }, paint: { 'fill-pattern': 'nodata-hatch', 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 8, 0, 10, 1] } }, firstRoad);
    // the sea/rivers inside Ukraine's (maritime) outline stay plain water: a copy of the water fill over the hatch
    const water = layers.find((l) => l.id === 'water');
    if (water?.type === 'fill') add({ ...water, id: 'ua-water', layout: { ...(water.layout ?? {}), visibility: u.basemap === 'sat' ? 'none' : 'visible' } } as LayerSpecification, firstRoad);
    // MAP-TASKS 3: below z9 the country markers replace the raster. No fade (board item 10: no half-faded frame to re-show)
    if (d.fillUrl && !m.getSource('heatfill'))
      m.addSource('heatfill', { type: 'raster', tiles: [retryingTileUrl(d.fillUrl)], tileSize: tileOptions.tileSize, maxzoom: tileOptions.maxzoom });
    if (d.fillUrl) add({ id: 'heat-fill', type: 'raster', source: 'heatfill', minzoom: ovZ.current, paint: { ...(dark ? {} : LIGHT_RASTER), 'raster-opacity': fillOpacity(layerT(u.heatTransparency, u.layer)), 'raster-fade-duration': 0 } }, firstRoad);
    if (d.heatUrl) add({ id: 'heat', type: 'raster', source: 'heat', minzoom: ovZ.current, paint: { ...(dark ? {} : LIGHT_RASTER), 'raster-opacity': heatOpacity(layerT(u.heatTransparency, u.layer)), 'raster-fade-duration': 0 } }, firstRoad);
    // item 13: dim non-built land over the heat (raster-opacity = the slider)
    if (d.nbUrl && !m.getSource('nonbuilt'))
      m.addSource('nonbuilt', { type: 'raster', tiles: [retryingTileUrl(d.nbUrl)], tileSize: tileOptions.tileSize, maxzoom: tileOptions.maxzoom });
    if (d.nbUrl) add({ id: 'nonbuilt', type: 'raster', source: 'nonbuilt', minzoom: ovZ.current, paint: { 'raster-opacity': veilOpacity(u), 'raster-fade-duration': 0 } }, firstRoad);
    // MAP-TASKS 4: no-LST areas (soft hatch + label), war oblasts (thin dashed outline), optional occupied territory
    const o = overlays.current;
    if (!m.getSource('nolst')) m.addSource('nolst', { type: 'geojson', data: o?.no_lst ?? EMPTY });
    if (!m.getSource('war')) m.addSource('war', { type: 'geojson', data: o?.war_regions ?? EMPTY });
    // the occupied-areas source (Мінрозвитку order No. 376) is credited in Details › credits, not on the map
    if (!m.getSource('occ')) m.addSource('occ', { type: 'geojson', data: o?.occupied?.features?.length ? o.occupied : EMPTY });
    if (!m.hasImage('nolst-hatch')) m.addImage('nolst-hatch', lineHatch(dark ? [150, 160, 190] : [90, 96, 110], dark ? 120 : 110, 1), { pixelRatio: 2 });
    if (!m.hasImage('occ-hatch')) m.addImage('occ-hatch', lineHatch(dark ? [170, 172, 180] : [110, 112, 120], dark ? 110 : 100, -1), { pixelRatio: 2 });
    add({ id: 'nolst-fill', type: 'fill', source: 'nolst', paint: { 'fill-pattern': 'nolst-hatch' } }, firstRoad);
    // no_scenes: the map year's swath with too few clear scenes (cross-hatch; only the feature of the shown year)
    if (!m.getSource('noscn')) m.addSource('noscn', { type: 'geojson', data: o?.no_scenes ?? EMPTY });
    if (!m.hasImage('noscn-hatch')) m.addImage('noscn-hatch', crossHatch(dark ? [170, 180, 210] : [80, 86, 100], dark ? 110 : 100), { pixelRatio: 2 });
    add({ id: 'noscn-fill', type: 'fill', source: 'noscn', filter: ['==', ['get', 'year'], yearRef.current ?? -1], paint: { 'fill-pattern': 'noscn-hatch' } }, firstRoad);
    add({ id: 'occ-fill', type: 'fill', source: 'occ', paint: { 'fill-pattern': 'occ-hatch' } }, firstSymbol);
    add({ id: 'war-line', type: 'line', source: 'war', paint: { 'line-color': dark ? '#e0b45c' : '#9a6a12', 'line-opacity': 0.7, 'line-width': 1.2, 'line-dasharray': [3, 2] }, layout: { 'line-join': 'round' } }, firstSymbol);
    add({ id: 'war-hit', type: 'line', source: 'war', paint: { 'line-color': '#000', 'line-opacity': 0, 'line-width': 12 } }, firstSymbol);
    add({ id: 'mask', type: 'fill', source: 'mask', paint: { 'fill-color': cssVar('--wash'), 'fill-opacity': MASK_OPACITY, 'fill-opacity-transition': { duration: 0, delay: 0 }, 'fill-antialias': false } }, firstSymbol);
    // MAP-TASKS 2: the rest of the world under a semi-transparent veil (neighbours stay faintly visible), Ukraine's border as a thin light line
    add({ id: 'veil', type: 'fill', source: 'ua', filter: ['!', ['has', 'border']], paint: { 'fill-color': dark ? '#050813' : '#5b6170', 'fill-opacity': dark ? 0.5 : 0.22, 'fill-antialias': false } }, firstSymbol);
    add({ id: 'ua-border', type: 'line', source: 'ua', filter: ['has', 'border'], paint: { 'line-color': dark ? '#c9d3ee' : '#4a5160', 'line-opacity': dark ? 0.75 : 0.6, 'line-width': ['interpolate', ['linear'], ['zoom'], 5, 1, 10, 1.6] }, layout: { 'line-join': 'round' } });
    add({ id: 'city', type: 'line', source: 'city', paint: { 'line-color': cssVar('--ink'), 'line-opacity': 0.45, 'line-width': 1.5, 'line-dasharray': [3, 3] } });
    // item 20 D: reference forest — above the outside wash (it lies outside the zone), below the zone outline and labels
    if (!m.getSource('reference')) m.addSource('reference', { type: 'geojson', data: refFc.current });
    const refColor = REFERENCE_COLOR[document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'];
    add({ id: 'ref-fill', type: 'fill', source: 'reference', minzoom: ovZ.current, paint: { 'fill-color': refColor, 'fill-opacity': 0.14 } }, firstSymbol);
    add({ id: 'ref-line', type: 'line', source: 'reference', minzoom: ovZ.current, paint: { 'line-color': refColor, 'line-width': 1.6, 'line-dasharray': [3, 2] }, layout: { 'line-join': 'round' } }, firstSymbol);
    add({ id: 'zone-halo', type: 'line', source: 'zone', paint: { 'line-color': cssVar('--halo'), 'line-width': 9 }, layout: { 'line-join': 'round' } });
    add({ id: 'zone-line', type: 'line', source: 'zone', paint: { 'line-color': cssVar('--ink'), 'line-width': 3.5 }, layout: { 'line-join': 'round' } });
    if (!m.getSource('hot')) m.addSource('hot', { type: 'geojson', data: hotFc(d.hotspots) });
    const vis = d.showHotspots ? 'visible' : 'none';
    // backend polygons (when present): thin outline of the hot area under the numbered dot
    add({ id: 'hot-area', type: 'line', source: 'hot', filter: ['!=', ['geometry-type'], 'Point'], layout: { visibility: vis, 'line-join': 'round' }, paint: { 'line-color': cssVar('--heat'), 'line-width': 1.5, 'line-dasharray': [2, 1] } });
    add({ id: 'hot-dot', type: 'circle', source: 'hot', filter: ['==', ['geometry-type'], 'Point'], layout: { visibility: vis }, paint: { 'circle-radius': 9, 'circle-color': cssVar('--heat'), 'circle-stroke-color': cssVar('--surf'), 'circle-stroke-width': 2 } });
    // numbers use the basemap's own font (other fonts are not on its glyph server)
    const font = m.getStyle().layers.map((l) => (l.type === 'symbol' ? m.getLayoutProperty(l.id, 'text-font') : undefined)).find((f) => Array.isArray(f)) as string[] | undefined;
    add({ id: 'hot-num', type: 'symbol', source: 'hot', filter: ['==', ['geometry-type'], 'Point'], layout: { visibility: vis, 'text-field': ['get', 'n'], 'text-size': 12, 'text-allow-overlap': true, 'text-ignore-placement': true, ...(font ? { 'text-font': font } : {}) }, paint: { 'text-color': '#ffffff' } });
    add({ id: 'draft-fill', type: 'fill', source: 'draft', filter: ['==', '$type', 'Polygon'], paint: { 'fill-color': cssVar('--heat'), 'fill-opacity': 0.12 } });
    add({ id: 'draft-line', type: 'line', source: 'draft', filter: ['!=', '$type', 'Point'], paint: { 'line-color': cssVar('--heat'), 'line-width': 2.5, 'line-dasharray': [2, 1] } });
    add({ id: 'draft-pts', type: 'circle', source: 'draft', filter: ['==', '$type', 'Point'], paint: { 'circle-radius': 5, 'circle-color': cssVar('--surf'), 'circle-stroke-color': cssVar('--heat'), 'circle-stroke-width': 2.5 } });
    // MAP-TASKS 3: country markers below z9 (districts from z8); label collisions resolved by rank (lower = first)
    if (!m.getSource('ov')) m.addSource('ov', { type: 'geojson', data: ovFc() });
    if (!m.hasImage('ov-pill')) m.addImage('ov-pill', pillSdf(), { sdf: true, pixelRatio: 2 });
    const ovLayer = (id: string, district: boolean): LayerSpecification => ({
      id, type: 'symbol', source: 'ov', maxzoom: ovZ.current, ...(district ? { minzoom: Math.min(8, ovZ.current - 1) } : {}),
      filter: ['==', ['get', 'district'], district],
      layout: {
        'icon-image': 'ov-pill',
        'text-field': ['get', 'label'], 'text-size': 13, 'symbol-sort-key': ['get', 'rank'], 'text-padding': 4,
        ...(font ? { 'text-font': font } : {}),
      },
      paint: {
        'icon-color': ['get', 'color'], 'text-color': ['get', 'ink'],
        // war regions: an amber outline as a caveat; no-data: a quiet grey pill
        'icon-halo-color': ['case', ['==', ['get', 'kind'], 'war'], dark ? '#e0b45c' : '#9a6a12', dark ? '#0b0f1a' : '#ffffff'],
        'icon-halo-width': ['case', ['==', ['get', 'kind'], 'war'], 2, 1],
      },
    });
    // labels only on the larger areas (≈ 100 polygons would repeat the sentence everywhere); hover works on all
    add({ id: 'nolst-label', type: 'symbol', source: 'nolst', minzoom: 7, filter: ['>=', ['coalesce', ['get', 'area_km2'], 0], 300], layout: { 'text-field': nolstText(getLocale()), 'text-size': 12, 'text-max-width': 10, ...(font ? { 'text-font': font } : {}) }, paint: { 'text-color': dark ? '#c9d0e0' : '#4a5160', 'text-halo-color': dark ? '#141a2a' : '#ffffff', 'text-halo-width': 1.5 } });
    add({ id: 'noscn-label', type: 'symbol', source: 'noscn', minzoom: 7, filter: ['==', ['get', 'year'], yearRef.current ?? -1], layout: { 'text-field': noscnText(getLocale()), 'text-size': 12, 'symbol-placement': 'line', 'symbol-spacing': 420, 'text-keep-upright': true, ...(font ? { 'text-font': font } : {}) }, paint: { 'text-color': dark ? '#c9d0e0' : '#4a5160', 'text-halo-color': dark ? '#141a2a' : '#ffffff', 'text-halo-width': 1.5 } });
    add(ovLayer('ov-district', true));
    add(ovLayer('ov-city', false));
    // basemap ground in the F7 page colour so the map sits in the design palette
    if (m.getLayer('background')) m.setPaintProperty('background', 'background-color', dark ? DARK_BASEMAP.background! : LIGHT_GROUND);
    // MAP-TASKS 5: a brighter dark basemap — land above the page colour, blue water, visible roads and borders
    if (dark) for (const [id, paint] of Object.entries(DARK_PAINT)) if (m.getLayer(id)) for (const [k, v] of Object.entries(paint)) m.setPaintProperty(id, k as "fill-color", v);
    // roads/rails sit above the heat now: semi-transparent so the colours underneath stay readable
    for (const l of layers) if (l.type === 'line' && /^(highway|railway|road_|aeroway)/.test(l.id)) m.setPaintProperty(l.id, 'line-opacity', dark ? 0.6 : 0.55);
    // larger place labels at country / region zoom (MAP-TASKS 5 d)
    for (const [id, size] of Object.entries(LABEL_SIZE)) if (m.getLayer(id)) m.setLayoutProperty(id, 'text-size', size);
    // naming/border policy: no Russian-imposed entities on Ukrainian territory, no claim line cutting Crimea off
    for (const l of layers) {
      if (l.type === 'symbol' && 'source-layer' in l && l['source-layer'] === 'place') m.setFilter(l.id, withoutImposed(l.filter));
      if (l.type === 'line' && 'source-layer' in l && l['source-layer'] === 'boundary') {
        if (DISPUTED_LAYERS.includes(l.id)) m.setLayoutProperty(l.id, 'visibility', 'none');
        else m.setFilter(l.id, undisputedBorder(l.filter));
      }
    }
    // Ukrainian place names where OSM has them (English / Latin ones in the English UI)
    for (const l of m.getStyle().layers)
      if (l.type === 'symbol' && !OVERLAY_IDS.has(l.id) && m.getLayoutProperty(l.id, 'text-field')) {
        m.setLayoutProperty(l.id, 'text-field', placeName(getLocale()));
        // labels must stay readable over the heat layer (QA-25): ink text on a page-colour halo
        // dark (UX-14/QA-25): near-white text on the darkest surface with a wider, slightly blurred halo
        if (dark) m.setPaintProperty(l.id, 'text-color', l.id === 'water_name' ? '#9dbbe0' : cssVar('--ink'));
        m.setPaintProperty(l.id, 'text-halo-color', cssVar(dark ? '--surf' : '--bg'));
        m.setPaintProperty(l.id, 'text-halo-width', dark ? 2.2 : 1.6);
        if (dark) m.setPaintProperty(l.id, 'text-halo-blur', 0.6);
      }
  };

  /** F7 spotlight: the map stays vivid around the zone and fades into the page wash further out. */
  const updateSpot = (m: MlMap) => {
    const g = data.current.geometry;
    const div = spot.current;
    if (!div) return;
    if (!g) { div.style.background = 'none'; return; }
    const [w, s, e, n] = bbox(g);
    const a = m.project([w, n]);
    const b = m.project([e, s]);
    // board item 10: wash and mask fade CONTINUOUSLY with the zone's distance from the viewport (a binary
    // in-view switch flashed the whole map 49 → 98 luma within one 40 px drag step near the edge).
    const cw = m.getContainer().clientWidth, chh = m.getContainer().clientHeight;
    // marker mode (below z9): no wash at all, so markers far from the zone read like the rest (fades in z8 → z9)
    const wash = washFactor({ dark: document.documentElement.dataset.theme === 'dark', sat: getMapUi().basemap === 'sat', exploring: !!data.current.exploring });
    const k = spotFactor([a.x, a.y, b.x, b.y], cw, chh) * Math.max(0, Math.min(1, m.getZoom() - (ovZ.current - 1))) * wash;
    if (m.getLayer('mask')) {
      const want = +(MASK_OPACITY * k).toFixed(3);
      const cur = m.getPaintProperty('mask', 'fill-opacity');
      if (typeof cur !== 'number' || Math.abs(cur - want) >= 0.01) m.setPaintProperty('mask', 'fill-opacity', want);
    }
    if (k <= 0) { div.style.background = 'none'; div.style.opacity = '0'; return; }
    div.style.opacity = k.toFixed(3);
    const cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2;
    const r = Math.max(110, Math.hypot(b.x - a.x, b.y - a.y) / 2 + 60);
    div.style.background = `radial-gradient(circle at ${cx.toFixed(0)}px ${cy.toFixed(0)}px, transparent 0, transparent ${r.toFixed(0)}px, var(--wash) ${(r + 300).toFixed(0)}px)`;
  };

  const ready = (m: MlMap | null): m is MlMap => !!m && !!m.getSource('zone');

  /** strip legend line: the shown year's no-scenes swath is (partly) in view */
  const checkNoScenes = (m: MlMap) => {
    const f = m.getLayer('noscn-fill') ? m.queryRenderedFeatures({ layers: ['noscn-fill'] })[0] : undefined;
    setMapUi({ noScenes: (f?.properties?.label_uk as string | undefined) ?? null });
  };

  /** R-MAP-1: recompute the marker/raster switch zoom for the open zone and apply it to the layers */
  const applyOverviewZoom = (m: MlMap) => {
    const { geometry: g, leftInset: inset } = data.current;
    const c = m.getContainer();
    const z = overviewZoom(g ? frameCamera(bbox(g), c.clientWidth, c.clientHeight, inset, occluders(c)).zoom : null);
    if (Math.abs(z - ovZ.current) < 0.01) return;
    ovZ.current = z;
    for (const id of RASTER_IDS) if (m.getLayer(id)) m.setLayerZoomRange(id, z, 24);
    if (m.getLayer('ov-city')) m.setLayerZoomRange('ov-city', 0, z);
    if (m.getLayer('ov-district')) m.setLayerZoomRange('ov-district', Math.min(8, z - 1), z);
    m.fire('zoom'); // re-evaluate the strip's marker-mode band
    updateSpot(m);
  };

  const placePin = (m: MlMap) => {
    pin.current?.remove();
    pin.current = null;
    const { geometry: g, label: text } = data.current;
    if (!g || !text) return;
    const [w, , e, n] = bbox(g);
    const div = document.createElement('div');
    div.className = 'pin';
    div.textContent = text;
    div.setAttribute('aria-hidden', 'true');
    pin.current = new maplibregl.Marker({ element: div, anchor: 'bottom', offset: [0, -14] }).setLngLat([(w + e) / 2, n]).addTo(m);
  };

  /** Frame the zone in the free part of the screen (right of the panel), leaving context around it as in F7. */
  const frame = (m: MlMap, duration: number) => {
    const { geometry: g, leftInset: inset } = data.current;
    if (!g) return;
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const c = m.getContainer();
    m.flyTo({ ...frameCamera(bbox(g), c.clientWidth, c.clientHeight, inset, occluders(c)), duration: reduce ? 0 : duration, essential: false });
  };

  // init once
  useEffect(() => {
    if (!el.current) return;
    let map: MlMap;
    try {
      ensureTileProtocol();
      map = new maplibregl.Map({
        container: el.current,
        style: BASEMAP[theme],
        center: KYIV,
        zoom: 10.5,
        attributionControl: { compact: true },
        dragRotate: false,
        // MAP-TASKS 1: Ukraine only — zooming out stops when all of Ukraine is visible, panning stays around it
        ...(({ zoom, bounds }) => ({ minZoom: zoom, maxBounds: bounds }))(viewLimits(el.current.clientWidth || 1280, el.current.clientHeight || 720, leftInset)),
        pitchWithRotate: false,
        fadeDuration: 0,
      });
    } catch {
      el.current.dataset.nomap = '1'; // WebGL unavailable — the rest of the UI still works.
      return;
    }
    // MapLibre's compact credit starts expanded: collapse it to the ⓘ button once (it expands on click)
    const box = el.current;
    map.once('load', () => {
      const at = box.querySelector('.maplibregl-ctrl-attrib');
      at?.removeAttribute('open');
      at?.classList.remove('maplibregl-compact-show');
    });
    map.touchZoomRotate.disableRotation();
    map.keyboard.disableRotation();
    map.getCanvas().setAttribute('aria-label', tr(getLocale(), 'map.canvasAria'));
    mapRef.current = map;
    satCap.current = new SatCaption();
    map.addControl(satCap.current, 'bottom-right');
    satCap.current.set(getMapUi().basemap === 'sat' ? satCaption(getLocale(), yearRef.current, satProviderOf(getMapUi().satEox), satSpec(satProviderOf(getMapUi().satEox), yearRef.current, null).shown) : null);
    const centrePoint = () => {
      setTileZoom(Math.round(map.getZoom() + 1));
      if (map.getZoom() < 12) { setViewPoint(null); return; }
      const c = map.getCenter();
      const t = tileOf(c.lng, c.lat, 14);
      setViewPoint((p) => { const q = tileCentre(t); return p && p[0] === q[0] && p[1] === q[1] ? p : q; });
    };
    map.on('moveend', centrePoint);
    map.once('load', centrePoint);
    if (import.meta.env.DEV) (window as unknown as { __uhdMap?: MlMap }).__uhdMap = map; // dev-only handle for visual checks
    map.on('move', () => updateSpot(map));
    map.on('resize', () => applyLimits(map));
    // 1b: the panning box depends on the zoom (the free-area half-size in degrees)
    map.on('zoom', () => applyLimits(map));
    limitsMap = map;
    map.once('load', () => applyLimits(map));
    // fully zoomed out: drop the zone-framing padding and settle on Ukraine centred right of the card
    map.on('zoomend', (e) => {
      const p = map.getPadding();
      if ((e as { originalEvent?: unknown }).originalEvent && map.getZoom() <= map.getMinZoom() + 0.05 && (p.top || p.bottom || p.left || p.right)) showAllUkraine(map, 300);
    });
    // one tooltip for the country layers: markers, no-LST areas, war outlines, occupied territory
    const info = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12, className: 'hot-pop', maxWidth: '300px' });
    // outside Ukraine: say why there is nothing there
    const veilTip = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 14, className: 'hot-pop veil-pop' });
    // one tooltip at a time (mentor review, Simferopol): a hotspot marker wins over every area tooltip under it
    const overHot = (pt: maplibregl.PointLike) => !!map.getLayer('hot-dot') && map.queryRenderedFeatures(pt, { layers: ['hot-dot'] }).length > 0;
    map.on('mousemove', 'veil', (e) => {
      if (overHot(e.point)) { veilTip.remove(); return; }
      veilTip.setText(tr(getLocale(), 'map.veil')).setLngLat(e.lngLat).addTo(map);
    });
    map.on('mouseleave', 'veil', () => veilTip.remove());
    // hotspot tooltip: hover on desktop, tap on touch
    const showTip = (e: maplibregl.MapLayerMouseEvent) => {
      const f = e.features?.[0];
      const tip = f?.properties?.tip as string | undefined;
      if (!f || !tip || f.geometry.type !== 'Point') return;
      map.getCanvas().style.cursor = 'pointer';
      info.remove();
      veilTip.remove();
      hotPopup.current ??= new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12, className: 'hot-pop', maxWidth: '280px' });
      hotPopup.current.setLngLat(f.geometry.coordinates as [number, number]).setText(tip).addTo(map);
    };
    map.on('mouseenter', 'hot-dot', showTip);
    map.on('click', 'hot-dot', showTip);
    map.on('mouseleave', 'hot-dot', () => { map.getCanvas().style.cursor = ''; hotPopup.current?.remove(); });
    map.on('style.load', () => {
      installOverlay(map);
      placePin(map);
      el.current?.setAttribute('data-ready', '1');
      frame(map, 0);
    });
    // MAP-TASKS 2/4: Ukraine outline (veil + border), no-data hatch, war outline — from GET /api/overlays
    void getOverlays().then((o) => {
      if (!o || mapRef.current !== map) return;
      overlays.current = o;
      (map.getSource('ua') as GeoJSONSource | undefined)?.setData(uaFeatures(o.ukraine.geometry));
      (map.getSource('nolst') as GeoJSONSource | undefined)?.setData(o.no_lst);
      if (o.no_scenes) (map.getSource('noscn') as GeoJSONSource | undefined)?.setData(o.no_scenes);
      (map.getSource('war') as GeoJSONSource | undefined)?.setData(o.war_regions);
      // occupied: optional; its source goes into the attribution, so the source is (re)added with it
      if (o.occupied?.features?.length && map.getSource('occ')) {
        if (map.getLayer('occ-fill')) map.removeLayer('occ-fill');
        map.removeSource('occ');
        installOverlay(map);
      }
      (map.getSource('ov') as GeoJSONSource | undefined)?.setData(ovFc()); // war caveat texts in the marker tips
    });
    // one tooltip for the country layers: markers, no-LST areas, war outlines, occupied territory (declared above)
    const tipFor: Record<string, (p: Record<string, unknown>) => string | undefined> = {
      'ov-city': (p) => p.tip as string, 'ov-district': (p) => p.tip as string,
      'nolst-fill': (p) => srv(p, 'label', getLocale()) ?? tr(getLocale(), 'map.noLst'),
      'noscn-fill': (p) => srv(p, 'label', getLocale()),
      // war: text_en is null until science writes it; then a neutral English line from the region's name, never the uk text
      'war-hit': (p) => (getLocale() === 'en' ? str(p.text_en) ?? (p.since ? tr('en', 'map.markerWar', { region: str(p.name_en) ?? String(p.name ?? ''), since: String(p.since) }) : undefined) : str(p.text_uk)),
      'occ-fill': (p) => srv(p, 'label', getLocale()),
    };
    for (const [id, f] of Object.entries(tipFor)) {
      map.on('mousemove', id, (e) => {
        // a zone hotspot marker has its own tooltip (hotPopup) — never stack the area text under it
        if (overHot(e.point)) { info.remove(); return; }
        // markers win over areas under them
        const hits = map.queryRenderedFeatures(e.point, { layers: Object.keys(tipFor).filter((l) => map.getLayer(l)) });
        const top = hits[0];
        if (top?.layer.id !== id) return;
        let texts: string[];
        if (id.startsWith('ov-')) {
          const text = f(top.properties ?? {});
          if (!text) return;
          // board item 22 (TOOLTIPS §3 map canvas): the glossary line goes under the marker text on the first hover per session
          const extra = firstTimeGlossary(top.properties?.kind === 'nodata' ? 'markerNoData' : 'countryMarkers');
          texts = extra ? [text, extra] : [text];
        } else {
          // R-MAP-3: overlapping areas (occupied over no-LST, a no-scenes swath, a war oblast) — every text, in AREA_ORDER
          texts = [...new Set(AREA_ORDER.map((l) => hits.find((h) => h.layer.id === l)).map((h) => (h ? tipFor[h.layer.id]!(h.properties ?? {}) : undefined)).filter((t): t is string => !!t))];
          if (!texts.length) return;
        }
        map.getCanvas().style.cursor = id.startsWith('ov-') ? 'pointer' : '';
        if (texts.length === 1) { info.setLngLat(e.lngLat).setText(texts[0]!).addTo(map); return; }
        const box = document.createElement('div');
        for (const t of texts) { const para = document.createElement('p'); para.className = 'pop-p'; para.textContent = t; box.appendChild(para); }
        info.setLngLat(e.lngLat).setDOMContent(box).addTo(map);
      });
      map.on('mouseleave', id, () => { map.getCanvas().style.cursor = ''; info.remove(); });
    }
    const pick = (e: maplibregl.MapLayerMouseEvent) => {
      const id = e.features?.[0]?.properties?.id as string | undefined;
      const p = data.current.overview?.places.find((x) => x.place_id === id);
      if (p) { info.remove(); data.current.onPickPlace?.(p); }
    };
    map.on('click', 'ov-city', pick);
    map.on('click', 'ov-district', pick);
    // Роман 15.11: basemap settlement / district names are clickable (markers, hotspots and drawing keep their own clicks)
    installLabelPick(map, LABEL_BLOCKERS, () => !data.current.draw && !!data.current.onPickLabel, (l) => { info.remove(); data.current.onPickLabel?.(l); });
    let low: boolean | null = null;
    const band = () => {
      const l = map.getZoom() < ovZ.current;
      if (l !== low) { low = l; data.current.onOverviewZoom?.(l); }
    };
    map.on('zoom', band);
    map.once('load', band);
    // board item 10: some Windows GPU drivers re-present a stale buffer while idle (vivid/dark flicker). After a camera
    // change or tile load, repaint once when the map goes idle — debounced, never in a loop; no preserveDrawingBuffer.
    let dirty = false;
    map.on('moveend', () => { dirty = true; });
    map.on('sourcedata', (e) => { if (e.sourceId === 'heat' && e.tile) dirty = true; });
    map.on('idle', () => { if (dirty) { dirty = false; map.triggerRepaint(); } });
    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // theme: swap basemap; the overlay is re-installed on style.load
  const shownTheme = useRef(theme);
  useEffect(() => {
    const m = mapRef.current;
    if (!m || shownTheme.current === theme) return;
    shownTheme.current = theme;
    el.current?.removeAttribute('data-ready');
    m.setStyle(BASEMAP[theme]);
  }, [theme, mapRef]);

  // hotspots
  const hotKey = JSON.stringify(hotspots ?? []);
  useEffect(() => {
    const m = mapRef.current;
    if (!ready(m)) return;
    (m.getSource('hot') as GeoJSONSource | undefined)?.setData(hotFc(hotspots));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hotKey]);
  useEffect(() => {
    const m = mapRef.current;
    if (!ready(m)) return;
    for (const id of ['hot-area', 'hot-dot', 'hot-num']) if (m.getLayer(id)) m.setLayoutProperty(id, 'visibility', showHotspots ? 'visible' : 'none');
    if (!showHotspots) hotPopup.current?.remove();
  }, [showHotspots, mapRef]);

  // heat tiles: layer / year / theme
  useEffect(() => {
    const m = mapRef.current;
    if (!ready(m)) return;
    // re-create the raster source instead of setTiles(): setTiles while the previous layer's tiles are still
    // loading sometimes never requests the new ones (seen when switching layers quickly)
    if (m.getSource('heat')) { if (m.getLayer('heat')) m.removeLayer('heat'); m.removeSource('heat'); }
    if (m.getSource('heatfill')) { if (m.getLayer('heat-fill')) m.removeLayer('heat-fill'); m.removeSource('heatfill'); }
    if (m.getSource('nonbuilt')) { if (m.getLayer('nonbuilt')) m.removeLayer('nonbuilt'); m.removeSource('nonbuilt'); }
    if (heatUrl) installOverlay(m);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [heatUrl, fillUrl, nbUrl]);

  // item 20 D: «Показати ліс-еталон» — load the current report's outline (cached per report id)
  const hasZone = !!geometry;
  useEffect(() => {
    const m = mapRef.current;
    const want = ui.showReference && hasZone && tiles ? ui.reportId : null;
    const put = (f: FeatureCollection) => { refFc.current = f; if (ready(m)) (m.getSource('reference') as GeoJSONSource | undefined)?.setData(f); };
    // Never keep the previous report's forest visible while the next one loads.
    put(EMPTY);
    if (!want) { setMapUi({ reference: 'idle' }); return; }
    let live = true;
    setMapUi({ reference: 'loading' });
    void getReference(want).then((f) => {
      if (!live) return;
      put(f ? { type: 'FeatureCollection', features: [f] } : EMPTY);
      setMapUi({ reference: f ? 'ok' : 'none' });
    });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ui.showReference, ui.reportId, hasZone, tiles]);

  // no_scenes: show the shown year's swath only; tell the strip whether it is in view
  useEffect(() => {
    const m = mapRef.current;
    if (!m) return;
    const f: maplibregl.FilterSpecification = ['==', ['get', 'year'], year ?? -1];
    const apply = () => {
      for (const id of ['noscn-fill', 'noscn-label']) if (m.getLayer(id)) m.setFilter(id, f);
      checkNoScenes(m);
    };
    if (ready(m)) apply();
    m.on('moveend', apply);
    m.on('idle', apply);
    return () => { m.off('moveend', apply); m.off('idle', apply); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [year, mapRef]);

  // the map year drives the satellite mosaic (strip / panel notes read it from mapUi); the caption sits by the attribution
  useEffect(() => { setMapUi({ mapYear: year }); }, [year]);
  // the place whose imagery is dated: the zone (its bbox centre), else the map centre (snapped, z ≥ 12)
  const satPoint = useMemo((): [number, number] | null => {
    if (shape) { const [w, s, e, n] = bbox(shape); return [(w + e) / 2, (s + n) / 2]; }
    return viewPoint;
  }, [shape, viewPoint]);
  const satProbe = ui.basemap === 'sat' && !ui.satEox && satPoint ? satPoint : null;
  useEffect(() => {
    if (!satProbe) { setSatSite(null); return; }
    const [lon, lat] = satProbe;
    let live = true;
    setSatSite(null);
    const on = (s: SatSite) => { if (live) setSatSite(s); };
    void probeSatSite(lon, lat, on);
    return () => { live = false; unprobe(lon, lat, on); };
  }, [satProbe?.[0], satProbe?.[1]]); // eslint-disable-line react-hooks/exhaustive-deps
  const satNow = useMemo(() => satSpec(satProviderOf(ui.satEox), year, satSite, tileZoom), [ui.satEox, year, satSite, tileZoom]);
  useEffect(() => {
    satCap.current?.set(ui.basemap === 'sat' ? satCaption(locale, year, satNow.prov, satNow.shown) : null);
    setMapUi({ satShown: ui.basemap === 'sat' ? satNow.shown : null });
  }, [ui.basemap, satNow, year, locale]);

  // «Шари» panel (item 7): basemap, heat transparency, non-built dimming
  useEffect(() => {
    const m = mapRef.current;
    if (!ready(m)) return;
    const sat = ui.basemap === 'sat';
    if (sat) showSatellite(m, satNow); else hideSatellite(m);
    // over imagery the no-data hatch and the water copy would hide the photo
    for (const id of ['ua-ground', 'ua-water']) if (m.getLayer(id)) m.setLayoutProperty(id, 'visibility', sat ? 'none' : 'visible');
    if (m.getLayer('heat')) m.setPaintProperty('heat', 'raster-opacity', heatOpacity(layerT(ui.heatTransparency, ui.layer)));
    if (m.getLayer('heat-fill')) m.setPaintProperty('heat-fill', 'raster-opacity', fillOpacity(layerT(ui.heatTransparency, ui.layer)));
    updateSpot(m); // the light wash is lighter over imagery
    if (m.getLayer('nonbuilt')) m.setPaintProperty('nonbuilt', 'raster-opacity', muteApplies(getMapUi()) ? veilOpacity(ui) : 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ui.basemap, satNow.id, ui.heatTransparency, ui.mute, ui.layer, year, mapRef]);

  // once every capture date is known: warm the cache with the neighbouring years' imagery for this view
  useEffect(() => {
    const m = mapRef.current;
    if (!ready(m) || ui.basemap !== 'sat' || satNow.prov !== 'esri' || !satSite?.complete || year == null) return;
    const ac = new AbortController();
    const go = () => {
      const near = [year - 1, year + 1].map((y) => satSpec('esri', y, satSite)).filter((sp, i, a) => sp.id !== satNow.id && a.findIndex((x) => x.id === sp.id) === i);
      prefetchSat(m, near, ac.signal);
    };
    const t = window.setTimeout(go, 1500); // after the shown layer has had its turn
    m.on('moveend', go);
    return () => { window.clearTimeout(t); m.off('moveend', go); ac.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ui.basemap, satNow.id, satSite?.complete, year, mapRef]);

  // the light wash follows the card: off while it is collapsed
  useEffect(() => {
    const m = mapRef.current;
    if (ready(m)) updateSpot(m);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exploring, theme, mapRef]);

  // item 32 (2e-map): a language switch re-labels the map in place (popups read the locale when they open)
  useEffect(() => {
    const m = mapRef.current;
    if (!ready(m)) return; // first install labels from getLocale(); this only re-applies (idempotent)
    m.getCanvas().setAttribute('aria-label', tr(locale, 'map.canvasAria'));
    for (const l of m.getStyle().layers) if (BASEMAP_LABEL(l.id, m)) m.setLayoutProperty(l.id, 'text-field', placeName(locale));
    if (m.getLayer('nolst-label')) m.setLayoutProperty('nolst-label', 'text-field', nolstText(locale));
    if (m.getLayer('noscn-label')) m.setLayoutProperty('noscn-label', 'text-field', noscnText(locale));
    (m.getSource('ov') as GeoJSONSource | undefined)?.setData(ovFc()); // marker labels («н/д» / «n/a») and tips
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale, mapRef]);

  // zone geometry: data + pin + fly
  useEffect(() => {
    const m = mapRef.current;
    if (!ready(m)) return;
    placePin(m);
    applyOverviewZoom(m);
    frame(m, 1200);
    updateSpot(m);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geometry, label]);
  // outline + wash follow the shape (the clipped outline arrives with the report — no re-framing)
  useEffect(() => {
    const m = mapRef.current;
    if (!ready(m)) return;
    (m.getSource('zone') as GeoJSONSource | undefined)?.setData(fc(shape));
    (m.getSource('mask') as GeoJSONSource | undefined)?.setData(fc(shape ? maskPolygon(shape) : null));
  }, [shape, mapRef]);

  // country markers: new overview data or a theme change (stops)
  useEffect(() => {
    const m = mapRef.current;
    (m?.getSource('ov') as GeoJSONSource | undefined)?.setData(ovFc());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overview, gapStops, mapRef]);

  // keep the zone framed when the side panel width changes — only while the zone is in view (MAP-TASKS 12: an
  // auto-minimised card after a pan away must not fly the camera back to the zone)
  useEffect(() => {
    const m = mapRef.current;
    const g = data.current.geometry;
    if (!ready(m) || !g) return;
    const [w, s, e, n] = bbox(g), a = m.project([w, n]), b = m.project([e, s]), c = m.getContainer();
    if (spotFactor([a.x, a.y, b.x, b.y], c.clientWidth, c.clientHeight) >= 1) frame(m, 600);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leftInset]);
  useEffect(() => {
    const m = mapRef.current;
    if (!m) return;
    const id = requestAnimationFrame(() => applyLimits(m)); // after the strip/card have laid out
    return () => cancelAnimationFrame(id);
  }, [leftInset, chrome, mapRef]);

  useEffect(() => {
    const m = mapRef.current;
    if (ready(m)) (m.getSource('city') as GeoJSONSource).setData(fc(cityGeometry));
  }, [cityGeometry, mapRef]);

  // drawing tools
  useEffect(() => {
    const m = mapRef.current;
    if (!m || !draw) return;
    const src = () => m.getSource('draft') as GeoJSONSource | undefined;
    const pts: [number, number][] = [];
    let cursor: [number, number] | null = null;
    let center: [number, number] | null = null;
    let radiusKm = 0;
    let downPx: maplibregl.Point | null = null;
    const set = (features: Feature[]) => src()?.setData({ type: 'FeatureCollection', features });
    const pt = (c: Position): Feature => ({ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: c } });
    const render = () => {
      if (draw === 'polygon') {
        const ring = cursor ? [...pts, cursor] : [...pts];
        const f: Feature[] = pts.map(pt);
        if (ring.length >= 3) f.unshift({ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[...ring, ring[0]!]] } });
        else if (ring.length === 2) f.unshift({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: ring } });
        set(f);
      } else if (center) {
        const f: Feature[] = [pt(center)];
        if (radiusKm > 0) f.unshift({ type: 'Feature', properties: {}, geometry: circlePolygon(center, radiusKm) });
        set(f);
      }
    };
    const finish = (p: Polygon) => { set([]); pts.length = 0; cursor = null; center = null; radiusKm = 0; cbs.current.onDrawn(p); };
    const finishPolygon = () => { if (pts.length >= 3) finish({ type: 'Polygon', coordinates: [[...pts, pts[0]!]] }); };
    const near = (a: [number, number], b: [number, number], px: number) => {
      const pa = m.project(a), pb = m.project(b);
      return Math.hypot(pa.x - pb.x, pa.y - pb.y) < px;
    };
    const ll = (e: maplibregl.MapMouseEvent): [number, number] => [e.lngLat.lng, e.lngLat.lat];

    const onClick = (e: maplibregl.MapMouseEvent) => {
      const c = ll(e);
      if (draw === 'polygon') {
        if (pts.length >= 3 && near(c, pts[0]!, 10)) return finishPolygon();
        if (pts.length && near(c, pts[pts.length - 1]!, 6)) return; // second click of a dblclick
        pts.push(c);
        render();
      } else if (draw === 'circle' && center && !downPx) {
        radiusKm = haversineKm(center, c);
        if (radiusKm > 0) finish(circlePolygon(center, radiusKm));
      }
    };
    const onDbl = (e: maplibregl.MapMouseEvent) => { e.preventDefault(); if (draw === 'polygon') finishPolygon(); };
    const onMove = (e: maplibregl.MapMouseEvent) => {
      if (draw === 'polygon') { cursor = ll(e); if (pts.length) render(); }
      else if (center) { radiusKm = haversineKm(center, ll(e)); render(); }
    };
    const onDown = (e: maplibregl.MapMouseEvent) => {
      if (draw !== 'circle' || center) return;
      center = ll(e); downPx = e.point; m.dragPan.disable(); render();
    };
    const onUp = (e: maplibregl.MapMouseEvent) => {
      if (draw !== 'circle' || !center || !downPx) return;
      const dragged = Math.hypot(e.point.x - downPx.x, e.point.y - downPx.y) > 6;
      m.dragPan.enable();
      if (dragged) { radiusKm = haversineKm(center, ll(e)); downPx = null; finish(circlePolygon(center, radiusKm)); }
      else setTimeout(() => { downPx = null; }, 0); // click-move-click: the next click sets the radius
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); set([]); cbs.current.onDrawCancel(); }
      else if (e.key === 'Enter' && draw === 'polygon') { e.preventDefault(); finishPolygon(); }
      else if (e.key === 'Backspace' && draw === 'polygon' && pts.length && (e.target as HTMLElement).tagName !== 'INPUT') { e.preventDefault(); pts.pop(); render(); }
    };
    m.doubleClickZoom.disable();
    const container = el.current;
    container?.classList.add('drawing');
    m.on('click', onClick);
    m.on('dblclick', onDbl);
    m.on('mousemove', onMove);
    m.on('mousedown', onDown);
    m.on('mouseup', onUp);
    window.addEventListener('keydown', onKey);
    return () => {
      m.off('click', onClick);
      m.off('dblclick', onDbl);
      m.off('mousemove', onMove);
      m.off('mousedown', onDown);
      m.off('mouseup', onUp);
      window.removeEventListener('keydown', onKey);
      m.dragPan.enable();
      container?.classList.remove('drawing');
      set([]);
      setTimeout(() => m.doubleClickZoom.enable(), 300);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draw]);

  return (
    <>
      <div ref={el} className="map" data-testid="map" data-inset={leftInset} role="region" aria-label={tr(locale, 'map.aria')} />
      <div ref={spot} className="spot" aria-hidden="true" />
    </>
  );
}

const mercY = (lat: number) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));

// re-fit when the strip appears / changes height (it mounts after the map)
let limitsMap: MlMap | null = null;
const limitsObserver = typeof ResizeObserver === 'undefined' ? { observe() {} } : new ResizeObserver(() => { if (limitsMap) applyLimits(limitsMap); });

/** The top bar, the bottom strip and the tools hide the map too: their extent from the container edges (px). */
function occluders(c: HTMLElement) {
  const box = c.getBoundingClientRect();
  const head = document.querySelector('header.top')?.getBoundingClientRect();
  const strip = document.querySelector('[data-testid=strip]')?.getBoundingClientRect();
  const tools = document.querySelector('section.tools')?.getBoundingClientRect();
  const top = head ? Math.max(0, head.bottom - box.top) : 0;
  const bottom = strip && strip.height ? Math.max(0, box.bottom - strip.top) : 0;
  const right = tools && tools.width ? Math.max(0, box.right - tools.left) : 0;
  return { top, bottom, right };
}

/** Re-derive minZoom + maxBounds from the container size and the card inset (MAP-TASKS 1). */
function applyLimits(m: MlMap) {
  const c = m.getContainer();
  const inset = Number(c.dataset.inset ?? 0);
  const { top, bottom, right } = occluders(c);
  limitsObserver.observe(document.querySelector('[data-testid=strip]') ?? c);
  // min zoom: all of Ukraine fits the free rectangle; panning (1b): any border point can reach the free-area centre
  const { zoom, bounds: minView } = viewLimits(c.clientWidth, c.clientHeight, inset, undefined, top, bottom, right);
  minViewOf.set(m, minView);
  const bounds = unionBox(minView, panBounds(c.clientWidth, c.clientHeight, Math.max(zoom, m.getZoom()), { left: inset, right, top, bottom }));
  const cur = m.getMaxBounds()?.toArray().flat();
  if (Math.abs(m.getMinZoom() - zoom) < 0.01 && cur && cur.every((v, i) => Math.abs(v - bounds.flat()[i]!) < 0.005)) return;
  if (Math.abs(m.getMinZoom() - zoom) >= 0.01) {
    m.setMaxBounds(null);
    m.setMinZoom(zoom);
  }
  m.setMaxBounds(bounds);
}

/**
 * Camera that centres the zone in the free area (screen minus the left panel) and sizes it to
 * ~30 % of that area for districts (more context) or ~80 % for whole cities.
 */
export function frameCamera([w, s, e, n]: [number, number, number, number], width: number, height: number, inset: number, occ: { top: number; bottom: number } = { top: 0, bottom: 0 }) {
  // the share of the free area grows continuously with the zone's size (was a jump at 0.25° wide, so Одеса — 0.22° wide
  // but 0.29° tall — was framed like a district at ~14 % and opened at z7.3 with a lot of sea around it)
  const span = Math.max(e - w, (n - s) * 1.5);
  const share = 0.14 + 0.56 * Math.max(0, Math.min(1, (span - 0.05) / 0.2)); // ≤ 70 %: a tall city clears the strip
  const big = share > 0.45;
  const freeW = Math.max(200, width - inset - 80);
  // the strip is 160–180 px tall at 1280–1440 wide: frame above it, not behind it (Одеса at 1280×720)
  const padTop = Math.max(100, occ.top + 16);
  const padBottom = Math.max(120, occ.bottom + 16);
  const freeH = Math.max(200, height - padTop - padBottom);
  const zx = Math.log2((freeW * share * 360) / (512 * Math.max(e - w, 1e-4)));
  const zy = Math.log2((freeH * share * 2 * Math.PI) / (512 * Math.max(mercY(n) - mercY(s), 1e-6)));
  const zoom = Math.min(zx, zy, big ? 11.5 : 12.4);
  return {
    center: [(w + e) / 2, (s + n) / 2] as [number, number],
    zoom,
    padding: { left: inset, right: 80, top: padTop, bottom: padBottom },
  };
}
