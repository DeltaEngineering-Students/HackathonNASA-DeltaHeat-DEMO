import { spotFactor } from './spot';

describe('spotFactor (board item 10)', () => {
  it('is 1 while the zone intersects the viewport and 0 one longer side away', () => {
    expect(spotFactor([100, 100, 200, 200], 1440, 900)).toBe(1);
    expect(spotFactor([1400, 100, 1600, 200], 1440, 900)).toBe(1);
    expect(spotFactor([1440 + 1440, 100, 1440 + 1600, 200], 1440, 900)).toBe(0);
    expect(spotFactor([1440 + 720, 100, 1440 + 800, 200], 1440, 900)).toBeCloseTo(0.5);
    expect(spotFactor([-2000, -2000, -1900, -1900], 1440, 900)).toBe(0);
  });
  it('changes by ≤ 40/1440 per 40 px drag step — no jumps', () => {
    let prev = 1;
    for (let x = 1300; x < 3200; x += 40) {
      const k = spotFactor([x, 300, x + 100, 400], 1440, 900);
      expect(prev - k).toBeLessThanOrEqual(40 / 1440 + 1e-9);
      expect(k).toBeLessThanOrEqual(prev);
      prev = k;
    }
  });
});
