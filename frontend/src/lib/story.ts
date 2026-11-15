// Card story for a zone: magnitude + context first, then what heats / cools it, then the climate outlook.
// Every number comes from API fields (report, presets' reports, /api/climate); rounding = fmt (half-up).
import type { Climate, ContextClimate, ContextRank, DistrictRef, Hotspot, Report } from '../api/types';
import { CITY_GEN } from '../api/adapt';
import { fmt, summersGen } from './format';
import { isCounted } from './verdict';
import type { GlossaryKey } from './glossary';
import { builtFactorText } from './builtShare';
import { getLocale } from '../i18n/locale';
import { DICTS, tr, type MsgKey } from '../i18n';
import { SENTENCES } from '../i18n/sentences';
import { nameEn } from '../i18n/placeName';

const isEn = () => getLocale() === 'en';

/** «гарячіше, ніж у середньому в N з M районів Києва» — rank of the zone gap among the city's district means. */
export interface Rank {
  hotterThan: number; of: number; cityGen: string;
  /** city id (for the English name, I18N.md) */
  city?: string;
  /** backend label «порівняно із забудовою 10 районів Києва» and the not-like-for-like note (API v1.9) */
  comparedTo?: string; note?: string;
  /** false: a small dense zone vs whole districts — no rank in the headline (coordinator review) */
  likeForLike?: boolean;
  /** district built-up gap range [min, max], °C */
  range?: [number, number];
  /** extreme districts (short name without «район», raw gap), unless it is the zone itself */
  hottest?: { name: string; gap: number };
  coolest?: { name: string; gap: number };
}

export function rankAmong(gap: number | null, others: (number | null)[], cityGen: string): Rank | null {
  const vals = others.filter((v): v is number => v != null);
  if (gap == null || vals.length < 3) return null;
  return { hotterThan: vals.filter((v) => v < gap).length, of: vals.length, cityGen };
}

/** Backend `context.rank` → Rank: of the `of − 1` other districts, `of − rank` are cooler (rank 1 = hottest). */
export function rankFromContext(c: ContextRank | null | undefined, selfId?: string | null): Rank | null {
  if (!c || typeof c.rank !== 'number' || typeof c.of !== 'number') return null;
  const others = c.of - 1;
  const ext = (d: DistrictRef | undefined) => {
    const n0 = d && d.id !== selfId ? (d.short_name || d.name || '').replace(/\s*\([^()]*\)\s*$/, '').replace(/\s+район$/u, '') : '';
    // English UI: the API's short_name_en / name_en, else the KMU 2010 transliteration («Деснянський» → «Desnianskyi»)
    const x = d as (DistrictRef & { short_name_en?: string; name_en?: string }) | undefined;
    const n = n0 && isEn() ? nameEn(n0, (x?.short_name_en || x?.name_en || '').replace(/\s*\([^()]*\)\s*$/, '').replace(/\s+District$/, '')) : n0;
    return n && typeof d!.gap === 'number' ? { name: n, gap: d!.gap } : undefined;
  };
  const hot = ext(c.district_extremes?.hottest), cool = ext(c.district_extremes?.coolest);
  if (others < 3 || c.rank < 1 || c.rank > c.of) return null;
  return {
    hotterThan: c.of - c.rank, of: others, cityGen: CITY_GEN[c.city] ?? 'міста', city: c.city,
    // English UI: the backend's *_en (lang=en); a Ukrainian fallback is shown with lang="uk"
    ...(pickRank(c, 'compared_to') ? { comparedTo: pickRank(c, 'compared_to')! } : {}),
    ...(pickRank(c, 'note') ? { note: pickRank(c, 'note')! } : {}),
    ...(typeof c.like_for_like === 'boolean' ? { likeForLike: c.like_for_like } : {}),
    ...(Array.isArray(c.district_gap_range) && c.district_gap_range.length === 2 ? { range: c.district_gap_range } : {}),
    ...(hot ? { hottest: hot } : {}),
    ...(cool ? { coolest: cool } : {}),
  };
}

const pickRank = (c: ContextRank, f: 'compared_to' | 'note'): string | null =>
  (isEn() ? (c as unknown as Record<string, string | null | undefined>)[`${f}_en`] : null) || (f === 'note' ? c.note_uk : c.compared_to_uk) || null;

export function rankText(r: Rank): string {
  if (isEn()) return SENTENCES.en.rank(r);
  if (r.hotterThan === r.of) return `гарячіше, ніж у середньому в будь-якому з ${r.of} районів ${r.cityGen}`;
  if (r.hotterThan === 0) return `прохолодніше, ніж у середньому в кожному з ${r.of} районів ${r.cityGen}`;
  return `гарячіше, ніж у середньому в ${r.hotterThan} з ${r.of} районів ${r.cityGen}`;
}

