import { expect, test } from '@playwright/test';
import { encodeRing } from '../src/lib/geo';

// item 15 A: the card number is the mean over all summers; one line ties it to the map's summer.
const live = !!process.env.E2E_LIVE;
const SHOTS = process.env.UHD_SHOTS_DIR;
// a rural Полтавщина polygon (the review's Рис. 4 area: 2022 is cloudy there)
const poltava = { type: 'Polygon' as const, coordinates: [[[34.42, 49.52], [34.70, 49.52], [34.70, 49.70], [34.42, 49.70], [34.42, 49.52]]] };

for (const vp of [{ width: 1440, height: 900 }, { width: 1280, height: 720 }]) {
  test.describe(`${vp.width}×${vp.height}`, () => {
    test.use({ viewport: vp, colorScheme: 'dark' });
    test.describe.configure({ timeout: 120_000 });

    test('mean label + the map summer line, follows the strip year', async ({ page }) => {
      await page.goto('/?year=2025');
      await expect(page.getByTestId('answer')).toBeVisible({ timeout: 60_000 });
      await expect(page.getByTestId('surface-note')).toContainText(/середнє за \d+ літн(?:ій сезон|і сезони|іх сезонів)/);
      await expect(page.getByTestId('card-year')).toHaveText(/^У 2025: [+−]\d+,\d\s°C$/u);
      await page.getByRole('radio', { name: /2017/ }).first().click();
      await expect(page.getByTestId('card-year')).toHaveText(/^У 2017: /);
      await expect(page.getByTestId('open-details')).toBeInViewport();
    });

    test('Полтавщина polygon: 2022 and 2025 (live)', async ({ page }) => {
      test.skip(!live, 'needs the live API (real cloudy 2022)');
      for (const year of [2022, 2025]) {
        await page.goto(`/?area=${encodeURIComponent(encodeRing(poltava))}&year=${year}`);
        await expect(page.getByTestId('answer')).toBeVisible({ timeout: 90_000 });
        const line = page.getByTestId('card-year');
        await expect(line).toHaveText(new RegExp(`^У ${year}: (?:[+−]\\d+,\\d\\s°C|немає даних)`, 'u'));
        await expect(page.getByTestId('open-details')).toBeInViewport();
        await page.waitForTimeout(2500);
        if (SHOTS) await page.screenshot({ path: `${SHOTS}/a15_dark_${vp.width}x${vp.height}_poltava_${year}.png` });
        console.log('A15', vp.width, year, await line.innerText(), '|', (await page.getByTestId('strip').innerText()).replace(/\s+/g, ' ').slice(0, 80));
      }
      // a summer left out of the analysis (Позняки 2020: one clear pass) → «немає даних (…)»
      await page.goto('/?zone=kyiv-pozniaky&year=2020');
      await expect(page.getByTestId('card-year')).toHaveText(/^У 2020: немає даних/, { timeout: 90_000 });
      await page.waitForTimeout(2500);
      if (SHOTS) await page.screenshot({ path: `${SHOTS}/a15_dark_${vp.width}x${vp.height}_pozniaky_2020.png` });
      console.log('A15', vp.width, 2020, await page.getByTestId('card-year').innerText());
    });
  });
}
