// Phase 2a: the libs answer in English when the locale is en, and stay Ukrainian otherwise (I18N.md §7).
import sample from '../api/samples/analyze.json';
import { adaptReport } from '../api/adapt';
import type { OverviewPlace, Report } from '../api/types';
import { fmt, fmtArea, fmtP, fmtPct, summers } from '../lib/format';
import { ciSentence, excludedLabel, excludedText, highlightVerdict, trendSub, verdictView, verdictWord } from '../lib/verdict';
import { cardYearLine, climateLineFromContext, factors, hotspotTip, magnitudeHeadline, rankFromContext, rankText, stableHotText } from '../lib/story';
import { barsMetric, mapLayers, ndviNoData, ndviTicks, overviewNote } from '../lib/layers';
import { markerLabel, markerLegend, markerTip } from '../lib/overview';
import { builtFactorText, builtRows } from '../lib/builtShare';
import { validateDrawn } from '../lib/geo';
import { errorMessage } from '../state/store';
import { gloss } from '../lib/glossary';
import { setLocale } from './locale';

const CYR = /[А-Яа-яІіЇїЄєҐґ]/;
const report = adaptReport(sample as Record<string, unknown>) as Report;
const place: OverviewPlace = { place_id: 'x', name: 'Uzhhorod', kind: 'city', city: null, lon: 22.3, lat: 48.6, bbox: [0, 0, 1, 1], rank: 1,
  status: 'ok', gap_mean: 10.06, war_region: { name: 'Kharkiv', since: 2022 }, reason_uk: null, lst_mean: 36.2 };
const layers = ['gap', 'lst', 'ndvi', 'dndvi'].map((id) => ({ id, name_uk: 'Шар', stops: [], unit: '°C' })) as never;

function texts(): string[] {
  const t = report.trend;
  return [
    fmt(9.55), fmtArea(3.14), fmtP(0.0001), fmtPct(0.45), summers(13),
    verdictView(t).label, verdictView(t).sub, trendSub(t), verdictWord(t.verdict), ciSentence(t),
    excludedLabel('low_coverage'), excludedText({ excluded: 'too_few_scenes', excluded_detail: { text_uk: 'укр' } }),
    rankText(rankFromContext({ rank: 2, of: 10, city: 'kyiv' })!), stableHotText(8), magnitudeHeadline(report).forest,
    ...factors(report).map((f) => `${f.lead ?? ''}${f.text}${f.title ?? ''}`),
    climateLineFromContext({ scenario: 'ssp245', period: '2041-2050', delta: 1.7, delta_range: [0.6, 2.8], baseline_period: [2005, 2014] }, 5)!.main,
    hotspotTip({ center: [0, 0], gap: 11.1, delta_vs_zone: 4.2, years: [2023, 2024] }, 0),
    cardYearLine(report, 2020)?.text ?? '', cardYearLine(report, 2021)?.text ?? '',
    ...mapLayers(layers).flatMap((l) => [l.name, l.short]), ...['gap', 'lst', 'ndvi', 'dndvi'].map((l) => barsMetric(l).caption),
    overviewNote('gap', 'x'), overviewNote('ndvi', 'x'), ndviNoData(), ndviTicks(),
    markerLabel({ ...place, gap_mean: null, status: 'no_data' }), markerLegend(), markerTip(place, null),
    markerTip({ ...place, occupied: { snapshot_date: '2026-09-15', source: 'Мінрозвитку' } }, null),
    builtFactorText(report) ?? '', ...builtRows(report).flat(),
    (validateDrawn({ type: 'Polygon', coordinates: [[[30, 50], [30.001, 50], [30, 50.001], [30, 50]]] }) as { reason: string }).reason,
    errorMessage(422, undefined), errorMessage(undefined, 'insufficient_data'),
    gloss('gap').term, gloss('gap').short, gloss('pValue').more ?? '',
  ];
}

describe('libs in English', () => {
  beforeAll(() => setLocale('en'));
  afterAll(() => setLocale('uk'));
  it('no Cyrillic, decimal point', () => {
    for (const s of texts()) {
      expect(s, s).not.toMatch(CYR);
      expect(s, s).not.toMatch(/\d,\d(?!\d\d)/);
    }
  });
  it('key strings', () => {
    expect(fmt(9.55)).toBe('9.6');
    expect(summers(13)).toBe('13 summer seasons');
    expect(verdictView({ verdict: 'not_significant', slope_per_decade: 0.3 }).label).toBe('Not yet significant');
    expect(magnitudeHeadline(report).forest).toBe('the forest around Kyiv');
    expect(markerTip(place, null)).toBe('Uzhhorod: built-up surface +10.1 °C hotter than the forest around · the surface itself ≈ 36 °C (mean over all summer seasons). War region (Kharkiv, since 2022): changes may result from destruction. Click to open.');
    expect(highlightVerdict('The built-up surface is on average 9.5 °C hotter on summer days than the forest around Kyiv.').filter((x) => x.tone).map((x) => [x.tone, x.text]))
      .toEqual([['heat', '9.5 °C hotter'], ['ref', 'the forest around Kyiv']]);
  });
});

describe('libs in Ukrainian (unchanged)', () => {
  it('still Ukrainian', () => {
    expect(fmt(9.55)).toBe('9,6');
    expect(verdictView({ verdict: 'not_significant', slope_per_decade: 0.3 }).label).toBe('Поки несуттєво');
    expect(gloss('gap').term).toBe('Розрив з лісом');
  });
});
