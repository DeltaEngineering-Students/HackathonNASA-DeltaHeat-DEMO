import { expect, test } from '@playwright/test';

// R-MAP-1: a city opened from the list must open on its heat map, not on country markers. Needs the heat tiles, so it
// runs against a live backend only (E2E_LIVE=1 UHD_API_TARGET=…); fixtures mode has no raster tiles.
test.skip(!process.env.E2E_LIVE, 'live backend only (heat tiles)');
test.describe.configure({ mode: 'serial' });

type M = { isMoving(): boolean; getZoom(): number; getLayer(id: string): { minzoom?: number; maxzoom?: number } | undefined };
for (const vp of [{ width: 1440, height: 900 }, { width: 1280, height: 720 }]) {
  // Одеса, Львів, Чернівці (framing grows with the city's span since the pitch polish: ~z9–10.5)
  for (const zone of ['osm:R1413934', 'lviv', 'osm:R1742393']) {
    test(`${zone} opens on heat ${vp.width}×${vp.height}`, async ({ page }) => {
      test.setTimeout(90_000);
      await page.setViewportSize(vp);
      let tiles = 0;
      page.on('response', (r) => { if (/\/tiles\/gap\/\d{4}\//.test(r.url()) && r.status() === 200) tiles++; });
      await page.goto(`/?zone=${encodeURIComponent(zone)}`);
      await expect(page.getByTestId('answer')).toBeVisible({ timeout: 60_000 });
      await page.locator('.map[data-ready]').waitFor();
      await page.waitForTimeout(500);
      await expect.poll(() => page.evaluate(() => (globalThis as unknown as { __uhdMap: M }).__uhdMap.isMoving()), { timeout: 15_000 }).toBe(false);
      const before = tiles;
      await page.waitForTimeout(300);
      await expect.poll(() => tiles, { timeout: 20_000 }).toBeGreaterThan(Math.max(0, before - 1));
      const s = await page.evaluate(() => { const m = (globalThis as unknown as { __uhdMap: M }).__uhdMap; return { z: m.getZoom(), heat: m.getLayer('heat')?.minzoom ?? 99, ov: m.getLayer('ov-city')?.maxzoom ?? 0 }; });
      expect(s.z).toBeGreaterThanOrEqual(s.heat); // the heat layer is drawn at this zoom
      expect(s.z).toBeGreaterThanOrEqual(s.ov); // and no country markers
      await expect(page.getByTestId('map-note')).not.toContainText('Маркери');
      await expect(page.getByTestId('marker-legend')).toHaveCount(0);
    });
  }
}
