import { hotspotTip, hotspotYears, hotspotsOnLayer, climateLine, climateLineFromContext, districtRangeLine, factors, rankInHeadline, rankFromContext, rankAmong, rankText, stableHotText, isMagnitudeCase } from './story';
import { REPORTS } from '../fixtures';
import type { Report } from '../api/types';

const base = REPORTS['kyiv-pozniaky']!;
const norm = (x: string) => x.replace(/[\u00a0\u202f]/g, ' ');

describe('card story', () => {
  it('ranks among district means', () => {
    const r = rankAmong(10.5, [7.7, 8.2, 11.0, 6.1, null, 9.9], 'Києва')!;
    expect(r).toEqual({ hotterThan: 4, of: 5, cityGen: 'Києва' });
    expect(rankText(r)).toBe('гарячіше, ніж у середньому в 4 з 5 районів Києва');
    expect(rankText({ hotterThan: 5, of: 5, cityGen: 'Києва' })).toMatch(/будь-якому з 5/);
    expect(rankAmong(10, [1, 2], 'Києва')).toBeNull();
  });
  it('magnitude headline only for n.s. hot built-up zones', () => {
    const ns: Report = { ...base, trend: { ...base.trend, verdict: 'not_significant' }, gap_summary: { ...base.gap_summary, mean: 10.5 }, zone: { ...base.zone, analysed: 'built' } };
    expect(isMagnitudeCase(ns)).toBe(true);
    expect(isMagnitudeCase({ ...ns, trend: { ...ns.trend, verdict: 'significant' } })).toBe(false);
    expect(isMagnitudeCase({ ...ns, zone: { ...ns.zone, analysed: 'all_land' } })).toBe(false);
    expect(isMagnitudeCase({ ...ns, gap_summary: { ...ns.gap_summary, mean: 0.2 } })).toBe(false);
    expect(stableHotText(13)).toBe('помітної зміни не видно (дані 13 літніх сезонів)');
  });
  it('factors come from fields only', () => {
    const r: Report = { ...base, zone: { ...base.zone, analysed: 'built' }, green_gap: 9.66, green_scope: 'urban_parks',
      new_built_gap: { area_km2: 0.4, before: { years: [2013, 2014], gap: 2.1 }, after: { years: [2024, 2025], gap: 9.3 } } };
    const fs = factors(r);
    const f = fs.map((x) => x.text);
    expect(f.some((t) => /^Забудова \(міська тканина, Esri\) — [\d,]+\s% ділянки/u.test(t))).toBe(true);
    expect(f).toContain('Парки й сквери в місті на 9,7 °C прохолодніші за цю забудову');
    // QA-UX R4-3: before/after in words, neutral dot, physical caveat in the title
    const nb = fs.find((x) => x.lead === 'Нова забудова')!;
    expect(nb.tone).toBe('neutral');
    expect(nb.text.replace(/\u00a0/g, ' ')).toBe(' (0,4 км², з’явилась після 2014 р.): до будівництва (2013, 2014) ця земля була на 2,1 °C гарячіша за ліс, після (2024, 2025) — на 9,3 °C.');
    expect(nb.title).toMatch(/^Відкритий ґрунт/);
    // |after − before| < 1 °C → no line
    expect(factors({ ...r, new_built_gap: { ...r.new_built_gap!, after: { years: [2024, 2025], gap: 2.6 } } }).some((x) => x.lead)).toBe(false);
    expect(factors({ ...r, green_scope: 'urban_area' }).some((x) => x.text.startsWith('Парки'))).toBe(false);
  });
  it('climate line is the moderate scenario, labelled as air', () => {
    const line = climateLine({ baseline: '2005–2014', projections: [
      { scenario: 'ssp585', period: '2041–2050', delta: 2.7 },
      { scenario: 'ssp245', period: '2071–2080', delta: 2.1 },
      { scenario: 'ssp245', period: '2041–2050', delta: 2.04 },
    ] })!;
    expect(norm(line.main)).toBe('Прогноз: до 2050 денний максимум приземної температури повітря (на висоті 2 м) зросте приблизно на +2,0 °C (порівняно з 2005–2014)');
    expect(line.sub).toBe('Помірний сценарій (SSP2‑4.5). Повітря, не поверхня.');
    expect(climateLine('error')).toBeNull();
  });
  it('backend context.rank: rank 1 = hottest, `of` includes the zone', () => {
    expect(rankFromContext({ rank: 2, of: 11, city: 'kyiv' })).toEqual({ hotterThan: 9, of: 10, cityGen: 'Києва', city: 'kyiv' });
    expect(rankText(rankFromContext({ rank: 1, of: 10, city: 'kyiv', is_district: true })!)).toBe('гарячіше, ніж у середньому в будь-якому з 9 районів Києва');
    expect(rankFromContext({ rank: 1, of: 3, city: 'kyiv' })).toBeNull();
    expect(rankFromContext(null)).toBeNull();
    expect(rankFromContext({ rank: 1, of: 11, city: 'kyiv', compared_to_uk: 'порівняно із забудовою 10 районів Києва', like_for_like: false, note_uk: 'Зона невелика.' }))
      .toMatchObject({ comparedTo: 'порівняно із забудовою 10 районів Києва', note: 'Зона невелика.' });
  });
  it('not like-for-like: no rank in the headline, the districts range instead', () => {
    const r = rankFromContext({ rank: 1, of: 11, city: 'kyiv', like_for_like: false, district_gap_range: [6.78, 9.7],
      note_uk: 'Зона невелика (2,9 км² забудови), а в районах — 15–51 км²: щільний квартал зазвичай гарячіший за середнє по цілому району.' })!;
    expect(rankInHeadline(r)).toBe(false);
    expect(districtRangeLine(r)).toBe('Для порівняння: забудова районів Києва — від +6,8 до +9,7 °C.');
    const d = rankFromContext({ rank: 4, of: 10, city: 'kyiv', is_district: true, like_for_like: true, district_gap_range: [6.78, 9.7] })!;
    expect(rankInHeadline(d)).toBe(true);
    const ex = { hottest: { id: 'kyiv-desnianskyi', short_name: 'Деснянський район', gap: 9.7 }, coolest: { id: 'kyiv-holosiivskyi', short_name: 'Голосіївський район', gap: 6.78 } };
    const withHot = rankFromContext({ rank: 1, of: 11, city: 'kyiv', like_for_like: false, district_gap_range: [6.78, 9.7], district_extremes: ex }, 'kyiv-pozniaky')!;
    expect(districtRangeLine(withHot)).toBe('Для порівняння: забудова районів Києва — від +6,8 (Голосіївський) до +9,7 °C (Деснянський).');
    expect(districtRangeLine({ ...withHot, coolest: { name: 'Голосіївський', gap: 6.75 } })).toContain('від +6,8 (Голосіївський)'); // half-up from the raw gap
    const self = rankFromContext({ rank: 1, of: 10, city: 'kyiv', district_extremes: ex }, 'kyiv-desnianskyi')!;
    expect(self.hottest).toBeUndefined();
    expect(self.coolest).toEqual({ name: 'Голосіївський', gap: 6.78 });
    expect(districtRangeLine(d)).toBeNull();
  });
  it('backend context.climate line', () => {
    // QA-UX R4-1: subject, «прогноз», «ніж у …», model spread and count, air last — all from API fields
    // item 19 F: plain main line; scenario, model range and «air, not surface» in the muted second line
    const o = climateLineFromContext({ scenario: 'ssp245', period: '2041-2050', delta: 1.72, delta_range: [0.58, 2.76], baseline_period: [2005, 2014] }, 5)!;
    expect(norm(o.main)).toBe('Прогноз: до 2050 денний максимум приземної температури повітря (на висоті 2 м) зросте приблизно на +1,7 °C (порівняно з 2005–2014)');
    expect(norm(o.sub)).toBe('Помірний сценарій (SSP2‑4.5), медіана 5 моделей; діапазон 10–90 %: від +0,6 до +2,8 °C. Повітря, не поверхня.');
    expect(norm(climateLineFromContext({ scenario: 'ssp245', period: '2041-2050', delta: -0.4, baseline_period: '2005-2014' })!.main))
      .toBe('Прогноз: до 2050 денний максимум приземної температури повітря (на висоті 2 м) знизиться приблизно на 0,4 °C (порівняно з 2005–2014)');
    expect(climateLineFromContext(null)).toBeNull();
  });
  it('hotspot tooltip uses only API fields', () => {
    expect(hotspotTip({ center: [30.6, 50.4], gap: 13.84, years: [2023, 2024, 2025] }, 0)).toBe('Місце 1: на 13,8 °C гарячіше за ліс. Літні сезони 2023, 2024, 2025.');
    // QA-UX R4-4: the real list of summers (2022 excluded → not «2020–2024»)
    expect(hotspotTip({ center: [30.6, 50.4], gap: 11.1, delta_vs_zone: 4.2, years: [2020, 2021, 2024], type_uk: 'забудова' }, 0))
      .toBe('Місце 1: на 11,1 °C гарячіше за ліс — на 4,2 °C гарячіше, ніж забудова ділянки в середньому. Літні сезони 2020, 2021, 2024. Тут переважно забудова.');
    expect(hotspotsOnLayer('gap') && hotspotsOnLayer('lst')).toBe(true);
    expect(hotspotsOnLayer('ndvi') || hotspotsOnLayer('dndvi')).toBe(false);
  });
});

