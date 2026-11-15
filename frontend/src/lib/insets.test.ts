import { awayStep, CARD_INSET, DETAILS_INSET, leftInset, PILL_INSET, zoneK } from './insets';

describe('free-area insets (MAP-TASKS 12)', () => {
  it('details > card > collapsed pill', () => {
    expect(leftInset({ details: true, collapsed: true })).toBe(DETAILS_INSET);
    expect(leftInset({ details: false, collapsed: false })).toBe(CARD_INSET);
    expect(leftInset({ details: false, collapsed: true })).toBe(PILL_INSET);
  });
  it('away clock: weighted by k, resets in view, ~1 s when far', () => {
    let acc = 0;
    for (let i = 0; i < 10; i++) acc = awayStep(acc, 0, 0.1);
    expect(acc).toBeCloseTo(1);
    expect(awayStep(acc, 1, 0.1)).toBe(0);
    // just past the edge (k = 0.8) accumulates 5× slower — no hard threshold
    expect(awayStep(0, 0.8, 1)).toBeCloseTo(0.2);
  });
  it('zoneK: in view 1, a screen away 0', () => {
    const id = ([x, y]: [number, number]) => ({ x, y: -y });
    expect(zoneK([10, -20, 20, -10], id, 100, 100)).toBe(1);
    expect(zoneK([300, -20, 310, -10], id, 100, 100)).toBe(0);
  });
});
