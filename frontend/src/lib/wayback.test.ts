import { beforeEach, describe, expect, it } from 'vitest';
import {
  CONFIG_URL, STATIC_RELEASES, esriChoice, loadWaybackReleases, parseIdentify, parseWaybackConfig, pickVersion, probeSatSite,
  releaseMaxzoom, resetWaybackForTests, tileCentre, tileOf, versionOf, walkVersions, type SatSite, type SatVersion, type WaybackRelease,
} from './wayback';
import { ESRI_RELEASES, captureMonth, isSatLayerId, esriLayerId, satCaption } from './satellite';

const v = (release: number, date: string, captured: string | null, maxzoom = 19): SatVersion => ({ release, date, captured, maxzoom });
// Nyzhni Sady, Kyiv (30.6155, 50.3935): tile versions found by the tilemap walk and their capture dates (identify, 15.11.2026)
const NS: SatVersion[] = [
  v(22252, '2026-01-29', '2025-04-20'), v(20512, '2025-10-23', '2025-04-20'), v(27982, '2025-04-24', '2024-07-13'),
  v(34007, '2025-02-27', '2024-07-13'), v(60013, '2024-03-07', '2022-02-28'), v(45134, '2022-12-14', '2022-02-28'),
  v(17825, '2022-08-10', '2022-02-28'), v(44710, '2022-06-08', '2021-10-11'), v(48232, '2022-04-06', '2019-04-03'),
  v(15423, '2021-05-19', '2019-04-03'), v(9812, '2021-02-24', '2019-04-03'), v(16062, '2020-03-23', '2017-03-28'),
  v(11351, '2019-10-09', '2017-03-28'), v(2168, '2018-09-06', '2017-03-28'), v(29387, '2017-03-15', '2016-07-15'),
  v(9486, '2017-01-25', '2013-04-16'), v(15084, '2015-03-18', '2013-04-16'), v(30195, '2014-11-12', '2011-09-20', 17),
  v(4230, '2014-03-26', '2011-09-20', 17), v(10, '2014-02-20', '2011-09-20', 17),
];
const site = (versions: SatVersion[], complete = true): SatSite => ({ key: '17/0/0', versions, complete });
const cap = (y: number | null, vs = NS) => pickVersion(y, vs)?.captured;

describe('pickVersion: the capture closest to the map year', () => {
  it('a capture in that year wins (closest to mid-summer)', () => {
    expect(cap(2016)).toBe('2016-07-15');
    expect(cap(2017)).toBe('2017-03-28');
    expect(cap(2019)).toBe('2019-04-03');
    expect(cap(2021)).toBe('2021-10-11');
    expect(cap(2022)).toBe('2022-02-28');
    expect(cap(2024)).toBe('2024-07-13');
    expect(cap(2025)).toBe('2025-04-20');
  });
  it('else the latest capture before the year; before every capture → the earliest', () => {
    expect(cap(2014)).toBe('2013-04-16');
    expect(cap(2015)).toBe('2013-04-16');
    expect(cap(2018)).toBe('2017-03-28');
    expect(cap(2020)).toBe('2019-04-03');
    expect(cap(2023)).toBe('2022-02-28');
    expect(cap(2013)).toBe('2013-04-16');
    expect(cap(2010)).toBe('2011-09-20');
    expect(cap(null)).toBe('2025-04-20');
  });
  it('one version per capture date (the newest release), so years with the same picture share one layer', () => {
    expect(pickVersion(2025, NS)?.release).toBe(22252);
    expect(pickVersion(2024, NS)?.release).toBe(27982);
    expect(pickVersion(2022, NS)?.release).toBe(60013);
    expect(pickVersion(2023, NS)?.release).toBe(60013);
    const layers = new Set([2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025].map((y) => pickVersion(y, NS)?.release));
    expect(layers.size).toBe(8); // 13 map years → 8 distinct pictures (2013 2016 2017 2019 2021 2022 2024 2025)
  });
  it('a later release with an OLDER capture (Uzhhorod 2024 → 2022-03-27) does not hide the newer capture', () => {
    const uzh = [v(58924, '2025-09-25', '2022-05-12'), v(20337, '2024-09-19', '2022-03-27'), v(64776, '2023-08-31', '2022-05-12'), v(47471, '2022-09-21', '2019-10-17')];
    expect(cap(2024, uzh)).toBe('2022-05-12');
    expect(pickVersion(2024, uzh)?.release).toBe(58924);
    expect(cap(2022, uzh)).toBe('2022-05-12');
    expect(cap(2020, uzh)).toBe('2019-10-17');
  });
  it('unknown captures are ignored; none known → null', () => {
    expect(pickVersion(2020, [v(1, '2020-01-01', null)])).toBeNull();
    expect(pickVersion(2020, [v(1, '2021-01-01', null), v(2, '2019-01-01', '2018-06-01')])?.release).toBe(2);
  });
});

