import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import type { Climate, Hotspot, Report } from '../api/types';
import { hotspotTip, hotspotYears, climateLine, climateLineFromContext, districtRangeLine, factors, rankInHeadline, magnitudeHeadline, rankFromContext, rankText, stableHotText, isMagnitudeCase, cardYearLine, type Rank } from '../lib/story';
import type { ReportState, Selection } from '../state/store';
import { fmt, fmtArea, fmtDeg, summers } from '../lib/format';
import { leadSentence } from '../api/adapt';
import { excludedLabel, highlightVerdict, isCounted, trendSub, validSeries, verdictView } from '../lib/verdict';
import { LineChart } from './charts';
import { Arrow } from './icons';
import { Hint, Term } from './Hint';
import '../styles/card-fold.css';
import { getLocale, tr, useLocale } from '../i18n';
import { pick } from '../i18n/server';
import { SENTENCES } from '../i18n/sentences';
import { CITY_EN } from '../i18n/story.en';
import { Rich, ukIfCyrillic } from './Rich';
import { nameEn } from '../i18n/placeName';
import { cardTips, pLabel } from '../lib/cardTips';

/** «Як ми це рахуємо →»: open Details and bring its block (§1 gap, §2 trend) into view once it has mounted. */
export function openDetailsAt(onDetails: () => void, sec: number) {
  onDetails();
  let tries = 0;
  const go = () => {
    const h = document.getElementById(`sec-${sec}`);
    if (h) { h.scrollIntoView({ block: 'start', behavior: 'smooth' }); return; }
    if (++tries < 20) window.setTimeout(go, 100);
  };
  window.setTimeout(go, 50);
}

/** Роман P1-3: the auto-picked reference is said in Details (derived_reference caveat), not in the card's first line. */
const AUTO_REF = /\s*\((ліс-еталон підібрано автоматично|reference forest picked automatically)\)/;

const cityIn = (c: string | undefined) => (c && getLocale() === 'en' ? CITY_EN[c] ?? c : c);

/** «Позняки (≈1 км)» → { name: «Позняки», extent: «коло ≈1 км» }; geocoder names get a capital letter (QA-UX C3, C8). */
export function splitName(raw: string): { name: string; extent?: string } {
  const m = raw.match(/^(.*?)\s*\((≈\s*[\d,.]+\s*(?:км|km))(?:\s+(?:навколо|around))?\)\s*$/);
  const name = (m ? m[1]! : raw).trim();
  const cap = name ? name.charAt(0).toLocaleUpperCase('uk') + name.slice(1) : name;
  return { name: cap, extent: m ? tr(getLocale(), 'card.circleExtent', { size: m[2]!.replace(/\s+/g, '\u00a0') }) : undefined };
}

/**
 * Eyebrow over the title. «Ваш район» only for built-up (residential) zones; forests/parks and other
 * all-land zones are «Обрана територія»; addresses are «Навколо адреси» (QA-UX C4–C7).
 */
/** MAP-TASKS 24: part of the zone outside Ukraine is cut off → «3,3 км², з них в Україні 1,3 км²» (null when nothing is cut). */
export function clippedArea(r: Report | undefined): string | null {
  const c = r?.zone.clipped_km2;
  if (!r || !c || c <= 0) return null;
  return tr(getLocale(), 'card.clippedArea', { total: fmtArea(r.zone.area_km2 + c), inside: fmtArea(r.zone.area_km2) });
}

