// «Шари» panel state (item 7 + item 13 slider), shared by MapTools (UI), MapView (applies it) and the strip (notes)
// without threading props through App. Remembered for the browser session (sessionStorage, best effort).
import { useSyncExternalStore } from 'react';
import type { ZoneGeometry } from '../api/types';
import { satUseEox } from './satellite';

export type Basemap = 'map' | 'sat';
export interface MapUi {
  basemap: Basemap;
  /** heat transparency 0..1 (0 = the default opacity, 1 = invisible); the panel shows it inverted, «Видимість тепла» */
  heatTransparency: number;
  /** the user moved the heat slider — then switching to satellite no longer changes it (item 26) */
  heatTouched: boolean;
  /** dim non-built land 0..1 (item 13; the backend `nonbuilt` overlay), default 0.7 */
  mute: number;
  /** set by MapView: the current data layer and whether meta offers the nonbuilt overlay */
  layer: string;
  nonbuilt: { label_uk?: string; default_strength?: number; applies_to?: string[] } | null;
  /** item 20 D: draw the reference-forest outline of the current report */
  showReference: boolean;
  /** set by App: the accepted active report; MapView: whether its outline could be loaded */
  reportId: string | null;
  reference: 'idle' | 'loading' | 'ok' | 'none';
  /** MAP-TASKS 24: the active report's zone clipped to Ukraine (`zone_outline`, API v2.9); null = not clipped */
  zoneOutline: ZoneGeometry | null;
  /** set by MapView: label of the map year's «too few clear scenes» swath when it is in view, else null */
  noScenes: string | null;
  /** set by MapView: the map year (the satellite mosaic follows it) */
  mapYear: number | null;
  /** satellite imagery comes from the EOX fallback (Esri failed this session, or `?sat=eox`) */
  satEox: boolean;
}

const KEY = 'uhd-map-ui';
const DEFAULTS: MapUi = { basemap: 'map', heatTransparency: 0, heatTouched: false, mute: 0.7, layer: 'gap', nonbuilt: null, showReference: false, reportId: null, reference: 'idle', zoneOutline: null, noScenes: null, mapYear: null, satEox: satUseEox() };
let state: MapUi = (() => {
  try {
    const raw = sessionStorage.getItem(KEY);
    const v = raw ? (JSON.parse(raw) as Partial<MapUi>) : {};
    return {
      ...DEFAULTS,
      basemap: v.basemap === 'sat' ? 'sat' : 'map',
      heatTransparency: typeof v.heatTransparency === 'number' ? clamp01(v.heatTransparency) : 0,
      heatTouched: v.heatTouched === true,
      mute: typeof v.mute === 'number' ? clamp01(v.mute) : DEFAULTS.mute,
      showReference: v.showReference === true,
    };
  } catch { return { ...DEFAULTS }; }
})();
function clamp01(x: number) { return Math.max(0, Math.min(1, x)); }

const subs = new Set<() => void>();
export function setMapUi(patch: Partial<MapUi>) {
  const next = { ...state, ...patch };
  if (Object.keys(patch).every((k) => Object.is(next[k as keyof MapUi], state[k as keyof MapUi]))) return;
  state = next;
  try { sessionStorage.setItem(KEY, JSON.stringify({ basemap: state.basemap, heatTransparency: state.heatTransparency, heatTouched: state.heatTouched, mute: state.mute, showReference: state.showReference })); } catch { /* private mode */ }
  for (const f of subs) f();
}
export const getMapUi = () => state;
export function useMapUi(): MapUi {
  return useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f); }, getMapUi, getMapUi);
}
/**
 * The nonbuilt veil applies ONLY to «Розрив» (item 27: «Температура» and the green layers stay whole — a temperature map
 * cropped to the built-up area reads as missing data). Meta `applies_to` can only narrow it further.
 */
export const muteApplies = (s: MapUi) => !!s.nonbuilt && s.layer === 'gap' && (s.nonbuilt.applies_to ?? ['gap']).includes('gap');

/** heat transparency used with satellite imagery while the user has not set one (item 26) */
export const SAT_HEAT_TRANSPARENCY = 0.5;
/**
 * Effective transparency of the shown raster for the «Видимість шару» slider value t (0..1 = 1 − visibility).
 * The green layers (ndvi / dndvi) keep most of their colour at the satellite default (t = 0.5 → 0.15, ≥ 85 % visible),
 * but the curve still ends at 1: 0 % visibility hides every layer (it used to be 0.3·t, so ndvi/dndvi stayed at 70 %).
 */
export function layerTransparency(t: number, layer: string | undefined): number {
  const v = Math.min(1, Math.max(0, t));
  if (layer !== 'ndvi' && layer !== 'dndvi') return v;
  const knee = SAT_HEAT_TRANSPARENCY, kneeOut = 0.3 * knee;
  return v <= knee ? 0.3 * v : kneeOut + ((v - knee) / (1 - knee)) * (1 - kneeOut);
}
/** basemap switch (item 26): over imagery the heat goes half-transparent unless the user already chose a value */
export function setBasemap(b: Basemap) {
  setMapUi(state.heatTouched ? { basemap: b } : { basemap: b, heatTransparency: b === 'sat' ? SAT_HEAT_TRANSPARENCY : 0 });
}

/** reference-forest outline colour (API meta `layers.reference_color`, ultramarine — not used by any raster) */
export const REFERENCE_COLOR = { light: '#1D3FBF', dark: '#7F9BFF' } as const;