describe('esriChoice: what is shown and captioned', () => {
  it('complete site → the picked version, nearest when the capture year differs', () => {
    expect(esriChoice(2016, site(NS))).toMatchObject({ release: 29387, captured: '2016-07-15', nearest: false, maxzoom: 19 });
    expect(esriChoice(2020, site(NS))).toMatchObject({ release: 48232, captured: '2019-04-03', nearest: true });
    expect(esriChoice(2013, site(NS))).toMatchObject({ captured: '2013-04-16', nearest: false });
  });
  it('no site → the static release of the year (2014 release: maxzoom 17)', () => {
    expect(esriChoice(2019, null)).toEqual({ release: 9892, date: '2019-09-18', captured: null, maxzoom: 19, minzoom: null, nearest: false });
    expect(esriChoice(2013, null)).toMatchObject({ release: 25586, maxzoom: 17, nearest: true });
  });
  it('captures still coming in → the static release (no reload yet), captioned with its tile version\'s capture', () => {
    const c = esriChoice(2019, site(NS, false)); // static 2019 release 9892 (2019-09-18) shows tile version 2168 (2018-09-06)
    expect(c).toMatchObject({ release: 9892, date: '2019-09-18', captured: '2017-03-28', nearest: true });
  });
  it('complete, no capture known (metadata down) → the static release mapped onto its tile version: same picture, one layer', () => {
    const undated = site(NS.map((x) => ({ ...x, captured: null })), true);
    expect(esriChoice(2019, undated)).toMatchObject({ release: 2168, date: '2018-09-06', captured: null, nearest: false });
    expect(esriChoice(2020, undated).release).toBe(16062);
    expect(esriChoice(2013, null)).toMatchObject({ minzoom: null });
  });
  it('versionOf: the newest version not newer than the release', () => {
    expect(versionOf({ release: 58924, date: '2025-09-25' }, NS)?.release).toBe(27982);
    expect(versionOf({ release: 1, date: '2013-01-01' }, NS)).toBeNull();
  });
});

describe('captions', () => {
  it('capture month in en / uk (genitive)', () => {
    expect(captureMonth('en', '2024-07-13')).toBe('Jul 2024');
    expect(captureMonth('uk', '2024-07-13')).toBe('липня 2024');
    expect(captureMonth('uk', '2019-04-03')).toBe('квітня 2019');
  });
  it('captured caption with the nearest note only when the capture year differs', () => {
    const shown = (y: number) => { const c = esriChoice(y, site(NS)); return { date: c.date, captured: c.captured, nearest: c.nearest }; };
    expect(satCaption('en', 2024, 'esri', shown(2024))).toBe('Satellite: Esri World Imagery, captured Jul 2024');
    expect(satCaption('uk', 2024, 'esri', shown(2024))).toBe('Супутник: Esri World Imagery, знімок липня 2024');
    expect(satCaption('en', 2020, 'esri', shown(2020))).toBe('Satellite: Esri World Imagery, captured Apr 2019 (nearest available)');
    expect(satCaption('uk', 2020, 'esri', shown(2020))).toBe('Супутник: Esri World Imagery, знімок квітня 2019 (найближчий доступний)');
  });
  it('zoomed out below the dated imagery → «zoom in to see it»', () => {
    expect(satCaption('en', 2024, 'esri', { date: '2025-04-24', captured: '2024-07-13', nearest: false, zoomIn: true })).toBe('Satellite: Esri World Imagery, captured Jul 2024 · zoom in to see it');
    expect(satCaption('uk', 2020, 'esri', { date: '2022-04-06', captured: '2019-04-03', nearest: true, zoomIn: true })).toBe('Супутник: Esri World Imagery, знімок квітня 2019 (найближчий доступний) · наблизьте, щоб побачити');
  });
  it('capture unknown → the release-date caption of the version shown', () => {
    expect(satCaption('en', 2019, 'esri', { date: '2018-09-06', captured: null, nearest: false })).toBe('Satellite: Esri World Imagery, archive version 2018-09 (imagery may be older)');
    expect(satCaption('en', 2013, 'esri', { date: '2014-09-17', captured: null, nearest: true })).toContain('(nearest available version)');
  });
  it('layer ids: Esri sat-w<release>, EOX sat-YYYY', () => {
    expect(esriLayerId(9892)).toBe('sat-w9892');
    for (const id of ['sat-w9892', 'sat-w10', 'sat-2019']) expect(isSatLayerId(id)).toBe(true);
    for (const id of ['sat-', 'sat-wx', 'satellite', 'heat']) expect(isSatLayerId(id)).toBe(false);
  });
});