/**
 * The card answers with the size of the gap when the trend is not significant: «помітної зміни не видно», not
 * «нічого не змінилось». Only for built-up zones that are clearly hotter than the forest (≥ 0,5 °C);
 * significant trends and forest/all-land zones keep the backend sentence.
 */
export function isMagnitudeCase(r: Report): boolean {
  const m = r.gap_summary.mean;
  return r.trend.verdict === 'not_significant' && m != null && m >= 0.5 && r.zone.analysed !== 'all_land';
}

export function magnitudeHeadline(r: Report): { gap: string; forest: string } {
  if (isEn()) return { gap: `${fmt(r.gap_summary.mean, 1)} °C`, forest: SENTENCES.en.forest(r.reference.city, r.reference.kind === 'derived') };
  return { gap: `${fmt(r.gap_summary.mean, 1)} °C`, forest: r.reference.forest_uk ?? 'ліс навколо міста' };
}

/** QA-UX R4-8: no «стабільно» next to a non-zero slope; the summers are counted with gaps, not as a run. */
export const stableHotText = (nSummers: number) => (isEn() ? SENTENCES.en.stableHot(nSummers) : `помітної зміни не видно (дані ${summersGen(nSummers)})`);

/** «Що гріє / що охолоджує»: short facts from report fields only. */
/** `lead` is shown in bold before `text`; `title` is a hover/long-press explanation. */
export interface Factor { tone: 'heat' | 'cool' | 'neutral'; text: string; lead?: string; title?: string;
  /** item 22: glossary tip for this line (TOOLTIPS.md, card) */
  hint?: GlossaryKey }

export function factors(r: Report): Factor[] {
  const out: Factor[] = [];
  const counted = r.series.filter(isCounted);
  const builtText = builtFactorText(r); // item 14: share of the zone, labelled as Esri urban fabric
  if (builtText && r.zone.analysed !== 'all_land') out.push({ tone: 'heat', text: builtText, hint: 'built' });
  // parks before the rest: with three lines above the fold, one heat and one cool fact come first
  if (r.green_scope === 'urban_parks' && r.green_gap != null && r.green_gap > 0 && r.zone.analysed !== 'all_land')
    out.push({ tone: 'cool', text: isEn() ? SENTENCES.en.parksCooler(r.green_gap) : `Парки й сквери в місті на ${fmt(r.green_gap, 1)} °C прохолодніші за цю забудову`, hint: 'parksGap' });
  const nb = newBuiltFactor(r);
  if (nb) out.push(nb);
  const nd = r.ndvi_trend;
  const withNdvi = counted.filter((x) => x.ndvi != null);
  if (nd?.verdict === 'significant' && nd.slope_per_decade != null && withNdvi.length >= 2) {
    const a = withNdvi[0]!, b = withNdvi[withNdvi.length - 1]!;
    if (isEn()) out.push({ tone: nd.slope_per_decade > 0 ? 'cool' : 'heat', text: SENTENCES.en.greenTrend(nd.slope_per_decade > 0, a.ndvi, b.ndvi), hint: 'ndviTrend' });
    else out.push({ tone: nd.slope_per_decade > 0 ? 'cool' : 'heat', text: `Зелені ${nd.slope_per_decade > 0 ? 'суттєво більшає' : 'суттєво меншає'} (NDVI ${fmt(a.ndvi, 2)} → ${fmt(b.ndvi, 2)})`, hint: 'ndviTrend' });
  }
  return out;
}

/** «вже X °C гарячіша за ліс» / «прохолодніша» for a gap (raw, rounded half-up here). */
const vsForest = (g: number) => `на ${fmt(Math.abs(g), 1)} °C ${g >= 0 ? 'гарячіша' : 'прохолодніша'} за ліс`;

/**
 * New built-up land (QA-UX R4-3, METHOD.md): pixels not built in the first two valid years and built in the last two;
 * before/after = their gap in those years. Shown only when |after − before| ≥ 1 °C. Neutral grey dot: the change is
 * not a causal claim (a building site / bare soil in summer is as hot as roofs).
 */
