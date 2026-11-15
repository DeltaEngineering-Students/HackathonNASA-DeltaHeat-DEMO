import { expect, test, type Page } from '@playwright/test';

// The satellite basemap follows the map year (lib/satellite.ts, lib/wayback.ts): one raster layer per imagery version, exactly
// one visible. Primary: Esri World Imagery Wayback, `sat-w<release>` — the tile version whose capture date at the place is
// closest to the year (release list + tilemap + metadata); with those services down, the static release of the year
// (2014–2025; 2013 → the 2014 release). Fallback: the EOX Sentinel-2 mosaics `sat-YYYY` (2013–2015 → 2016) when Esri tiles
// fail or `?sat=eox`.
type M = {
  getStyle(): { layers: { id: string }[]; sources: Record<string, { tiles?: string[] }> };
  getLayoutProperty(id: string, p: string): unknown;
};

const visibleSat = (page: Page) =>
  page.evaluate(() => {
    const m = (globalThis as unknown as { __uhdMap: M }).__uhdMap;
    return m.getStyle().layers.filter((l) => /^sat-w?\d+$/.test(l.id) && m.getLayoutProperty(l.id, 'visibility') !== 'none').map((l) => l.id);
  });
const satTilesUrl = (page: Page, id: string) =>
  page.evaluate((i) => (globalThis as unknown as { __uhdMap: M }).__uhdMap.getStyle().sources[i]?.tiles?.[0] ?? null, id);

const ESRI = /wayback\.maptiles\.arcgis\.com/;
const EOX = /tiles\.maps\.eox\.at/;
// a 1×1 PNG: a tile MapLibre can decode, so the source counts as healthy
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64');
const png = { status: 200, contentType: 'image/png', body: PNG };

const WB_CONFIG = /config\.maptiles\.arcgis\.com\/waybackconfig\.json/;
const WB_TILEMAP = /wayback\.maptiles\.arcgis\.com\/arcgis\/rest\/services\/World_Imagery\/MapServer\/tilemap\//;
const WB_META = /metadata\.maptiles\.arcgis\.com/;
/** release list and metadata unreachable: the static per-year releases with their release-date caption */
async function noWaybackMeta(page: Page) {
  await page.route(WB_CONFIG, (r) => r.abort());
  await page.route(WB_META, (r) => r.abort());
}
async function openSatellite(page: Page, url: string) {
  await page.goto(url);
  await page.locator('.map[data-ready]').waitFor();
  await page.getByTestId('layers-toggle').click();
  await page.getByTestId('layers-panel').getByRole('radio', { name: 'Супутник' }).click();
}

