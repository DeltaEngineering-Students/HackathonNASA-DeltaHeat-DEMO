import { expect, test } from '@playwright/test';

// Production bundle (playwright.prod.config.ts). R8-1: «Показати ліс-еталон» needs the opened report's id in the map UI
// store; 3deba8c dropped the only writer and the dev server hid it.
test('prod build: «Шари» offers the reference forest once a report is open', async ({ page }) => {
  await page.goto('/?zone=kyiv-pozniaky');
  await expect(page.getByTestId('answer')).toBeVisible({ timeout: 30_000 });
  await page.locator('.map[data-ready]').waitFor();
  await page.getByTestId('layers-toggle').click();
  await expect(page.getByTestId('show-reference')).toBeVisible();
});

test.describe('clean storage', () => {
  test.use({ storageState: { cookies: [], origins: [] } }); // the config pre-seeds uhd-lang=uk
  test('prod build: map tools in English by default, Ukrainian with ?lang=uk', async ({ page }) => {
    test.skip(!process.env.E2E_I18N, 'needs initLocale() in main.tsx (i18n 2b) — run with E2E_I18N=1');
    // c6e5bac: English is the default (clean storage); ?lang=uk switches to Ukrainian
    await page.goto('/');
    await page.locator('.map[data-ready]').waitFor();
    await expect(page.getByTestId('fit-ukraine')).toHaveAttribute('aria-label', 'All of Ukraine');
    await page.goto('/?lang=uk');
    await page.locator('.map[data-ready]').waitFor();
    await expect(page.getByTestId('fit-ukraine')).toHaveAttribute('aria-label', 'Вся Україна');
  });
});
