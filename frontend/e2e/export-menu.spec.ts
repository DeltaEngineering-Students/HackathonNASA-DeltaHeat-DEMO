/// <reference lib="dom" />
import { expect, test, type Locator, type Page } from '@playwright/test';

// The «Експорт ▾» menu was clipped by the card's scroll container (user report). It is a fixed popover in a portal now:
// every item must be fully on screen and on top (elementFromPoint at its right edge hits the item itself).
const SHOTS = process.env.UHD_SHOTS_DIR;

async function assertItemsVisible(page: Page) {
  const menu = page.getByTestId('export-menu');
  await expect(menu).toBeVisible();
  const items = menu.locator('[role=menuitem]');
  const n = await items.count();
  expect(n).toBe(5);
  for (let i = 0; i < n; i++) {
    const it: Locator = items.nth(i);
    const r = await it.evaluate((el) => {
      const b = el.getBoundingClientRect();
      const hit = document.elementFromPoint(b.right - 4, (b.top + b.bottom) / 2);
      return { left: b.left, right: b.right, top: b.top, bottom: b.bottom, vw: innerWidth, vh: innerHeight, onTop: !!hit && (hit === el || el.contains(hit)), text: el.textContent };
    });
    expect(r.left, r.text!).toBeGreaterThanOrEqual(0);
    expect(r.top, r.text!).toBeGreaterThanOrEqual(0);
    expect(r.right, r.text!).toBeLessThanOrEqual(r.vw);
    expect(r.bottom, r.text!).toBeLessThanOrEqual(r.vh);
    expect(r.onTop, `${r.text} is on top at its right edge`).toBe(true);
  }
  // labels are not cut: the item is at least as wide as its text
  const cut = await items.evaluateAll((els) => els.filter((e) => e.scrollWidth > e.clientWidth + 1).map((e) => e.textContent));
  expect(cut).toEqual([]);
}

for (const vp of [{ width: 1440, height: 900 }, { width: 1280, height: 720 }]) {
  for (const scheme of ['dark'] as const) {
    test.describe(`${vp.width}×${vp.height} ${scheme}`, () => {
      test.use({ viewport: vp, colorScheme: scheme });
      test.describe.configure({ timeout: 120_000 });
      test('card: normal, scrolled, collapsed → expanded; keyboard and Esc still work', async ({ page }) => {
        await page.goto('/?zone=kyiv-pozniaky');
        const card = page.getByTestId('answer');
        await expect(card.getByTestId('linechart')).toBeVisible({ timeout: 60_000 });
        const btn = card.getByTestId('export-btn');

        await btn.click();
        await assertItemsVisible(page);
        if (SHOTS) await page.screenshot({ path: `${SHOTS}/export-card-${vp.width}-${scheme}.png` });
        await page.keyboard.press('Escape');
        await expect(page.getByTestId('export-menu')).toBeHidden();
        await expect(btn).toBeFocused();
        await expect(card).toBeVisible(); // Esc closed the menu only

        // scrolled card body
        await page.locator('.answer-body').evaluate((e) => { e.scrollTop = e.scrollHeight; });
        await btn.press('ArrowDown');
        await expect(page.getByTestId('export-menu').locator('[role=menuitem]:focus')).toHaveCount(1); // first enabled item
        await assertItemsVisible(page);
        await page.keyboard.press('Escape');

        // collapsed then expanded
        await page.getByTestId('card-collapse').click();
        await page.getByTestId('card-expand').click();
        await expect(card.getByTestId('linechart')).toBeVisible();
        await btn.click();
        await assertItemsVisible(page);
        await page.mouse.click(vp.width - 300, 300); // outside closes
        await expect(page.getByTestId('export-menu')).toBeHidden();
      });

      test('Details §7: the menu is fully visible', async ({ page }) => {
        await page.goto('/?zone=kyiv-pozniaky');
        await expect(page.getByTestId('answer')).toBeVisible({ timeout: 60_000 });
        await page.getByTestId('open-details').click();
        const btn = page.getByTestId('details').getByTestId('export-btn');
        await btn.scrollIntoViewIfNeeded();
        await btn.click();
        await assertItemsVisible(page);
        if (SHOTS) await page.screenshot({ path: `${SHOTS}/export-details-${vp.width}-${scheme}.png` });
        await page.keyboard.press('Escape');
        await expect(page.getByTestId('details')).toBeVisible(); // Esc closed the menu, not Details
      });
    });
  }
}