export function eyebrowFor(sel: Selection | null, report?: Report, placeKind?: string): string {
  if (!sel) return '';
  const clipped = clippedArea(report);
  const l = getLocale();
  if (sel.kind === 'drawn') return tr(l, 'card.eyebrowYourArea', { area: clipped ?? fmtArea(sel.areaKm2) });
  if (clipped) return `${eyebrowFor(sel, undefined, placeKind)} · ${clipped}`;
  if ((sel.cityId && sel.id === sel.cityId) || placeKind === 'city') return tr(l, 'card.eyebrowCity');
  // one rule (QA-UX R3-7): «Приклад · Київ», «Район · Київ», «Коло ≈1 км навколо адреси · Київ», «Місто / населений пункт»
  const city = cityIn(report?.reference.city || undefined);
  const extent = splitName(sel.name || report?.zone.name || '').extent;
  if (placeKind === 'demo_zone') return [tr(l, 'card.eyebrowExample'), city].filter(Boolean).join(' · ');
  if (placeKind === 'district') return [tr(l, 'card.eyebrowDistrict'), city].filter(Boolean).join(' · ');
  if (placeKind === 'locality') return [tr(l, 'card.eyebrowLocality'), city].filter(Boolean).join(' · ');
  if (placeKind === 'geocoder_circle' || (sel.id.startsWith('osm:') && extent))
    return [tr(l, 'card.eyebrowAroundAddress', { extent: extent ? extent.charAt(0).toLocaleUpperCase(l) + extent.slice(1) : tr(l, 'card.eyebrowCircle') }), city].filter(Boolean).join(' · ');
  if (placeKind === 'geocoder') return [tr(l, 'card.eyebrowGeocoder'), city].filter(Boolean).join(' · ');
  if (sel.id.startsWith('osm:')) return [tr(l, 'card.eyebrowPicked'), city].filter(Boolean).join(' · ');
  const what = tr(l, report?.zone.analysed === 'all_land' ? 'card.eyebrowPickedArea' : 'card.eyebrowDistrict');
  return [what, city ?? cityIn(sel.subtitle?.split(' · ')[0])].filter(Boolean).join(' · ');
}

/** «Котеджне містечко «Деснянське» (Троєщина)» → «Деснянське (Троєщина)»: the card and chart use the short form (QA-UX R3-1). */
export function shortName(name: string): string {
  const q = name.match(/«([^«»]+)»/);
  if (!q || name.length <= 24) return name;
  const paren = name.match(/\(([^()]+)\)\s*$/);
  return paren ? `${q[1]} (${paren[1]})` : q[1]!;
}

/** A raw id («kharkiv-saltivka», «osm:R123») is never a title (QA R3-9). */
const isSlug = (x: string) => /^[a-z0-9]+([-:][a-z0-9]+)+$/i.test(x) && !/[а-яіїєґ]/i.test(x);

/** Zone title; the card uses the short form, the map pill and Details pass `full` (QA-UX R3-1). */
export const zoneTitle = (sel: Selection | null, report?: Report, full = false) => {
  const sh = full ? (x: string) => x : shortName;
  // English UI: the report's zone.name_en (API lang=en) for the same name, else KMU 2010 transliteration
  const zoneEn = (report?.zone as { name_en?: string | null } | undefined)?.name_en;
  const loc = (uk: string) => (uk && getLocale() === 'en' ? nameEn(uk, uk === report?.zone.name ? zoneEn : undefined) : uk);
  if (sel?.kind === 'preset') {
    const raw = [sel.name, report?.zone.name].find((x) => x && !isSlug(x) && x !== sel.id) ?? '';
    const localized = raw && getLocale() === 'en' ? nameEn(raw, sel.name_en ?? (raw === report?.zone.name ? zoneEn : undefined)) : raw;
    return sh(splitName(localized).name); // '' = not known yet
  }
  const yours = tr(getLocale(), 'app.yourArea');
  return report?.zone.name && report.zone.name !== 'Ваша ділянка' && report.zone.name !== 'Your area' ? sh(splitName(loc(report.zone.name)).name) : yours;
};

/** Card lead: the first sentence without the «(поки не значуще, p = 0,37)» aside — the label shows it. */
export const cardLead = (text: string, title: string, mean?: number | null) => {
  const t = leadSentence(text, title).replace(/\s*\([^()]*\bp\s*=\s*[\d,.]+\)/, '').replace(AUTO_REF, '');
  if (mean == null) return t;
  if (getLocale() === 'en')
    return t.replace(/\(a difference of\s+[\d.]+\s*°C\)/, () => {
      const x = fmt(Math.abs(mean), 1);
      return x === '0.0' ? tr('en', 'card.leadDiffLess') : `(${x}\u00a0°C ${mean < 0 ? 'cooler' : 'warmer'})`;
    });
  // «(різниця 0,2 °C)» loses the sign: say the direction, like the card and Details (QA R3-8, QA-UX R3-6)
  return t.replace(/\(різниця\s+[\d,]+\s*°C\)/, () => {
    const x = fmt(Math.abs(mean), 1);
    if (x === '0,0') return tr('uk', 'card.leadDiffLess').replace(' °C', '\u00a0°C');
    return `(на ${x}\u00a0°C ${mean < 0 ? 'прохолодніша' : 'тепліша'})`;
  });
};

