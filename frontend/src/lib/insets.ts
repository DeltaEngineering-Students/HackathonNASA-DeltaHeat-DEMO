// ONE place for the left inset of the free map area (MAP-TASKS 1b/12): how much of the map the left panel covers.
// MapView reads it via the `leftInset` prop (frame padding) and `data-inset` (viewLimits in applyLimits).
import { spotFactor } from './spot';

export const CARD_INSET = 480; // .answer: left 32 + width 448
export const DETAILS_INSET = 928;
export const PILL_INSET = 32; // collapsed card: a small pill top-left, the map gets the full width

export function leftInset({ details, collapsed }: { details: boolean; collapsed: boolean }): number {
  if (details) return DETAILS_INSET;
  return collapsed ? PILL_INSET : CARD_INSET;
}

/**
 * Auto-minimise (MAP-TASKS 12): accumulate how long the zone has been away from the view, weighted by the same
 * continuous fade factor k as the map wash (item 10) — no separate pixel threshold. Out of view by a screen (k = 0)
 * → ~1 s; just past the edge → proportionally longer; back in view (k = 1) → the clock resets.
 */
export const AWAY_SECONDS = 1;
export function awayStep(acc: number, k: number, dtSec: number): number {
  if (k >= 1) return 0;
  return acc + (1 - k) * dtSec;
}

/** k for the zone bbox [w, s, e, n] in a viewport, given a projection (lon, lat) → screen px. */
export function zoneK(b: [number, number, number, number], project: (ll: [number, number]) => { x: number; y: number }, w: number, h: number): number {
  const a = project([b[0], b[3]]);
  const c = project([b[2], b[1]]);
  return spotFactor([a.x, a.y, c.x, c.y], w, h);
}

const KEY = 'uhd.card';
/** The user's manual choice for this session (sessionStorage; may be unavailable). */
export function loadCollapsed(): boolean {
  try { return sessionStorage.getItem(KEY) === 'collapsed'; } catch { return false; }
}
export function saveCollapsed(c: boolean) {
  try { sessionStorage.setItem(KEY, c ? 'collapsed' : 'expanded'); } catch { /* private mode */ }
}
