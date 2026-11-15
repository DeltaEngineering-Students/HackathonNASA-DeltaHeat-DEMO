// Ukraine-only map (MAP-TASKS 1–2). The outline itself comes from GET /api/overlays (`ukraine.geometry`).
import type { Map as MlMap } from 'maplibre-gl';
import type { Feature, FeatureCollection, Polygon, MultiPolygon, Position } from 'geojson';
import { signedArea } from './geo';

export const UA_BBOX: [number, number, number, number] = [22.14, 44.38, 40.23, 52.38];
const MARGIN = 1.5;
/** bbox + 1,5° (MapLibre LngLatBoundsLike: [[w, s], [e, n]]). */
export const maxBoundsFor = (b: [number, number, number, number] = UA_BBOX): [[number, number], [number, number]] =>
  [[b[0] - MARGIN, b[1] - MARGIN], [b[2] + MARGIN, b[3] + MARGIN]];

const mercY = (lat: number) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));

/**
 * Zoom at which the bbox just fits a w×h px viewport (web mercator, 512 px tiles as in MapLibre).
 * Used as the dynamic minZoom: zooming out stops when the whole of Ukraine is visible.
 */
export function zoomToFit(b: [number, number, number, number], w: number, h: number, pad = 0): number {
  const zx = Math.log2(((w - 2 * pad) * 360) / (512 * (b[2] - b[0])));
  const zy = Math.log2(((h - 2 * pad) * 2 * Math.PI) / (512 * (mercY(b[3]) - mercY(b[1]))));
  return Math.max(0, Math.min(zx, zy));
}

const rings = (g: Polygon | MultiPolygon): Position[][] => (g.type === 'Polygon' ? [g.coordinates[0]!] : g.coordinates.map((p) => p[0]!));

/** RFC 7946 hole: clockwise (as in maskPolygon). A counter-clockwise hole is read as a second polygon in some tiles (R-MAP-4). */
const asHole = (r: Position[]) => (signedArea(r) > 0 ? r.slice().reverse() : r);

/** World minus Ukraine: the veil drawn over the neighbours (outer ring = world, CCW; holes = Ukraine's outer rings, CW). */
export function veilFeature(g: Polygon | MultiPolygon): Feature<Polygon> {
  const world: Position[] = [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]];
  return { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [world, ...rings(g).map(asHole)] } };
}

const invMercY = (y: number) => (360 / Math.PI) * Math.atan(Math.exp(y)) - 90;
const PAD = 24;

/**
 * Zoom-out limit (MAP-TASKS 1). `zoom` = the zoom at which the whole bbox fits the free part of the viewport
 * (right of the `inset` px card, PAD px around); `bounds` = the viewport box at that zoom with Ukraine centred in
 * the free part. Used as minZoom + maxBounds together: at min zoom the camera is locked on all of Ukraine, and when
 * zoomed in the panning box is just that view (≈ bbox + 1–4°, depending on the screen aspect).
 */
export function viewLimits(w: number, h: number, inset = 0, b: [number, number, number, number] = UA_BBOX, top = 0, bottom = 0, right = 0) {
  const aw = Math.max(200, w - inset - right - 2 * PAD);
  const ah = Math.max(200, h - top - bottom - 2 * PAD);
  const zoom = zoomToFit(b, aw, ah);
  const k = 512 * 2 ** zoom; // px per world
  const dLon = 360 / k;
  const lonC = (b[0] + b[2]) / 2;
  const west = lonC - (inset + (w - inset - right) / 2) * dLon;
  // Ukraine's centre sits in the middle of the free band (below the top bar, above the strip)
  const yC = (mercY(b[1]) + mercY(b[3])) / 2;
  const pxPerRad = k / (2 * Math.PI);
  const cy = top + (h - top - bottom) / 2; // px from the top where the centre lands
  const eps = 0.02;
  const bounds: [[number, number], [number, number]] = [
    [west - eps, invMercY(yC - (h - cy) / pxPerRad) - eps],
    [west + w * dLon + eps, invMercY(yC + cy / pxPerRad) + eps],
  ];
  return { zoom, bounds };
}

/** Source data for the veil + border (+ the hatched «ground» under the heat); empty until the outline arrives. */
export function uaFeatures(g: Polygon | MultiPolygon | null | undefined): FeatureCollection {
  if (!g) return { type: 'FeatureCollection', features: [] };
  return { type: 'FeatureCollection', features: [veilFeature(g), { type: 'Feature', properties: { border: 1 }, geometry: g }] };
}

/** Kept for callers that only need the zoom: see viewLimits. */
export const minZoomFor = (w: number, h: number, inset = 0) => viewLimits(w, h, inset).zoom;

/** Occluders over the map: the card (left), the top bar and the bottom strip, measured from the DOM. */
export interface Occluders { left: number; top: number; bottom: number }

/** «Вся Україна»: the zoomed-out view, Ukraine centred right of the card. */
/** The min-zoom view box per map (set by MapView's limits), so «Вся Україна» can fly there exactly. */
export const minViewOf = new WeakMap<MlMap, [[number, number], [number, number]]>();

export function showAllUkraine(m: MlMap, duration = 700) {
  const v = minViewOf.get(m);
  const b = m.getMaxBounds();
  if (!v && !b) return;
  const center: [number, number] = v ? [(v[0][0] + v[1][0]) / 2, invMercY((mercY(v[0][1]) + mercY(v[1][1])) / 2)] : b!.getCenter().toArray() as [number, number];
  m.flyTo({ center, zoom: m.getMinZoom(), padding: { left: 0, right: 0, top: 0, bottom: 0 }, duration, essential: false });
}

/** The free part of the map: right of the card, left of the tools, below the top bar, above the strip (px). */
export interface FreeArea { left: number; right: number; top: number; bottom: number }

/**
 * Task 1b: panning box at zoom `z` such that ANY point of the bbox can sit at the centre of the free area: the bbox
 * padded on each side by the distance from the free-area centre to that viewport edge (in degrees at `z`).
 */
export function panBounds(w: number, h: number, z: number, free: FreeArea, b: [number, number, number, number] = UA_BBOX): [[number, number], [number, number]] {
  const k = 512 * 2 ** z;
  const dLon = 360 / k;
  const pxPerRad = k / (2 * Math.PI);
  const cx = free.left + (w - free.left - free.right) / 2;
  const cy = free.top + (h - free.top - free.bottom) / 2;
  // MapLibre clamps a ±w/2 × ±h/2 box around the camera centre (the PADDED centre when camera padding is set), so pad
  // symmetrically by the larger of the free-centre offsets and the half viewport: works with and without padding
  const px = Math.max(cx, w - cx, w / 2), py = Math.max(cy, h - cy, h / 2);
  return [
    [b[0] - px * dLon, invMercY(mercY(b[1]) - py / pxPerRad)],
    [b[2] + px * dLon, invMercY(mercY(b[3]) + py / pxPerRad)],
  ];
}

/** Union of two [[w, s], [e, n]] boxes. */
export const unionBox = (a: [[number, number], [number, number]], b: [[number, number], [number, number]]): [[number, number], [number, number]] =>
  [[Math.min(a[0][0], b[0][0]), Math.min(a[0][1], b[0][1])], [Math.max(a[1][0], b[1][0]), Math.min(85, Math.max(a[1][1], b[1][1]))]];
