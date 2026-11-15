import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';

/**
 * The production CSP, read from the backend (uhd/api/app.py `_CSP`), so a host the map needs but the server does not
 * allow fails here and not only on the live site (item 7: satellite was blank on live behind the CSP). Dev-only
 * additions: inline/eval scripts and the HMR websocket for the Vite dev server — img/connect/font stay exactly as served.
 */
function prodCsp(): string {
  const py = readFileSync(new URL('../../backend/uhd/api/app.py', import.meta.url), 'utf8');
  const m = /_CSP = \(([\s\S]*?)\)\n/.exec(py);
  if (!m) throw new Error('no _CSP in backend/uhd/api/app.py');
  const csp = [...m[1]!.matchAll(/"([^"]*)"/g)].map((x) => x[1]).join('');
  return csp
    .replace("script-src 'self'", "script-src 'self' 'unsafe-inline' 'unsafe-eval'")
    .replace("connect-src 'self'", "connect-src 'self' ws://localhost:*");
}
async function withProdCsp(page: Page, violations: string[]) {
  const csp = prodCsp();
  await page.route((u) => u.pathname === '/', async (route) => {
    const r = await route.fetch();
    await route.fulfill({ response: r, headers: { ...r.headers(), 'content-security-policy': csp } });
  });
  await page.exposeFunction('__cspViolation', (v: string) => { violations.push(v); });
  await page.addInitScript(() => {
    const g = globalThis as unknown as { addEventListener(t: string, f: (e: { violatedDirective: string; blockedURI: string }) => void): void; __cspViolation(v: string): void };
    g.addEventListener('securitypolicyviolation', (e) => g.__cspViolation(`${e.violatedDirective} ${e.blockedURI}`));
  });
}

// item 7: one «Шари» panel — basemap «Карта / Супутник», «Видимість тепла», («Розрив» + backend overlay) «Приглушити не-забудову».
type M = { jumpTo(o: unknown): void; getZoom(): number; getLayer(id: string): unknown; getLayoutProperty(id: string, p: string): unknown; once(e: string, f: () => void): void; getStyle(): { layers: { id: string }[] }; loaded(): boolean };
// hosts the page may talk to: our app/API, the OpenFreeMap basemap and (satellite on) Esri Wayback tiles — nothing else
const ALLOWED = new Set(['localhost', '127.0.0.1', 'tiles.openfreemap.org', 'wayback.maptiles.arcgis.com']);

test('«Шари»: keyboard, satellite at z5–17 from Esri Wayback only, sliders remembered — under the production CSP', async ({ page }) => {
  const violations: string[] = [];
  await withProdCsp(page, violations);
  const hosts = new Set<string>();
  const eox: { z: number; status: number }[] = []; // Esri Wayback tiles (name kept)
  page.on('request', (r) => { const u = new URL(r.url()); if (u.protocol.startsWith('http')) hosts.add(u.hostname); });
  page.on('response', (r) => {
    const m = r.url().match(/wayback\.maptiles\.arcgis\.com\/arcgis\/rest\/services\/world_imagery\/wmts\/1\.0\.0\/default028mm\/mapserver\/tile\/\d+\/(\d+)\//i);
    if (m) eox.push({ z: Number(m[1]), status: r.status() });
  });
  await page.goto('/');
  await expect(page.getByTestId('answer')).toBeVisible();
  await page.locator('.map[data-ready]').waitFor();

  // no satellite requests until it is switched on
  expect(eox).toHaveLength(0);
  const toggle = page.getByTestId('layers-toggle');
  await toggle.focus();
  await page.keyboard.press('Enter');
  const panel = page.getByTestId('layers-panel');
  await expect(panel).toBeVisible();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  const vis = page.getByTestId('heat-visibility-value');
  await expect(vis).toHaveText('100 %');
  // fixtures have no `nonbuilt` overlay → the mute slider is not offered
  await expect(page.getByTestId('mute')).toHaveCount(0);

  // item 26: satellite → heat at 50 % until the user sets it; back to the map → 100 %
  await panel.getByRole('radio', { name: 'Супутник' }).click();
  await expect(vis).toHaveText('50 %');
  await panel.getByRole('radio', { name: 'Карта' }).click();
  await expect(vis).toHaveText('100 %');
  await panel.getByRole('radio', { name: 'Супутник' }).click();
  await expect(vis).toHaveText('50 %');
  // keyboard: a value the user chose is kept across basemap switches
  await page.getByTestId('heat-visibility').focus();
  for (let i = 0; i < 2; i++) await page.keyboard.press('ArrowLeft');
  await expect(vis).toHaveText('40 %');
  await panel.getByRole('radio', { name: 'Карта' }).click();
  await expect(vis).toHaveText('40 %');
  await panel.getByRole('radio', { name: 'Супутник' }).click();
  await expect(panel.getByRole('radio', { name: 'Супутник' })).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByTestId('sat-note')).toContainText('Esri World Imagery');
  await expect.poll(() => page.evaluate(() => { const m = (globalThis as unknown as { __uhdMap: M }).__uhdMap; return m.getStyle().layers.filter((l) => /^sat-\d{4}$/.test(l.id) && m.getLayoutProperty(l.id, 'visibility') !== 'none').length; })).toBe(1);
  await expect(page.locator('.maplibregl-ctrl-attrib')).toContainText('Esri World Imagery', { useInnerText: false });
  await expect(page.locator('.sat-cap')).toContainText(/Супутник: Esri World Imagery, версія архіву \d{4}-\d{2}/);

  // map zoom z asks for 256-px raster tiles at ≈ z+1 (MapLibre's 512-px world), capped by the source maxzoom 19
  // (each step a little further east so its tiles are not already cached from the previous step)
  for (const [i, z] of [5.5, 9, 13, 16, 17].entries()) {
    const from = eox.length;
    await page.evaluate((zz) => (globalThis as unknown as { __uhdMap: M }).__uhdMap.jumpTo({ center: [30.62 + zz[1] * 0.02, 50.4], zoom: zz[0] }), [z, i]);
    await expect.poll(() => eox.slice(from).filter((e) => e.status === 200).length, { timeout: 15_000, message: `Esri tiles at map zoom ${z}: ${JSON.stringify(eox.slice(from))}` }).toBeGreaterThan(0);
  }
  console.log('esri tile zooms', [...new Set(eox.map((e) => e.z))].sort((a, b) => a - b).join(','));
  // a 301 is Wayback pointing at the release that holds the tile, a 404 a tile it does not have; anything else is a failure
  expect(eox.filter((e) => ![200, 301, 404].includes(e.status))).toEqual([]);

  // Esc closes and returns focus; the choice survives a reload (session)
  await page.keyboard.press('Escape');
  await expect(panel).toHaveCount(0);
  await page.reload();
  await page.locator('.map[data-ready]').waitFor();
  await expect.poll(() => page.evaluate(() => { const m = (globalThis as unknown as { __uhdMap: M }).__uhdMap; return m.getStyle().layers.filter((l) => /^sat-\d{4}$/.test(l.id) && m.getLayoutProperty(l.id, 'visibility') !== 'none').length; })).toBe(1);
  await toggle.click();
  await expect(vis).toHaveText('40 %');
  await panel.getByRole('radio', { name: 'Карта' }).click();
  await expect.poll(() => page.evaluate(() => { const m = (globalThis as unknown as { __uhdMap: M }).__uhdMap; return m.getStyle().layers.filter((l) => /^sat-\d{4}$/.test(l.id) && m.getLayoutProperty(l.id, 'visibility') !== 'none').length; })).toBe(0);
  await expect(page.getByTestId('sat-note')).toHaveCount(0);

  expect([...hosts].filter((h) => !ALLOWED.has(h))).toEqual([]);
  expect(violations).toEqual([]);
});

