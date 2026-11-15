import { describe, expect, it } from 'vitest';
import { cardTips, gapTipText, pLabel, trendTipText } from './cardTips';
import { seeAlsoLinks, SEE_ALSO_MAX } from '../components/Hint';
import type { Report } from '../api/types';

const sp = (s: string) => s.replace(/ /g, ' ');

describe('pLabel', () => {
  it('formats p per language', () => {
    expect(sp(pLabel(0.002, 'uk')!)).toBe('p = 0,002');
    expect(sp(pLabel(0.002, 'en')!)).toBe('p = 0.002');
    expect(sp(pLabel(0.372, 'uk')!)).toBe('p = 0,37');
    expect(sp(pLabel(0.00001, 'en')!)).toBe('p < 0.001');
    expect(pLabel(null, 'uk')).toBeNull();
  });
});

describe('trend tip is about THIS trend (Володя 15.11)', () => {
  const ns = { verdict: 'not_significant' as const, slope_per_decade: 0.4, p: 0.37, n_years: 12 };
  const sig = { verdict: 'significant' as const, slope_per_decade: 0.62, p: 0.002, n_years: 12 };
  const down = { ...sig, slope_per_decade: -0.5 };
  const none = { verdict: 'insufficient_data' as const, slope_per_decade: null, p: null, n_years: 5 };
  it('not significant: its slope, p and «поки несуттєво / статистично незначущий»', () => {
    const t = sp(trendTipText(ns, 'uk'));
    expect(t).toBe('+0,4 °C за 10 років, p = 0,37 → поки несуттєво: тренд статистично незначущий. За 12 літніх сезонів зміна не відрізняється від випадкових коливань погоди.');
    expect(t).not.toMatch(/Суттєво|кожна 20-та/);
    expect(sp(trendTipText(ns, 'en'))).toMatch(/^\+0\.4 °C per 10 years, p = 0\.37 → not yet significant: the trend is not statistically significant\. Over 12 summer seasons/);
  });
  it('significant: says so, «сигнал, а не вирок» and the multiple-testing line', () => {
    const t = sp(trendTipText(sig, 'uk'));
    expect(t).toMatch(/^\+0,6 °C за 10 років, p = 0,002 → суттєво: тренд статистично значущий, розрив росте\./);
    expect(t).toMatch(/Це сигнал, а не вирок\. Якщо перевірити дуже багато ділянок, приблизно кожна 20-та/);
    expect(sp(trendTipText(down, 'uk'))).toMatch(/розрив зменшується/);
    expect(sp(trendTipText(sig, 'en'))).toMatch(/→ significant: the trend is statistically significant, the gap is growing\..*A signal, not a verdict\. If very many areas/);
  });
  it('insufficient data: no p, the number of seasons', () => {
    expect(trendTipText(none, 'uk')).toBe('Тренд не рахуємо: є лише 5 літніх сезонів із чистими знімками, а потрібно щонайменше 8.');
    expect(trendTipText(none, 'en')).not.toMatch(/p =/);
  });
});

describe('gap tip', () => {
  const r = {
    gap_summary: { mean: 11.4 }, series: [{ year: 2013 }, { year: 2025 }],
    reference: { city: 'kyiv', kind: 'preset', forest_uk: 'ліс навколо Києва' },
    trend: { verdict: 'not_significant', slope_per_decade: 0.4, p: 0.37, n_years: 12 },
  } as unknown as Report;
  it('what was compared, which summers, surface not air', () => {
    expect(sp(gapTipText(r, 'Позняки', 'uk', 12))).toBe('Поверхня забудови (Позняки) влітку вдень на 11,4 °C гарячіша, ніж ліс навколо Києва: середнє за 12 літніх сезонів (2013–2025). Це температура поверхні (дахи, асфальт) за Landsat 8, не повітря.');
    expect(sp(gapTipText({ ...r, gap_summary: { mean: -1.2 } } as unknown as Report, 'Парк', 'en', 12))).toMatch(/is 1\.2 °C cooler than/);
  });
  it('card tips carry one «Як ми це рахуємо →» link and nothing else', () => {
    const t = cardTips(r, 'Позняки', 'uk', 12, () => {});
    expect(t.trend.link?.label).toBe('Як ми це рахуємо →');
    expect(t.gap.term).toBe('Розрив з лісом тут');
  });
});

describe('«Див. також» (Володя 15.11)', () => {
  it('at most two links, none to the entry itself or to what is on screen', () => {
    expect(seeAlsoLinks(['a', 'b', 'c', 'd'], new Set(), 'x')).toHaveLength(SEE_ALSO_MAX);
    expect(seeAlsoLinks(['pValue', 'notSignificant', 'mannKendall'], new Set(['pValue', 'mannKendall']), 'significant')).toEqual(['notSignificant']);
    expect(seeAlsoLinks(undefined, new Set(), 'x')).toEqual([]);
  });
});
