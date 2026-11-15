import { builtFactorText, builtRows, latestSealed } from './builtShare';
import { factors } from './story';
import { numbersToCheck } from '../components/DetailsPanel';
import { REPORTS } from '../fixtures';
import type { Report } from '../api/types';

const n = (x: string | null | undefined) => x?.replace(/[\u00a0\u202f]/g, ' ');
const base = REPORTS['kyiv-pozniaky']!;
// Франківськ, INVESTIGATION-BUILT-SHARE: 92 % of the land, 73 % of the zone (lake + park), GHSL sealed 13 %
const frankivsk = (fresh: boolean): Report => ({
  ...base,
  zone: { ...base.zone, analysed: 'built', ...(fresh ? { sealed_share_ghsl: { '2015': 0.12, '2020': 0.13, '2025': null } } : {}) },
  series: base.series.map((s) => (fresh ? { ...s, built_share: 0.92, built_share_land: 0.92, built_share_zone: 0.73 } : { ...s, built_share: 0.92 })),
});

describe('built share labels (board item 14)', () => {
  it('sci-v3.5.1: the card shows the share of the zone, labelled as Esri urban fabric', () => {
    const last = base.series.filter((s) => s.excluded == null).pop()!.year;
    expect(n(builtFactorText(frankivsk(true)))).toBe(`Забудова (міська тканина, Esri) — 73 % ділянки (${last})`);
    expect(factors(frankivsk(true)).map((f) => n(f.text))).toContain(`Забудова (міська тканина, Esri) — 73 % ділянки (${last})`);
  });
  it('sci-v3.5.1: Details add the land share and the latest GHSL year', () => {
    const rows = Object.fromEntries(builtRows(frankivsk(true)));
    expect(n(rows['Забудова (міська тканина, Esri)'])).toBe('73,0 % → 73,0 % ділянки — з них суходолу: 92,0 %');
    expect(n(rows['Запечатані поверхні (дахи, асфальт; GHSL)'])).toBe('13 % ділянки (2020)');
    expect(latestSealed(frankivsk(true))).toEqual({ year: '2020', share: 0.13 });
    const all = Object.fromEntries(numbersToCheck(frankivsk(true)));
    expect(all['Частка забудови']).toBeUndefined();
    expect(all['Забудова (міська тканина, Esri)']).toMatch(/суходолу/);
  });
  it('sci-v3.5 (no new fields): falls back to built_share, no land suffix, no GHSL line', () => {
    expect(n(builtFactorText(frankivsk(false)))).toMatch(/^Забудова \(міська тканина, Esri\) — 92 % ділянки/);
    const rows = Object.fromEntries(builtRows(frankivsk(false)));
    expect(n(rows['Забудова (міська тканина, Esri)'])).toBe('92,0 % → 92,0 % ділянки');
    expect(rows['Запечатані поверхні (дахи, асфальт; GHSL)']).toBeUndefined();
    expect(builtRows({ ...frankivsk(true), zone: { ...frankivsk(true).zone, sealed_share_ghsl: null } as Report['zone'] }).length).toBe(1);
  });
});
