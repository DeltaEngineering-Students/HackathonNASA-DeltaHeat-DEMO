import { clippedArea, eyebrowFor } from './AnswerCard';
import { numbersToCheck } from './DetailsPanel';
import { REPORTS } from '../fixtures';
import type { Report } from '../api/types';

// MAP-TASKS 24: Ужгород triangle — 3,3 км² drawn, 1,324 км² analysed in Ukraine, 1,997 км² cut off at the border
const base = REPORTS['kyiv-pozniaky']!;
const uzh: Report = { ...base, zone: { ...base.zone, area_km2: 1.324, clipped_km2: 1.997 } };
const n = (x: string | null | undefined) => x?.replace(/[  ]/g, ' ');

describe('area cut at the border (MAP-TASKS 24)', () => {
  it('card eyebrow and Details row say how much is in Ukraine', () => {
    expect(n(clippedArea(uzh))).toBe('3,3 км², з них в Україні 1,3 км²');
    const drawn = { kind: 'drawn' as const, geometry: { type: 'Polygon' as const, coordinates: [] }, areaKm2: 3.32 };
    expect(n(eyebrowFor(drawn, uzh))).toBe('Ваша ділянка · 3,3 км², з них в Україні 1,3 км²');
    expect(n(eyebrowFor(drawn, base))).toBe('Ваша ділянка · 3,3 км²');
    expect(n(Object.fromEntries(numbersToCheck(uzh))['Площа ділянки'])).toMatch(/^3,3 км², з них в Україні 1,3 км², забудова .*; 2,0 км² поза Україною не враховано$/);
  });
  it('nothing cut → no note', () => {
    expect(clippedArea(base)).toBeNull();
    expect(clippedArea({ ...base, zone: { ...base.zone, clipped_km2: 0 } })).toBeNull();
  });
});
