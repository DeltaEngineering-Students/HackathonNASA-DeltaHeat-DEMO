import { describe, expect, it } from 'vitest';
import {
  ESRI_RELEASES, SAT_ERROR_LIMIT, SAT_TIMEOUT_MS, esriAttribution, esriTiles, esriVersion, satAttribution, satAttributionFor, satCaption, satCaptionEox,
  satErrorCounts, satForcedEox, satLayerName, satLayerYear, satMaxzoom, satMosaicYear, satShouldFallback, satTiles, satTilesFor, SAT_YEARS,
} from './satellite';

describe('satellite mosaic follows the map year', () => {
  it('uses the same year when a mosaic exists', () => {
    for (const y of SAT_YEARS) expect(satMosaicYear(y)).toBe(y);
    expect(satMosaicYear(2019)).toBe(2019);
  });
  it('2013–2015 (no Sentinel-2) show the earliest mosaic; later years clamp to the latest', () => {
    for (const y of [2013, 2014, 2015]) expect(satMosaicYear(y)).toBe(2016);
    expect(satMosaicYear(2026)).toBe(2025);
    expect(satMosaicYear(null)).toBe(2025);
  });
  it('maps to the real EOX WMTS layer names (2016 has no year suffix)', () => {
    expect(satLayerName(2016)).toBe('s2cloudless_3857');
    expect(satLayerName(2019)).toBe('s2cloudless-2019_3857');
    expect(satTiles(2024)).toBe('https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2024_3857/default/g/{z}/{y}/{x}.jpg');
    expect(new URL(satTiles(2020).replace(/[{}]/g, '')).hostname).toBe('tiles.maps.eox.at');
  });
  it('licence differs per mosaic: 2016–2017 CC BY 4.0, 2018+ CC BY-NC-SA 4.0', () => {
    expect(satAttribution(2016)).toContain('CC BY 4.0');
    expect(satAttribution(2016)).not.toContain('NC-SA');
    expect(satAttribution(2018)).toContain('CC BY-NC-SA 4.0');
    expect(satAttribution(2018)).toContain('Sentinel data 2017 &amp; 2018');
    expect(satAttribution(2024)).toContain('Sentinel data 2024');
  });
  it('EOX caption in uk and en, with the nearest-year note only when the year differs', () => {
    expect(satCaptionEox('uk', 2019)).toBe('Супутник: Sentinel‑2, 2019');
    expect(satCaptionEox('en', 2019)).toBe('Satellite: Sentinel‑2, 2019');
    expect(satCaptionEox('en', 2014)).toBe('Satellite: Sentinel‑2, 2016 (nearest available year)');
    expect(satCaptionEox('uk', 2014)).toBe('Супутник: Sentinel‑2, 2016 (найближчий доступний рік)');
    expect(satCaption('en', 2014, 'eox')).toBe(satCaptionEox('en', 2014));
  });
});

