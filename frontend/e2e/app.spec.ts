import { expect, test, type Page } from '@playwright/test';
import { ukState } from './lang';

// Exact numbers are checked against fixtures; against a live backend (E2E_LIVE=1) only their format.
const live = !!process.env.E2E_LIVE;
const num = (fixture: string) => (live ? /^[+−]\d+,\d°$/ : fixture);

const ready = async (page: Page) => {
  await expect(page.getByTestId('answer')).toBeVisible();
  await page.locator('.map[data-ready]').waitFor();
};

test('initial load shows the Pozniaky answer', async ({ page }) => {
  await page.goto('/');
  await ready(page);
  const card = page.getByTestId('answer');
  await expect(card.getByRole('heading', { level: 1 })).toHaveText(/^Позняки/);
  await expect(card).toContainText('Приклад · Київ');
  await expect(page.getByTestId('gap-mean')).toHaveText(num('+9,0°'));
  await expect(card).toContainText(live ? /середнє за \d+ літн/ : 'середнє за 13 літніх сезонів');
  await expect(page.getByTestId('verdict-label')).toHaveText('Поки несуттєво');
  await expect(page.getByTestId('linechart')).toBeVisible();
  await expect(page.getByTestId('map-year')).toHaveText('Мапа: літо 2025');
  await expect(page).toHaveURL(/zone=kyiv-pozniaky/);
});

test('search → select Оболонь → card updates', async ({ page }) => {
  await page.goto('/');
  await ready(page);
  const box = page.getByRole('combobox');
  await box.click();
  await expect(page.getByRole('listbox')).toContainText('Приклади');
  await box.fill('Обол');
  await expect(page.getByRole('listbox')).toContainText('Райони й приклади', { timeout: 20_000 }); // query results (geocoder can be slow)
  await page.getByRole('option', { name: /^Оболонь/ }).first().click();
  await expect(page.getByTestId('answer').getByRole('heading', { level: 1 })).toHaveText('Оболонь');
  await expect(page.getByTestId('gap-mean')).toHaveText(num('+7,9°'));
  await expect(page).toHaveURL(/zone=kyiv-obolon/);
});

test('search with keyboard only (examples list)', async ({ page }) => {
  await page.goto('/');
  await ready(page);
  await page.getByRole('combobox').focus();
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('ArrowDown');
  const name = (await page.getByRole('option', { selected: true }).locator('.dd-name').textContent())!;
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('answer').getByRole('heading', { level: 1 })).toHaveText(name);
});

test('open and close details', async ({ page }) => {
  await page.goto('/');
  await ready(page);
  await page.getByTestId('open-details').click();
  const d = page.getByTestId('details');
  await expect(d.getByRole('heading', { level: 1 })).toHaveText(/^Деталі аналізу · Позняки/);
  for (const h of ['Наскільки поверхня гарячіша за ліс — кожного літа', 'Чи росте розрив? Зміна на кожні 10 років', 'Цифри для перевірки', 'Як ми рахуємо', 'Сценарії клімату (CMIP6)'])
    await expect(d.getByRole('heading', { name: h })).toBeVisible();
  await expect(page.getByTestId('numbers')).toContainText(live ? 'p (тест Манна–Кендалла)' : '0,59 · статистично незначущо');
  await expect(page.getByTestId('climate')).toContainText('приземна температура повітря (2 м), не поверхні');
  if (!live) await expect(d).toContainText('шов між смугами');
  await expect(d.getByRole('listitem').filter({ hasText: 'Оболонь' })).toContainText(live ? '°' : '+7,9°');
  await expect(page).toHaveURL(/view=details/);
  await page.getByTestId('close-details').click();
  await expect(page.getByTestId('answer')).toBeVisible();
  await expect(page).not.toHaveURL(/view=details/);
});

test('year change via the strip updates map year and URL', async ({ page }) => {
  await page.goto('/');
  await ready(page);
  await page.getByRole('radio', { name: /^2018/ }).click();
  await expect(page.getByTestId('map-year')).toHaveText('Мапа: літо 2018');
  await expect(page).toHaveURL(/year=2018/);
  await page.keyboard.press('ArrowLeft');
  await expect(page.getByTestId('map-year')).toHaveText('Мапа: літо 2017');
});

