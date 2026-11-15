import { expect, test } from '@playwright/test';
import { ukState } from './lang';

// item 29: «Експорт ▾» in the card and Details; the share link reproduces the view in a fresh context.
test.use({ viewport: { width: 1440, height: 900 }, colorScheme: 'dark' });

test('export menu: options, keyboard, share link copied + toast; the link reproduces the view', async ({ page, browser, context, baseURL }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto('/?zone=kyiv-obolon&year=2022&layer=lst');
  await expect(page.getByTestId('answer')).toBeVisible({ timeout: 30_000 });
  const btn = page.getByTestId('answer').getByTestId('export-btn');
  await btn.focus();
  await page.keyboard.press('ArrowDown');
  const menu = page.getByRole('menu', { name: 'Експорт' }); // a portal at the end of <body> (was clipped inside the card)
  await expect(menu).toBeVisible();
  await expect(menu.getByRole('menuitem')).toHaveText([/^PDF — звіт для друку/, /^Excel \(\.xlsx\)/, /^CSV \(таблиця за роками\)/, /^JSON \(для розробників\)/, 'Поділитися посиланням']);
  await page.keyboard.press('Escape');
  await expect(menu).toBeHidden();
  await expect(btn).toBeFocused();
  await expect(page.getByTestId('answer')).toBeVisible(); // Esc closed the menu only, not the card
  // open Details, share from there: transient view=details is not in the link
  await page.getByTestId('open-details').click();
  await page.getByTestId('details').getByTestId('export-btn').click();
  await page.getByRole('menu', { name: 'Експорт' }).getByTestId('export-share').click();
  await expect(page.getByTestId('details').getByTestId('toast')).toHaveText('Посилання скопійовано');
  const link = await page.evaluate(() => (navigator as unknown as { clipboard: { readText(): Promise<string> } }).clipboard.readText());
  expect(link).toMatch(/\?zone=kyiv-obolon&year=2022&layer=lst&lang=uk$/); // item 32: explicit language
  expect(link).not.toContain('view=');
  // a fresh context opens the same view
  const ctx2 = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'dark', storageState: ukState(baseURL!) });
  const p2 = await ctx2.newPage();
  await p2.goto(link); // absolute, built from app state
  await expect(p2.getByTestId('answer').getByRole('heading', { level: 1 })).toHaveText('Оболонь', { timeout: 30_000 });
  await expect(p2.getByTestId('map-year')).toHaveText('Мапа: літо 2022');
  await expect(p2.getByTestId('quick-layers').locator('[aria-pressed=true]')).toHaveAttribute('data-layer', 'lst');
  await ctx2.close();
});

test('format gate: json 200 + pdf 422 → PDF stays «скоро», CSV/Excel/JSON link to the export (live API)', async ({ page }) => {
  test.skip(!process.env.E2E_LIVE, 'fixtures mode is demo: downloads are disabled there');
  await page.route('**/api/reports/*/export?format=json', (r) => r.fulfill({ status: 200, body: '' }));
  await page.route('**/api/reports/*/export?format=pdf', (r) => r.fulfill({ status: 422, body: '' }));
  await page.goto('/?zone=kyiv-pozniaky');
  await expect(page.getByTestId('answer')).toBeVisible({ timeout: 90_000 });
  await page.getByTestId('answer').getByTestId('export-btn').click();
  const menu = page.getByRole('menu', { name: 'Експорт' }); // a portal at the end of <body> (was clipped inside the card)
  await expect(menu.locator('[data-format=pdf]')).toHaveAttribute('aria-disabled', 'true');
  await expect(menu.locator('[data-format=pdf]')).not.toHaveAttribute('href', /./);
  for (const f of ['csv', 'xlsx', 'json']) await expect(menu.locator(`[data-format=${f}]`)).toHaveAttribute('href', new RegExp(`/export\\?format=${f}$`));
});