export function newBuiltFactor(r: Report): Factor | null {
  const nb = r.new_built_gap;
  if (!nb || nb.before.gap == null || nb.after.gap == null || Math.abs(nb.after.gap - nb.before.gap) < 1) return null;
  if (isEn()) {
    const g = (nb.series ?? []).map((x) => x.gap).filter((v): v is number => v != null);
    const e = SENTENCES.en.newBuilt({ area_km2: nb.area_km2, before: { years: nb.before.years, gap: nb.before.gap }, after: { years: nb.after.years, gap: nb.after.gap },
      spread: g.length >= 3 ? [Math.min(...g), Math.max(...g)] : null });
    return { tone: 'neutral', ...e, hint: 'newBuiltBeforeAfter' };
  }
  const b = nb.before, a = nb.after;
  const since = b.years.length ? ` з’явилась після ${b.years[b.years.length - 1]} р.` : '';
  const area = nb.area_km2 != null ? `${fmt(nb.area_km2, 1)} км²${since ? ',' : ''}` : '';
  const after = Math.sign(a.gap!) === Math.sign(b.gap!) || a.gap === 0 ? `на ${fmt(Math.abs(a.gap!), 1)} °C` : vsForest(a.gap!);
  const yrs = (ys: number[]) => (ys.length ? ` (${ys.join(', ')})` : '');
  const text = ` (${area}${since}): до будівництва${yrs(b.years)} ця земля була ${vsForest(b.gap!)}, після${yrs(a.years)} — ${after}.`;
  const gaps = (nb.series ?? []).map((x) => x.gap).filter((g): g is number => g != null);
  let title = 'Відкритий ґрунт, будмайданчик чи суха трава влітку вдень гріються не менше за дахи й асфальт, тому після забудови розрив не обов’язково росте.';
  if (gaps.length >= 3) {
    const lo = Math.min(...gaps), hi = Math.max(...gaps);
    if (Math.abs(a.gap! - b.gap!) < hi - lo) title += ` Різниця «до/після» тут менша за коливання між літніми сезонами (${fmt(lo, 1)}–${fmt(hi, 1)} °C).`;
  }
  return { tone: 'neutral', lead: 'Нова забудова', text: text.replace(' (: ', ' (').replace(' ()', ''), title, hint: 'newBuiltBeforeAfter' };
}

/** Forward look from /api/climate (air, not surface): the moderate scenario's nearest period. */
/** Item 19 F: the outlook as one plain main line + a muted second line (scenario, model range, air ≠ surface). */
export interface Outlook { main: string; sub: string }

export function climateLine(c: Climate | null | 'error'): Outlook | null {
  if (!c || c === 'error') return null;
  const p = c.projections.filter((x) => x.scenario === 'ssp245').sort((a, b) => a.period.localeCompare(b.period))[0];
  if (!p) return null;
  return climateLineFromContext({ scenario: p.scenario, period: p.period, delta: p.delta, baseline_period: c.baseline,
    delta_range: p.lo != null && p.hi != null ? [p.lo, p.hi] : undefined }, c.models?.length);
}

/** Same from backend `context.climate` (preferred: already the nearest ssp245 period for the zone). */
export function climateLineFromContext(c: ContextClimate | null | undefined, nModels?: number): Outlook | null {
  if (!c || typeof c.delta !== 'number' || !c.period) return null;
  if (isEn()) return SENTENCES.en.climate(c, nModels);
  const until = c.period.split(/[-–]/).pop();
  const bp = c.baseline_period;
  const bpText = Array.isArray(bp) ? (bp.length === 2 ? `${bp[0]}–${bp[1]}` : '') : (bp ?? '').replace('-', '–');
  const verb = c.delta >= 0 ? 'зросте' : 'знизиться';
  const main = `Прогноз: до ${until} денний максимум приземної температури повітря (на висоті 2 м) ${verb} приблизно на ${fmt(c.delta >= 0 ? c.delta : -c.delta, 1, c.delta >= 0)}\u00a0°C${bpText ? ` (порівняно з ${bpText})` : ''}`;
  const n = nModels && nModels > 1 ? nModels : null;
  const scen = c.scenario === 'ssp245' ? 'Помірний сценарій (SSP2‑4.5)' : `Сценарій ${c.scenario.toUpperCase()}`;
  const spread = c.delta_range ? `від ${fmt(c.delta_range[0], 1, true)} до ${fmt(c.delta_range[1], 1, true)}\u00a0°C` : null;
  // CMIP6 v2 (science, item 33): median of the models + the 10–90 % model range
  const models = n ? `, медіана ${n} моделей${spread ? `; діапазон 10–90\u00a0%: ${spread}` : ''}` : spread ? `; діапазон моделей 10–90\u00a0%: ${spread}` : '';
  const sub = `${scen}${models}. Повітря, не поверхня.`;
  return { main, sub };
}