test('shared link restores zone, year and details', async ({ page }) => {
  await page.goto('/?zone=kyiv-teremky&year=2016&view=details');
  await expect(page.getByTestId('details').getByRole('heading', { level: 1 })).toHaveText('Деталі аналізу · Теремки');
  await expect(page.getByTestId('map-year')).toHaveText('Мапа: літо 2016');
});

test('draw an area: too small is rejected, a proper polygon is analysed', async ({ page }) => {
  await page.goto('/');
  await ready(page);
  const map = page.getByTestId('map');
  // tiny triangle → clear error
  await page.getByTestId('draw-polygon').click();
  await expect(page.getByTestId('draw-hint')).toBeVisible();
  await map.click({ position: { x: 900, y: 450 } });
  await map.click({ position: { x: 910, y: 450 } });
  await map.dblclick({ position: { x: 905, y: 460 } });
  await expect(page.getByTestId('draw-error')).toContainText('замала');
  // a big polygon (still in draw mode)
  await map.click({ position: { x: 760, y: 300 } });
  await map.click({ position: { x: 1100, y: 300 } });
  await map.click({ position: { x: 1100, y: 600 } });
  await map.dblclick({ position: { x: 760, y: 600 } });
  await expect(page.getByTestId('answer').getByRole('heading', { level: 1 })).toHaveText('Ваша ділянка');
  await expect(page.getByTestId('answer')).toContainText('км²');
  await expect(page).toHaveURL(/area=/);
});

test('draw a circle', async ({ page }) => {
  await page.goto('/');
  await ready(page);
  await page.getByTestId('draw-circle').click();
  const map = page.getByTestId('map');
  const box = (await map.boundingBox())!;
  await page.mouse.move(box.x + 900, box.y + 450);
  await page.mouse.down();
  await page.mouse.move(box.x + 1000, box.y + 450, { steps: 5 });
  await page.mouse.up();
  await expect(page.getByTestId('answer').getByRole('heading', { level: 1 })).toHaveText('Ваша ділянка');
});

test('dark only: a light system and a stored light choice both end up dark; no theme toggle', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' });
  await page.addInitScript(() => { try { localStorage.setItem('uhd-theme', 'light'); } catch { /* */ } });
  const tiles: string[] = [];
  page.on('request', (r) => { if (r.url().includes('/tiles/')) tiles.push(r.url()); });
  await page.goto('/');
  await ready(page);
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  expect(tiles.every((u) => u.includes('theme=dark'))).toBe(true);
  await expect(page.getByTestId('theme-toggle')).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem('uhd-theme'))).toBeNull();
});

test('boot paints dark before the bundle runs (no light flash)', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' });
  await page.route('**/src/main.tsx', async (route) => { await new Promise((r) => setTimeout(r, 800)); await route.continue(); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
});

test('agent 503 shows the friendly offline state', async ({ page }) => {
  await page.goto('/');
  await ready(page);
  await page.getByTestId('ask').click();
  const chat = page.getByTestId('chat');
  await expect(chat).toBeVisible();
  await chat.getByRole('textbox').fill('Чому 2020 рік вибивається?');
  await chat.getByRole('button', { name: 'Надіслати' }).click();
  await expect(page.getByTestId('agent-offline')).toContainText('Аналітик ще не підключений');
  await expect(page.getByTestId('agent-offline')).toContainText('get_weather');
  await page.keyboard.press('Escape');
  await expect(chat).toBeHidden();
  await expect(page.getByTestId('ask')).toBeFocused();
});

test('unknown zone shows an error state with retry', async ({ page }) => {
  await page.goto('/?zone=no-such-zone');
  const card = page.getByTestId('answer-error');
  await expect(card).toContainText('Не знайшли межі');
  await expect(card.getByRole('button', { name: 'Спробувати ще раз' })).toBeVisible();
});

test('Back/Forward move between zones and details inside the app (QA-09)', async ({ page }) => {
  await page.goto('/');
  await ready(page);
  const h1 = page.getByTestId('answer').getByRole('heading', { level: 1 });
  const pick = async (q: string, name: RegExp) => {
    const box = page.getByRole('combobox');
    await box.click();
    await box.fill(q);
    await page.getByRole('option', { name }).first().click();
  };
  await pick('Обол', /^Оболонь/);
  await expect(h1).toHaveText('Оболонь');
  await pick('Тере', /^Теремки/);
  await expect(h1).toHaveText('Теремки');
  await page.getByTestId('open-details').click();
  await expect(page).toHaveURL(/view=details/);
  await page.goBack();
  await expect(h1).toHaveText('Теремки');
  await expect(page).not.toHaveURL(/view=details/);
  await page.goBack();
  await expect(h1).toHaveText('Оболонь');
  await expect(page).toHaveURL(/zone=kyiv-obolon/);
  await page.goBack();
  await expect(h1).toHaveText(/^Позняки/);
  await page.goForward();
  await expect(h1).toHaveText('Оболонь');
});

test('keyboard: skip link reaches the search first; Esc closes details (QA-20)', async ({ page }) => {
  await page.goto('/');
  await ready(page);
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'Перейти до пошуку' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('combobox')).toBeFocused();
  await page.keyboard.press('Escape');
  await page.getByTestId('open-details').click();
  await expect(page.getByTestId('details')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('details')).toBeHidden();
  await expect(page.getByTestId('open-details')).toBeFocused();
});

