import { expect, test, type Page } from '@playwright/test';

// MAP-TASKS 12: collapsible card — manual collapse/expand, Esc, auto-minimise after a pan away, the search flow.
const SHOTS = process.env.UHD_SHOTS_DIR;
const ready = async (page: Page) => {
  await expect(page.getByTestId('answer')).toBeVisible({ timeout: 30_000 });
  await page.locator('.map[data-ready]').waitFor();
};
type M = { getCenter(): { lng: number; lat: number }; isMoving(): boolean };
const center = (page: Page) => page.evaluate(() => { const c = (globalThis as unknown as { __uhdMap: M }).__uhdMap.getCenter(); return [c.lng, c.lat]; });
const idle = (page: Page) => expect.poll(() => page.evaluate(() => (globalThis as unknown as { __uhdMap: M }).__uhdMap.isMoving()), { timeout: 10_000 }).toBe(false);
const drag = async (page: Page, dx: number) => {
  const { width, height } = page.viewportSize()!;
  const x = width - 300, y = height / 2 - 60;
  await page.mouse.move(x, y);
  await page.mouse.down();
  for (let i = 1; i <= 8; i++) await page.mouse.move(x + (dx * i) / 8, y); // few events: the map renders each one (slow under a loaded parallel run)
  await page.mouse.up();
};

for (const vp of [{ width: 1440, height: 900 }, { width: 1280, height: 720 }]) {
  test.describe(`${vp.width}×${vp.height}`, () => {
    test.use({ viewport: vp, colorScheme: 'dark' });
    test.describe.configure({ timeout: 90_000 });

    test('manual collapse / expand: pill with name, gap and «Розгорнути», no layout jump, remembered for the session', async ({ page }) => {
      await page.goto('/');
      await ready(page);
      await idle(page);
      if (SHOTS) await page.screenshot({ path: `${SHOTS}/dark_${vp.width}x${vp.height}_expanded.png` });
      const map = page.getByTestId('map');
      const box0 = await map.boundingBox();
      const btn = page.getByTestId('card-collapse');
      await expect(btn).toHaveAttribute('aria-expanded', 'true');
      await btn.click();
      const pill = page.getByTestId('card-pill');
      await expect(pill).toBeVisible();
      await expect(page.getByTestId('answer')).toHaveCount(0);
      await expect(pill).toContainText('Позняки');
      await expect(page.getByTestId('pill-gap')).toHaveText(/^[+−]?\d+,\d°$/);
      const exp = page.getByTestId('card-expand');
      await expect(exp).toHaveText(/Розгорнути/);
      await expect(exp).toHaveAttribute('aria-expanded', 'false');
      await expect(exp).toBeFocused();
      await expect(map).toHaveAttribute('data-inset', '32');
      expect(await map.boundingBox()).toEqual(box0); // the map element never resizes
      // the pill stays clear of the strip and the top bar
      const p = (await pill.boundingBox())!;
      expect(p.y).toBeGreaterThanOrEqual(80);
      expect(p.x + p.width).toBeLessThan(vp.width / 2);
      await idle(page);
      if (SHOTS) await page.screenshot({ path: `${SHOTS}/dark_${vp.width}x${vp.height}_collapsed.png` });
      // remembered for the session
      await page.reload();
      await expect(page.getByTestId('card-pill')).toBeVisible();
      await page.getByTestId('card-expand').click();
      await expect(page.getByTestId('answer')).toBeVisible();
      await expect(page.getByTestId('card-collapse')).toBeFocused();
      await expect(map).toHaveAttribute('data-inset', '480');
      await page.reload();
      await ready(page);
    });

    test('Esc toggles the card', async ({ page }) => {
      await page.goto('/');
      await ready(page);
      await page.locator('body').click({ position: { x: vp.width - 200, y: 120 } }); // focus out of the search box
      await page.keyboard.press('Escape');
      await expect(page.getByTestId('card-pill')).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(page.getByTestId('answer')).toBeVisible();
    });

    test('auto-minimise after panning away; no auto-expand and no fly-back', async ({ page }) => {
      await page.goto('/');
      await ready(page);
      await idle(page);
      // a small pan that keeps the zone in view → stays expanded
      await drag(page, -120);
      await page.waitForTimeout(1500);
      await expect(page.getByTestId('answer')).toBeVisible();
      // pan far away → minimised after ~1 s
      await drag(page, -1.6 * vp.width);
      await drag(page, -1.6 * vp.width);
      await expect(page.getByTestId('card-pill')).toBeVisible({ timeout: 4000 });
      await page.waitForTimeout(800);
      const away = await center(page);
      expect(away[0]).toBeGreaterThan(31); // the camera stayed where the user put it (no fly back to Позняки)
      await page.waitForTimeout(1000);
      expect(await center(page)).toEqual(away); // and does not move afterwards
      if (SHOTS) await page.screenshot({ path: `${SHOTS}/dark_${vp.width}x${vp.height}_auto_minimised.png` });
      // pan back → stays collapsed
      await drag(page, 1.6 * vp.width);
      await drag(page, 1.6 * vp.width);
      await page.waitForTimeout(1500);
      await expect(page.getByTestId('card-pill')).toBeVisible();
      // expanded by hand while away → not re-minimised at once
      await drag(page, -1.6 * vp.width);
      await drag(page, -1.6 * vp.width);
      await page.getByTestId('card-expand').click();
      await page.waitForTimeout(2000);
      await expect(page.getByTestId('answer')).toBeVisible();
    });

    test('no auto-minimise while Details are open', async ({ page }) => {
      await page.goto('/');
      await ready(page);
      await page.getByTestId('open-details').click();
      await expect(page.getByTestId('close-details')).toBeVisible();
      await page.locator('.map[data-ready]').waitFor();
      await idle(page);
      await drag(page, -1.6 * vp.width);
      await drag(page, -1.6 * vp.width);
      await page.waitForTimeout(2000);
      await page.getByTestId('close-details').click();
      await expect(page.getByTestId('answer')).toBeVisible();
    });

    test('search focus minimises the card; a new result opens expanded', async ({ page }) => {
      await page.goto('/');
      await ready(page);
      const box = page.getByRole('combobox');
      await box.click();
      await expect(page.getByTestId('card-pill')).toBeVisible();
      await expect(page.getByTestId('answer')).toHaveCount(0);
      // Esc out of the search without a pick restores the card
      await page.keyboard.press('Escape');
      await expect(page.getByTestId('answer')).toBeVisible();
      await box.click();
      await expect(page.getByTestId('card-pill')).toBeVisible();
      await box.fill('Обол');
      await page.getByRole('option', { name: /^Оболонь/ }).first().click({ timeout: 20_000 });
      await expect(page.getByTestId('answer').getByRole('heading', { level: 1 })).toHaveText('Оболонь');
    });
  });
}
