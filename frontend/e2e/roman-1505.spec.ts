import { expect, test, type Page } from '@playwright/test';

// Роман's bug list 15.11 15:05 + his 15:42 message + Володя's card-tip report: exact p on the card, a contextual
// trend tip (this report's p and verdict, no «Див. також»), the layer-named slider, and a click on a basemap name.
const ready = async (page: Page) => {
  await expect(page.getByTestId('answer')).toBeVisible({ timeout: 30_000 });
  await page.locator('.map[data-ready]').waitFor();
};
type Feat = { sourceLayer?: string; properties: Record<string, unknown>; geometry: { type: string; coordinates: [number, number] } };
type M = {
  isMoving(): boolean; loaded(): boolean; jumpTo(o: unknown): void; areTilesLoaded(): boolean;
  queryRenderedFeatures(): Feat[]; project(ll: [number, number]): { x: number; y: number };
};
const idle = (page: Page) => expect.poll(() => page.evaluate(() => { const m = (globalThis as unknown as { __uhdMap: M }).__uhdMap; return !m.isMoving() && m.areTilesLoaded(); }), { timeout: 15_000 }).toBe(true);

test('card: exact p next to the verdict; the trend tip is about this trend (no «Див. також»)', async ({ page }) => {
  await page.goto('/');
  await ready(page);
  const p = (await page.getByTestId('card-p').innerText()).replace(/ /g, ' ');
  expect(p).toMatch(/^p (=|<) \d,\d+$/);
  const label = (await page.getByTestId('verdict-label').innerText()).trim();
  await page.locator('[data-testid=answer] [data-hint="trend"]').hover();
  const tip = page.getByTestId('tip-text');
  await expect(tip).toBeVisible();
  const text = (await tip.innerText()).replace(/ /g, ' ');
  expect(text).toContain(p);
  expect(text.toLocaleLowerCase('uk')).toContain(label.toLocaleLowerCase('uk')); // «поки несуттєво» / «суттєво»
  expect(text).toMatch(label === 'Суттєво' ? /статистично значущий/ : /статистично незначущий/);
  await expect(page.getByTestId('tip')).not.toContainText('Див. також');
  // one link: «Як ми це рахуємо →» opens Details at the trend block
  await page.getByTestId('tip-how').click();
  await expect(page.getByTestId('details')).toBeVisible();
});

test('«Шари»: the visibility slider is named after the active layer', async ({ page }) => {
  await page.goto('/');
  await ready(page);
  await page.getByTestId('layers-toggle').click();
  await expect(page.getByTestId('heat-visibility-label')).toContainText('Видимість шару «Розрив»');
  await page.keyboard.press('Escape');
  await page.locator('[data-testid=quick-layers] [data-layer=ndvi]').click();
  await page.getByTestId('layers-toggle').click();
  await expect(page.getByTestId('heat-visibility-label')).toContainText('Видимість шару «Зелень»');
});

test('a click on a basemap district name opens it like the search does', async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto('/');
  await ready(page);
  await page.evaluate(() => (globalThis as unknown as { __uhdMap: M }).__uhdMap.jumpTo({ center: [30.498, 50.507], zoom: 12.5 }));
  await idle(page);
  const pt = await page.evaluate(() => {
    const m = (globalThis as unknown as { __uhdMap: M }).__uhdMap;
    const f = m.queryRenderedFeatures().find((x) => x.sourceLayer === 'place' && (x.properties['name:uk'] ?? x.properties.name) === 'Оболонь' && x.geometry.type === 'Point');
    return f ? m.project(f.geometry.coordinates) : null;
  });
  test.skip(!pt, 'basemap tiles (OpenFreeMap) not reachable — no label to click');
  // hover gives the pointer cursor, the click selects
  await page.mouse.move(pt!.x, pt!.y);
  await expect.poll(() => page.evaluate(() => (document.querySelector('.maplibregl-canvas') as HTMLElement).style.cursor)).toBe('pointer');
  await page.mouse.click(pt!.x, pt!.y);
  await expect(page.locator('#ans-title')).toHaveText('Оболонь', { timeout: 15_000 });
  await expect(page).toHaveURL(/zone=kyiv-obolon/);
});