describe('Esri World Imagery Wayback (primary)', () => {
  it('max zoom: 19, 17 for the 2014 release (no z18–19 tiles), 17 for EOX', () => {
    expect(satMaxzoom('esri', 2025)).toBe(19);
    expect(satMaxzoom('esri', 2015)).toBe(19);
    expect(satMaxzoom('esri', 2014)).toBe(17);
    expect(satMaxzoom('esri')).toBe(19);
    expect(satMaxzoom('eox', 2014)).toBe(17);
  });
  it('has one release for every year 2014–2025 with a date in that year', () => {
    for (let y = 2014; y <= 2025; y++) {
      const r = ESRI_RELEASES[y];
      expect(r, String(y)).toBeDefined();
      expect(r?.date.startsWith(String(y))).toBe(true);
      expect(Number.isInteger(r?.release)).toBe(true);
    }
    expect(Object.keys(ESRI_RELEASES)).toHaveLength(12);
  });
  it('maps a map year to its release; 2013 → 2014, 2026+ and no year → 2025', () => {
    expect(esriVersion(2019)).toEqual({ year: 2019, release: 9892, date: '2019-09-18' });
    expect(esriVersion(2013).year).toBe(2014);
    expect(esriVersion(2013).release).toBe(25586);
    expect(esriVersion(2026).release).toBe(58924);
    expect(esriVersion(null).year).toBe(2025);
    expect(esriVersion(Number.NaN).year).toBe(2025);
  });
  it('tile URL is {release}/{z}/{y}/{x} on the Wayback host', () => {
    expect(esriTiles(9892)).toBe('https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/WMTS/1.0.0/default028mm/MapServer/tile/9892/{z}/{y}/{x}');
    expect(satTilesFor('esri', 2019)).toBe(esriTiles(9892));
    expect(satTilesFor('eox', 2019)).toBe(satTiles(2019));
    expect(satLayerYear('esri', 2013)).toBe(2014);
    expect(satLayerYear('eox', 2013)).toBe(2016);
  });
  it('attribution carries the Esri credit line; EOX keeps its own', () => {
    expect(esriAttribution()).toContain('Esri, Maxar, Earthstar Geographics, and the GIS User Community');
    expect(satAttributionFor('esri', 2019)).toBe(esriAttribution());
    expect(satAttributionFor('eox', 2019)).toBe(satAttribution(2019));
  });
  it('caption in uk and en; the nearest-version note only when the version year differs', () => {
    expect(satCaption('en', 2019)).toBe('Satellite: Esri World Imagery, archive version 2019-09 (imagery may be older)');
    expect(satCaption('uk', 2019)).toBe('Супутник: Esri World Imagery, версія архіву 2019-09 (дата зйомки може бути ранішою)');
    expect(satCaption('en', 2013)).toBe('Satellite: Esri World Imagery, archive version 2014-09 (imagery may be older) (nearest available version)');
    expect(satCaption('uk', 2013)).toBe('Супутник: Esri World Imagery, версія архіву 2014-09 (дата зйомки може бути ранішою) (найближча доступна версія)');
    expect(satCaption('en', null)).not.toContain('nearest');
  });
});

describe('fallback to EOX', () => {
  it('?sat=eox forces EOX', () => {
    expect(satForcedEox('?sat=eox')).toBe(true);
    expect(satForcedEox('?year=2019&sat=eox')).toBe(true);
    expect(satForcedEox('?sat=esri')).toBe(false);
    expect(satForcedEox('')).toBe(false);
  });
  it('404 (no tile at that zoom) is not a failure, 5xx and network errors are', () => {
    expect(satErrorCounts(404)).toBe(false);
    expect(satErrorCounts(500)).toBe(true);
    expect(satErrorCounts(503)).toBe(true);
    expect(satErrorCounts(undefined)).toBe(true);
  });
  it('falls back after a few failures that outnumber the answers', () => {
    expect(satShouldFallback({ errors: SAT_ERROR_LIMIT - 1, answered: 0, elapsedMs: 100 })).toBe(false);
    expect(satShouldFallback({ errors: SAT_ERROR_LIMIT, answered: 0, elapsedMs: 100 })).toBe(true);
    expect(satShouldFallback({ errors: SAT_ERROR_LIMIT, answered: 50, elapsedMs: 100 })).toBe(false); // flaky, but working
    expect(satShouldFallback({ errors: 60, answered: 50, elapsedMs: 100 })).toBe(true);
  });
  it('falls back when nothing answered within the timeout', () => {
    expect(satShouldFallback({ errors: 0, answered: 0, elapsedMs: SAT_TIMEOUT_MS - 1 })).toBe(false);
    expect(satShouldFallback({ errors: 0, answered: 0, elapsedMs: SAT_TIMEOUT_MS })).toBe(true);
    expect(satShouldFallback({ errors: 0, answered: 1, elapsedMs: SAT_TIMEOUT_MS * 3 })).toBe(false);
  });
});
