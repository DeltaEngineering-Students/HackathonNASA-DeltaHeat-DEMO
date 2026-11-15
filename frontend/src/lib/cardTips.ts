// Card tooltips built from THIS report (Володя, 15.11): the ⓘ next to the gap, the trend and the verdict label say
// what was found here — the numbers, p and the verdict word — instead of the generic glossary entry with its
// «Див. також» chain. Wording: TERMS-UK / TERMS-EN («статистично значущий / незначущий» next to p).
import type { Report, Trend } from '../api/types';
import { num, pValue, summers } from '../i18n/format';
import { SENTENCES } from '../i18n/sentences';
import { tr, type Locale } from '../i18n';

/** A tooltip text that replaces a glossary entry: a title, one paragraph, optionally one link. */
export interface CustomTip { term: string; short: string; link?: { label: string; onClick: () => void } }

/** «p = 0,37» / «p = 0.002» / «p < 0,001»; null without a p. */
export function pLabel(p: number | null | undefined, l: Locale): string | null {
  if (p == null || !Number.isFinite(p)) return null;
  const v = pValue(p, l);
  return v.startsWith('<') ? `p ${v}` : `p = ${v}`;
}

const NBSP = ' ';

/** The trend / verdict tip: slope, p, the verdict word and what it means for these summers. */
export function trendTipText(t: Pick<Trend, 'verdict' | 'slope_per_decade' | 'p' | 'n_years'>, l: Locale, nSeasons = t.n_years): string {
  const seasons = summers(nSeasons, l);
  if (t.verdict === 'insufficient_data' || t.slope_per_decade == null) return tr(l, 'cardTip.trendInsufficient', { seasons });
  const slope = `${num(t.slope_per_decade, l, 1, true)}${NBSP}°C`;
  const p = pLabel(t.p, l) ?? 'p = —';
  if (t.verdict === 'significant')
    return `${tr(l, t.slope_per_decade >= 0 ? 'cardTip.trendSigUp' : 'cardTip.trendSigDown', { slope, p, seasons })} ${tr(l, 'cardTip.multiple')}`;
  return tr(l, 'cardTip.trendNs', { slope, p, seasons });
}

/** The gap tip: what was compared with what, over which summers, and that it is the surface, not air. */
export function gapTipText(r: Pick<Report, 'gap_summary' | 'series' | 'reference'>, name: string, l: Locale, nSeasons: number): string {
  const mean = r.gap_summary.mean ?? 0;
  const years = r.series.map((s) => s.year);
  const forest = l === 'en'
    ? SENTENCES.en.forest(r.reference.city, r.reference.kind === 'derived')
    : r.reference.forest_uk ?? SENTENCES.uk.forest(r.reference.city, r.reference.kind === 'derived');
  return tr(l, mean >= 0 ? 'cardTip.gapHot' : 'cardTip.gapCool', {
    name, gap: `${num(Math.abs(mean), l, 1)}${NBSP}°C`, forest, seasons: summers(nSeasons, l),
    from: years.length ? Math.min(...years) : '', to: years.length ? Math.max(...years) : '',
  });
}

/** Both card tips; `onHow` opens the method block in Details («Як ми це рахуємо →»). */
export function cardTips(r: Report, name: string, l: Locale, nSeasons: number, onHow?: () => void): { gap: CustomTip; trend: CustomTip } {
  const link = onHow ? { label: tr(l, 'cardTip.howLink'), onClick: onHow } : undefined;
  return {
    gap: { term: tr(l, 'cardTip.gapTerm'), short: gapTipText(r, name, l, nSeasons), link },
    trend: { term: tr(l, 'cardTip.trendTerm'), short: trendTipText(r.trend, l, nSeasons), link },
  };
}
