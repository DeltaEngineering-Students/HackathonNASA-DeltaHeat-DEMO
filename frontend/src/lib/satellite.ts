// Satellite basemap. PRIMARY: Esri World Imagery Wayback (sharp sub-metre archive versions from 2014; see ESRI_RELEASES below).
// FALLBACK (Esri tiles failing, or `?sat=eox`): EOX Sentinel-2 cloudless yearly mosaics (WMTS, EPSG:3857, no key).
// Either way the imagery follows the map year, one raster layer `sat-YYYY` visible at a time.
// ── EOX ──
// Layer names checked against https://tiles.maps.eox.at/wmts/1.0.0/WMTSCapabilities.xml (tiles return 200 for 2016–2025):
// 2016 is `s2cloudless_3857`, later years `s2cloudless-<year>_3857`. 2026 does not exist yet.
import { tr, type Locale } from '../i18n';

export const SAT_FIRST = 2016;
export const SAT_LAST = 2025;
/** Sentinel-2 mosaics that exist (2013–2015 have no Sentinel-2: Landsat years before the launch) */
export const SAT_YEARS: readonly number[] = Array.from({ length: SAT_LAST - SAT_FIRST + 1 }, (_, i) => SAT_FIRST + i);

/** The mosaic shown for a map year: the same year, else the nearest available one (2013–2015 → 2016); no year → latest. */
export function satMosaicYear(year: number | null | undefined): number {
  if (year == null || !Number.isFinite(year)) return SAT_LAST;
  return Math.min(SAT_LAST, Math.max(SAT_FIRST, Math.round(year)));
}
export const satLayerName = (mosaic: number) => (mosaic === SAT_FIRST ? 's2cloudless_3857' : `s2cloudless-${mosaic}_3857`);
export const satTiles = (mosaic: number) => `https://tiles.maps.eox.at/wmts/1.0.0/${satLayerName(mosaic)}/default/g/{z}/{y}/{x}.jpg`;
/** 2016 and 2017 are CC BY 4.0, 2018 onwards CC BY-NC-SA 4.0 (EOX WMTS capabilities, per-layer abstract). */
export const satNonCommercial = (mosaic: number) => mosaic >= 2018;
/** the 2018 mosaic is built from 2017 and 2018 scenes (EOX abstract) */
const dataYears = (mosaic: number) => (mosaic === 2018 ? '2017 &amp; 2018' : String(mosaic));
export function satAttribution(mosaic: number): string {
  const lic = satNonCommercial(mosaic)
    ? '<a href="https://creativecommons.org/licenses/by-nc-sa/4.0/" target="_blank" rel="noreferrer">CC BY-NC-SA 4.0</a>'
    : '<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">CC BY 4.0</a>';
  return `<a href="https://cloudless.eox.at" target="_blank" rel="noreferrer">EOxCloudless</a> by EOX IT Services GmbH (Contains modified Copernicus Sentinel data ${dataYears(mosaic)}), ${lic}`;
}
export const satLayerId = (mosaic: number) => `sat-${mosaic}`;
export const isSatLayerId = (id: string) => /^sat-\d{4}$/.test(id);

/** «Супутник: Sentinel‑2, 2019» (+ «(найближчий доступний рік)» when the mosaic year differs from the selected one) — the EOX caption */
export function satCaptionEox(l: Locale, year: number | null | undefined): string {
  const mosaic = satMosaicYear(year);
  const base = tr(l, 'map.satCaptionEox', { year: mosaic });
  return year != null && year !== mosaic ? `${base} ${tr(l, 'map.satNearestEox')}` : base;
}

// ── Esri World Imagery Wayback ──
// Tiles: https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/WMTS/1.0.0/default028mm/MapServer/tile/{release}/{z}/{y}/{x}
// (row before column). A release with no change at a tile answers 301 to the release that has it (same host, relative
// Location; CORS `*`), which fetch follows; a missing tile (mostly z19 outside the big cities) is a plain 404.
/**
 * One Wayback release per year. Generated once (15.11.2026) from
 * https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json (itemTitle "World Imagery (Wayback YYYY-MM-DD)"):
 * for each year the LATEST release dated June–September (else the latest of the year); key = releaseNum, date = the title's date.
 */
export const ESRI_RELEASES: Readonly<Record<number, { release: number; date: string }>> = {
  2014: { release: 25586, date: '2014-09-17' },
  2015: { release: 3630, date: '2015-09-30' },
  2016: { release: 6984, date: '2016-09-14' },
  2017: { release: 18358, date: '2017-09-13' },
  2018: { release: 14426, date: '2018-09-26' },
  2019: { release: 9892, date: '2019-09-18' },
  2020: { release: 19187, date: '2020-09-23' },
  2021: { release: 51313, date: '2021-09-28' },
  2022: { release: 47471, date: '2022-09-21' },
  2023: { release: 64776, date: '2023-08-31' },
  2024: { release: 20337, date: '2024-09-19' },
  2025: { release: 58924, date: '2025-09-25' },
};
export const ESRI_FIRST = 2014;
export const ESRI_LAST = 2025;
export const ESRI_MAXZOOM = 19;
/** Esri World Imagery credit line (Esri's current World Imagery attribution) */
export const ESRI_CREDIT = 'Esri, Maxar, Earthstar Geographics, and the GIS User Community';

