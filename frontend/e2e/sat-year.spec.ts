import { expect, test, type Page } from '@playwright/test';

// The satellite basemap follows the map year (lib/satellite.ts): one `sat-YYYY` raster layer per archive version, exactly one
// visible. Primary: Esri World Imagery Wayback (one release per year 2014–2025; 2013 → the 2014 release). Fallback: the EOX
// Sentinel-2 mosaics (2013–2015 → 2016) when Esri tiles fail or `?sat=eox`.
type M = {
  getStyle(): { layers: { id: string }[]; sources: Record<string, { tiles?: string[] }> };
  getLayoutProperty(id: string, p: string): unknown;
};

const visibleSat = (page: Page) =>
  page.evaluate(() => {
    const m = (globalThis as unknown as { __uhdMap: M }).__uhdMap;
    return m.getStyle().layers.filter((l) => /^sat-\d{4}$/.test(l.id) && m.getLayoutProperty(l.id, 'visibility') !== 'none').map((l) => l.id);
  });
const satTilesUrl = (page: Page, id: string) =>
  page.evaluate((i) => (globalThis as unknown as { __uhdMap: M }).__uhdMap.getStyle().sources[i]?.tiles?.[0] ?? null, id);

const ESRI = /wayback\.maptiles\.arcgis\.com/;
const EOX = /tiles\.maps\.eox\.at/;
// a 1×1 PNG: a tile MapLibre can decode, so the source counts as healthy
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64');
const png = { status: 200, contentType: 'image/png', body: PNG };

async function openSatellite(page: Page, url: string) {
  await page.goto(url);
  await page.locator('.map[data-ready]').waitFor();
  await page.getByTestId('layers-toggle').click();
  await page.getByTestId('layers-panel').getByRole('radio', { name: 'Супутник' }).click();
}

test('Esri Wayback release swaps with the map year (sat-YYYY); 2013 → the 2014 release with the nearest note', async ({ page }) => {
  const releases = new Set<string>();
  await page.route(ESRI, (r) => { releases.add(/\/tile\/(\d+)\//.exec(r.request().url())?.[1] ?? '?'); return r.fulfill(png); });
  await page.route(EOX, (r) => r.fulfill({ status: 500 })); // must not be touched
  await openSatellite(page, '/?year=2019');

  await expect.poll(() => visibleSat(page)).toEqual(['sat-2019']);
  expect(await satTilesUrl(page, 'sat-2019')).toBe('https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/WMTS/1.0.0/default028mm/MapServer/tile/9892/{z}/{y}/{x}');
  await expect(page.locator('.sat-cap')).toHaveText('Супутник: Esri World Imagery, версія архіву 2019-09 (дата зйомки може бути ранішою)');
  await expect.poll(() => [...releases]).toContain('9892');

  await page.keyboard.press('Escape');
  await page.getByRole('radio', { name: /^2017/ }).click();
  await expect(page.getByTestId('map-year')).toHaveText('Мапа: літо 2017');
  await expect.poll(() => visibleSat(page)).toEqual(['sat-2017']);
  await expect(page.locator('.sat-cap')).toContainText('2017-09');
  await expect(page.locator('.sat-cap')).not.toContainText('найближча');

  await page.getByRole('radio', { name: /^2013/ }).click();
  await expect(page.getByTestId('map-year')).toHaveText('Мапа: літо 2013');
  await expect.poll(() => visibleSat(page)).toEqual(['sat-2014']);
  expect(await satTilesUrl(page, 'sat-2014')).toContain('/tile/25586/');
  await expect(page.locator('.sat-cap')).toHaveText('Супутник: Esri World Imagery, версія архіву 2014-09 (дата зйомки може бути ранішою) (найближча доступна версія)');
  // still Esri: no fallback happened
  expect(await satTilesUrl(page, 'sat-2014')).toMatch(ESRI);
});

test('Esri tiles failing (500) fall back to the EOX mosaic with its caption', async ({ page }) => {
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
