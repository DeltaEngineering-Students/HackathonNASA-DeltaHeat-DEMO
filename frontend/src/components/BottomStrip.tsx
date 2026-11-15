import type { LayerMeta, SeriesPoint } from '../api/types';
import { gradientCss, legendTicks } from '../lib/colors';
import { isCounted } from '../lib/verdict';
import { fmt } from '../lib/format';
import { barsMetric, layerName as cleanName, mapLayers, ndviTicks, overviewNote, yearNoData } from '../lib/layers';
import { markerLegend } from '../lib/overview';
import { DICTS, getLocale, tr, useLocale, type Locale } from '../i18n';
import { ukIfCyrillic } from './Rich';


/** The selected year's value in the zone for the shown layer (QA-UX S1, UX-17). */
export function yearValue(layer: string | undefined, row: SeriesPoint | undefined): string | null {
  if (!row) return null;
  if (getLocale() === 'en') {
    if (layer === 'ndvi' && row.ndvi != null) return tr('en', 'strip.ndviOnArea', { value: fmt(row.ndvi, 2) });
    if (!isCounted(row)) return null;
    if (layer === 'gap' && row.gap != null) return tr('en', 'strip.onArea', { value: `${fmt(row.gap, 1, true)}\u00a0°C` });
    if (layer === 'lst' && row.zone_lst != null) return tr('en', 'strip.onArea', { value: `${fmt(row.zone_lst, 1)}\u00a0°C` });
    return null;
  }
  if (layer === 'ndvi' && row.ndvi != null) return `NDVI ${fmt(row.ndvi, 2)} на ділянці`;
  if (!isCounted(row)) return null;
  if (layer === 'gap' && row.gap != null) return `${fmt(row.gap, 1, true)}\u00a0°C на ділянці`;
  if (layer === 'lst' && row.zone_lst != null) return `${fmt(row.zone_lst, 1)}\u00a0°C на ділянці`;
  if (layer === 'ndvi' && row.ndvi != null) return `NDVI ${fmt(row.ndvi, 2)} на ділянці`;
  return null;
}
import { YearBars } from './charts';
import { Hint, Term } from './Hint';
import type { GlossaryKey } from '../lib/glossary';
import { muteApplies, useMapUi } from '../lib/mapUi';
import { esriVersion, satMosaicYear } from '../lib/satellite';

const LAYER_TERMS = new Set(['gap', 'lst', 'ndvi', 'dndvi']);

/** «Зелень (NDVI)» → «зелень (NDVI)»: only the first letter, abbreviations stay upper case */
const lowerFirst = (t: string, l: Locale = 'uk') => t.charAt(0).toLocaleLowerCase(l) + t.slice(1);

/** Legend end words come from meta in Ukrainian only; in English they map back through the uk dictionary (legend.*). */
const LEGEND_KEYS = ['legend.cooler', 'legend.hotter', 'legend.little', 'legend.lots', 'legend.less', 'legend.more'] as const;
const legendEnd = (l: Locale, uk: string | undefined): string => {
  if (!uk || l === 'uk') return uk ?? '';
  const k = LEGEND_KEYS.find((x) => DICTS.uk[x] === uk);
  return k ? tr(l, k) : uk;
};