test('first screen says surface temperature; legend has °C ticks (QA-10, QA-12)', async ({ page }) => {
  await page.goto('/');
  await ready(page);
  await expect(page.getByTestId('surface-note')).toHaveText(/поверхн/);
  await expect(page.getByTestId('legend')).toContainText('°C');
  await expect(page.getByTestId('legend')).toContainText('0');
});

for (const [w, h] of [[1280, 720], [1366, 768], [1280, 800]] as const)
  test(`«Деталі аналізу» is visible without scrolling at ${w}×${h} (UX-07)`, async ({ browser, baseURL }) => {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, storageState: ukState(baseURL!) });
    const page = await ctx.newPage();
    for (const zone of ['kyiv-pozniaky', 'kyiv-hatne']) {
      await page.goto(`/?zone=${zone}`);
      await expect(page.getByTestId('answer')).toBeVisible({ timeout: 30_000 });
      const b = (await page.getByTestId('open-details').boundingBox())!;
      expect(b.y + b.height, `${zone}: button inside the viewport`).toBeLessThanOrEqual(h);
      await expect(page.getByTestId('open-details')).toBeInViewport();
      const t = (await page.getByTestId('answer').getByRole('heading', { level: 1 }).boundingBox())!;
      expect(t.height, 'title at most 2 lines').toBeLessThan(100);
    }
    await ctx.close();
  });

test('main screen: quick layer switch and the selected year value (UX-17)', async ({ page }) => {
  await page.goto('/');
  await ready(page);
  const g = page.getByTestId('quick-layers');
  await expect(g.getByRole('button')).toHaveCount(4);
  await g.getByRole('button', { name: 'Температура' }).click();
  await expect(page).toHaveURL(/layer=lst/);
  await expect(page.getByTestId('year-value')).toContainText('°C на ділянці');
});

test('not-significant card: magnitude lead, chart before the factors, outlook, fade above the footer (R3-1)', async ({ browser, baseURL }) => {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 }, storageState: ukState(baseURL!) });
  const page = await ctx.newPage();
  await page.goto('/?zone=kyiv-pozniaky');
  const card = page.getByTestId('answer');
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('verdict')).toContainText(/Поверхня забудови влітку вдень на \+?9,0\s°C гарячіша/u);
  await expect(card).toContainText(/помітної зміни не видно \(дані \d+ літн(?:ього сезону|іх сезонів)\)/);
  await expect(page.getByTestId('factors')).toContainText('Що гріє · що охолоджує');
  await expect(page.getByTestId('climate-line')).toContainText(/Прогноз(?: клімату)?:.*(Це температура повітря, не поверхні|Повітря, не поверхня)\./u);
  // the chart comes before the extra blocks
  const chartY = (await page.getByTestId('linechart').boundingBox())!.y;
  const factorsY = (await page.getByTestId('factors').boundingBox())!.y;
  expect(chartY).toBeLessThan(factorsY);
  // content continues under the pinned footer → the card says so, and the CTA stays on screen
  await expect(card).toHaveClass(/\bmore\b/);
  await expect(page.getByTestId('open-details')).toBeInViewport();
  await card.locator('.answer-body').evaluate((e) => { e.scrollTop = e.scrollHeight; });
  await expect(card).not.toHaveClass(/\bmore\b/);
  await ctx.close();
});

