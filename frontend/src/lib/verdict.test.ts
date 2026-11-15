import { ciSentence, excludedLabel, highlightVerdict, isCounted, isEmptyReport, trendSub, verdictView } from './verdict';
import { REPORTS } from '../fixtures';

describe('verdict mapping', () => {
  it('maps backend verdicts to card labels — never «Доведено» (decision #10)', () => {
    expect(verdictView({ verdict: 'not_significant', slope_per_decade: -1 }).label).toBe('Поки несуттєво');
    expect(verdictView({ verdict: 'significant', slope_per_decade: 1.2 })).toMatchObject({ label: 'Суттєво', sub: 'розрив росте — це не схоже на випадковість' });
    expect(verdictView({ verdict: 'significant', slope_per_decade: -0.8 }).sub).toBe('розрив зменшується — це не схоже на випадковість');
    expect(verdictView({ verdict: 'insufficient_data', slope_per_decade: null }).label).toBe('Замало даних для тренду');
    for (const v of ['significant', 'not_significant', 'insufficient_data'] as const)
      for (const sl of [-1, 0.3, null]) {
        const view = verdictView({ verdict: v, slope_per_decade: sl });
        expect(`${view.label} ${view.sub} ${trendSub({ verdict: v, slope_per_decade: sl })}`).not.toMatch(/Доведено|доведено,|не росте/);
      }
  });
  it('phrases the trend number honestly about its sign', () => {
    expect(trendSub({ verdict: 'not_significant', slope_per_decade: 0.3 })).toBe('за 10 років — розрив помітно не змінився');
    expect(trendSub({ verdict: 'not_significant', slope_per_decade: -1 })).toBe('за 10 років — розрив помітно не змінився');
    expect(trendSub({ verdict: 'significant', slope_per_decade: 0.5 })).toBe('за 10 років — розрив росте');
    expect(trendSub({ verdict: 'significant', slope_per_decade: -0.5 })).toBe('за 10 років — розрив зменшується');
    expect(trendSub({ verdict: 'insufficient_data', slope_per_decade: null })).toBe('за 10 років — невідомо');
  });
  it('keeps the CI sentence consistent with the verdict', () => {
    const t = REPORTS['kyiv-pozniaky']!.trend;
    expect(ciSentence(t)).toContain('разом із «без змін»');
    expect(ciSentence({ ...t, ci95: [0.2, 1.4], slope_per_decade: 0.8, verdict: 'significant' })).toContain('не включає «без змін», і тест');
    expect(ciSentence({ ...t, ci95: [-0.1, 1.4], slope_per_decade: 0.8, verdict: 'significant' })).toContain('доказ слабкий');
    expect(ciSentence({ ...t, ci95: [0.1, 1.4], slope_per_decade: 0.8, verdict: 'not_significant' })).toContain('сприймайте обережно');
    expect(ciSentence({ ...t, ci95: null })).toMatch(/Замало/);
    expect(ciSentence({ ...t, verdict: 'insufficient_data' })).toMatch(/Замало/);
  });
  it('highlights heat amount and reference in the verdict sentence', () => {
    const segs = highlightVerdict('Щоліта тут на 9 °C гарячіше, ніж у лісі за містом, і поки не видно, що стає гірше.');
    expect(segs.filter((s) => s.tone === 'heat').map((s) => s.text)).toEqual(['9 °C гарячіше']);
    expect(segs.filter((s) => s.tone === 'ref').map((s) => s.text)).toEqual(['лісі за містом']);
    expect(segs.map((s) => s.text).join('')).toBe('Щоліта тут на 9 °C гарячіше, ніж у лісі за містом, і поки не видно, що стає гірше.');
  });
  it('leaves unknown sentences intact', () => {
    expect(highlightVerdict('Без цифр.')).toEqual([{ text: 'Без цифр.' }]);
  });
  it('detects empty reports', () => {
    const r = structuredClone(REPORTS['kyiv-pozniaky']!);
    expect(isEmptyReport(r)).toBe(false);
    r.gap_summary.mean = null;
    expect(isEmptyReport(r)).toBe(true);
  });
});

describe('verdict highlight: cooler statements use the reference colour', () => {
  it('colours "прохолодніша" as ref', () => {
    const segs = highlightVerdict('Зелень усередині міста на 11,0 °C прохолодніша за цю забудову.');
    expect(segs.find((s) => s.tone)?.tone).toBe('ref');
  });
});

describe('excluded years (sci-v3.2)', () => {
  it('human reason, never the raw enum', () => {
    expect(excludedLabel('low_coverage')).toBe('немає даних: хмари закрили більшу частину ділянки');
    expect(excludedLabel('something_new')).toBe('немає даних');
    expect(excludedLabel(null)).toBe('немає даних');
  });
  it('a year counts only with a gap and no exclusion', () => {
    expect(isCounted({ gap: 1, excluded: null })).toBe(true);
    expect(isCounted({ gap: null })).toBe(false);
    expect(isCounted({ gap: 1, excluded: 'too_few_scenes' })).toBe(false);
  });
});

describe('highlightVerdict on the M4 driver sentence (item 11)', () => {
  it('leaves «ліс-еталон не має значущого тренду…» plain and still marks the numbers in the same text', () => {
    const t = 'Поверхня забудови на 2,4 °C гарячіша за ліс навколо Києва; ліс-еталон не має значущого тренду, тож зміна йде від самої території.';
    const segs = highlightVerdict(t);
    expect(segs.map((s) => s.text).join('')).toBe(t);
    expect(segs.filter((s) => s.tone).map((s) => [s.tone, s.text])).toEqual([['heat', '2,4 °C гарячіша'], ['ref', 'ліс навколо Києва']]);
  });
});