export function BottomStrip({ year, years, series, layer, layers, theme, onYear, onLayer, showBars, hotLegend = 0, hotYears = '', overview = false, dndviBase = 2013, fillNote = null }: {
  year: number; years: number[]; series: SeriesPoint[] | null; layer: LayerMeta | undefined; layers: LayerMeta[];
  theme: 'light' | 'dark'; onYear: (y: number) => void; onLayer: (id: string) => void; showBars: boolean;
  /** «1–3 — найгарячіші місця на ділянці» next to the legend while the map shows hotspot dots */
  hotLegend?: number;
  /** summers the hotspots are taken from («2023–2025»), shown after the hotspot line */
  hotYears?: string;
  /** the map is below z9 and shows country markers instead of the raster (MAP-TASKS 3) */
  overview?: boolean;
  dndviBase?: number;
  /** item 9: «заповнено з сусідніх років» while the fill layer is drawn */
  fillNote?: string | null;
}) {
  const ui = useMapUi();
  const l = useLocale();
  const en = l === 'en';
  const muteOn = muteApplies(ui) && ui.mute > 0;
  const stops = layer ? (theme === 'dark' && layer.stops_dark ? layer.stops_dark : layer.stops) : [];
  const layerName = en
    ? (layer?.id === 'gap' ? tr(l, 'strip.layerGapUnit') : layer?.id === 'lst' ? tr(l, 'strip.layerLstUnit') : layer?.id === 'dndvi' ? tr(l, 'strip.layerDndviUnit', { name: lowerFirst(cleanName(layer), l), year: dndviBase }) : layer ? lowerFirst(cleanName(layer), l) : '')
    : layer?.id === 'gap' ? 'розрив з лісом, °C' : layer?.id === 'lst' ? 'температура поверхні, °C' : layer?.id === 'dndvi' ? `${lowerFirst(cleanName(layer))} від ${dndviBase} (ΔNDVI)` : lowerFirst(layer?.name_uk ?? '');
  const loText = legendEnd(l, layer?.legend_lo_uk), hiText = legendEnd(l, layer?.legend_hi_uk);
  const quick = mapLayers(layers);
  const heatLayer = layer?.id === 'gap' || layer?.id === 'lst';
  // ticks from the light stops in both themes: the dark palette has other stop values (QA-UX R3-3)
  const ticks = layer ? legendTicks(layer.stops.length ? layer.stops : stops, layer.units, layer.kind === 'diverging' || layer.id === 'gap' || layer.id === 'dndvi') : [];
  const row = series?.find((s) => s.year === year);
  // MAP-TASKS 28: per layer — NDVI years are not the heat years
  const nd = yearNoData(layer?.id, row ?? undefined);
  const noData = nd?.label ?? null;
  const noDataFull = nd?.full ?? null;
  const value = yearValue(layer?.id, row ?? undefined);
  return (
    <section className={`strip${showBars ? "" : " compact"}`} data-testid="strip" aria-label={tr(l, 'strip.aria')}>
      <div className="strip-title">
        {/* board item 22: glossary tips (TOOLTIPS.md §3, bottom strip) — test ids stay on the visible text */}
        <b><Term k="mapYear" side="above"><span data-testid="map-year">{tr(l, 'strip.mapYear', { year })}</span></Term></b>
        <span className="s" lang={ukIfCyrillic(l, layerName)}>{LAYER_TERMS.has(layer?.id ?? '') ? <Term k={layer!.id as GlossaryKey} side="above">{layerName}</Term> : layerName}</span>
        {value && <span className="s strip-value" data-testid="year-value">{value}</span>}
        {noData && <span className="s nodata-note"><Term k="noDataYear" side="above"><span data-testid="year-nodata" data-full={noDataFull ?? undefined} lang={ukIfCyrillic(l, noData)}>{noData}</span></Term></span>}
      </div>
      {showBars && <YearBars series={series} years={years} year={year} onChange={onYear} metric={barsMetric(layer?.id, dndviBase)} />}
      {showBars && <div className="vrule" />}
      {/* legend + its ⓘ stay on one row (the ⓘ wrapped alone onto its own line at 1280 and beside Details) */}
      <div className="legend-row">
      <div className="legend" data-testid="legend" role="img" aria-label={tr(l, 'strip.legendAria', { lo: ticks[0]?.label ?? '', loText, hi: ticks[ticks.length - 1]?.label ?? '', hiText })}>
        <div className="legend-bar" style={{ background: gradientCss(stops) }} />
        <div className="legend-ticks" aria-hidden="true">
          {ticks.map((t, i) => (
            <span key={t.label} style={{ left: `${t.pos}%` }} className={i === 0 ? 'first' : i === ticks.length - 1 ? 'last' : undefined}>{t.label}</span>
          ))}
        </div>
        <div className="legend-ends" aria-hidden="true"><span lang={ukIfCyrillic(l, loText)}>{loText}</span><span lang={ukIfCyrillic(l, hiText)}>{hiText}</span></div>
        {layer?.id === 'ndvi' && <div className="xs ndvi-ticks" data-testid="ndvi-ticks">{ndviTicks()}</div>}
      </div>
      <Hint k="legend" side="above" className="legend-hint" />
      </div>
      {overview && <div className="ov-legend s" data-testid="marker-legend"><span className="ov-key" aria-hidden="true">{en ? '+8.0°' : '+8,0°'}</span><Term k="countryMarkers" side="above">{markerLegend()}</Term></div>}
      {/* R7-4: the secondary keys share ONE wrapping row (was one row each — 3 rows at 1280×720); details are in their tips */}
      <div className="strip-notes">
      {!overview && muteOn && <div className="mute-legend s" data-testid="mute-note"><span className="mute-key" aria-hidden="true" /><span><Term k="muteNonBuilt" side="above">{tr(l, 'strip.muted')}</Term>{tr(l, 'strip.mutedWhat')}</span></div>}
      {!overview && ui.basemap === 'sat' && <div className="xs sat-note" data-testid="sat-note">
        <Term k="basemap" side="above">{tr(l, 'strip.basemap')}</Term>{ui.satEox ? tr(l, 'strip.basemapWhatEox', { year: satMosaicYear(year) }) : tr(l, 'strip.basemapWhat', { version: esriVersion(year).date.slice(0, 7) })}</div>}
      {!overview && ui.showReference && ui.reference === 'ok' && <div className="ref-legend s" data-testid="reference-legend"><span className="ref-key" aria-hidden="true" />{tr(l, 'strip.refDashes')}</div>}
      {!overview && ui.noScenes && <div className="noscn-legend s" data-testid="noscenes-legend"><span className="noscn-key" aria-hidden="true" />{(() => { const what = lowerFirst(ui.noScenes.replace(/^\d{4}:\s*/, ''), l); return <span lang={ukIfCyrillic(l, what)}>{tr(l, 'strip.crossHatch', { what, year })}</span>; })()}</div>}
      {fillNote && <div className="fill-legend s" data-testid="fill-legend"><span className="fill-key" aria-hidden="true" /><Term k="filledFromNeighbours" side="above">{fillNote}</Term></div>}
      {hotLegend > 0 && (
        <div className="hot-legend s" data-testid="hot-legend"><span className="hot-dot-key" aria-hidden="true">1</span><Term k="hotspots" side="above">{(hotLegend > 1 ? tr(l, 'strip.hotMany', { n: hotLegend }) : tr(l, 'strip.hotOne')) + (hotYears ? ` (${hotYears})` : '')}</Term></div>
      )}
      </div>
      <div className="strip-foot">
        {showBars && quick.length > 1 && (
          <div className="seg seg-sm" role="group" aria-label={tr(l, 'strip.quickLayers')} data-testid="quick-layers">
            {quick.map((q) => (
              <button key={q.id} type="button" aria-pressed={layer?.id === q.id} aria-label={q.name === q.short ? undefined : `${q.short}: ${q.name}`} data-layer={q.id} onClick={() => onLayer(q.id)}>{q.short}</button>
            ))}
          </div>
        )}
        {showBars && quick.length > 1 && <Hint k="layerSwitch" side="above" />}
        <p className="strip-note" data-testid="map-note">
          {overview ? (() => { const t = overviewNote(layer?.id, layer?.name_uk); const m = tr(l, 'strip.markers'); return t.startsWith(m) ? <><Term k="countryMarkers" side="above">{m}</Term>{t.slice(m.length)}</> : t; })() : (
            <>{tr(l, 'strip.noteMap')} — <Term k="mapVsCard" side="above">{tr(l, 'strip.noteSummerMean')}</Term>, <Term k="seams" side="above">{tr(l, 'strip.noteSeams')}</Term>{heatLayer ? tr(l, 'strip.noteSeamsUpTo') : ''}. <Term k="hatchNoData" side="above">{tr(l, 'strip.noteTransparent')}</Term>{tr(l, 'strip.noteNoData')}</>
          )}
        </p>
      </div>
    </section>
  );
}
