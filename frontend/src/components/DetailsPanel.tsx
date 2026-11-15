import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { mapLayers } from '../lib/layers';
import type { Climate, LayerMeta, Report, Trend } from '../api/types';
import { fmt, fmtArea, fmtC, fmtP, fmtPct, summers } from '../lib/format';
import { ciSentence, excludedText, highlightVerdict, isCounted, validSeries, verdictWord } from '../lib/verdict';

import { getLocale, tr, useLocale, useT, type Locale } from '../i18n';
import { pick } from '../i18n/server';
import { SENTENCES } from '../i18n/sentences';
import { Rich, ukIfCyrillic } from './Rich';

const BASIS = ['always_built', 'built_each_year', 'all_land'] as const;
const basisText = (b: string | undefined, l: Locale = getLocale()) =>
  tr(l, b && (BASIS as readonly string[]).includes(b) ? `details.basis.${b as (typeof BASIS)[number]}` : 'details.basis.default');
import { CompareBars, GapBars, TrendInterval, type CompareRow } from './charts';
import { Back } from './icons';
import { clippedArea } from './AnswerCard';
import { builtRows } from '../lib/builtShare';
import { Hint, Term, TipShownContext } from './Hint';

/** Glossary texts Details already shows (§6 statistics line, «p простими словами»): never a «Див. також» link here. */
/** Роман P2-1: data sources as their owners ask to be credited (names, so English in both languages). */
const DATA_CREDITS = 'NASA/USGS Landsat 8 · ESA WorldCover · Esri Land Cover · JRC GHSL · © OpenStreetMap contributors · Esri World Imagery Wayback (Esri, Maxar, Earthstar Geographics) · Sentinel\u20112 cloudless by EOX (Copernicus data, fallback) · Ministry of Development of Ukraine, order No.\u00a0376 (occupied areas) · NASA NEX\u2011GDDP\u2011CMIP6 · Open\u2011Meteo / ERA5 (Copernicus)';
const SHOWN_IN_DETAILS: ReadonlySet<string> = new Set(['pValue', 'theilSen', 'mannKendall']);
import type { GlossaryKey } from '../lib/glossary';

