import type { Report, Trend, Verdict } from '../api/types';
import { fmt } from './format';
import { getLocale } from '../i18n/locale';
import { DICTS, tr, type MsgKey } from '../i18n';
import { SENTENCES } from '../i18n/sentences';

const isEn = () => getLocale() === 'en';

export interface VerdictView {
  label: string;
  sub: string;
  tone: 'heat' | 'neutral' | 'muted';
}

/**
 * Card label for the backend's trend verdict (the backend decides; we only phrase it).
 * Decision #10: we show evidence, never «доведено» — a p < 0.05 trend on 13 summers is a statistical signal, not proof.
 */
export function verdictView(t: Pick<Trend, 'verdict' | 'slope_per_decade'>): VerdictView {
  if (isEn()) {
    if (t.verdict === 'significant')
      return (t.slope_per_decade ?? 0) >= 0
        ? { label: tr('en', 'verdict.significant'), sub: tr('en', 'verdict.subUp'), tone: 'heat' }
        : { label: tr('en', 'verdict.significant'), sub: tr('en', 'verdict.subDown'), tone: 'neutral' };
    if (t.verdict === 'not_significant') return { label: tr('en', 'verdict.notSignificant'), sub: tr('en', 'verdict.subNs'), tone: 'neutral' };
    return { label: tr('en', 'verdict.insufficient'), sub: tr('en', 'verdict.subInsufficient'), tone: 'muted' };
  }
  switch (t.verdict) {
    case 'significant':
      return (t.slope_per_decade ?? 0) >= 0
        ? { label: 'Суттєво', sub: 'розрив росте — це не схоже на випадковість', tone: 'heat' }
        : { label: 'Суттєво', sub: 'розрив зменшується — це не схоже на випадковість', tone: 'neutral' };
    case 'not_significant':
      // concept §7: «поки не значуще» — «не доведено» reads as «не доведено, що тут спекотно» (QA-UX C12)
      return { label: 'Поки несуттєво', sub: 'зміна менша за різницю між окремими літніми сезонами', tone: 'neutral' };
    case 'insufficient_data':
    default:
      return { label: 'Замало даних для тренду', sub: 'потрібно щонайменше 8 чистих літніх сезонів', tone: 'muted' };
  }
}

/** Sub-label under the trend number; honest about the sign («+0,3°» + «у межах шуму», never «не росте»). */
export function trendSub(t: Pick<Trend, 'verdict' | 'slope_per_decade'>): string {
  if (isEn()) {
    if (t.verdict === 'insufficient_data' || t.slope_per_decade == null) return tr('en', 'verdict.trendUnknown');
    if (t.verdict === 'not_significant') return tr('en', 'verdict.trendFlat');
    return tr('en', t.slope_per_decade >= 0 ? 'verdict.trendUp' : 'verdict.trendDown');
  }
  if (t.verdict === 'insufficient_data' || t.slope_per_decade == null) return 'за 10 років — невідомо';
  if (t.verdict === 'not_significant') return 'за 10 років — розрив помітно не змінився';
  return t.slope_per_decade >= 0 ? 'за 10 років — розрив росте' : 'за 10 років — розрив зменшується';
}

export const verdictWord = (v: Verdict) =>
  isEn() ? tr('en', v === 'significant' ? 'verdict.wordSig' : v === 'not_significant' ? 'verdict.wordNs' : 'verdict.wordInsufficient') :
  v === 'significant' ? 'статистично значущо' : v === 'not_significant' ? 'статистично незначущо' : 'замало даних';

/** Years with a usable gap value. */
export const validSeries = (r: Report) => r.series.filter((s) => s.gap != null && !s.excluded);

/** Whole report is unusable (no mean gap at all) → empty state instead of the card. */
export const isEmptyReport = (r: Report) => r.gap_summary.mean == null || validSeries(r).length === 0;

const degC = (x: number) => `${fmt(x, 1, true)}\u00a0°C`;

