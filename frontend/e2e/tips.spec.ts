import { expect, test } from '@playwright/test';

// item 22: glossary tips in the card and Details open by hover and by keyboard; Esc closes the tip only.
const SHOTS = process.env.UHD_SHOTS_DIR;

for (const vp of [{ width: 1440, height: 900 }, { width: 1280, height: 720 }]) {
  test.describe(`${vp.width}×${vp.height}`, () => {
    test.use({ viewport: vp, colorScheme: 'dark' });
    test.describe.configure({ timeout: 120_000 });

    test('card: hover opens a tip, keyboard focus opens it, Esc closes only the tip', async ({ page }) => {
      await page.goto('/?year=2025');
      const card = page.getByTestId('answer');
      await expect(card).toBeVisible({ timeout: 60_000 });

      // hover the ⓘ next to the big number
      const gapHint = card.locator('[data-hint="gap"]');
      await gapHint.hover();
      const tip = page.getByTestId('tip');
      await expect(tip).toHaveCount(1);
      await expect(tip).toHaveAttribute('role', 'tooltip');
      await expect(tip.locator('.tip-term')).not.toBeEmpty();
      await expect(tip).toBeInViewport({ ratio: 1 });
      await page.waitForTimeout(300); // fade-in
      if (SHOTS && vp.width === 1440) await page.screenshot({ path: `${SHOTS}/tips-card-hover-1440.png` });
      await page.mouse.move(vp.width - 10, vp.height / 2);
      await expect(tip).toHaveCount(0);

      // keyboard: focus a Term, the tip opens; Esc closes it and the card stays expanded
      const term = card.locator('[data-term="referenceForest"]').first();
      await term.focus();
      await expect(tip).toHaveCount(1);
      await expect(term).toHaveAttribute('aria-expanded', 'true');
      await page.keyboard.press('Escape');
      await expect(tip).toHaveCount(0);
      await expect(page.getByTestId('card-pill')).toHaveCount(0);
      await expect(card).toBeVisible();

      // one tip at a time
      await card.locator('[data-hint="trend"]').click();
      await card.locator('[data-term="dataCredit"]').click();
      await expect(tip).toHaveCount(1);
      await expect(tip.locator('.tip-term')).toHaveText(/Дані|Landsat|джерел/i);
    });

    test('Details: section ⓘ, §5 terms and caveat hints; Esc keeps Details open', async ({ page }) => {
      await page.goto('/?year=2025');
      await expect(page.getByTestId('answer')).toBeVisible({ timeout: 60_000 });
      await page.getByTestId('open-details').click();
      const numbers = page.getByTestId('numbers');
      await expect(numbers).toBeVisible();
      for (const k of ['theilSen', 'ci', 'pValue', 'scenesCount']) await expect(numbers.locator(`[data-term="${k}"]`)).toHaveCount(1);
      await expect(page.locator('.sec-h [data-hint="numbersToCheck"]')).toHaveCount(1);
      await expect(page.locator('.caveats [data-hint]').first()).toBeVisible();
      // item 20 D: the two explanation lines, each with its tip
      await expect(page.getByTestId('green-still-warm')).toContainText('Навіть ліс чи парк у місті');
      await expect(page.getByTestId('green-still-warm').locator('[data-hint="greenStillWarm"]')).toHaveCount(1);
      await expect(page.getByTestId('ndvi-vs-lst')).toContainText('тому зелень буває там, де температури немає');

      const p = numbers.locator('[data-term="pValue"]');
      await p.focus();
      const tip = page.getByTestId('tip');
      await expect(tip).toHaveCount(1);
      await page.waitForTimeout(300);
      if (SHOTS && vp.width === 1440) await page.screenshot({ path: `${SHOTS}/tips-details-1440.png` });
      await page.keyboard.press('Escape');
      await expect(tip).toHaveCount(0);
      await expect(numbers).toBeVisible(); // Details still open
    });
  });
}