describe('metadata and config parsing', () => {
  it('identify: the result covering z17, the deepest dated level; SRC_DATE or SRC_DATE2', () => {
    const r = (layer: string, d: string, min: number, max: number, d2 = '') => ({ layerName: layer, attributes: { SRC_DATE: d, SRC_DATE2: d2, MinMapLevel: String(min), MaxMapLevel: String(max) } });
    expect(parseIdentify({ results: [r('30cm', '20220228', 19, 19), r('60cm', '20211011', 16, 18), r('4.8m', '20211011', 12, 15), r('75m', 'Null', 0, 11)] })).toEqual({ captured: '2021-10-11', maxLevel: 19, minLevel: 12 });
    expect(parseIdentify({ results: [r('1.2m', '', 14, 17, '9/20/2011')] })).toEqual({ captured: '2011-09-20', maxLevel: 17, minLevel: 14 });
    expect(parseIdentify({ results: [r('75m', 'Null', 0, 11)] })).toEqual({ captured: null, maxLevel: null, minLevel: null });
    expect(parseIdentify({ error: { code: 500 } })).toEqual({ captured: null, maxLevel: null, minLevel: null });
  });
  it('config: dated releases with an Esri metadata URL, newest first', () => {
    const meta = 'https://metadata.maptiles.arcgis.com/arcgis/rest/services/World_Imagery_Metadata_2019_r12/MapServer';
    const rs = parseWaybackConfig({
      9892: { itemTitle: 'World Imagery (Wayback 2019-09-18)', metadataLayerUrl: meta },
      22252: { itemTitle: 'World Imagery (Wayback 2026-01-29)', metadataLayerUrl: meta },
      1: { itemTitle: 'no date', metadataLayerUrl: meta },
      2: { itemTitle: 'World Imagery (Wayback 2020-01-01)', metadataLayerUrl: 'https://evil.example/x' },
    });
    expect(rs.map((r) => r.release)).toEqual([22252, 9892]);
    expect(parseWaybackConfig(null)).toEqual([]);
  });
  it('static fallback list = the 12 per-year releases with their metadata services', () => {
    expect(STATIC_RELEASES).toHaveLength(Object.keys(ESRI_RELEASES).length);
    for (const r of STATIC_RELEASES) expect(r.meta).toMatch(/^https:\/\/metadata\.maptiles\.arcgis\.com\/arcgis\/rest\/services\/World_Imagery_Metadata_\d{4}_r\d\d\/MapServer$/);
    expect(releaseMaxzoom('2014-09-17')).toBe(17);
    expect(releaseMaxzoom('2015-03-18')).toBe(19);
  });
  it('tiles: Nyzhni Sady z16 tile, centre round trip', () => {
    expect(tileOf(30.6155, 50.3935, 16)).toEqual({ z: 16, x: 38341, y: 22114 });
    const t = tileOf(22.295, 48.62, 17);
    expect(tileOf(...tileCentre(t), 17)).toEqual(t);
  });
});

// a synthetic release history: 100 releases, the tile changes at a few of them
const REL: WaybackRelease[] = Array.from({ length: 100 }, (_, i) => ({ release: 1000 + i, date: `20${String(26 - Math.floor(i / 8)).padStart(2, '0')}-${String(12 - (i % 8)).padStart(2, '0')}-01`, meta: '' }));
const selectFor = (changes: number[]) => async (r: number) => { const i = r - 1000; const c = changes.filter((x) => x >= i).sort((a, b) => a - b)[0]; return c == null ? null : 1000 + c; };

