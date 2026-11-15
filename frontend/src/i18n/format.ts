// Locale-aware number / unit / plural / date formatting (uhd/docs/I18N.md §4, TERMS-EN.md §7, TERMS-UK.md §7).
// Rounding is the SAME half-up rule as lib/format.ts and the backend in both languages: a locale changes how a number
// is written, never its value («7,6» ⇔ «7.6»).
import { roundHalfUp } from '../lib/format';
import { INTL_TAG, type Locale } from './locale';

export const MINUS = '−';
/** no-break space between a number and its unit («11.4 °C», «3.1 km²») */
export const NBSP = ' ';
/** narrow no-break space: Ukrainian thousands separator («12 500») */
export const NNBSP = ' ';
export const EM_DASH = '—';

/** Decimal separator per locale (TERMS-EN §7: point; TERMS-UK §7: comma). */
export const DECIMAL: Record<Locale, string> = { en: '.', uk: ',' };

function group(int: string, l: Locale): string {
  // en: 1,000 and up; uk: 10 000 and up (four-digit numbers stay solid, as in the current Ukrainian UI)
  if (l === 'en' ? int.length < 4 : int.length < 5) return int;
  return int.replace(/\B(?=(\d{3})+(?!\d))/g, l === 'en' ? ',' : NNBSP);
}

/** «+1.3» / «−0.4» / «7,6» — half-up, U+2212 minus, no «−0.0». */
export function num(x: number | null | undefined, l: Locale, digits = 1, sign = false): string {
  if (x == null || !Number.isFinite(x)) return EM_DASH;
  const r = roundHalfUp(x, digits);
  const v = Object.is(r, -0) ? 0 : r;
  const [i, f] = Math.abs(v).toFixed(digits).split('.');
  let s = group(i!, l) + (f ? DECIMAL[l] + f : '');
  if (v < 0) s = MINUS + s;
  else if (sign && v > 0) s = '+' + s;
  return s;
}

/** «+9.0°» (big card number, no «C» — TERMS-UK §7 / TERMS-EN §7). */
export const deg = (x: number | null | undefined, l: Locale, digits = 1, sign = true) =>
  x == null ? EM_DASH : `${num(x, l, digits, sign)}°`;

/** «11.4 °C» */
export const degC = (x: number | null | undefined, l: Locale, digits = 1, sign = false) =>
  x == null ? EM_DASH : `${num(x, l, digits, sign)}${NBSP}°C`;

/** share 0..1 → «45%» (en, no space — English convention) / «45 %» (uk). */
export const pct = (x: number | null | undefined, l: Locale, digits = 0) =>
  x == null ? EM_DASH : `${num(x * 100, l, digits)}${l === 'uk' ? NBSP : ''}%`;

/** p-value without «p =»: «0.37», «0.004», «< 0.001». */
export function pValue(p: number | null | undefined, l: Locale): string {
  if (p == null) return EM_DASH;
  if (p < 0.001) return `<${NBSP}${num(0.001, l, 3)}`;
  return num(p, l, p < 0.01 ? 3 : 2);
}

/** «3.1 km²» / «3,1 км²»; one decimal under 10 km². */
export function area(km2: number | null | undefined, l: Locale): string {
  if (km2 == null) return EM_DASH;
  return `${num(km2, l, km2 < 10 ? 1 : 0)}${NBSP}${l === 'en' ? 'km²' : 'км²'}`;
}

/** Trend unit: «+0.4 °C per 10 years» (UI) / «+0,4 °C за 10 років». Table form: «+0.4 °C / 10 yr» / «+0,4 °C / 10 р.». */
export function perDecade(x: number | null | undefined, l: Locale, table = false): string {
  if (x == null) return EM_DASH;
  const v = degC(x, l, 1, true);
  if (table) return `${v} / 10${NBSP}${l === 'en' ? 'yr' : 'р.'}`;
  return `${v} ${l === 'en' ? 'per 10 years' : 'за 10 років'}`;
}

// ── Plurals ─────────────────────────────────────────────────────────────────────────────────────

/** CLDR categories used by en (one, other) and uk (one, few, many, other). */
export interface PluralForms { one: string; few?: string; many?: string; other: string }