test('metadata down: the static Esri release swaps with the map year (sat-w<release>); 2013 → the 2014 release with the nearest note', async ({ page }) => {
  await noWaybackMeta(page);
  const releases = new Set<string>();
  await page.route(ESRI, (r) => { releases.add(/\/tile\/(\d+)\//.exec(r.request().url())?.[1] ?? '?'); return r.fulfill(png); });
  await page.route(EOX, (r) => r.fulfill({ status: 500 })); // must not be touched
  await openSatellite(page, '/?year=2019');

  await expect.poll(() => visibleSat(page)).toEqual(['sat-w9892']);
  expect(await satTilesUrl(page, 'sat-w9892')).toBe('https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/WMTS/1.0.0/default028mm/MapServer/tile/9892/{z}/{y}/{x}');
  await expect(page.locator('.sat-cap')).toHaveText('Супутник: Esri World Imagery, версія архіву 2019-09 (дата зйомки може бути ранішою)');
  await expect.poll(() => [...releases]).toContain('9892');

  await page.keyboard.press('Escape');
  await page.getByRole('radio', { name: /^2017/ }).click();
  await expect(page.getByTestId('map-year')).toHaveText('Мапа: літо 2017');
  await expect.poll(() => visibleSat(page)).toEqual(['sat-w18358']);
  await expect(page.locator('.sat-cap')).toContainText('2017-09');
  await expect(page.locator('.sat-cap')).not.toContainText('найближча');

  await page.getByRole('radio', { name: /^2013/ }).click();
  await expect(page.getByTestId('map-year')).toHaveText('Мапа: літо 2013');
  await expect.poll(() => visibleSat(page)).toEqual(['sat-w25586']);
  expect(await satTilesUrl(page, 'sat-w25586')).toContain('/tile/25586/');
  await expect(page.locator('.sat-cap')).toHaveText('Супутник: Esri World Imagery, версія архіву 2014-09 (дата зйомки може бути ранішою) (найближча доступна версія)');
  // still Esri: no fallback happened
  expect(await satTilesUrl(page, 'sat-w25586')).toMatch(ESRI);
});

test('Esri tiles failing (500) fall back to the EOX mosaic with its caption', async ({ page }) => {
  await noWaybackMeta(page);
  await page.route(ESRI, (r) => r.fulfill({ status: 500 }));
  await page.route(EOX, (r) => r.fulfill(png));
  await openSatellite(page, '/?year=2019');

  await expect.poll(() => satTilesUrl(page, 'sat-2019'), { timeout: 15_000 }).toMatch(EOX);
  await expect.poll(() => visibleSat(page)).toEqual(['sat-2019']);
  await expect(page.locator('.sat-cap')).toHaveText('Супутник: Sentinel‑2, 2019');
  await expect(page.getByTestId('sat-note')).toContainText('Sentinel‑2');
  // the fallback holds for the session: a later year uses EOX straight away (2014 → nearest mosaic 2016)
  await page.keyboard.press('Escape');
  await page.getByRole('radio', { name: /^2014/ }).click();
  await expect.poll(() => visibleSat(page)).toEqual(['sat-2016']);
  await expect(page.locator('.sat-cap')).toHaveText('Супутник: Sentinel‑2, 2016 (найближчий доступний рік)');
});

test('?sat=eox forces the EOX mosaic without asking Esri', async ({ page }) => {
  let esri = 0;
  await page.route(ESRI, (r) => { esri++; return r.fulfill(png); });
  await page.route(EOX, (r) => r.fulfill(png));
  await openSatellite(page, '/?year=2019&sat=eox');
  await expect.poll(() => visibleSat(page)).toEqual(['sat-2019']);
  expect(await satTilesUrl(page, 'sat-2019')).toMatch(EOX);
  await expect(page.locator('.sat-cap')).toHaveText('Супутник: Sentinel‑2, 2019');
  expect(esri).toBe(0);
});

// capture dates known: years with the same picture share one layer, the caption names the capture month
test('capture dates: one layer per capture, «знімок <month> <year>», the nearest note when the capture year differs', async ({ page }) => {
  const meta = (n: number) => `https://metadata.maptiles.arcgis.com/arcgis/rest/services/World_Imagery_Metadata_${n}/MapServer`;
  // 16 releases 2025…2010; the tile changed at 500 (captured 2025-04-20), 504 (2021-06-01) and 509 (2016-07-15)
  const config = Object.fromEntries(Array.from({ length: 16 }, (_, i) => [String(500 + i), { itemTitle: `World Imagery (Wayback ${2025 - i}-06-01)`, metadataLayerUrl: meta(500 + i) }]));
  const capture: Record<number, string> = { 500: '20250420', 504: '20210601', 509: '20160715' };
  const sel = (r: number) => (r <= 500 ? 500 : r <= 504 ? 504 : r <= 509 ? 509 : null);
  // tiles first: the later, more specific routes (tilemap) take precedence
  await page.route(ESRI, (r) => r.fulfill(png));
  await page.route(EOX, (r) => r.fulfill({ status: 500 }));
  await page.addInitScript(() => { for (const k of Object.keys(localStorage)) if (k.startsWith('uhd-wb-')) localStorage.removeItem(k); });
  await page.route(WB_CONFIG, (r) => r.fulfill({ json: config, headers: { 'access-control-allow-origin': '*' } }));
  await page.route(WB_TILEMAP, (r) => {
    const n = Number(/tilemap\/(\d+)\//.exec(r.request().url())?.[1]);
    const s = sel(n);
    return r.fulfill({ json: s ? { data: [1], select: [s] } : { data: [0] }, headers: { 'access-control-allow-origin': '*' } });
  });
  await page.route(WB_META, (r) => {
    const n = Number(/Metadata_(\d+)\//.exec(r.request().url())?.[1]);
    return r.fulfill({ json: { results: [{ attributes: { SRC_DATE: capture[n] ?? 'Null', MinMapLevel: '12', MaxMapLevel: '19' } }] }, headers: { 'access-control-allow-origin': '*' } });
  });
  await openSatellite(page, '/?year=2021');
  await page.evaluate(() => (globalThis as unknown as { __uhdMap: { jumpTo(o: unknown): void } }).__uhdMap.jumpTo({ center: [30.6155, 50.3935], zoom: 14 }));

  await expect.poll(() => visibleSat(page), { timeout: 15_000 }).toEqual(['sat-w504']);
  await expect(page.locator('.sat-cap')).toHaveText('Супутник: Esri World Imagery, знімок червня 2021');
  await page.keyboard.press('Escape');
  await page.getByRole('radio', { name: /^2020/ }).click();
  await expect.poll(() => visibleSat(page)).toEqual(['sat-w509']);
  await expect(page.locator('.sat-cap')).toHaveText('Супутник: Esri World Imagery, знімок липня 2016 (найближчий доступний)');
  await page.getByRole('radio', { name: /^2017/ }).click();
  await expect.poll(() => visibleSat(page)).toEqual(['sat-w509']); // same picture: the same layer, nothing reloaded
  await page.getByRole('radio', { name: /^2025/ }).click();
  await expect.poll(() => visibleSat(page)).toEqual(['sat-w500']);
  await expect(page.locator('.sat-cap')).toHaveText('Супутник: Esri World Imagery, знімок квітня 2025');
});