/**
 * Not like-for-like (a 1 km dense circle vs whole districts): instead of a rank, the districts' range and the
 * reason from the backend note («…: щільний квартал зазвичай гарячіший за середнє по цілому району.»).
 */
export function districtRangeLine(r: Rank): string | null {
  if (r.likeForLike !== false || !r.range) return null;
  if (isEn()) return SENTENCES.en.districtRange(r);
  // extremes: raw district gaps rounded here (half-up); a zone that is itself an extreme is skipped
  const lo = r.coolest ? `${fmt(r.coolest.gap, 1, true)} (${r.coolest.name})` : fmt(r.range[0], 1, true);
  const hi = r.hottest ? `${fmt(r.hottest.gap, 1, true)} °C (${r.hottest.name})` : `${fmt(r.range[1], 1, true)} °C`;
  // two lines at most above the fold: the reason (note_uk) goes into the note below the fold
  return `Для порівняння: забудова районів ${r.cityGen} — від ${lo} до ${hi}.`;
}
export const rankInHeadline = (r: Rank | null): boolean => !!r && r.likeForLike !== false;

/** The summers a hotspot was averaged over, as the real list (QA-UX R4-4: «2020–2024» would include excluded years). */
const yearList = (ys?: number[]) => (ys?.length ? ys.join(', ') : '');

/** Tooltip for hotspot i (0-based), on the map and the card chip. Only fields the API gives. */
export function hotspotTip(h: Hotspot, i: number): string {
  if (isEn()) return SENTENCES.en.hotspotTip(h, i);
  let t = `Місце ${i + 1}: на ${fmt(Math.abs(h.gap), 1)} °C ${h.gap >= 0 ? 'гарячіше' : 'прохолодніше'} за ліс`;
  if (h.delta_vs_zone != null && h.delta_vs_zone > 0) t += ` — на ${fmt(h.delta_vs_zone, 1)} °C гарячіше, ніж забудова ділянки в середньому`;
  t += '.';
  const ys = yearList(h.years);
  if (ys) t += ` ${h.years!.length > 1 ? 'Літні сезони' : 'Літо'} ${ys}.`;
  if (h.type_uk) t += ` Тут переважно ${h.type_uk}.`;
  return t;
}
/** Summers the hotspots are averaged over (the last 3 with data, whatever the map year): the union across hotspots,
 * «2023–2025» when consecutive, else «2019, 2023, 2025»; '' when the API gives none. */
export function hotspotYears(hot: Hotspot[]): string {
  const ys = [...new Set(hot.flatMap((h) => h.years ?? []))].sort((a, b) => a - b);
  if (!ys.length) return '';
  if (ys.length === 1) return `${ys[0]}`;
  return ys.every((y, i) => i === 0 || y === ys[i - 1]! + 1) ? `${ys[0]}–${ys[ys.length - 1]}` : ys.join(', ');
}
/** hotspot dots belong to the gap / temperature layers, not to greenery */
export const hotspotsOnLayer = (layer: string) => layer === 'gap' || layer === 'lst';

/** Short reason for a year the map shows empty (item 15 A): fits one line under the card number. */
const YEAR_GAP_UK: Record<string, string> = {
  low_coverage: 'хмари', too_few_pixels: 'хмари', too_few_scenes: 'замало знімків',
  no_reference: 'немає даних по лісу-еталону', no_lst_product: 'прогалина в даних USGS',
};

/**
 * Item 15 A: the card number is the mean over all summers, the map shows one summer. One compact line that ties the
 * two: «У 2022: +9,1 °C» or «У 2022: немає даних (хмари)». Null when there is no map year or it is not in the series.
 */
export function cardYearLine(r: Report, year: number | null | undefined): { text: string; empty: boolean } | null {
  if (year == null) return null;
  const row = r.series.find((s) => s.year === year);
  if (!row) return null;
  if (isEn()) {
    if (isCounted(row)) return { text: tr('en', 'cardYear.value', { year, value: `${fmt(row.gap!, 1, true)}\u00a0°C` }), empty: false };
    const k = row.excluded ? (`excludedShort.${row.excluded}` as MsgKey) : null;
    return { text: k && k in DICTS.en ? tr('en', 'cardYear.noDataWhy', { year, why: tr('en', k as 'excludedShort.low_coverage') }) : tr('en', 'cardYear.noData', { year }), empty: true };
  }
  if (isCounted(row)) return { text: `У ${year}: ${fmt(row.gap!, 1, true)}\u00a0°C`, empty: false };
  const why = row.excluded ? YEAR_GAP_UK[row.excluded] : undefined;
  return { text: `У ${year}: немає даних${why ? ` (${why})` : ''}`, empty: true };
}