/** The lead's source text: the backend sentence in the UI language; in English without `verdict_text_en` (older
 * backend / not yet localised) the client-side English port (i18n/story.en.ts), never the Ukrainian sentence. */
export function leadText(r: Report, l = getLocale()): string {
  if (l !== 'en') return r.verdict_text_uk;
  const en = (r as unknown as { verdict_text_en?: string | null }).verdict_text_en;
  return en || SENTENCES.en.verdict(r) || r.verdict_text_uk;
}
const AIR_RE = / (Повітря, не поверхня|Air, not surface)\.$/;

/** R7-3: with no gap there are no numbers to qualify — the empty card keeps only the caveats that explain the absence
 * or the place (an allow-list, so new method caveats such as ref_higher / ref_weak never leak in). Details lists all. */
const EMPTY_KEEP = new Set([
  'no_lst_product', 'no_lst', 'no_data', 'no_scenes', 'no_reference', 'few_reference_px', 'few_years', 'few_scene_dates',
  'years_excluded', 'low_coverage', 'occupied', 'war_zone', 'war_region', 'geocoder_circle', 'geocoder_busy', 'geocoder_unavailable',
  'zone_clipped', 'urban_area_clipped', 'small_zone',
]);
export const emptyCaveats = <C extends { code: string }>(cs: C[]): C[] => cs.filter((c) => EMPTY_KEEP.has(c.code));

/** Empty state (no gap result): the reason comes from the caveat codes, not a guess (QA R3-4). */
export function emptyReason(r: Report): { lead: string; hint: string | null } {
  const codes = new Set(r.caveats.map((c) => c.code));
  const l = getLocale();
  if (codes.has('no_lst_product'))
    return { lead: tr(l, 'card.emptyNoLst'), hint: null };
  if (codes.has('war_zone')) return { lead: tr(l, 'card.emptyWar'), hint: null };
  return { lead: tr(l, 'card.emptyGeneric'), hint: tr(l, 'card.emptyHint') };
}

/** «ще нижче» fade above the pinned footer while the card body has hidden content (QA-UX R3-1). */
function useMoreBelow(): [(el: HTMLDivElement | null) => void, boolean] {
  const [more, setMore] = useState(false);
  const el = useRef<HTMLDivElement | null>(null);
  const check = useCallback(() => {
    const e = el.current;
    setMore(!!e && e.scrollHeight - e.scrollTop - e.clientHeight > 8);
  }, []);
  const ref = useCallback((e: HTMLDivElement | null) => {
    if (el.current) el.current.removeEventListener('scroll', check);
    el.current = e;
    if (e) { e.addEventListener('scroll', check, { passive: true }); requestAnimationFrame(check); }
  }, [check]);
  useEffect(() => {
    window.addEventListener('resize', check);
    const ro = typeof ResizeObserver !== 'undefined' && el.current ? new ResizeObserver(check) : null;
    if (ro && el.current) { ro.observe(el.current); if (el.current.firstElementChild) ro.observe(el.current.firstElementChild); }
    return () => { window.removeEventListener('resize', check); ro?.disconnect(); };
  });
  return [ref, more];
}

/** Big number and its caption without double negatives (QA-UX C10). */
export function bigNumber(mean: number | null): { text: string; caption: string; tone: 'heat' | 'cool' | 'flat' } {
  const l = getLocale();
  if (mean == null) return { text: '—', caption: tr(l, 'card.bigNoData'), tone: 'flat' };
  if (Math.abs(mean) < 0.5) return { text: '≈\u00a00°', caption: tr(l, 'card.bigLikeForest'), tone: 'flat' };
  if (mean < 0) return { text: `${fmt(-mean, 1)}°`, caption: tr(l, 'card.bigCooler'), tone: 'cool' };
  return { text: fmtDeg(mean), caption: tr(l, 'card.bigHotter'), tone: 'heat' };
}