// PM / QA: a strip layer button clicked while «Шари» is open must switch the layer at once (no catcher over the strip);
// the outside pointerdown closes the panel and the click still goes through. Down to 1280×640, where the panel is tallest.
for (const vp of [{ width: 1440, height: 900 }, { width: 1280, height: 720 }, { width: 1280, height: 640 }]) {
  test(`strip layer buttons work while «Шари» is open ${vp.width}×${vp.height}`, async ({ page }) => {
    await page.setViewportSize(vp);
    await page.goto('/');
    await page.locator('.map[data-ready]').waitFor();
    const strip = page.getByTestId('strip');
    for (const id of ['dndvi', 'ndvi', 'lst', 'gap']) {
      await page.getByTestId('layers-toggle').click();
      await expect(page.locator('.layers-panel')).toBeVisible();
      await strip.locator(`button[data-layer=${id}]`).click({ timeout: 10_000 }); // no force: fails if anything intercepts
      await expect(strip.locator(`button[data-layer=${id}]`)).toHaveAttribute('aria-pressed', 'true');
      await expect(page.locator('.layers-panel')).toHaveCount(0);
    }
  });
}

// item 32 (2e-map): ?lang=en — map tools and the «Layers» panel in English, no Cyrillic; Ukrainian stays the default
test('map tools and «Layers» panel in English with ?lang=en', async ({ page }) => {
  test.skip(!process.env.E2E_I18N, 'needs initLocale() in main.tsx (i18n 2b) — run with E2E_I18N=1');
  await page.goto('/?lang=en');
  await page.locator('.map[data-ready]').waitFor();
  const cyr = /[А-Яа-яЇїІіЄєҐґ]/;
  const aria = await page.locator('section.tools, section.tools [aria-label]').evaluateAll((els) => els.map((e) => e.getAttribute('aria-label') ?? ''));
  expect(aria.filter((a) => cyr.test(a))).toEqual([]);
  expect(aria).toContain('All of Ukraine');
  await page.getByTestId('layers-toggle').click();
  const panel = page.getByTestId('layers-panel');
  await expect(panel).toContainText('Visibility: Gap');
  await page.getByRole('radio', { name: 'Satellite' }).click();
  await expect(panel).toContainText(/Satellite: Esri World Imagery, archive \d{4}-\d{2}/);
  expect(cyr.test(await panel.innerText())).toBe(false);
  await expect(page.getByTestId('heat-visibility')).toHaveAttribute('aria-valuetext', /^50%: 0% — basemap only, 100% — full layer$/);
  expect(await page.getByTestId('map').getAttribute('aria-label')).toBe('Heat gap map');
});
