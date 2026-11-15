import { fmt, fmtDeg, roundHalfUp, fmtP, plural, summers, summersGen, MINUS, fmtPct } from './format';

describe('format', () => {
  it('uses decimal comma and a true minus', () => {
    expect(fmt(9.0)).toBe('9,0');
    expect(fmt(-1.04)).toBe(`${MINUS}1,0`);
    expect(fmt(3.6, 1, true)).toBe('+3,6');
  });
  it('never prints −0,0', () => {
    expect(fmt(-0.01)).toBe('0,0');
    expect(fmt(-0.04, 1, true)).toBe('0,0');
  });
  it('handles missing values', () => {
    expect(fmt(null)).toBe('—');
    expect(fmt(Number.NaN)).toBe('—');
    expect(fmtDeg(null)).toBe('—');
  });
  it('formats degrees with sign', () => {
    expect(fmtDeg(8.97)).toBe('+9,0°');
    expect(fmtDeg(-2.5)).toBe(`${MINUS}2,5°`);
  });
  it('formats p-values', () => {
    expect(fmtP(0.59)).toBe('0,59');
    expect(fmtP(0.0042)).toBe('0,004');
    expect(fmtP(0.0001)).toBe('< 0,001');
  });
  it('formats percent', () => {
    expect(fmtPct(0.968, 1)).toBe('96,8 %');
  });
  it('picks Ukrainian plural forms', () => {
    expect(plural(1, ['літо', 'літа', 'літ'])).toBe('літо');
    expect(plural(3, ['літо', 'літа', 'літ'])).toBe('літа');
    expect(plural(13, ['літо', 'літа', 'літ'])).toBe('літ');
    expect(plural(21, ['літо', 'літа', 'літ'])).toBe('літо');
    expect(summers(12)).toBe('12 літніх сезонів');
    expect(summers(1)).toBe('1 літній сезон');
    expect(summers(3)).toBe('3 літні сезони');
    expect(summersGen(1)).toBe('1 літнього сезону');
    expect(summersGen(13)).toBe('13 літніх сезонів');
  });
});

describe('half-up rounding like the backend (QA-05)', () => {
  it('rounds .x5 away from zero', () => {
    expect(roundHalfUp(7.55, 1)).toBe(7.6);
    expect(roundHalfUp(1.005, 2)).toBe(1.01);
    expect(roundHalfUp(-0.25, 1)).toBe(-0.3);
    expect(roundHalfUp(11.24, 1)).toBe(11.2);
    expect(roundHalfUp(1e-7, 1)).toBe(0);
    expect(fmt(7.55, 1, true)).toBe('+7,6');
  });
});