/** Viewport height, to shrink the card chart on short screens so «Деталі аналізу» stays visible (UX-07). */
function useViewportHeight() {
  const [h, setH] = useState(() => (typeof window === 'undefined' ? 900 : window.innerHeight));
  useEffect(() => {
    const on = () => setH(window.innerHeight);
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []);
  return h;
}

const NO_RETRY = new Set(['outside_coverage', 'insufficient_data', 'too_small', 'too_large', 'area_too_small', 'area_too_large', 'bbox_too_large', 'invalid_geometry', 'missing_geometry', 'too_many_vertices', 'bad_geometry', 'invalid_years']);

/** Compact hotspot row inside «Що гріє»: numbered like the map dots, click flies the map there. */
function HotRow({ hot, years, onHotspot }: { hot: Hotspot[]; years: string; onHotspot?: (c: [number, number]) => void }) {
  const l = useLocale();
  return (
    <div className="hot-row" data-testid="hotspots">
      <span className="hot-row-h" title={years ? tr(l, 'card.hotspotsTitle', { years }) : undefined}><Term k="hotspots">{tr(l, 'card.hotspots')}</Term>{years ? ` (${years})` : ''}:</span>
      {hot.map((h, i) => (
        <button key={i} type="button" className="hot-chip" onClick={() => onHotspot?.(h.center)} title={hotspotTip(h, i)}
          aria-label={tr(l, 'card.showOnMap', { tip: hotspotTip(h, i) })}><b>{i + 1}</b> {fmt(h.gap, 1, true)}&nbsp;°C</button>
      ))}
    </div>
  );
}

export function AnswerCard({ selection, state, onDetails, onRetry, onSearch, rank: rankProp = null, climate = null, onHotspot, placeKind, year = null, exportMenu }: {
  selection: Selection | null; state: ReportState; onDetails: () => void; onRetry: () => void; onSearch: () => void;
  rank?: Rank | null; climate?: Climate | null | 'error'; onHotspot?: (center: [number, number]) => void;
  /** the map's summer (item 15 A) */
  year?: number | null;
  /** item 29: «Експорт ▾» (built by App: report id + share link) */
  exportMenu?: ReactNode;
  /** meta preset kind (demo_zone, district, city, locality) or place kind (geocoder, geocoder_circle) */
  placeKind?: string;
}) {
  const l = useLocale();
  const vh = useViewportHeight();
  const [bodyRef, more] = useMoreBelow();
  const title = zoneTitle(selection, 'report' in state ? state.report : undefined);
  const titleCls = `clamp${title.length > 12 ? ' long' : ''}`;

  // 1440×900 cut the chart under the pinned footer (QA-UX R3-1): full height only on tall screens
  const chartH = vh <= 760 ? 88 : vh <= 820 ? 124 : vh <= 960 ? 100 : 176;
  // compact type up to 960 px tall so the factors fit above the fold at 1440×900; the chart caption goes only ≤ 820
  const compact = vh <= 820 ? ' short tiny' : vh <= 960 ? ' short' : '';

  if (state.status === 'loading' || state.status === 'idle') {
    return (
      <section className={`card answer${compact}`} aria-busy="true" aria-label={tr(l, 'card.loading')} data-testid="answer-loading">
        <div className="answer-body">
          <div className="eyebrow">{eyebrowFor(selection, undefined, placeKind)}</div>
          <h1 style={{ marginTop: 6 }} className={titleCls}>{selection && title ? title : <span className="skel" style={{ display: 'block', height: 48, width: 220 }} />}</h1>
          <div className="skel" style={{ height: 22, marginTop: 18 }} />
          <div className="skel" style={{ height: 22, marginTop: 8, width: '80%' }} />
          <div className="nums">
            <div className="skel" style={{ height: 80, width: 140 }} />
            <div style={{ flex: 1 }}><div className="skel" style={{ height: 34 }} /><div className="skel" style={{ height: 34, marginTop: 12 }} /></div>
          </div>
          <div className="skel" style={{ height: chartH, marginTop: 22 }} />
          <p className="sr-only" aria-live="polite">{tr(l, 'card.computing')}</p>
        </div>
      </section>
    );
  }

  if (state.status === 'error') {
    const noRetry = NO_RETRY.has(state.code ?? '');
    return (
      <section className={`card answer${compact}`} data-testid="answer-error" aria-labelledby="ans-title">
        <div className="answer-body">
          <div className="eyebrow">{eyebrowFor(selection, undefined, placeKind)}</div>
          <h1 id="ans-title" style={{ marginTop: 6 }} className={titleCls} lang={ukIfCyrillic(l, title)}>{title || tr(l, 'card.placeNotFound')}</h1>
          <p className="lead" style={{ marginTop: 14 }} role="alert">{state.message}</p>
        </div>
        <div className="card-foot">
          {/* retry cannot help for areas outside coverage / too small (QA-19, QA-UX Q7) */}
          {noRetry
            ? <button type="button" className="btn" onClick={onSearch}>{tr(l, 'card.pickPlace')}</button>
            : <button type="button" className="btn" onClick={onRetry}>{tr(l, 'app.retry')}</button>}
        </div>
      </section>
    );
  }

  const r = state.report;
  if (state.status === 'empty') {
    const why = emptyReason(r);
    return (
      <section className={`card answer${compact}`} data-testid="answer-empty" aria-labelledby="ans-title">
        <div className="answer-body">
          <div className="eyebrow">{eyebrowFor(selection, r, placeKind)}</div>
          <h1 id="ans-title" style={{ marginTop: 6 }} className={titleCls} lang={ukIfCyrillic(l, title)}>{title}</h1>
          <p className="lead" style={{ marginTop: 14 }} data-testid="empty-reason">{why.lead}</p>
          {why.hint && <p className="s" style={{ marginTop: 10 }}>{why.hint}</p>}
          {emptyCaveats(r.caveats).length > 0 && (
            <ul className="caveats" style={{ marginTop: 12 }} aria-label={tr(l, 'card.caveats')} data-testid="empty-caveats">
              {emptyCaveats(r.caveats).map((c) => { const t = pick(c as unknown as Record<string, unknown>, 'text', l); return <li key={c.code} className="s" lang={t.lang !== l ? t.lang : undefined}>• {t.text}</li>; })}
            </ul>
          )}
        </div>
        <div className="card-foot">
          <button type="button" className="btn" onClick={onDetails} data-testid="open-details">{tr(l, 'card.details')} <Arrow /></button>
          <button type="button" className="btn-link s" onClick={onSearch}>{tr(l, 'card.pickOther')}</button>
        </div>
      </section>
    );
  }

  const n = validSeries(r).length;
  const magnitude = isMagnitudeCase(r) ? magnitudeHeadline(r) : null;
  const facts = factors(r);
  const hot = r.hotspots ?? [];
  const hotYears = hotspotYears(hot);
  const cap = hot.length ? 2 : 3;
  // item 22: one tip per line (the computed «Нова забудова» explanation stays its title)
  const factorLi = (f: (typeof facts)[number]) => <li key={f.lead ?? f.text} className={`f-${f.tone}`} title={f.title}>{f.lead && <b>{f.lead}</b>}{f.text}{f.hint && <Hint k={f.hint} />}</li>;
  const nModels = climate && climate !== 'error' ? climate.models?.length : undefined;
  const outlook = climateLineFromContext(r.context?.climate, nModels) ?? climateLine(climate);
  // no district rank for a whole city (backend 12f09ee does the same)
  const wholeCity = placeKind === 'city' || (selection?.kind === 'preset' && !!selection.cityId && selection.id === selection.cityId);
  const rank = wholeCity ? null : rankFromContext(r.context?.rank, selection?.kind === 'preset' ? selection.id : null) ?? rankProp;
  const rangeLine = rank ? districtRangeLine(rank) : null;
  const big = bigNumber(r.gap_summary.mean);
  const yearLine = cardYearLine(r, year); // item 15 A: the map's summer next to the all-summers mean
  const v = verdictView(r.trend);
  const tips = cardTips(r, title, l, n, onDetails);
  const howGap = { ...tips.gap, link: tips.gap.link && { ...tips.gap.link, onClick: () => openDetailsAt(onDetails, 1) } };
  const howTrend = { ...tips.trend, link: tips.trend.link && { ...tips.trend.link, onClick: () => openDetailsAt(onDetails, 2) } };
  const pText = r.trend.verdict === 'insufficient_data' ? null : pLabel(r.trend.p, l);
  const excluded = r.series.filter((x) => !isCounted(x));
  const partial = r.series.filter((x) => isCounted(x) && x.valid_share < 0.7).map((x) => x.year);
  const y0 = r.series[0]?.year, y1 = r.series[r.series.length - 1]?.year;
  return (
    <section className={`card answer${compact}${more ? ' more' : ''}`} data-testid="answer" aria-labelledby="ans-title">
      <div className="answer-body" ref={bodyRef}>
        <div className="eyebrow">{eyebrowFor(selection, r, placeKind)}{clippedArea(r) && <Hint k="zoneClipped" />}</div>
        <h1 id="ans-title" style={{ marginTop: 6 }} className={titleCls} title={title} lang={ukIfCyrillic(l, title)}>{title}</h1>
        {magnitude ? (
          // not significant: lead with the size of the gap and its context, not with «nothing changed»
          <p className="lead" style={{ marginTop: 12 }} data-testid="verdict">
            <Rich text={tr(l, 'card.magnitude', { gap: magnitude.gap, forest: magnitude.forest })} termClass={{ referenceForest: 'r' }} />
            {rankInHeadline(rank) ? <> — <span data-testid="rank">{rankText(rank!)}</span></> : null}.
          </p>
        ) : (
          <p className="lead" style={{ marginTop: 12 }} data-testid="verdict">
            {highlightVerdict(cardLead(leadText(r, l), title, r.gap_summary.mean)).map((x, i) => (x.tone === 'ref' ? <Term key={i} k="referenceForest" className="r">{x.text}</Term> : x.tone ? <span key={i} className="h">{x.text}</span> : x.text))}
            {/* item 20 D: a green / mixed area (all land analysed) still warmer than the forest — why */}
            {r.zone.analysed === 'all_land' && <Hint k="greenStillWarm" />}
            {rankInHeadline(rank) ? <span className="s rank-line" data-testid="rank">{rankText(rank!)}</span> : null}
          </p>
        )}
        <div className="nums">
          <div>
            <div className="big-row" style={{ display: 'flex', alignItems: 'center', gap: 6 }}><div className={`big${big.tone === 'heat' ? '' : ' cool'}`} data-testid="gap-mean">{big.text}</div><Hint k="gap" tip={howGap} /></div>
            <div className="s" style={{ marginTop: 8 }} data-testid="surface-note">
              {big.tone === 'heat' ? big.caption : tr(l, 'card.surfaceTempSuffix', { caption: big.caption })},<br /><Term k="gapMean">{tr(l, 'card.meanOver', { seasons: summers(n) })}</Term>
            </div>
          </div>
          <div className="nums-side">
            <div>
              <div className="mid">{r.trend.slope_per_decade == null ? '—' : `${fmt(r.trend.slope_per_decade, 1, true)}°`}<Hint k="trend" tip={howTrend} /></div>
              <div className="s">{magnitude ? tr(l, 'card.trendCaption', { text: stableHotText(n) }) : trendSub(r.trend)}</div>
            </div>
            <div>
              <div className={`mid${v.tone === 'muted' ? ' muted' : ''}`} data-testid="verdict-label"><Term k={r.trend.verdict === 'significant' ? 'significant' : r.trend.verdict === 'not_significant' ? 'notSignificant' : 'insufficientData'} tip={howTrend}>{v.label}</Term></div>
              {/* Роман P0-2: the exact p on the first screen («p = 0,002»), its own tip is the trend's */}
              <div className="s">{pText && <><Term k="pValue" tip={howTrend}><b className="card-p" data-testid="card-p">{pText}</b></Term> · </>}{v.sub}</div>
            </div>
          </div>
        </div>
        {/* QA R7: the year line shares the chart caption's row (no extra row above the chart; under both number
            columns, so «немає даних (замало знімків)» never squeezes the trend column — 15 A nit) */}
        <div className="chart-head">
          <div className="chart-title xs"><Term k="lst">{tr(l, 'card.chartTitle')}</Term><Hint k="chartLines" /></div>
          {yearLine && <div className={`s card-year${yearLine.empty ? ' empty' : ''}`} data-testid="card-year">{yearLine.text}</div>}
        </div>
        <LineChart series={r.series} zoneName={title} h={chartH} />
        {(excluded.length > 0 || partial.length > 0) && (
          // a chart footnote, not a box: the factors must stay above the fold (coordinator review)
          <p className="xs chart-foot" data-testid="excluded-note">
            {/* QA-UX R4-2: count + years; each year's reason on hover, the full list in Details §4 */}
            {excluded.length > 0 && <><b><Term k="noDataYear">{tr(l, 'card.noDataSeasons', { seasons: summers(excluded.length) })}</Term></b> — {excluded.map((x, i) => (
              <span key={x.year}>{i ? ', ' : ''}<span className="nd-year" title={excludedLabel(x.excluded).replace(/^(немає даних|no data): /, '').replace(/\.$/, '')}>{x.year}</span></span>
            ))}.</>}
            {partial.length > 0 && <> <Term k="partialYear">{tr(l, 'card.partial')}</Term>: {partial.join(', ')}.</>}
          </p>
        )}
        {/* after the chart (QA R5-1): the chart must stay above the fold at 1280×720 */}
        {rangeLine && <p className="s range-line" data-testid="district-range">{rangeLine}</p>}
        {facts.length > 0 && (
          <div className="factors" data-testid="factors">
            <div className="xs factors-h">{tr(l, 'card.factorsTitle')}</div>
            <ul>{facts.slice(0, cap).map(factorLi)}</ul>
            {/* with hotspots the row takes the third line: two facts + the row fit above the fold at 1440×900 */}
            {hot.length > 0 && <HotRow hot={hot} years={hotYears} onHotspot={onHotspot} />}
            {/* the rest (e.g. «Нова забудова») below the fold, still in the card */}
            {facts.length > cap && <ul className="factors-more">{facts.slice(cap).map(factorLi)}</ul>}
          </div>
        )}
        {facts.length === 0 && hot.length > 0 && <div className="factors"><HotRow hot={hot} years={hotYears} onHotspot={onHotspot} /></div>}
        {/* below the fold: hotspots, rank basis, outlook */}
        {rank && (rankInHeadline(rank) ? rank.comparedTo || rank.note : rank.note) && (
          <p className="s rank-note note" data-testid="rank-note" lang={ukIfCyrillic(l, `${rank.comparedTo ?? ''}${rank.note ?? ''}`)}>
            {rank.comparedTo && rankInHeadline(rank) ? `${rank.comparedTo.charAt(0).toLocaleUpperCase(l)}${rank.comparedTo.slice(1)}.` : ''}
            {rank.note ? ` ${rank.note}` : ''}
          </p>
        )}
        {outlook && (
          // item 19 F: one plain line; scenario, model range and «повітря, не поверхня» muted underneath
          <p className="note outlook" data-testid="climate-line"><b><Term k="forecast2050">{tr(l, 'card.forecast')}</Term>:</b>{outlook.main.replace(/^(Прогноз|Outlook):/, '')}.
            <span className="outlook-sub xs" data-testid="climate-sub">{outlook.sub.replace(AIR_RE, '')}{AIR_RE.test(outlook.sub) && <> <Term k="climateIsAir">{tr(l, 'card.airNotSurface')}</Term>.</>}<Hint k="ssp245" /></span></p>
        )}
        {/* QA R7: the credit scrolls with the story (it cost the pinned footer a whole row) */}
        <p className="xs credit card-credit" data-testid="card-credit"><Term k="dataCredit">{tr(l, 'card.credit', { from: y0 ?? '', to: y1 ?? '' }).replace('Landsat 8', 'Landsat\u00a08')}</Term></p>
      </div>
      <div className="card-foot">
        <button type="button" className="btn" onClick={onDetails} data-testid="open-details">{tr(l, 'card.details')} <Arrow /></button>
        {exportMenu}
      </div>
    </section>
  );
}