/** CI sentence for details §2 — always consistent with the backend verdict (MK p) and the Theil–Sen interval. */
export function ciSentence(t: Trend): string {
  if (isEn()) return SENTENCES.en.ci(t);
  if (t.verdict === 'insufficient_data' || !t.ci95 || t.slope_per_decade == null)
    return 'Замало чистих літніх сезонів, щоб оцінити, як змінюється розрив.';
  const [lo, hi] = t.ci95;
  const includesZero = lo <= 0 && hi >= 0;
  const head = `Найімовірніше ${degC(t.slope_per_decade)} за 10 років`;
  const range = `від ${fmt(lo, 1, true)} до ${degC(hi)}`;
  if (t.verdict === 'significant')
    return includesZero
      ? `${head}. Тест Манна–Кендалла бачить зміну (p < 0,05), але довірчий інтервал ${range} ще зачіпає «без змін» — доказ слабкий.`
      : `${head}; довірчий інтервал ${range} не включає «без змін», і тест Манна–Кендалла це підтверджує — це статистичний доказ, не вирок.`;
  return includesZero
    ? `${head}, але справжня зміна може бути будь-де ${range} — разом із «без змін». Поки це в межах погодного шуму.`
    : `${head}; довірчий інтервал ${range} не включає «без змін», але тест Манна–Кендалла не бачить статистично значущої зміни — сприймайте обережно.`;
}

export interface Seg { text: string; tone?: 'heat' | 'ref' }

/**
 * Colour the verdict sentence like F7: the heat amount in heat colour ("9 °C гарячіше"),
 * the reference in ref colour ("лісі за містом"). Purely presentational.
 */
export function highlightVerdict(text: string): Seg[] {
  // Ukrainian and English (I18N.md): «9 °C гарячіша» / «9.5 °C hotter» = heat; «ліс навколо Києва» / «the forest around Kyiv» and the cooler amount = ref
  const re = /([+−-]?\d+(?:[.,]\d+)?\s*°C\s+(?:гаряч|тепліш|hotter|warmer)\p{L}*)|(лісі? (?:за містом|навколо(?: [А-ЯІЇЄҐ][\p{L}’'-]+)?)|the forest around (?:the city|[A-Z][\p{L}’'-]+)|[+−-]?\d+(?:[.,]\d+)?\s*°C\s+(?:прохолодн|холодн|cooler|colder)\p{L}*)/gu;
  const out: Seg[] = [];
  let last = 0;
  for (const m of text.matchAll(re)) {
    const i = m.index ?? 0;
    if (i > last) out.push({ text: text.slice(last, i) });
    out.push({ text: m[0], tone: m[1] ? 'heat' : 'ref' });
    last = i + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  return out;
}

const EXCLUDED_UK: Record<string, string> = {
  too_few_pixels: 'замало чистих пікселів',
  low_coverage: 'хмари закрили більшу частину ділянки',
  no_reference: 'немає даних по еталонному лісу',
  too_few_scenes: 'замало знімків за літо',
  no_lst_product: 'немає супутникової температури за це літо (прогалина в даних USGS)',
};

/** «немає даних: <причина>» for a year left out of the analysis; never shows the raw enum. */
/** Full reason for one year: the backend sentence (sci-v3.4 `excluded_detail.text_uk`) when present, else the label. */
export function excludedText(row: { excluded?: string | null; excluded_detail?: { text_uk?: string; text_en?: string | null } | null }): string {
  if (isEn()) return row.excluded_detail?.text_en || excludedLabel(row.excluded); // never the Ukrainian sentence in EN
  return row.excluded_detail?.text_uk || excludedLabel(row.excluded);
}

export function excludedLabel(reason: string | null | undefined): string {
  if (isEn()) {
    const k = reason ? (`excluded.${reason}` as MsgKey) : null;
    return k && k in DICTS.en ? tr('en', 'excluded.noDataBecause', { reason: tr('en', k as 'excluded.low_coverage') }) : tr('en', 'excluded.noData');
  }
  const r = reason ? EXCLUDED_UK[reason] : undefined;
  return r ? `немає даних: ${r}` : 'немає даних';
}

/** A year counted in the analysis (has a gap and is not excluded). */
export const isCounted = (s: { gap: number | null; excluded?: string | null }) => s.gap != null && !s.excluded;
