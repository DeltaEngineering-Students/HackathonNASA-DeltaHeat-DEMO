// Роман 15.11 15:42: a click on a settlement / district name on the basemap selects it, the same way as picking it in
// the search: /api/places?q=<name> → the preset nearest to the label (else the geocoder hit) → analyse.
// The basemap is OpenFreeMap (OpenMapTiles schema): labels are symbol layers on the `place` source layer with `class`.
import type { Map as MlMap, MapGeoJSONFeature, PointLike } from 'maplibre-gl';
import type { PlaceHit } from '../api/types';
import { haversineKm } from './geo';

/** Label classes that are places people search for (settlements and city districts). */
export const PLACE_CLASSES = new Set(['city', 'town', 'village', 'hamlet', 'suburb', 'quarter', 'neighbourhood', 'borough']);
/** How far a hit may lie from the clicked label (a city's bbox centre can sit a few km off its label). */
const MAX_KM: Record<string, number> = { city: 25, town: 12, village: 6, hamlet: 4 };
const maxKm = (cls: string) => MAX_KM[cls] ?? 8;

export interface MapLabel { name: string; nameEn?: string; cls: string; lngLat: [number, number] }

/** The settlement / district label under a screen point (± 4 px), or null. Our own layers never count. */
export function placeLabelAt(map: Pick<MlMap, 'queryRenderedFeatures'>, point: { x: number; y: number }, own: ReadonlySet<string>): MapLabel | null {
  const box: [PointLike, PointLike] = [[point.x - 4, point.y - 4], [point.x + 4, point.y + 4]];
  let feats: MapGeoJSONFeature[];
  try { feats = map.queryRenderedFeatures(box); } catch { return null; }
  // a marker / hotspot / drawing on top wins: it has its own click
  if (feats.some((f) => own.has(f.layer.id))) return null;
  for (const f of feats) {
    if (f.layer.type !== 'symbol' || f.sourceLayer !== 'place') continue;
    const p = (f.properties ?? {}) as Record<string, unknown>;
    const cls = String(p.class ?? '');
    const name = String(p['name:uk'] ?? p.name ?? '').trim();
    if (!PLACE_CLASSES.has(cls) || !name || f.geometry.type !== 'Point') continue;
    const en = p['name:en'] ?? p['name:latin'];
    return { name, ...(typeof en === 'string' && en ? { nameEn: en } : {}), cls, lngLat: f.geometry.coordinates as [number, number] };
  }
  return null;
}

const fold = (s: string) => s.toLocaleLowerCase('uk').replace(/[’'`ʼ]/g, '').replace(/ё/g, 'е').replace(/\s*\(.*\)\s*$/, '').replace(/^(увесь|уся|усе|whole|all of)\s+/, '').trim();

/** A hit's name «is» the label: equal after folding, or one starts with the other («Оболонь» / «Оболонський район»). */
export function sameName(hit: string, label: string): boolean {
  const a = fold(hit), b = fold(label);
  if (!a || !b) return false;
  if (a === b) return true;
  let n = 0;
  while (n < a.length && n < b.length && a[n] === b[n]) n += 1;
  return n >= Math.max(4, Math.min(a.length, b.length) - 1);
}

/**
 * The search hit a label click opens: a preset (city, district, demo area) named like the label and nearest to it;
 * else the geocoder hit named like it; only within a few km of the label (same-named villages elsewhere never win).
 */
export function choosePlaceHit(hits: PlaceHit[], label: MapLabel): PlaceHit | null {
  const lim = maxKm(label.cls);
  const near = (h: PlaceHit) => (h.center ? haversineKm(h.center, label.lngLat) : Infinity);
  const ok = hits.filter((h) => sameName(h.name, label.name) && near(h) <= lim);
  const exact = (h: PlaceHit) => (fold(h.name) === fold(label.name) ? 0 : 1);
  const best = (xs: PlaceHit[]) => [...xs].sort((a, b) => exact(a) - exact(b) || near(a) - near(b))[0] ?? null;
  return best(ok.filter((h) => h.kind !== 'geocoder')) ?? best(ok.filter((h) => h.kind === 'geocoder'));
}

/**
 * Wire the map: a pointer cursor over a place label, a click runs `onPick`. `active()` is false while drawing.
 * Returns the uninstaller.
 */
export function installLabelPick(map: MlMap, own: ReadonlySet<string>, active: () => boolean, onPick: (l: MapLabel) => void): () => void {
  let ours = false; // the cursor is ours to reset
  const onMove = (e: { point: { x: number; y: number } }) => {
    const hit = active() ? placeLabelAt(map, e.point, own) : null;
    const c = map.getCanvas().style;
    if (hit) { if (!c.cursor) { c.cursor = 'pointer'; ours = true; } }
    else if (ours) { c.cursor = ''; ours = false; }
  };
  const onClick = (e: { point: { x: number; y: number } }) => {
    if (!active()) return;
    const hit = placeLabelAt(map, e.point, own);
    if (hit) onPick(hit);
  };
  map.on('mousemove', onMove);
  map.on('click', onClick);
  return () => { map.off('mousemove', onMove); map.off('click', onClick); };
}