const rules = new Map<Locale, Intl.PluralRules>();
const ruleFor = (l: Locale) => {
  let r = rules.get(l);
  if (!r) rules.set(l, (r = new Intl.PluralRules(INTL_TAG[l])));
  return r;
};

/** The plural form for n (integers; Ukrainian «few» = 2–4, 22–24 …, «many» = 0, 5–20, 25–30 …). */
export function plural(n: number, l: Locale, f: PluralForms): string {
  const cat = ruleFor(l).select(n) as keyof PluralForms;
  return f[cat] ?? f.other;
}

const SEASONS: Record<Locale, { nom: PluralForms; gen: PluralForms }> = {
  en: {
    nom: { one: 'summer season', other: 'summer seasons' },
    gen: { one: 'summer season', other: 'summer seasons' },
  },
  uk: {
    // TERMS-UK §1 (mentor): «літній сезон», never the counting plural «літ»
    nom: { one: 'літній сезон', few: 'літні сезони', many: 'літніх сезонів', other: 'літнього сезону' },
    gen: { one: 'літнього сезону', few: 'літніх сезонів', many: 'літніх сезонів', other: 'літнього сезону' },
  },
};

/** «13 summer seasons» / «13 літніх сезонів». */
export const summers = (n: number, l: Locale) => `${n} ${plural(n, l, SEASONS[l].nom)}`;
/** genitive in uk («дані 13 літніх сезонів»); same as `summers` in English («data from 13 summer seasons»). */
export const summersGen = (n: number, l: Locale) => `${n} ${plural(n, l, SEASONS[l].gen)}`;

// ── Dates and years ─────────────────────────────────────────────────────────────────────────────

/**
 * ISO date → «15.09.2026» (numeric; both locales — the official dated-list wording, TERMS-EN §8) or, with
 * style 'long', «15 September 2026» / «15 вересня 2026 р.».
 */
export function date(iso: string | null | undefined, l: Locale, style: 'numeric' | 'long' = 'numeric'): string {
  const m = iso ? /^(\d{4})-(\d{2})-(\d{2})/.exec(iso) : null;
  if (!m) return EM_DASH;
  const [, y, mo, d] = m;
  if (style === 'numeric') return `${d}.${mo}.${y}`;
  const dt = new Date(Date.UTC(Number(y), Number(mo) - 1, Number(d)));
  const s = new Intl.DateTimeFormat(INTL_TAG[l], { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }).format(dt);
  return s;
}

/** [2013, 2014, 2015, 2020] → «2013–2015, 2020» (en dash, same as the backend's _years_str). */
export function yearRanges(years: readonly number[]): string {
  const ys = [...new Set(years)].sort((a, b) => a - b);
  const parts: string[] = [];
  for (let i = 0; i < ys.length; ) {
    let j = i;
    while (j + 1 < ys.length && ys[j + 1] === ys[j]! + 1) j++;
    parts.push(j === i ? `${ys[i]}` : j === i + 1 ? `${ys[i]}, ${ys[j]}` : `${ys[i]}–${ys[j]}`);
    i = j + 1;
  }
  return parts.join(', ');
}

/** Bound formatters for one locale: `const f = formatter(l); f.degC(x)`. */
export function formatter(l: Locale) {
  return {
    locale: l,
    num: (x: number | null | undefined, digits = 1, sign = false) => num(x, l, digits, sign),
    deg: (x: number | null | undefined, digits = 1, sign = true) => deg(x, l, digits, sign),
    degC: (x: number | null | undefined, digits = 1, sign = false) => degC(x, l, digits, sign),
    pct: (x: number | null | undefined, digits = 0) => pct(x, l, digits),
    p: (p: number | null | undefined) => pValue(p, l),
    area: (km2: number | null | undefined) => area(km2, l),
    perDecade: (x: number | null | undefined, table = false) => perDecade(x, l, table),
    summers: (n: number) => summers(n, l),
    summersGen: (n: number) => summersGen(n, l),
    plural: (n: number, f: PluralForms) => plural(n, l, f),
    date: (iso: string | null | undefined, style: 'numeric' | 'long' = 'numeric') => date(iso, l, style),
  };
}
export type Formatter = ReturnType<typeof formatter>;