describe('card year line (item 15 A)', () => {
  const r = REPORTS['kyiv-pozniaky']!;
  const n = (x: string | undefined) => x?.replace(/[  ]/g, ' ');
  it('counted year → its gap; excluded → reason; no year → nothing', async () => {
    const { cardYearLine } = await import('./story');
    const ok = r.series.find((s) => s.gap != null && !s.excluded)!;
    expect(n(cardYearLine(r, ok.year)?.text)).toMatch(new RegExp(`^У ${ok.year}: [+−]\\d+,\\d °C$`));
    const cloudy: Report = { ...r, series: r.series.map((s) => (s.year === 2022 ? { ...s, gap: null, excluded: 'low_coverage' } : s)) };
    expect(cardYearLine(cloudy, 2022)).toEqual({ text: 'У 2022: немає даних (хмари)', empty: true });
    expect(cardYearLine({ ...cloudy, series: cloudy.series.map((s) => (s.year === 2022 ? { ...s, excluded: 'weird' } : s)) }, 2022)?.text).toBe('У 2022: немає даних');
    expect(cardYearLine(r, null)).toBeNull();
    expect(cardYearLine(r, 1999)).toBeNull();
  });
});

describe('hotspot years label', () => {
  const h = (years?: number[]) => ({ center: [30, 50] as [number, number], gap: 10, years });
  it('union across hotspots, a range when consecutive', () => {
    expect(hotspotYears([h([2024, 2025]), h([2023, 2025])])).toBe('2023–2025');
    expect(hotspotYears([h([2019, 2023, 2025])])).toBe('2019, 2023, 2025');
    expect(hotspotYears([h([2025])])).toBe('2025');
    expect(hotspotYears([h(), h()])).toBe('');
  });
});
