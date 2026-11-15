// Ukrainian number formatting: decimal comma, true minus sign (U+2212), thin no-break spaces.
// English (default UI, I18N.md §4) goes through i18n/format: decimal point, the same rounding; Ukrainian output is unchanged.
import { getLocale } from '../i18n/locale';
import { num, summers as summersL } from '../i18n/format';

const isEn = () => getLocale() === 'en';
export const MINUS = '−';

/** Round half away from zero using the shortest decimal representation of `x` (like Python Decimal(repr(x))). */
export function roundHalfUp(x: number, digits: number): number {
  const a = Math.abs(x);
  let r = Number(`${Math.round(Number(`${a}e${digits}`))}e-${digits}`);
  if (!Number.isFinite(r)) r = Number(a.toFixed(digits)); // exponent notation (tiny/huge values)
  return x < 0 ? -r : r;
}

export function fmt(x: number | null | undefined, digits = 1, sign = false): string {
  if (x == null || !Number.isFinite(x)) return '—';
  if (isEn()) return num(x, 'en', digits, sign); // I18N.md §4: decimal point, same half-up value
  // avoid "−0,0"
  // half away from zero on the decimal representation — same as the backend (Decimal ROUND_HALF_UP), so the
  // card's numbers match the numbers inside the backend's sentences (7.55 → 7,6; toFixed would give 7,5)
  const rounded = roundHalfUp(x, digits);
  const v = Object.is(rounded, -0) ? 0 : rounded;
  let s = Math.abs(v).toFixed(digits).replace('.', ',');
  if (v < 0) s = MINUS + s;
  else if (sign && v > 0) s = '+' + s;
  return s;
}

/** "+9,0°" style. */
export const fmtDeg = (x: number | null | undefined, digits = 1, sign = true) =>
  x == null ? '—' : `${fmt(x, digits, sign)}°`;

export const fmtC = (x: number | null | undefined, digits = 1, sign = false) =>
  x == null ? '—' : `${fmt(x, digits, sign)} °C`;

export const fmtPct = (x: number | null | undefined, digits = 0) =>
  x == null ? '—' : isEn() ? `${fmt(x * 100, digits)}%` : `${fmt(x * 100, digits)} %`;

/** p-value: "0,59", small values "< 0,001". */
export function fmtP(p: number | null | undefined): string {
  if (p == null) return '—';
  if (p < 0.001) return isEn() ? '< 0.001' : '< 0,001';
  return fmt(p, p < 0.01 ? 3 : 2);
}

/** Ukrainian plural: plural(13, ['літо','літа','літ']) → 'літ'. */
export function plural(n: number, forms: [string, string, string]): string {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return forms[2];
  if (b === 1) return forms[0];
  if (b >= 2 && b <= 4) return forms[1];
  return forms[2];
}

// TERMS-UK §1 (mentor, item 31): «літній сезон», never the counting plural «літ»
export const summers = (n: number) => (isEn() ? summersL(n, 'en') : `${n} ${plural(n, ['літній сезон', 'літні сезони', 'літніх сезонів'])}`);
/** genitive: «дані 13 літніх сезонів», «1 літнього сезону» */
export const summersGen = (n: number) => (isEn() ? summersL(n, 'en') : `${n} ${plural(n, ['літнього сезону', 'літніх сезонів', 'літніх сезонів'])}`);

export function fmtArea(km2: number | null | undefined): string {
  if (km2 == null) return '—';
  return `${fmt(km2, km2 < 10 ? 1 : 0)} ${isEn() ? 'km²' : 'км²'}`;
}