/** item 22: §5 row label → glossary key (TOOLTIPS.md §3, Details) */
export function dtKey(label: string, basis?: string): GlossaryKey | null {
  const rules: [RegExp, GlossaryKey][] = [
    [/^Тренд \(оцінка/, 'theilSen'], [/^Довірчий інтервал/, 'ci'], [/^p \(/, 'pValue'], [/^Ряд даних/, 'summer'],
    [/^Знімків Landsat/, 'scenesCount'], [/частка ділянки без хмар/, 'validShare'], [/^Пропущені роки/, 'excludedYears'],
    [/^Що рахуємо/, basis === 'all_land' ? 'allLand' : 'basisAlwaysBuilt'], [/^Варіант «/, 'variantEachYear'],
    [/^Нова забудова: до/, 'newBuiltBeforeAfter'], [/^Зелень \(NDVI\)/, 'ndvi'], [/^Забудова \(міська|^Частка забудови/, 'builtShare'],
    [/^Запечатані/, 'sealed'], [/^Нова забудова$/, 'newBuilt'], [/^Тренд самої забудови/, 'zoneTrend'], [/^Тренд лісу/, 'refTrend'],
    [/^Built-up \(urban/, 'builtShare'], [/^Sealed/, 'sealed'],
    [/^Забудова − /, 'parksGap'], [/^Ліс-еталон$/, 'referenceForest'], [/^Площа ділянки/, 'areaAndBuilt'],
  ];
  return rules.find(([re]) => re.test(label))?.[1] ?? null;
}

/** item 22: caveat code → glossary key (TOOLTIPS.md §3, §6 caveat list) */
export const CAVEAT_KEY: Record<string, GlossaryKey> = {
  lst_not_air: 'surfaceVsAir', lst_surface: 'surfaceVsAir', basis_always_built: 'basisAlwaysBuilt', classes_extrapolated: 'classesExtrapolated',
  not_significant_physics: 'notSignificant', composite_method: 'composite', mixed_method: 'composite',
  derived_reference: 'derivedReference', urban_area_is_zone: 'derivedReference', ring_widened: 'ring', few_reference_px: 'ring',
  suburb_reference: 'suburb', low_coverage: 'validShare', low_valid_share: 'validShare', years_excluded: 'noDataYear', few_years: 'noDataYear',
  no_lst_product: 'noLst', war_zone: 'warRegion', occupied: 'occupied', zone_clipped: 'zoneClipped', geocoder_circle: 'geocoderCircle',
  small_zone: 'minArea', all_land_zone: 'allLand', landsat_seam: 'seams',
};

/** «2013–2025 — reason» instead of the same reason repeated for every year (Маріуполь); years with a
 * backend sentence (sci-v3.4 `excluded_detail.text_uk`, e.g. Позняки 2020) get their own. */
export function skippedYears(rows: { year: number; excluded?: string | null; excluded_detail?: { text_uk?: string } | null }[]): string {
  const by = new Map<string, number[]>();
  for (const x of rows) {
    const why = excludedText(x).replace('немає даних: ', '').replace(tr('en', 'excluded.noDataBecause', { reason: '' }), '');
    by.set(why, [...(by.get(why) ?? []), x.year]);
  }
  const span = (ys: number[]) => {
    const parts: string[] = [];
    let a = ys[0]!, b = a;
    for (const y of ys.slice(1)) { if (y === b + 1) b = y; else { parts.push(a === b ? `${a}` : `${a}–${b}`); a = b = y; } }
    parts.push(a === b ? `${a}` : `${a}–${b}`);
    return parts.join(', ');
  };
  return [...by].map(([why, ys]) => `${span(ys.sort((p, q) => p - q))} — ${why}`).join('; ');
}

/** Caveats written for the card point «у деталях»; inside Details point at the row instead (QA-UX R3-9). */
export const inDetails = (t: string, l: Locale = getLocale()) =>
  t.replace(/\s*—\s*у деталях\./, tr('uk', 'details.inNumbers')).replace(/\s*—\s*(?:see|in) (?:the )?details\./i, tr(l, 'details.inNumbers'));

const Sec = ({ n, title, hint, children }: { n: number; title: string; hint?: GlossaryKey; children: ReactNode }) => (
  <section className="sec" aria-labelledby={`sec-${n}`}>
    <div className="sec-h"><span className="n" aria-hidden="true">{n}</span><h2 id={`sec-${n}`}>{title}</h2>{hint && <Hint k={hint} />}</div>
    {children}
  </section>
);

/** One accordion point of §6: native details/summary (keyboard + screen-reader friendly), collapsed by default. */
const MPoint = ({ head, children }: { head: string; children: ReactNode }) => (
  <details className="mpoint">
    <summary>{head}</summary>
    <div className="mpoint-body">{children}</div>
  </details>
);

const firstLast = <T,>(xs: T[]) => [xs[0], xs[xs.length - 1]] as const;

/** §5 rows: [label, value, glossary key]; labels and units follow the UI language (item 32), values use the lib formatters. */
export function numbersToCheck(r: Report, l: Locale = getLocale()): [string, string, GlossaryKey?][] {
  const t = r.trend;
  const valid = validSeries(r);
  const ndvi = r.series.filter((s) => s.ndvi != null);
  const scenes = r.series.reduce((a, s) => a + s.scenes, 0);
  const sc = r.series.map((s) => s.scenes);
  // coverage only over the years actually counted (excluded years are listed separately, QA-17)
  const counted = r.series.filter(isCounted);
  const minValid = counted.length ? counted.reduce((m, s) => (s.valid_share < m.valid_share ? s : m), counted[0]!) : null;
  const excluded = r.series.filter((s) => !isCounted(s));
  const [n0, n1] = firstLast(ndvi);
  const rk = r.reference.ring_km;
  const ring = Array.isArray(rk) ? tr(l, 'details.ringKm', { a: rk[0]!, b: rk[1]! }) : tr(l, 'details.ringKmOne', { a: rk as number });
  const unit = tr(l, 'details.perDecadeUnit');
  const rows: [string, string, GlossaryKey?][] = [
    [tr(l, 'details.rowTrend'), t.slope_per_decade == null ? '—' : `${fmt(t.slope_per_decade, 1, true)} ${unit}`, 'theilSen'],
    [tr(l, 'details.rowCi'), t.ci95 ? `${fmt(t.ci95[0], 1, true)} … ${fmt(t.ci95[1], 1, true)} °C` : '—', 'ci'],
    [tr(l, 'details.rowP'), `${fmtP(t.p)} · ${verdictWord(t.verdict)}`, 'pValue'],
    [tr(l, 'details.rowSeries'), `${summers(valid.length)}, ${r.series[0]?.year}–${r.series[r.series.length - 1]?.year}`, 'summer'],
    [tr(l, 'details.rowScenes'), tr(l, 'details.rowScenesValue', { total: scenes, min: Math.min(...sc), max: Math.max(...sc) }), 'scenesCount'],
  ];
  if (minValid) rows.push([tr(l, 'details.rowMinValid'), `${fmtPct(minValid.valid_share)} (${minValid.year})`, 'validShare']);
  if (excluded.length) rows.push([tr(l, 'details.rowExcluded'), skippedYears(excluded), 'excludedYears']);
  rows.push([tr(l, 'details.rowBasis'), `${basisText(r.zone.basis, l)}${r.zone.analysed_area_km2 != null ? `, ${fmtArea(r.zone.analysed_area_km2)}` : ''}`, r.zone.basis === 'all_land' ? 'allLand' : 'basisAlwaysBuilt']);
  const sec = r.secondary;
  if (sec && sec.gap_summary.mean != null)
    rows.push([tr(l, 'details.rowVariant', { basis: basisText(sec.basis, l) }), `${fmtC(sec.gap_summary.mean, 1, true)}${sec.trend.slope_per_decade != null ? ` · ${fmt(sec.trend.slope_per_decade, 1, true)} ${unit} · ${verdictWord(sec.trend.verdict)}` : ''}`, 'variantEachYear']);
  const nb = r.new_built_gap;
  if (nb && nb.before.gap != null && nb.after.gap != null)
    rows.push([tr(l, 'details.rowNewBuiltBA'), `${fmtC(nb.before.gap, 1, true)} (${nb.before.years.join(', ')}) → ${fmtC(nb.after.gap, 1, true)} (${nb.after.years.join(', ')}), ${fmtArea(nb.area_km2)}`, 'newBuiltBeforeAfter']);
  if (n0 && n1) rows.push([tr(l, 'details.rowNdvi'), `${fmt(n0.ndvi, 2)} → ${fmt(n1.ndvi, 2)}${r.ndvi_trend?.p != null ? ` · p = ${fmtP(r.ndvi_trend.p)}` : ''}`, 'ndvi']);
  rows.push(...builtRows(r)); // item 14: share of the zone (+ of the land) and GHSL sealed surface (key from dtKey)
  if (r.land_change) rows.push([tr(l, 'details.rowNewBuilt'), tr(l, 'details.rowNewBuiltValue', { area: fmtArea(r.land_change.new_built), total: fmtArea(r.land_change.always_built + r.land_change.new_built) }), 'newBuilt']);
  const trendRow = (x: Trend) => (x.slope_per_decade == null ? `— · ${verdictWord(x.verdict)}` : tr(l, 'details.trendRow', { v: fmt(x.slope_per_decade, 1, true), word: verdictWord(x.verdict) }));
  // the gap trend = zone trend − reference trend; show both parts so a cooling forest is not read as a heating city (UX-04)
  if (r.zone_trend) rows.push([tr(l, 'details.rowZoneTrend'), trendRow(r.zone_trend), 'zoneTrend']);
  if (r.ref_trend) rows.push([tr(l, 'details.rowRefTrend'), trendRow(r.ref_trend), 'refTrend']);
  if (r.green_gap != null) rows.push([tr(l, r.green_scope === 'urban_parks' ? 'details.rowParks' : 'details.rowGreen'), fmtC(r.green_gap, 1, true), 'parksGap']);
  rows.push([tr(l, 'details.rowReference'), tr(l, 'details.rowReferenceValue', { ring, area: fmtArea(r.reference.area_km2) }), 'referenceForest']); // item 18 E
  rows.push([tr(l, 'details.rowArea'), `${tr(l, 'details.rowAreaValue', { area: clippedArea(r) ?? fmtArea(r.zone.area_km2), built: fmtArea(r.zone.built_area_km2) })}${r.zone.clipped_km2 ? tr(l, 'details.rowAreaClipped', { clipped: fmtArea(r.zone.clipped_km2) }) : ''}`, 'areaAndBuilt']); // MAP-TASKS 24
  return rows;
}

export function DetailsPanel(props: {
  report: Report; title: string; year: number | null; onYear: (y: number) => void; onBack: () => void;
  layers: LayerMeta[]; layer: string; onLayer: (id: string) => void; compare: CompareRow[];
  climate: Climate | null | 'error'; demo: boolean;
  exportMenu?: ReactNode;
}) {
  const { report: r, title, year, onYear, onBack, layers, layer, onLayer, compare, climate, demo, exportMenu } = props;
  const l = useLocale();
  const t = useT();
  // report texts: *_en from the API (?lang=en), else the English port of the verdict, else Ukrainian marked lang="uk"
  const vEn = pick(r as unknown as Record<string, unknown>, 'verdict_text', 'en');
  const verdict = l === 'en' ? (vEn.lang === 'en' ? vEn.text : SENTENCES.en.verdict(r, title) ?? r.verdict_text_uk) : r.verdict_text_uk;
  // English: the sentence builder («the forest around Kyiv»); the backend sends no forest_en, only the Ukrainian label
  const forest = (l === 'en' ? SENTENCES.en.forest(r.reference.city, r.reference.kind === 'derived') : pick(r.reference as unknown as Record<string, unknown>, 'forest', l).text) || t('details.refForestFallback');
  const head = useRef<HTMLHeadingElement>(null);
  useEffect(() => head.current?.focus(), []);
  const composite = r.series.filter((s) => isCounted(s) && s.method === 'composite').map((s) => s.year);
  const mean = r.gap_summary.mean;
  const leftMain = useRef<HTMLDivElement>(null);
  const rightMain = useRef<HTMLDivElement>(null);
  const tailRef = useRef<HTMLDivElement>(null);
  const place = useTailPlace(leftMain, rightMain, tailRef);
  const tail = (
    <div className={`details-tail${place === 'span' ? ' span' : ''}`} data-testid="details-tail" data-place={place} ref={tailRef}>
      <Sec n={6} title={t('details.s7')} hint="layerSwitch">
        <div className="seg" role="group" aria-label={t('details.s7')}>
          {mapLayers(layers).map((x) => (
            <button key={x.id} type="button" aria-pressed={x.id === layer} data-layer={x.id} onClick={() => onLayer(x.id)}>{x.name}</button>
          ))}
        </div>
        {/* item 29: one «Експорт ▾» menu (PDF / Excel / CSV / JSON / share) instead of the JSON link */}
        <div className="xs details-export" style={{ marginTop: 10 }}>{exportMenu}{!demo && <span>{t('details.reportId', { id: r.report_id })}</span>}</div>
      </Sec>
      {/* Роман P2-1: team and data credits */}
      <p className="xs credit details-credits" data-testid="credits">
        <b>{t('credits.madeBy', { team: '\u2060', org: '\u2061' }).split(/(\u2060|\u2061)/).map((x, i) => (x === '\u2060' ? <span key={i} lang="en">Coaches Team</span> : x === '\u2061' ? <span key={i} lang="en">KSE Delta Engineering</span> : x))}</b><br />
        {t('credits.dataLabel')}: <span lang="en">{DATA_CREDITS}</span></p>
    </div>
  );

  return (
    <TipShownContext.Provider value={SHOWN_IN_DETAILS}>
    <section className="card details" data-testid="details" aria-labelledby="details-title">
      <div className="details-head">
        <button type="button" className="btn-ghost" onClick={onBack} data-testid="close-details"><Back />{t('details.back')}</button>
        <h1 id="details-title" tabIndex={-1} ref={head}>{t('details.title', { title })}</h1>
      </div>
      <p className="s" style={{ marginTop: 10, maxWidth: 780 }} data-testid="details-verdict" lang={ukIfCyrillic(l, verdict)}>
        {highlightVerdict(verdict).map((x, i) => (x.tone ? <b key={i} className={x.tone === 'heat' ? 'h' : 'r'}>{x.text}</b> : x.text))}
      </p>
      {/* §6 «Map layer» + credits («tail»): under the clearly shorter column, or across both when the columns end
          level — never beside a tall empty block (teammates' report: §6 beside empty space, §7 far below) */}
      <div className="details-grid">
        <div>
          <div ref={leftMain}>
            <Sec n={1} title={t('details.s1')} hint="gap">
              <GapBars series={r.series} trend={r.trend} mean={mean} selectedYear={year} onSelectYear={onYear} zoneName={title} w={440} />
              <p className="xs" style={{ marginTop: 4 }}>{t('details.s1hint')}</p>
            </Sec>
            <Sec n={2} title={t('details.s2')} hint="trend">
              <TrendInterval trend={r.trend} w={440} />
              <p className="s" style={{ marginTop: 6 }}>{ciSentence(r.trend)}</p>
              <WorseBlock r={r} />
            </Sec>
            <Sec n={3} title={t('details.s3', { from: r.series[0]?.year ?? '', to: r.series[r.series.length - 1]?.year ?? '' })} hint="compareZones">
              <CompareBars rows={compare} />
            </Sec>
            {/* CMIP6 in the left column so it is not empty below §3 (QA-UX R3-8) */}
            <Sec n={4} title={t('details.s4')} hint="cmip6">
              <ClimateBlock climate={climate} />
            </Sec>
          </div>
          {place === 'left' && tail}
        </div>
        <div>
          <div ref={rightMain}>
            <Sec n={5} title={t('details.s5')} hint="numbersToCheck">
              <dl data-testid="numbers">
                {numbersToCheck(r, l).map(([k, v, g]) => (
                  <div className="kv" key={k}><dt className="s">{((key) => (key ? <Term k={key}>{k}</Term> : k))(g ?? dtKey(k, r.zone.basis))}</dt><dd>{v}</dd></div>
                ))}
              </dl>
            </Sec>
          </div>
          {place === 'right' && tail}
        </div>
        {place === 'span' && tail}
      </div>
      {/* §6 «How we compute»: full width under both columns — a tall right column left the left one empty when scrolled (Роман) */}
      <div className="details-method">
        <Sec n={7} title={t('details.s6')}>
          {/* Роман: §6 as an accordion — one-line headlines, each unfolds to its text; all folded by default */}
          <div className="method-acc" data-testid="method-more">
            <MPoint head={t('details.m1')}><p className="s"><Rich text={t('details.howSurface')} /></p></MPoint>
            <MPoint head={t('details.m2')}><p className="s"><Term k="referenceForest">{t('details.refForest')}</Term> — <span className="r" lang={ukIfCyrillic(l, forest)}>{forest}</span>{r.reference.kind === 'derived' ? '' : t('details.oneRefPerCity')}.</p></MPoint>
            <MPoint head={t('details.m3')}><p className="s"><Rich text={t('details.howMapVsCard')} /></p></MPoint>
            <MPoint head={t('details.m4')}><p className="s"><Rich text={t('details.howSeams', { composite: composite.length ? t('details.composite', { years: composite.join(', ') }) : '' })} /></p></MPoint>
            <MPoint head={t('details.m5')}>
              <p className="s"><Rich text={t('details.howStats')} /></p>
              <p className="s" data-testid="p-plain"><b style={{ color: 'var(--ink)' }}>{t('details.pPlainHead')}</b> {t('details.pPlain')}</p>
            </MPoint>
            <MPoint head={t('details.m6')}>
              <p className="s" data-testid="green-still-warm"><Hint k="greenStillWarm" />{t('details.greenStillWarm')}</p>
              <p className="s" data-testid="ndvi-vs-lst"><Hint k="ndviVsLst" />{t('details.ndviVsLst')}</p>
            </MPoint>
          </div>
          {r.caveats.length > 0 && (
            <ul className="caveats" style={{ marginTop: 10 }} aria-label={t('details.caveatsAria')}>
              {/* physics caveat about new high-rises / growing trees only for built-up zones (QA-UX D13) */}
              {r.caveats.filter((c) => !(c.code === 'not_significant_physics' && r.zone.analysed === 'all_land')).map((c) => <li key={c.code} className="s">{CAVEAT_KEY[c.code] ? <Hint k={CAVEAT_KEY[c.code]!} /> : '• '}{((x) => <span lang={x.lang !== l ? x.lang : undefined}>{inDetails(x.text, l)}</span>)(pick(c as unknown as Record<string, unknown>, 'text', l))}</li>)}
            </ul>
          )}
        </Sec>
      </div>
    </section>
    </TipShownContext.Provider>
  );
}

type TailPlace = 'left' | 'right' | 'span';

/** Where §6 + credits go. Only the fixed parts (§1–4, §5) are compared, so moving the tail never feeds back into the
 * decision: a difference of more than half the tail's column height → the shorter column, else a full-width row
 * (§6 under the left column, credits under the right). One column (narrow panel) → after §5. */
function useTailPlace(left: RefObject<HTMLDivElement | null>, right: RefObject<HTMLDivElement | null>, tail: RefObject<HTMLDivElement | null>): TailPlace {
  const [place, setPlace] = useState<TailPlace>('span');
  const tailH = useRef(320); // the tail's height inside a column; measured whenever it sits in one
  useLayoutEffect(() => {
    const a = left.current, b = right.current;
    if (!a || !b) return;
    const check = () => {
      const tl = tail.current;
      if (tl && !tl.classList.contains('span') && tl.offsetHeight > 0) tailH.current = tl.offsetHeight;
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      if (ra.height === 0 && rb.height === 0) return; // not laid out (tests)
      if (rb.top >= ra.bottom - 1) { setPlace('right'); return; } // stacked columns
      const d = ra.height - rb.height;
      setPlace(Math.abs(d) <= tailH.current / 2 ? 'span' : d < 0 ? 'left' : 'right');
    };
    check();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(check);
    ro.observe(a); ro.observe(b);
    return () => ro.disconnect();
  }, [left, right, tail]);
  return place;
}

function ClimateBlock({ climate }: { climate: Climate | null | 'error' }) {
  const t = useT();
  // U+2011 non-breaking hyphens so «SSP2-4.5» never splits (QA-UX D15) — in the dictionary
  const SSP: Record<string, string> = { ssp245: t('details.ssp245'), ssp585: t('details.ssp585') };
  if (climate === null) return <div className="skel" style={{ height: 90 }} aria-label={t('details.loadingClimate')} />;
  if (climate === 'error' || climate.projections.length === 0) return <p className="s">{t('details.noClimate')}</p>;
  const periods = [...new Set(climate.projections.map((p) => p.period))];
  const scen = [...new Set(climate.projections.map((p) => p.scenario))];
  return (
    <div className="climate" data-testid="climate">
      <span className="badge"><Term k="climateIsAir">{t('details.climateBadge')}</Term></span>
      <table>
        <thead><tr><th scope="col">{t('details.period')}</th>{scen.map((s) => <th scope="col" key={s}>{s === 'ssp245' || s === 'ssp585' ? <Term k={s}>{SSP[s]}</Term> : (SSP[s] ?? s)}</th>)}</tr></thead>
        <tbody>
          {periods.map((p) => (
            <tr key={p}>
              <td className="nw">{p}</td>
              {scen.map((s) => {
                const x = climate.projections.find((q) => q.period === p && q.scenario === s);
                return (
                  <td key={s}>
                    <span className="nw">{x ? `${fmt(x.delta, 1, true)}\u00a0°C` : '—'}</span>
                    {x?.lo != null && x.hi != null ? <span className="xs nw rng">{t('details.range', { lo: fmt(x.lo, 1, true), hi: fmt(x.hi, 1, true) })}</span> : null}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="xs" style={{ marginTop: 8 }}>
        {t('details.climateNote')}{climate.baseline ? t('details.climateNoteBaseline', { baseline: climate.baseline }) : ''}
        {climate.models ? t('details.climateNoteModels', { n: climate.models.length }) : ''}{t('details.climateNoteTail')}
      </p>
    </div>
  );
}

const trendShort = (t: Trend, l: Locale = getLocale()) =>
  t.slope_per_decade == null ? tr(l, 'details.noEstimate') : tr(l, 'details.trendShort', { v: fmt(t.slope_per_decade, 1, true), word: verdictWord(t.verdict) });

/** «Чи стає гірше?»: the zone's own surface trend vs the reference forest, and what drives the gap (sci-v3.3). */
export function driverSentence(d: Report['gap_driver'], l: Locale = getLocale()): string | null {
  if (d === 'zone') return tr(l, 'details.driverZone');
  if (d === 'reference') return tr(l, 'details.driverRef');
  return null;
}

function WorseBlock({ r }: { r: Report }) {
  const l = useLocale();
  if (!r.zone_trend && !r.ref_trend) return null;
  const why = driverSentence(r.gap_driver, l);
  return (
    <div className="worse" data-testid="worse">
      <div className="s" style={{ color: 'var(--ink)', fontWeight: 600, marginTop: 12 }}>{tr(l, 'details.driverQ')}<Hint k="gapDriver" /></div>
      <dl>
        {r.zone_trend && <div className="kv"><dt className="s"><Term k="zoneTrend">{tr(l, 'details.builtItself')}</Term></dt><dd>{trendShort(r.zone_trend, l)}</dd></div>}
        {r.ref_trend && <div className="kv"><dt className="s"><Term k="refTrend">{tr(l, 'details.refForest')}</Term></dt><dd>{trendShort(r.ref_trend, l)}</dd></div>}
      </dl>
      {why && <p className="s" style={{ marginTop: 6 }}>{why}</p>}
    </div>
  );
}
