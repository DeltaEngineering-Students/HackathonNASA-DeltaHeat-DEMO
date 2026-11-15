import { legendTicks, tickLabel } from './colors';
import type { ColorStop } from '../api/types';

const GAP: ColorStop[] = [[-6, '#a'], [-2, '#b'], [0, '#c'], [2, '#d'], [5, '#e'], [8, '#f'], [12, '#g']];
const LST: ColorStop[] = [[15, '#a'], [22, '#b'], [27, '#c'], [31, '#d'], [36, '#e'], [42, '#f'], [50, '#g']];

describe('legend ticks (QA-12)', () => {
  it('formats with decimal comma, U+2212 minus and optional plus', () => {
    expect(tickLabel(-6, true)).toBe('−6');
    expect(tickLabel(0.15, true)).toBe('+0,15');
    expect(tickLabel(0, true)).toBe('0');
    expect(tickLabel(0.9, false)).toBe('0,9');
  });
  it('gap: ends, zero and spaced stops, unit on the last tick', () => {
    expect(legendTicks(GAP, '°C', true).map((t) => t.label)).toEqual(['−6', '0', '+5', '+12 °C']);
  });
  it('lst: sequential ticks without plus, positions in %', () => {
    const t = legendTicks(LST, '°C', false);
    expect(t.map((x) => x.label)).toEqual(['15', '22', '31', '50 °C']); // «42 50 °C» collided (R3-2)
    expect(t[0]!.pos).toBe(0);
    expect(t[t.length - 1]!.pos).toBe(100);
  });
  it('R3-2: no two labels touch at 200 px', () => {
    for (const st of [GAP, LST]) {
      const t = legendTicks(st, '°C', st === GAP);
      for (let i = 1; i < t.length; i++) {
        const gapPx = (t[i]!.pos - t[i - 1]!.pos) * 2;
        const half = (t[i - 1]!.label.length + t[i]!.label.length) * 3.7;
        expect(gapPx).toBeGreaterThan(i === t.length - 1 ? half / 2 + t[i]!.label.length * 3.7 : half / 2);
      }
    }
  });
  it('no stops → no ticks', () => expect(legendTicks([], '°C', true)).toEqual([]));
});
