import type { Polygon } from 'geojson';
import { decodeRing, encodeRing } from './geo';

export type Panel = 'card' | 'details';
export interface UrlState {
  zone: string | null; // preset id
  area: Polygon | null; // drawn polygon
  year: number | null;
  layer: string | null;
  panel: Panel;
}

export const DEFAULT_ZONE = 'kyiv-pozniaky';

export function parseUrl(search: string): UrlState {
  const q = new URLSearchParams(search);
  const yearRaw = Number(q.get('year'));
  const area = q.get('area') ? decodeRing(q.get('area')!) : null;
  return {
    zone: area ? null : q.get('zone') ?? DEFAULT_ZONE,
    area,
    year: Number.isInteger(yearRaw) && yearRaw > 1900 ? yearRaw : null,
    layer: q.get('layer'),
    panel: q.get('view') === 'details' ? 'details' : 'card',
  };
}

export function toSearch(s: UrlState): string {
  const q = new URLSearchParams();
  if (s.area) q.set('area', encodeRing(s.area));
  else if (s.zone) q.set('zone', s.zone);
  if (s.year) q.set('year', String(s.year));
  if (s.layer && s.layer !== 'gap') q.set('layer', s.layer);
  if (s.panel === 'details') q.set('view', 'details');
  const str = q.toString().replace(/%2C/g, ',').replace(/%3B/g, ';');
  return str ? `?${str}` : '';
}

/** The zone/area part of a search string (history entries differ by it). */
export function zoneKey(search: string): string {
  const q = new URLSearchParams(search);
  const area = q.get('area');
  return area ? `area:${area}` : `zone:${q.get('zone') ?? DEFAULT_ZONE}`;
}
