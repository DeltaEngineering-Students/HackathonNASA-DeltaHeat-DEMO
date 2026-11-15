import type { Polygon, Position } from 'geojson';
import type { ZoneGeometry } from '../api/types';
import { getLocale } from '../i18n/locale';
import { tr } from '../i18n';

const isEn = () => getLocale() === 'en';

const R = 6371.0088; // km

const rings = (g: ZoneGeometry): Position[][] =>
  g.type === 'Polygon' ? g.coordinates : g.coordinates.flat();
const outerRings = (g: ZoneGeometry): Position[][] =>
  g.type === 'Polygon' ? [g.coordinates[0]!] : g.coordinates.map((p) => p[0]!);

export function bbox(g: ZoneGeometry): [number, number, number, number] {
  let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
  for (const ring of rings(g))
    for (const [x, y] of ring as [number, number][]) {
      w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y);
    }
  return [w, s, e, n];
}

export function centroid(g: ZoneGeometry): [number, number] {
  const [w, s, e, n] = bbox(g);
  return [(w + e) / 2, (s + n) / 2];
}

/** Planar ring area (shoelace) in km² on a local equirectangular projection. */
function ringAreaKm2(ring: Position[], lat0: number): number {
  const kx = (Math.PI / 180) * R * Math.cos((lat0 * Math.PI) / 180);
  const ky = (Math.PI / 180) * R;
  let a = 0;
  for (let i = 0; i < ring.length - 1; i++) {
    const [x1, y1] = ring[i] as [number, number];
    const [x2, y2] = ring[i + 1] as [number, number];
    a += x1 * kx * (y2 * ky) - x2 * kx * (y1 * ky);
  }
  return Math.abs(a) / 2;
}

export function areaKm2(g: ZoneGeometry): number {
  const lat0 = centroid(g)[1];
  const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates;
  return polys.reduce((sum, p) => {
    const [outer, ...holes] = p;
    return sum + ringAreaKm2(outer!, lat0) - holes.reduce((h, r) => h + ringAreaKm2(r, lat0), 0);
  }, 0);
}

