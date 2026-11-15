import { area, date, deg, degC, num, pct, perDecade, plural, pValue, summers, summersGen, yearRanges } from './format';
import { fmt, fmtP, fmtArea, fmtPct, summers as summersLib, summersGen as summersGenLib } from '../lib/format';

describe('numbers per locale', () => {
  it('same value, different separator; half-up like the backend', () => {
    expect(num(7.55, 'en')).toBe('7.6');
    expect(num(7.55, 'uk')).toBe('7,6');
    expect(num(-0.04, 'en')).toBe('0.0');
    expect(num(-1.25, 'en', 1, true)).toBe('−1.3');
    expect(num(0.4, 'en', 1, true)).toBe('+0.4');
    expect(num(null, 'en')).toBe('—');
  });
  it('thousands: en from 1,000, uk from 10 000 (narrow no-break space)', () => {
    expect(num(5000, 'en', 0)).toBe('5,000');
    expect(num(5000, 'uk', 0)).toBe('5000');
    expect(num(12500.5, 'uk', 1)).toBe('12 500,5');
    expect(num(1234567, 'en', 0)).toBe('1,234,567');
  });
  it('units', () => {
    expect(degC(11.44, 'en')).toBe('11.4 °C');
    expect(deg(9, 'en')).toBe('+9.0°');
    expect(pct(0.453, 'en')).toBe('45%');
    expect(pct(0.453, 'uk')).toBe('45 %');
    expect(area(3.14, 'en')).toBe('3.1 km²');
    expect(area(31.4, 'uk')).toBe('31 км²');
    expect(perDecade(0.42, 'en')).toBe('+0.4 °C per 10 years');
    expect(perDecade(0.42, 'uk', true)).toBe('+0,4 °C / 10 р.');
  });
  it('p-values', () => {
    expect(pValue(0.372, 'en')).toBe('0.37');
    expect(pValue(0.0042, 'en')).toBe('0.004');
    expect(pValue(0.0001, 'en')).toBe('< 0.001');
  });
  it('Ukrainian output equals lib/format (no regression when the libs delegate)', () => {
    for (const x of [0, 0.05, 7.55, -1.25, 9.04, 0.372, 123.4]) {
      expect(num(x, 'uk')).toBe(fmt(x));
      expect(num(x, 'uk', 2, true)).toBe(fmt(x, 2, true));
    }
    // spacing: lib/format mixes ' ' and U+00A0; the new formatter always uses U+00A0 (TERMS-UK §7) — compare the rest
    const sp = (s: string) => s.replace(/[\u00a0 ]/g, ' ');
    for (const p of [0.37, 0.004, 0.0001]) expect(sp(pValue(p, 'uk'))).toBe(sp(fmtP(p)));
    expect(sp(area(3.14, 'uk'))).toBe(sp(fmtArea(3.14)));
    expect(sp(pct(0.453, 'uk'))).toBe(sp(fmtPct(0.453)));
    for (const n of [1, 2, 5, 11, 13, 21, 22]) {
      expect(summers(n, 'uk')).toBe(summersLib(n));
      expect(summersGen(n, 'uk')).toBe(summersGenLib(n));
    }
  });
});

describe('plurals', () => {
  it('English: one / other', () => {
    expect(summers(1, 'en')).toBe('1 summer season');
    expect(summers(13, 'en')).toBe('13 summer seasons');
    expect(summers(0, 'en')).toBe('0 summer seasons');
  });
  it('Ukrainian: one / few / many (Intl.PluralRules)', () => {
    const f = { one: 'знімок', few: 'знімки', many: 'знімків', other: 'знімка' };
    expect([1, 2, 4, 5, 11, 12, 14, 21, 22, 25, 101, 111].map((n) => plural(n, 'uk', f))).toEqual(
      ['знімок', 'знімки', 'знімки', 'знімків', 'знімків', 'знімків', 'знімків', 'знімок', 'знімки', 'знімків', 'знімок', 'знімків']);
    expect(summers(13, 'uk')).toBe('13 літніх сезонів');
    expect(summersGen(1, 'uk')).toBe('1 літнього сезону');
  });
});

describe('dates and years', () => {
  it('numeric date in both locales, long date per locale', () => {
    expect(date('2026-09-15', 'en')).toBe('15.09.2026');
    expect(date('2026-09-15', 'en', 'long')).toBe('15 September 2026');
    expect(date('2026-09-15', 'uk', 'long')).toMatch(/^15 вересня 2026/);
    expect(date(null, 'en')).toBe('—');
  });
  it('year ranges like the backend _years_str', () => {
    expect(yearRanges([2020, 2013, 2014, 2015])).toBe('2013–2015, 2020');
    expect(yearRanges([2013, 2014])).toBe('2013, 2014');
  });
});