test('dragging the zone off-screen fades the wash and mask smoothly — no flash (board item 10)', async ({ page }) => {
  test.setTimeout(90_000); // ~10 s alone; mouse-drag steps get slow under a full parallel run
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  await page.locator('.map[data-ready]').waitFor();
  await page.waitForTimeout(1500);
  // the wash opacity (CSS) drives most of the map luma; the GL mask is the rest
  const k = () => page.locator('.spot').evaluate((el) => Number((el as unknown as { style: { opacity: string } }).style.opacity || '1'));
  const ks: number[] = [await k()];
  await page.mouse.move(700, 450);
  await page.mouse.down();
  for (let i = 1, x = 700; i <= 30; i++) {
    x += 40;
    await page.mouse.move(x, 450, { steps: 2 });
    await page.waitForTimeout(60);
    ks.push(await k());
  }
  await page.mouse.up();
  for (let i = 1; i < ks.length; i++) {
    expect(ks[i]!).toBeLessThanOrEqual(ks[i - 1]! + 1e-6); // monotonic while the zone moves away
    expect(ks[i - 1]! - ks[i]!).toBeLessThanOrEqual(0.05); // no hard switch (was 1 → 0 in one step)
  }
  const full = 1; // full wash (dark only)
  expect(ks[0]).toBeCloseTo(full, 3);
  expect(ks[ks.length - 1]!).toBeLessThan(full); // it did fade
});

test('one layer list: all 4 layers from the strip and from Details, active state, tiles, legend, bars, hotspots (item 6)', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  const tiles: string[] = [];
  page.on('request', (r) => { if (r.url().includes('/tiles/')) tiles.push(r.url()); });
  await page.goto('/');
  await ready(page);
  const want: Record<string, { short: string; full: RegExp; legend: RegExp; bars: RegExp; hot: boolean }> = {
    gap: { short: 'Розрив', full: /^Розрив з лісом$/, legend: /прохолодніше.*гарячіше/, bars: /^розрив з лісом за роками$/, hot: true },
    lst: { short: 'Температура', full: /^Температура поверхні$/, legend: /прохолодніше.*гарячіше/, bars: /^температура поверхні ділянки за роками$/, hot: true },
    ndvi: { short: 'Зелень', full: /^Зелень \(NDVI\)$/, legend: /мало.*багато/, bars: /^зелень ділянки \(NDVI\) за роками$/, hot: false },
    dndvi: { short: 'Зміна зелені', full: /^Зміна зелені$/, legend: /поменшало.*побільшало/, bars: /^зелень ділянки \(NDVI\) за роками · шар — зміна від 2013$/, hot: false },
  };
  const strip = page.getByTestId('quick-layers');
  await expect(strip.getByRole('button')).toHaveText(Object.values(want).map((w) => w.short));
  const check = async (id: string, inDetails = false) => {
    const w = want[id]!;
    // with Details open the strip is compact (no switch): Details §7 shows the active layer instead
    if (!inDetails) {
      await expect(strip.locator(`[data-layer=${id}]`)).toHaveAttribute('aria-pressed', 'true');
      await expect(strip.locator('[aria-pressed=true]')).toHaveCount(1);
    }
    await expect(page.getByTestId('legend')).toHaveAttribute('aria-label', w.legend);
    // hotspot dots (map layer) and their legend only on Розрив / Температура (the fixtures have no hotspots: legend absent)
    if (!w.hot) await expect(page.getByTestId('hot-legend')).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => (globalThis as unknown as { __uhdMap?: { getLayer(id: string): unknown; getLayoutProperty(id: string, p: string): unknown } }).__uhdMap?.getLayoutProperty('hot-dot', 'visibility'))).toBe(w.hot ? 'visible' : 'none');
    if (tiles.length) await expect.poll(() => tiles[tiles.length - 1]).toContain(`/tiles/${id}/`);
  };
  // from the strip
  for (const id of Object.keys(want)) {
    await strip.locator(`[data-layer=${id}]`).click();
    await check(id);
    await expect(page.getByTestId('yearbars-cap')).toHaveText(want[id]!.bars);
  }
  // from Details §7: same list, same names, and the strip follows
  await page.getByTestId('open-details').click();
  const det = page.getByRole('group', { name: 'Шар мапи' }).first();
  await expect(det.getByRole('button')).toHaveCount(4);
  for (const id of ['dndvi', 'ndvi', 'lst', 'gap']) {
    const b = det.locator(`[data-layer=${id}]`);
    await expect(b).toHaveText(want[id]!.full);
    await b.click();
    await expect(b).toHaveAttribute('aria-pressed', 'true');
    await expect(det.locator('[aria-pressed=true]')).toHaveCount(1);
    await check(id, true);
  }
  // back on the card the strip shows the layer picked in Details
  await page.getByTestId('close-details').click();
  await check('gap');
});

