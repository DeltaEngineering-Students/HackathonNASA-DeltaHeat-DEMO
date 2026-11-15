import sample from '../api/samples/analyze.json';
import { adaptReport } from '../api/adapt';
import type { ContextClimate, Hotspot, Report, Trend } from '../api/types';
import { ciSentence } from '../lib/verdict';
import { climateLineFromContext, hotspotTip, newBuiltFactor, rankText, stableHotText } from '../lib/story';
import { SENTENCES, type RankIn } from './sentences';

const CYR = /[А-Яа-яІіЇїЄєҐґ]/;
/** numbers as values: «+9,1» / «+9.1» / «−0,4» → 9.1, -0.4 (thousands separators dropped) */
const nums = (s: string) =>
  (s.replace(/(\d)[, ](\d{3})(?!\d)/g, '$1$2').match(/[−-]?\d+(?:[.,]\d+)?/g) ?? []).map((x) => Number(x.replace('−', '-').replace(',', '.'))).sort((a, b) => a - b);

const report = adaptReport(sample as Record<string, unknown>) as Report;
const trends: Trend[] = [
  { verdict: 'significant', slope_per_decade: 0.84, ci95: [0.3, 1.41], p: 0.004, n_years: 12 },
  { verdict: 'significant', slope_per_decade: 0.5, ci95: [-0.05, 1.1], p: 0.04, n_years: 12 },
  { verdict: 'not_significant', slope_per_decade: 0.31, ci95: [-1.0, 2.1], p: 0.37, n_years: 13 },
  { verdict: 'not_significant', slope_per_decade: -0.6, ci95: [-1.2, -0.1], p: 0.08, n_years: 10 },
  { verdict: 'insufficient_data', slope_per_decade: null, ci95: null, p: null, n_years: 5 },
];
const ranks: RankIn[] = [
  { hotterThan: 9, of: 9, city: 'kyiv', cityGen: 'Києва' },
  { hotterThan: 0, of: 9, city: 'kharkiv', cityGen: 'Харкова' },
  { hotterThan: 6, of: 9, city: 'lviv', cityGen: 'Львова' },
];
const climates: ContextClimate[] = [
  { scenario: 'ssp245', period: '2041-2050', delta: 1.72, delta_range: [0.6, 2.8], baseline_period: [2005, 2014] },
  { scenario: 'ssp585', period: '2071–2080', delta: -0.25, baseline_period: '2005-2014' },
];
const hots: Hotspot[] = [
  { center: [30.6, 50.4], gap: 11.14, delta_vs_zone: 4.2, years: [2020, 2021, 2024], type_uk: 'забудова' },
  { center: [30.6, 50.4], gap: -0.4, years: [2025] },
];

describe('Ukrainian builders = current lib wording (no regression at wiring)', () => {
  it('rank, n.s. caption, climate, hotspots, CI', () => {
    for (const r of ranks) expect(SENTENCES.uk.rank(r)).toBe(rankText({ ...r, cityGen: r.cityGen! }));
    for (const n of [1, 8, 13]) expect(SENTENCES.uk.stableHot(n)).toBe(stableHotText(n));
    for (const c of climates) for (const m of [undefined, 5]) expect(SENTENCES.uk.climate(c, m)).toEqual(climateLineFromContext(c, m));
    hots.forEach((h, i) => expect(SENTENCES.uk.hotspotTip(h, i)).toBe(hotspotTip(h, i)));
    for (const t of trends) expect(SENTENCES.uk.ci(t)).toBe(ciSentence(t));
  });
  it('new built-up land', () => {
    const nb = { area_km2: 0.7, before: { years: [2014, 2016], gap: 8.1 }, after: { years: [2021, 2024], gap: 6.2 },
      series: [{ year: 2014, gap: 8.0 }, { year: 2016, gap: 8.2 }, { year: 2021, gap: 4.9 }, { year: 2024, gap: 6.4 }] };
    const lib = newBuiltFactor({ ...report, new_built_gap: nb } as Report)!;
    const gaps = nb.series.map((x) => x.gap);
    const ours = SENTENCES.uk.newBuilt({ ...nb, spread: [Math.min(...gaps), Math.max(...gaps)] });
    expect(ours).toEqual({ lead: lib.lead, text: lib.text, title: lib.title });
  });
});