/** The archive version shown for a map year: the same year, else the nearest (2013 → 2014, 2026+ → 2025); no year → latest. */
export function esriVersion(year: number | null | undefined): { year: number; release: number; date: string } {
  const y = year == null || !Number.isFinite(year) ? ESRI_LAST : Math.min(ESRI_LAST, Math.max(ESRI_FIRST, Math.round(year)));
  return { year: y, ...(ESRI_RELEASES[y] as { release: number; date: string }) };
}
export const esriTiles = (release: number) =>
  `https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/WMTS/1.0.0/default028mm/MapServer/tile/${release}/{z}/{y}/{x}`;
export const esriAttribution = (): string =>
  `<a href="https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9" target="_blank" rel="noreferrer">Esri World Imagery</a>: ${ESRI_CREDIT}`;

export function satCaptionEsri(l: Locale, year: number | null | undefined): string {
  const v = esriVersion(year);
  const base = tr(l, 'map.satCaption', { version: v.date.slice(0, 7) });
  return year != null && year !== v.year ? `${base} ${tr(l, 'map.satNearest')}` : base;
}

// ── provider choice and fallback ──
export type SatProvider = 'esri' | 'eox';
const FALLBACK_KEY = 'uhd-sat-eox';
/** `?sat=eox` forces EOX (escape hatch) */
export const satForcedEox = (search: string = globalThis.location?.search ?? ''): boolean => new URLSearchParams(search).get('sat') === 'eox';
/** EOX for this session: forced, or Esri already failed earlier in the session */
export function satUseEox(): boolean {
  if (satForcedEox()) return true;
  try { return sessionStorage.getItem(FALLBACK_KEY) === '1'; } catch { return false; }
}
export function rememberSatFallback() {
  try { sessionStorage.setItem(FALLBACK_KEY, '1'); } catch { /* private mode */ }
}
export const satProviderOf = (eox: boolean): SatProvider => (eox ? 'eox' : 'esri');
/** the year of the layer (`sat-YYYY`) shown for a map year */
export const satLayerYear = (p: SatProvider, year: number | null | undefined) => (p === 'eox' ? satMosaicYear(year) : esriVersion(year).year);
export const satTilesFor = (p: SatProvider, layerYear: number) => (p === 'eox' ? satTiles(layerYear) : esriTiles(esriVersion(layerYear).release));
export const satAttributionFor = (p: SatProvider, layerYear: number) => (p === 'eox' ? satAttribution(layerYear) : esriAttribution());
/**
 * Releases whose deepest level over Ukraine is below ESRI_MAXZOOM: the 2014 release (25586) answers 404 at z18 and z19 at
 * every Kyiv point checked (15.11.2026; z17 is 200), so MapLibre overzooms z17 instead of drawing blank tiles.
 */
export const ESRI_MAXZOOM_BY_YEAR: Readonly<Record<number, number>> = { 2014: 17 };
export const satMaxzoom = (p: SatProvider, layerYear?: number) =>
  (p === 'eox' ? 17 : (layerYear != null ? ESRI_MAXZOOM_BY_YEAR[layerYear] : undefined) ?? ESRI_MAXZOOM);

/** Caption by the attribution: the Esri one, or (after a fallback / `?sat=eox`) the EOX one. */
export const satCaption = (l: Locale, year: number | null | undefined, p: SatProvider = 'esri') => (p === 'eox' ? satCaptionEox(l, year) : satCaptionEsri(l, year));

/** a missing tile (404) is normal for Wayback at high zoom; any other failure counts against the source */
export const satErrorCounts = (status: number | undefined) => status !== 404;
export const SAT_ERROR_LIMIT = 3;
export const SAT_TIMEOUT_MS = 6000;
/**
 * Fallback decision for the Esri source while it is visible. `errors` = tile failures that are not 404 (5xx, network),
 * `answered` = tiles that loaded or answered 404. Fall back when the failures reach the limit and outnumber the answers,
 * or when nothing at all has answered within the timeout.
 */
export function satShouldFallback(s: { errors: number; answered: number; elapsedMs: number }): boolean {
  if (s.errors >= SAT_ERROR_LIMIT && s.errors > s.answered) return true;
  return s.answered === 0 && s.elapsedMs >= SAT_TIMEOUT_MS;
}
