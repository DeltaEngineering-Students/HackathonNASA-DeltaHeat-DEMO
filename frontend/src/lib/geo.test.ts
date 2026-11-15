import type { Polygon } from 'geojson';
import { areaKm2, circlePolygon, decodeRing, encodeRing, isSelfIntersecting, maskPolygon, signedArea, validateDrawn, zoneShape } from './geo';
import type { ZoneGeometry } from '../api/types';

const square = (km: number): Polygon => {
  const d = km / 111.2; const dx = d / Math.cos((50.45 * Math.PI) / 180);
  return { type: 'Polygon', coordinates: [[[30.5, 50.45], [30.5 + dx, 50.45], [30.5 + dx, 50.45 + d], [30.5, 50.45 + d], [30.5, 50.45]]] };
};

describe('geo', () => {
  it('computes polygon area in km²', () => {
    expect(areaKm2(square(2))).toBeCloseTo(4, 1);
  });
  it('builds circles with the right area', () => {
    expect(areaKm2(circlePolygon([30.5, 50.45], 1))).toBeCloseTo(Math.PI, 1);
  });
  it('rejects too-small and self-intersecting drawings with a clear reason', () => {
    const small = validateDrawn(square(0.5));
    expect(small.ok).toBe(false);
    if (!small.ok) expect(small.reason).toMatch(/замала.*0,5 км²/);
    const bow: Polygon = { type: 'Polygon', coordinates: [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]] };
    expect(isSelfIntersecting(bow.coordinates[0]!)).toBe(true);
    expect(validateDrawn(bow).ok).toBe(false);
    expect(validateDrawn(square(1.5))).toMatchObject({ ok: true });
    // backend limits from /api/meta can only tighten the UI floor
    expect(validateDrawn(square(1.5), { min_area_km2: 3, max_area_km2: 3000 }).ok).toBe(false);
    expect(validateDrawn(square(0.6), { min_area_km2: 0.05, max_area_km2: 3000 }).ok).toBe(false);
  });
  it('round-trips a ring through the URL encoding', () => {
    const p = square(1);
    const back = decodeRing(encodeRing(p))!;
    expect(back.coordinates[0]!.length).toBe(5);
    expect(back.coordinates[0]![2]![0]).toBeCloseTo(p.coordinates[0]![2]![0]!, 4);
    expect(decodeRing('garbage')).toBeNull();
  });
  it('makes a world mask with the zone as an oppositely wound hole', () => {
    for (const g of [square(1), { ...square(1), coordinates: [[...square(1).coordinates[0]!].reverse()] }]) {
      const m = maskPolygon(g);
      expect(m.coordinates.length).toBe(2);
      expect(signedArea(m.coordinates[0]!)).toBeGreaterThan(0);
      expect(signedArea(m.coordinates[1]!)).toBeLessThan(0);
    }
  });
});

describe('zoneShape (MAP-TASKS 24)', () => {
  const sq = (w: number, s: number, e: number, n: number): ZoneGeometry => ({ type: 'Polygon', coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] });
  it('uses the clipped outline only when it lies inside the zone', () => {
    const g = sq(22.2, 48.6, 22.3, 48.7);
    const clipped = sq(22.24, 48.6, 22.3, 48.7);
    expect(zoneShape(g, clipped)).toBe(clipped);
    expect(zoneShape(g, null)).toBe(g);
    expect(zoneShape(null, clipped)).toBeNull();
    expect(zoneShape(g, sq(30, 50, 30.1, 50.1))).toBe(g); // a stale outline of another zone
  });
});