describe('English builders', () => {
  const all: [string, string][] = [];
  for (const r of ranks) all.push([SENTENCES.en.rank(r), SENTENCES.uk.rank(r)]);
  all.push([SENTENCES.en.districtRange({ ...ranks[0]!, range: [5.1, 9.4], hottest: { name: 'Dniprovskyi', gap: 9.44 }, coolest: { name: 'Holosiivskyi', gap: 5.06 } })!,
    SENTENCES.uk.districtRange({ ...ranks[0]!, range: [5.1, 9.4], hottest: { name: 'Дніпровський', gap: 9.44 }, coolest: { name: 'Голосіївський', gap: 5.06 } })!]);
  for (const n of [1, 8, 13]) all.push([SENTENCES.en.stableHot(n), SENTENCES.uk.stableHot(n)]);
  for (const c of climates) for (const m of [undefined, 5]) {
    const e = SENTENCES.en.climate(c, m)!, u = SENTENCES.uk.climate(c, m)!;
    all.push([e.main, u.main], [e.sub, u.sub.replace(/SSP\d‑\d\.\d/, '')]);
  }
  hots.forEach((h, i) => all.push([SENTENCES.en.hotspotTip(h, i), SENTENCES.uk.hotspotTip(h, i)]));
  for (const t of trends) all.push([SENTENCES.en.ci(t), SENTENCES.uk.ci(t)]);
  all.push([SENTENCES.en.parksCooler(5.01), SENTENCES.uk.parksCooler(5.01)]);
  all.push([SENTENCES.en.greenTrend(true, 0.41, 0.48), SENTENCES.uk.greenTrend(true, 0.41, 0.48)]);
  const nb = { area_km2: 0.7, before: { years: [2014, 2016], gap: 8.1 }, after: { years: [2021, 2024], gap: -0.6 }, spread: [4.9, 8.2] as [number, number] };
  const ne = SENTENCES.en.newBuilt(nb), nu = SENTENCES.uk.newBuilt(nb);
  all.push([ne.text, nu.text], [ne.title, nu.title]);

  it.each(all.map(([e, u], i) => [i, e, u] as const))('#%i has no Cyrillic and the same numbers as Ukrainian: %s', (_i, e, u) => {
    expect(e).not.toMatch(CYR);
    expect(e).not.toMatch(/\d,\d(?!\d\d)/);
    expect(nums(e.replace(/SSP\d‑\d\.\d/, ''))).toEqual(nums(u.replace(/SSP\d‑\d\.\d/, '')));
  });

  it('reads naturally on the key cases', () => {
    expect(SENTENCES.en.rank(ranks[2]!)).toBe('hotter than the average of 6 of the 9 Lviv districts');
    expect(SENTENCES.en.rank({ hotterThan: 2, of: 4 })).toBe('hotter than the average of 2 of the 4 districts of the city');
    expect(SENTENCES.en.stableHot(1)).toBe('no clear change (data from 1 summer season)');
    expect(SENTENCES.en.forest('kyiv', false)).toBe('the forest around Kyiv');
    expect(SENTENCES.en.climate(climates[0]!, 5)!.main).toBe('Outlook: by 2050 the summer daily maximum near-surface air temperature (2 m) will rise by about +1.7 °C (compared with 2005–2014)');
  });

  it('verdict fallback: English lead from report fields, numbers identical to the backend sentence', () => {
    const e = SENTENCES.en.verdict(report)!;
    expect(e).not.toMatch(CYR);
    expect(e).toMatch(/^The (built-up )?surface/);
    // the sample is an older method version (its Ukrainian template also printed the slope); the current
    // science template prints mean, n, p and the parks gap — the same numbers the English lead must carry
    expect(e).toBe('The built-up surface is on average 9.5 °C hotter on summer days than the forest around Kyiv, and over 13 summer seasons this gap has not changed noticeably (not statistically significant, p = 0.08). Greenness in the area is increasing (statistically significant). Parks and squares inside the city are 9.4 °C cooler than this built-up land.');
    expect(SENTENCES.en.verdict(report, 'Pozniaky')!.startsWith('Pozniaky: the built-up surface')).toBe(true);
    expect(SENTENCES.en.verdict({ ...report, gap_summary: { ...report.gap_summary, mean: null } })).toBe('Too little data for a conclusion.');
    expect(SENTENCES.uk.verdict(report)).toBeNull();
  });
});