describe('walkVersions: tile versions in a few parallel rounds', () => {
  it('finds every change point, also several between two sampled releases', async () => {
    const changes = [0, 3, 4, 5, 6, 17, 40, 41, 77, 90];
    let asked = 0;
    const sel = selectFor(changes);
    const found = await walkVersions(REL, (r) => { asked++; return sel(r); });
    expect(found.map((r) => r.release - 1000)).toEqual(changes);
    expect(asked).toBeLessThan(REL.length / 2);
  });
  it('stops below the oldest tile (null) and survives failing requests', async () => {
    const sel = selectFor([2, 30]);
    const found = await walkVersions(REL, (r) => (r === 1016 ? Promise.reject(new Error('timeout')) : sel(r)));
    expect(found.map((r) => r.release - 1000)).toEqual([2, 30]);
  });
});

describe('probeSatSite / loadWaybackReleases with a fake network', () => {
  beforeEach(() => { resetWaybackForTests(); localStorage.clear(); });
  const meta = (n: number) => `https://metadata.maptiles.arcgis.com/arcgis/rest/services/World_Imagery_Metadata_${n}/MapServer`;
  const config = Object.fromEntries(Array.from({ length: 16 }, (_, i) => [String(500 + i), { itemTitle: `World Imagery (Wayback ${2025 - i}-06-01)`, metadataLayerUrl: meta(500 + i) }]));
  const capture: Record<number, string> = { 500: '20250420', 504: '20210601', 509: '20160715' };
  const fake = (calls: string[], slowMeta?: number) => async (url: string) => {
    calls.push(url);
    if (url === CONFIG_URL) return { ok: true, json: async () => config };
    const tm = /tilemap\/(\d+)\//.exec(url);
    if (tm) { const r = +tm[1]!; const s = r <= 500 ? 500 : r <= 504 ? 504 : r <= 509 ? 509 : null; return { ok: true, json: async () => (s ? { data: [1], select: [s] } : { data: [0] }) }; }
    const id = /Metadata_(\d+)\/MapServer\/identify/.exec(url);
    if (id) {
      if (+id[1]! === slowMeta) throw new Error('timeout');
      return { ok: true, json: async () => ({ results: [{ attributes: { SRC_DATE: capture[+id[1]!], MinMapLevel: '16', MaxMapLevel: '19' } }] }) };
    }
    return { ok: false, json: async () => ({}) };
  };
  it('walks the tile versions, dates them, picks per year; cached for the next probe', async () => {
    const calls: string[] = [];
    const updates: SatSite[] = [];
    const s = await probeSatSite(30.6155, 50.3935, (x) => updates.push(x), fake(calls));
    expect(s.complete).toBe(true);
    expect(s.versions.map((x) => [x.release, x.captured])).toEqual([[500, '2025-04-20'], [504, '2021-06-01'], [509, '2016-07-15']]);
    expect(updates.at(-1)?.complete).toBe(true);
    expect(esriChoice(2017, s)).toMatchObject({ release: 509, captured: '2016-07-15', nearest: true });
    // a fresh session (memory cleared): versions and captures come from localStorage, only the config is fetched
    resetWaybackForTests();
    const calls2: string[] = [];
    const s2 = await probeSatSite(30.6155, 50.3935, undefined, fake(calls2));
    expect(s2.versions).toEqual(s.versions);
    expect(calls2).toEqual([CONFIG_URL]);
  });
  it('a failing metadata service leaves that version undated (not picked)', async () => {
    const s = await probeSatSite(30.6155, 50.3935, undefined, fake([], 509));
    expect(s.versions.find((x) => x.release === 509)?.captured).toBeNull();
    expect(esriChoice(2016, s).captured).toBe('2021-06-01');
  });
  it('config fetch failing → the static release table', async () => {
    const r = await loadWaybackReleases(async () => { throw new Error('offline'); });
    expect(r.live).toBe(false);
    expect(r.releases.map((x) => x.release)).toEqual(STATIC_RELEASES.map((x) => x.release));
  });
});