for (const [vw, vh] of [[1440, 900], [1280, 720]] as const) {
  test(`every border point can be brought to the centre of the free map area at z7 and z11, ${vw}×${vh} (task 1b)`, async ({ page }) => {
    await page.setViewportSize({ width: vw, height: vh });
    await page.goto('/');
    await ready(page);
    await page.waitForTimeout(500);
    const POINTS: [string, number, number][] = [
      ['Ужгород', 22.29, 48.62], ['Закарпаття W', 22.15, 48.4], ['Ізмаїл', 29.7, 45.3],
      ['Крим S', 33.9, 44.39], ['Луганськ E', 40.2, 49.6], ['Чернігів N', 32.0, 52.35],
    ];
    for (const z of [7, 11]) {
      for (const [name, lon, lat] of POINTS) {
        const off = await page.evaluate(([lon, lat, z]) => {
          type M = { getContainer(): { getBoundingClientRect(): DOMRectLike; clientWidth: number; clientHeight: number; dataset: Record<string, string | undefined> };
            jumpTo(o: unknown): void; project(p: [number, number]): { x: number; y: number }; fire?: unknown };
          type DOMRectLike = { left: number; right: number; top: number; bottom: number; width: number; height: number };
          const g = globalThis as unknown as { __uhdMap: M; document: { querySelector(s: string): { getBoundingClientRect(): DOMRectLike } | null } };
          const m = g.__uhdMap;
          const c = m.getContainer();
          const box = c.getBoundingClientRect();
          const head = g.document.querySelector('header.top')?.getBoundingClientRect();
          const strip = g.document.querySelector('[data-testid=strip]')?.getBoundingClientRect();
          const tools = g.document.querySelector('section.tools')?.getBoundingClientRect();
          const L = Number(c.dataset.inset ?? 0), T = head ? head.bottom - box.top : 0;
          const B = strip ? box.bottom - strip.top : 0, R = tools ? box.right - tools.left : 0;
          const cx = L + (c.clientWidth - L - R) / 2, cy = T + (c.clientHeight - T - B) / 2;
          // zoom first (the panning box follows the zoom), then put the point at the free-area centre
          m.jumpTo({ zoom: z, center: [lon, lat], padding: { left: 0, right: 0, top: 0, bottom: 0 } });
          m.jumpTo({ center: [lon, lat], zoom: z, padding: { left: Math.max(0, 2 * cx - c.clientWidth), right: Math.max(0, c.clientWidth - 2 * cx), top: Math.max(0, 2 * cy - c.clientHeight), bottom: Math.max(0, c.clientHeight - 2 * cy) } });
          const p = m.project([lon, lat]);
          return Math.hypot(p.x - cx, p.y - cy);
        }, [lon, lat, z] as const);
        expect(off, `${name} at z${z}`).toBeLessThanOrEqual(5);
      }
    }
  });
}

// MAP-TASKS 16 B: the selected year label sits under the selected bar (not centred under the strip)
for (const vp of [{ width: 1440, height: 900 }, { width: 1280, height: 720 }]) {
  test(`year label under the selected bar ${vp.width}×${vp.height}`, async ({ page }) => {
    await page.setViewportSize(vp);
    await page.goto('/');
    await ready(page);
    const bars = page.locator('.yearbar');
    const n = await bars.count();
    for (const i of [0, 2, n - 1]) {
      await bars.nth(i).click();
      const bar = (await bars.nth(i).boundingBox())!;
      const year = (await bars.nth(i).getAttribute('aria-label'))!.slice(0, 4);
      const lab = page.getByTestId('yearbars-axis').locator('.cur');
      await expect(lab).toHaveText(year);
      const b = (await lab.boundingBox())!;
      expect(Math.abs(b.x + b.width / 2 - (bar.x + bar.width / 2))).toBeLessThan(2);
      // labels never overlap
      const boxes = await page.getByTestId('yearbars-axis').locator('span').evaluateAll((els) => els.map((e) => { const r = e.getBoundingClientRect(); return [r.left, r.right]; }));
      for (let k = 1; k < boxes.length; k++) expect(boxes[k]![0]).toBeGreaterThanOrEqual(boxes[k - 1]![1]);
    }
  });
}
