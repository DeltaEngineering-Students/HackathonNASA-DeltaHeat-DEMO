import type { ColorStop } from '../api/types';

/** CSS linear-gradient for a legend from value stops (positions proportional to value). */
export function gradientCss(stops: ColorStop[]): string {
  if (stops.length === 0) return 'transparent';
  const lo = stops[0]![0];
  const hi = stops[stops.length - 1]![0];
  const span = hi - lo || 1;
  return `linear-gradient(90deg, ${stops.map(([v, c]) => `${c} ${(((v - lo) / span) * 100).toFixed(1)}%`).join(', ')})`;
}

export interface LegendTick { pos: number; label: string }

/** Number label for a legend tick: decimal comma, U+2212 minus, «+» on diverging scales, ≤ 2 decimals. */
export function tickLabel(v: number, signed: boolean): string {
  const a = Math.abs(v).toFixed(2).replace(/\.?0+$/, '').replace('.', ',');
  if (v < 0) return `\u2212${a}`;
  return signed && v > 0 ? `+${a}` : a;
}

/**
 * Numeric legend ticks from the colour stops (QA-12): always both ends and 0 (when inside the range),
 * then other stops greedily while they stay ≥ `minGap` (fraction of the bar) apart. The unit goes on the last tick.
 */
export function legendTicks(stops: ColorStop[], unit: string, signed: boolean, minGap = 0.2, widthPx = 200): LegendTick[] {
  if (stops.length === 0) return [];
  const lo = stops[0]![0];
  const hi = stops[stops.length - 1]![0];
  const span = hi - lo || 1;
  const pos = (v: number) => (v - lo) / span;
  const label = (v: number) => tickLabel(v, signed) + (v === hi && unit ? ` ${unit}` : '');
  // labels as pixel intervals (first is left-aligned, last right-aligned, others centred): no two may touch
  // — «42 50 °C» read as «4250 °C» (QA-UX R3-2)
  const CH = 7.4, PAD = 8;
  const box = (v: number): [number, number] => {
    const x = pos(v) * widthPx, w = label(v).length * CH;
    return v === lo ? [x, x + w] : v === hi ? [x - w, x] : [x - w / 2, x + w / 2];
  };
  const fits = (v: number, chosen: number[]) => {
    const [a, b] = box(v);
    return chosen.every((c) => { const [ca, cb] = box(c); return b + PAD <= ca || cb + PAD <= a; }) &&
      chosen.every((c) => Math.abs(pos(c) - pos(v)) >= minGap);
  };
  const chosen = [lo, hi];
  if (lo < 0 && hi > 0 && fits(0, chosen)) chosen.push(0);
  for (const [v] of stops) {
    if (chosen.includes(v)) continue;
    if (fits(v, chosen)) chosen.push(v);
  }
  return chosen.sort((a, b) => a - b).map((v) => ({ pos: pos(v) * 100, label: label(v) }));
}
