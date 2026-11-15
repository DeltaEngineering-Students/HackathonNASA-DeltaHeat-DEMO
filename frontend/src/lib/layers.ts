// ONE list of map layers for the strip quick switch and Details §7 (board item 6): same ids, same order, same names,
// so the two places cannot diverge again. Full names come from meta (`name_uk`), short labels only for the strip.
import type { LayerMeta, SeriesPoint } from '../api/types';
import { excludedLabel, excludedText, isCounted } from './verdict';
import { getLocale } from '../i18n/locale';
import { tr } from '../i18n';

const isEn = () => getLocale() === 'en';

export const LAYER_ORDER = ['gap', 'lst', 'ndvi', 'dndvi'] as const;
const SHORT: Record<string, string> = { gap: 'Розрив', lst: 'Температура', ndvi: 'Зелень', dndvi: 'Зміна зелені' };

/** Short layer name in the UI language («Розрив», «Зелень» / «Gap», «Greenness»); unknown ids pass through. */
export const layerShort = (id: string) => (SHORT[id] ? (isEn() ? tr('en', `layerShort.${id as 'gap'}`) : SHORT[id]!) : id);

export interface MapLayerChoice { id: string; name: string; short: string }

/** Only the 4 user-facing layers; internal ones (gap_fill, nonbuilt, `internal: true`) never become buttons (item 17 C). */
export const isMapLayer = (l: LayerMeta) => (LAYER_ORDER as readonly string[]).includes(l.id) && !(l as { internal?: boolean }).internal;

/** Layer names carry no year (user, pre-pitch): «Зміна зелені з 2013» from an older meta → «Зміна зелені»; «від 2013» stays in the caption and legend. */
export const layerName = (l: Pick<LayerMeta, 'name_uk'> & { id?: string }) =>
  isEn() && l.id && (LAYER_ORDER as readonly string[]).includes(l.id) ? tr('en', `layer.${l.id as 'gap'}`) : l.name_uk.replace(/\s+з\s+\d{4}$/, '');

/** Meta layers in the fixed order, user-facing ones only. */
export function mapLayers(meta: LayerMeta[]): MapLayerChoice[] {
  const rank = (id: string) => (LAYER_ORDER as readonly string[]).indexOf(id);
  return meta.filter(isMapLayer).sort((a, b) => rank(a.id) - rank(b.id)).map((l) => ({ id: l.id, name: layerName(l), short: isEn() && SHORT[l.id] ? tr('en', `layerShort.${l.id as 'gap'}`) : SHORT[l.id] ?? l.name_uk }));
}

/** What the strip's year bars show on each layer (item 6 c): the layer's own series where the report has one. */
export interface BarsMetric { kind: 'gap' | 'lst' | 'ndvi'; caption: string; value: (s: SeriesPoint) => number | null; signed: boolean }
export function barsMetric(layer: string | undefined, baseYear = 2013): BarsMetric {
  if (isEn()) {
    if (layer === 'lst') return { kind: 'lst', caption: tr('en', 'layers.captionLst'), value: (s) => s.zone_lst, signed: false };
    if (layer === 'ndvi') return { kind: 'ndvi', caption: tr('en', 'layers.captionNdvi'), value: (s) => s.ndvi, signed: false };
    if (layer === 'dndvi') return { kind: 'ndvi', caption: tr('en', 'layers.captionDndvi', { year: baseYear }), value: (s) => s.ndvi, signed: false };
    return { kind: 'gap', caption: tr('en', 'layers.captionGap'), value: (s) => s.gap, signed: true };
  }
  if (layer === 'lst') return { kind: 'lst', caption: 'температура поверхні ділянки за роками', value: (s) => s.zone_lst, signed: false };
  if (layer === 'ndvi') return { kind: 'ndvi', caption: 'зелень ділянки (NDVI) за роками', value: (s) => s.ndvi, signed: false };
  // ΔNDVI: the bars stay NDVI itself — the map's change is the difference from the first bar
  if (layer === 'dndvi') return { kind: 'ndvi', caption: `зелень ділянки (NDVI) за роками · шар — зміна від ${baseYear}`, value: (s) => s.ndvi, signed: false };
  return { kind: 'gap', caption: 'розрив з лісом за роками', value: (s) => s.gap, signed: true };
}

/** Note under the strip while the map shows country markers (below z9, item 6 e / MAP-TASKS 3). */
export function overviewNote(layer: string | undefined, name: string | undefined): string {
  if (isEn()) {
    if (!layer || layer === 'gap') return tr('en', 'layers.markersGap');
    const known = (LAYER_ORDER as readonly string[]).includes(layer);
    const nm = known ? tr('en', `layer.${layer as 'gap'}`) : (name ?? layer);
    return tr('en', 'layers.markersOther', { what: (known ? tr('en', `layerShort.${layer as 'gap'}`) : nm).toLowerCase(), name: nm });
  }
  if (!layer || layer === 'gap') return 'Маркери — середній розрив з лісом за всі літні сезони. Наблизьте, щоб побачити мапу розриву.';
  return `Маркери — розрив з лісом, не ${(SHORT[layer] ?? name ?? layer).toLowerCase()}. Наблизьте, щоб побачити шар «${name ?? layer}».`;
}

/** Green layers (NDVI, ΔNDVI) have their own availability: NDVI uses April–October scenes, LST only clear summer ones. */
export const isGreenLayer = (layer: string | undefined) => layer === 'ndvi' || layer === 'dndvi';
export const NDVI_NODATA = 'немає даних про зелень за цей рік';
export const ndviNoData = () => (isEn() ? tr('en', 'layers.ndviNoData') : NDVI_NODATA);

/**
 * MAP-TASKS 28: «no data» for the strip and the year bars, per layer. A summer left out of the heat analysis
 * (too few clear summer scenes) can still have NDVI — then the green layers show it and say nothing about «no data».
 * Returns null when the layer has a value for that year.
 */
export function yearNoData(layer: string | undefined, row: SeriesPoint | undefined): { label: string; full: string } | null {
  if (!row) return null;
  if (isGreenLayer(layer)) return row.ndvi == null ? { label: ndviNoData(), full: ndviNoData() } : null;
  return isCounted(row) ? null : { label: excludedLabel(row.excluded), full: excludedText(row) };
}

/** NDVI reading aids under the «Зелень» legend (MAP-TASKS 28): what typical values look like on the ground. */
export const NDVI_TICKS_UK = '0,2 — асфальт, дахи · 0,5 — двори з деревами · 0,8 — ліс';
export const ndviTicks = () => (isEn() ? tr('en', 'legend.ndviTicks') : NDVI_TICKS_UK);
