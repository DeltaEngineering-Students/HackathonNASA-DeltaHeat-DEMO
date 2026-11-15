// Country markers (MAP-TASKS 3): below z9 the raster is hidden and each place from GET /api/overview is a pill with its
// mean gap («+8,0°», decimal comma, U+2212 minus), coloured by the current theme's gap legend stops. The number is the
// report's gap_summary.mean (same stored report as the card), so a marker always equals the card headline.
import type { FeatureCollection, Point } from 'geojson';
import type { ColorStop, Overlays, OverviewPlace } from '../api/types';
import { fmt } from './format';
import { getLocale } from '../i18n/locale';
import { tr } from '../i18n';
import { date } from '../i18n/format';

const isEn = () => getLocale() === 'en';

/** Colour of `v` on piecewise-linear stops (clamped at the ends). */
export function colorAt(stops: ColorStop[], v: number): string {
  if (!stops.length) return '#888888';
  if (v <= stops[0]![0]) return stops[0]![1];
  for (let i = 1; i < stops.length; i++) {
    const [v1, c1] = stops[i]!;
    if (v <= v1) {
      const [v0, c0] = stops[i - 1]!;
      const t = (v - v0) / (v1 - v0 || 1);
      const a = hex(c0), b = hex(c1);
      return `#${a.map((x, k) => Math.round(x + (b[k]! - x) * t).toString(16).padStart(2, '0')).join('')}`;
    }
  }
  return stops[stops.length - 1]![1];
}
const hex = (c: string) => { const h = c.replace('#', ''); return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)); };

/** Dark or light text on a marker of colour `bg` (WCAG relative luminance). */
export function inkOn(bg: string): '#10131c' | '#ffffff' {
  const [r, g, b] = hex(bg).map((x) => { const s = x / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; });
  const L = 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
  return L > 0.3 ? '#10131c' : '#ffffff';
}

export const markerLabel = (p: OverviewPlace): string => (p.gap_mean != null && p.status !== 'no_data' && p.status !== 'error' ? `${fmt(p.gap_mean, 1, true)}°` : isEn() ? tr('en', 'map.markerNa') : 'н/д');

export type MarkerKind = 'ok' | 'nodata' | 'war';
export const markerKind = (p: OverviewPlace): MarkerKind => (p.gap_mean == null || p.status === 'no_data' || p.status === 'error' ? 'nodata' : p.war_region ? 'war' : 'ok');

/** «2026-09-15» → «15.09.2026» */
const dateUk = (iso: string) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso); return m ? `${m[3]}.${m[2]}.${m[1]}` : iso; };

/** The number on a marker is a gap to the forest, not a temperature (MAP-TASKS 21 H) — one sentence for the strip chip. */
export const MARKER_LEGEND = 'Число = наскільки забудова міста гарячіша за ліс навколо (поверхня, літо вдень), не температура';
export const markerLegend = () => (isEn() ? tr('en', 'map.markerLegend') : MARKER_LEGEND);

/**
 * Hover text (MAP-TASKS 21 H): «Ужгород: забудова +10,1 °C гарячіша за ліс навколо · сама поверхня ≈ 36 °C», why there is no
 * number, and the caveat — the dated official occupation note when the place is occupied, else the oblast war caveat.
 */
export function markerTip(p: OverviewPlace, overlays: Overlays | null): string {
  const parts: string[] = [];
  if (isEn()) {
    // server texts: *_en when the backend sends them (phase 3), else a neutral English line — never the Ukrainian one
    const name = (p as { name_en?: string }).name_en ?? p.name;
    if (markerKind(p) === 'nodata') parts.push(tr('en', 'map.markerNoData', { name, reason: (p as { reason_en?: string }).reason_en ?? tr('en', 'excluded.noData') }));
    else {
      const g = p.gap_mean!;
      const lst = p.lst_mean != null ? tr('en', 'map.markerLst', { lst: fmt(p.lst_mean, 0) }) : '';
      parts.push(g >= 0 ? tr('en', 'map.markerHotter', { name, gap: fmt(g, 1, true), lst }) : tr('en', 'map.markerCooler', { name, gap: fmt(-g, 1), lst }));
    }
    if (p.occupied) parts.push(tr('en', 'map.markerOccupied', { date: date(p.occupied.snapshot_date, 'en', 'long'), // TERMS-EN §10: «15 September 2026»
 source: (p.occupied as { source_en?: string }).source_en ?? 'Ministry of Development of Ukraine, order No. 376' }));
    else if (p.war_region) {
      const w = overlays?.war_regions.features.find((f) => f.properties.name === p.war_region!.name);
      parts.push((w?.properties as { text_en?: string } | undefined)?.text_en ?? tr('en', 'map.markerWar', { region: (p.war_region as { name_en?: string }).name_en ?? p.war_region.name, since: p.war_region.since }));
    }
    if (markerKind(p) !== 'nodata') parts.push(tr('en', 'map.markerOpen'));
    return parts.join(' ');
  }
  if (markerKind(p) === 'nodata') parts.push(`${p.name}: ${p.reason_uk ?? 'немає даних'}.`);
  else {
    const g = p.gap_mean!;
    const gap = g >= 0 ? `забудова ${fmt(g, 1, true)} °C гарячіша за ліс навколо` : `забудова на ${fmt(-g, 1)} °C прохолодніша за ліс навколо`;
    const lst = p.lst_mean != null ? ` · сама поверхня ≈ ${fmt(p.lst_mean, 0)} °C` : '';
    parts.push(`${p.name}: ${gap}${lst} (середнє за всі літні сезони).`);
  }
  if (p.occupied) {
    parts.push(`Тимчасово окупована територія (станом на ${dateUk(p.occupied.snapshot_date)}; джерело: ${p.occupied.source}). Зміни можуть бути наслідком окупації й руйнувань.`);
  } else if (p.war_region) {
    const w = overlays?.war_regions.features.find((f) => f.properties.name === p.war_region!.name);
    parts.push(w?.properties.text_uk ?? `Регіон війни (${p.war_region.name}, з ${p.war_region.since} р.): зміни можуть бути наслідком руйнувань.`);
  }
  if (markerKind(p) !== 'nodata') parts.push('Натисніть, щоб відкрити.');
  return parts.join(' ');
}

export function overviewFeatures(places: OverviewPlace[], stops: ColorStop[], overlays: Overlays | null, dark: boolean): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: places.map((p) => {
      const kind = markerKind(p);
      const color = kind === 'nodata' ? (dark ? '#3a4258' : '#d9d9de') : colorAt(stops, p.gap_mean!);
      return {
        type: 'Feature',
        properties: { id: p.place_id, name: p.name, city: p.city ?? '', kind, district: p.kind === 'district', rank: p.rank, label: markerLabel(p), color, ink: kind === 'nodata' ? (dark ? '#c9d0e0' : '#4a5160') : inkOn(color), tip: markerTip(p, overlays) },
        geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
      };
    }),
  };
}
