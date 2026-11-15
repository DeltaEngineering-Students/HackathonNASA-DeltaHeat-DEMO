import { maxBoundsFor, panBounds, uaFeatures, UA_BBOX, unionBox, veilFeature, viewLimits, zoomToFit } from './ukraine';
import type { Polygon } from 'geojson';

const SQUARE: Polygon = { type: 'Polygon', coordinates: [[[22, 44], [40, 44], [40, 52], [22, 52], [22, 44]]] };
const mercY = (lat: number) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));

describe('Ukraine-only map', () => {
  it('zoomToFit: the whole country ≈ z5.4 at 1280×720 (512 px tiles); smaller windows fit lower', () => {
    const z = zoomToFit(UA_BBOX, 1280, 720);
    expect(z).toBeGreaterThan(5.3);
    expect(z).toBeLessThan(5.5);
    expect(zoomToFit(UA_BBOX, 1440, 900)).toBeGreaterThan(z);
    expect(zoomToFit(UA_BBOX, 640, 480)).toBeLessThan(z);
  });
  it('maxBoundsFor = bbox + 1,5°', () => {
    expect(maxBoundsFor()).toEqual([[20.64, 42.88], [41.73, 53.88]]);
  });
  for (const [w, h, inset] of [[1280, 720, 0], [1440, 900, 0], [1280, 720, 420], [1440, 900, 460], [390, 844, 0]] as const) {
    it(`viewLimits ${w}×${h}, card ${inset}px: the min-zoom view contains the bbox, centred in the free area`, () => {
      const { zoom, bounds: [[W, S], [E, N]] } = viewLimits(w, h, inset);
      const [bw, bs, be, bn] = UA_BBOX;
      expect(W).toBeLessThan(bw);
      expect(S).toBeLessThan(bs);
      expect(E).toBeGreaterThan(be);
      expect(N).toBeGreaterThan(bn);
      // the view box is exactly one viewport at `zoom` (so maxBounds never fights minZoom)
      const k = 512 * 2 ** zoom;
      expect(((E - W) * k) / 360).toBeCloseTo(w + (0.04 * k) / 360, 0);
      expect(((mercY(N) - mercY(S)) * k) / (2 * Math.PI)).toBeGreaterThan(h);
      // Ukraine's centre sits in the middle of the area right of the card
      const px = (((bw + be) / 2 - W) * k) / 360;
      expect(px).toBeCloseTo(inset + (w - inset) / 2, -1);
    });
  }
  it('veil = world with a Ukraine hole; nothing drawn before the outline arrives', () => {
    const v = veilFeature(SQUARE);
    expect(v.geometry.coordinates).toHaveLength(2);
    expect(v.geometry.coordinates[0]![0]).toEqual([-180, -85]);
    expect(uaFeatures(null).features).toHaveLength(0);
    expect(uaFeatures(SQUARE).features).toHaveLength(2);
  });
  it('veil hole is clockwise whatever the outline winding (R-MAP-4: a CCW hole veiled one z7 tile twice)', () => {
    const area = (r: number[][]) => r.reduce((s, p, i) => (i ? s + r[i - 1]![0]! * p[1]! - p[0]! * r[i - 1]![1]! : 0), 0);
    const cw: Polygon = { type: 'Polygon', coordinates: [SQUARE.coordinates[0]!.slice().reverse()] };
    for (const g of [SQUARE, cw]) {
      const [world, hole] = veilFeature(g).geometry.coordinates;
      expect(area(world!)).toBeGreaterThan(0);
      expect(area(hole!)).toBeLessThan(0);
    }
    expect(SQUARE.coordinates[0]![1]).toEqual([40, 44]); // input not mutated
  });
});

describe('task 1b: panning box', () => {
  it('lets every bbox corner reach the free-area centre (padded or not) and widens as you zoom out', () => {
    const free = { left: 480, right: 80, top: 70, bottom: 170 };
    const [[W, S], [E, N]] = panBounds(1440, 900, 7, free);
    const dLon = 360 / (512 * 2 ** 7);
    const cx = 480 + (1440 - 480 - 80) / 2; // 920
    expect(W).toBeCloseTo(UA_BBOX[0] - Math.max(cx, 1440 - cx) * dLon, 6);
    expect(E).toBeCloseTo(UA_BBOX[2] + Math.max(cx, 1440 - cx) * dLon, 6);
    expect(S).toBeLessThan(UA_BBOX[1]);
    expect(N).toBeGreaterThan(UA_BBOX[3]);
    const z11 = panBounds(1440, 900, 11, free);
    expect(z11[0][0]).toBeGreaterThan(W); // tighter when zoomed in
    expect(UA_BBOX[0] - z11[0][0]).toBeLessThan(0.5);
  });
  it('unionBox', () => {
    expect(unionBox([[0, 0], [1, 1]], [[-1, 0.5], [0.5, 2]])).toEqual([[-1, 0], [1, 2]]);
  });
});