export function haversineKm(a: [number, number], b: [number, number]): number {
  const toRad = Math.PI / 180;
  const dLat = (b[1] - a[1]) * toRad;
  const dLon = (b[0] - a[0]) * toRad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[1] * toRad) * Math.cos(b[1] * toRad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

export function circlePolygon(center: [number, number], radiusKm: number, steps = 64): Polygon {
  const [lon, lat] = center;
  const dy = (radiusKm / R) * (180 / Math.PI);
  const dx = dy / Math.cos((lat * Math.PI) / 180);
  const ring: Position[] = [];
  for (let i = 0; i < steps; i++) {
    const t = (i / steps) * 2 * Math.PI;
    ring.push([round6(lon + dx * Math.cos(t)), round6(lat + dy * Math.sin(t))]);
  }
  ring.push(ring[0]!);
  return { type: 'Polygon', coordinates: [ring] };
}

const round6 = (x: number) => Math.round(x * 1e6) / 1e6;

/** Signed planar area of a ring in degrees² (positive = counter-clockwise). */
export function signedArea(ring: Position[]): number {
  let a = 0;
  for (let i = 0; i < ring.length - 1; i++) a += ring[i]![0]! * ring[i + 1]![1]! - ring[i + 1]![0]! * ring[i]![1]!;
  return a / 2;
}

/**
 * World polygon with the zone cut out — used to wash out everything except the zone.
 * MapLibre classifies holes by winding, so the world ring is CCW and every hole CW.
 */
export function maskPolygon(g: ZoneGeometry): Polygon {
  const world: Position[] = [[-179.9, -85], [179.9, -85], [179.9, 85], [-179.9, 85], [-179.9, -85]];
  const holes = outerRings(g).map((r) => (signedArea(r) > 0 ? [...r].reverse() : r));
  return { type: 'Polygon', coordinates: [world, ...holes] };
}

/** Self-intersection check for a simple ring (O(n²), n is small for hand-drawn shapes). */
export function isSelfIntersecting(ring: Position[]): boolean {
  const n = ring.length - 1;
  const seg = (i: number) => [ring[i] as [number, number], ring[(i + 1) % n] as [number, number]] as const;
  const cross = (o: [number, number], a: [number, number], b: [number, number]) =>
    (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  for (let i = 0; i < n; i++)
    for (let j = i + 1; j < n; j++) {
      if (Math.abs(i - j) <= 1 || (i === 0 && j === n - 1)) continue;
      const [p1, p2] = seg(i);
      const [q1, q2] = seg(j);
      const d1 = cross(q1, q2, p1), d2 = cross(q1, q2, p2), d3 = cross(p1, p2, q1), d4 = cross(p1, p2, q2);
      if (d1 * d2 < 0 && d3 * d4 < 0) return true;
    }
  return false;
}

export const MIN_AREA_KM2 = 0.5;
export const MAX_AREA_KM2 = 3000;

export type AreaCheck = { ok: true; areaKm2: number } | { ok: false; reason: string };

export function validateDrawn(g: Polygon, limits?: { min_area_km2: number; max_area_km2: number }): AreaCheck {
  const minA = Math.max(MIN_AREA_KM2, limits?.min_area_km2 ?? 0);
  const maxA = limits?.max_area_km2 ?? MAX_AREA_KM2;
  const ring = g.coordinates[0]!;
  if (isEn()) {
    if (ring.length < 4) return { ok: false, reason: tr('en', 'draw.tooFewPoints') };
    if (isSelfIntersecting(ring)) return { ok: false, reason: tr('en', 'draw.selfIntersecting') };
    const a = areaKm2(g);
    if (a < minA) return { ok: false, reason: tr('en', 'draw.tooSmall', { area: a.toFixed(2), min: String(minA) }) };
    if (a > maxA) return { ok: false, reason: tr('en', 'draw.tooLarge', { max: maxA.toLocaleString('en-GB') }) };
    return { ok: true, areaKm2: a };
  }
  if (ring.length < 4) return { ok: false, reason: 'Потрібно щонайменше 3 точки.' };
  if (isSelfIntersecting(ring)) return { ok: false, reason: 'Контур перетинає сам себе — намалюйте його ще раз.' };
  const a = areaKm2(g);
  if (a < minA)
    return { ok: false, reason: `Ділянка замала: ${a.toFixed(2).replace('.', ',')} км². Потрібно щонайменше ${String(minA).replace('.', ',')} км², інакше результат нерепрезентативний.` };
  if (a > maxA) return { ok: false, reason: `Ділянка завелика: оберіть місто або його частину (до ${maxA} км²).` };
  return { ok: true, areaKm2: a };
}

/** Compact encoding of a drawn polygon for the URL: "lon,lat;lon,lat;…" (5 decimals). */
export function encodeRing(g: Polygon): string {
  return g.coordinates[0]!.slice(0, -1).map(([x, y]) => `${x!.toFixed(5)},${y!.toFixed(5)}`).join(';');
}
export function decodeRing(s: string): Polygon | null {
  const pts = s.split(';').map((p) => p.split(',').map(Number));
  if (pts.length < 3 || pts.some((p) => p.length !== 2 || p.some((v) => !Number.isFinite(v)))) return null;
  return { type: 'Polygon', coordinates: [[...pts, pts[0]!]] };
}

/**
 * The zone shape to draw: the report's `zone_outline` (clipped to Ukraine) when it belongs to this geometry — its bbox
 * lies inside the geometry's (a stale outline of the previous zone never shows) — else the geometry itself.
 */
export function zoneShape(g: ZoneGeometry | null, outline: ZoneGeometry | null): ZoneGeometry | null {
  if (!g || !outline) return g;
  const [w, s, e, n] = bbox(g), [w2, s2, e2, n2] = bbox(outline), eps = 1e-4;
  return w2 >= w - eps && s2 >= s - eps && e2 <= e + eps && n2 <= n + eps ? outline : g;
}
