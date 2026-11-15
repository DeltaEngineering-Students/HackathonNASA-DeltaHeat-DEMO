/// <reference lib="dom" />
import { expect, test, type Page } from '@playwright/test';

// QA R7-1 / R7-2 (regression of R5-1): with the year line, the export button and the credit the card must still show
// the whole chart above the pinned footer; the factors and hotspots are visible or one internal scroll away.
const live = !!process.env.E2E_LIVE;
const SHOTS = process.env.UHD_SHOTS_DIR;
const ZONES = live ? ['demo-nyzhni-sady', 'demo-desnianske', 'kyiv-solomianskyi'] : ['kyiv-pozniaky', 'kyiv-obolon', 'kyiv-teremky'];

async function boxes(page: Page) {
  return page.evaluate(() => {
    const r = (sel: string) => { const e = document.querySelector(sel); return e ? e.getBoundingClientRect() : null; };
    const body = r('.answer-body')!, foot = r('.answer .card-foot')!, chart = r('[data-testid=answer] [data-testid=linechart]');
    const fac = r('[data-testid=factors]'), hot = r('[data-testid=hotspots]'), f1 = r('[data-testid=factors] li');
    const b = document.querySelector('.answer-body')!;
    return { bodyBottom: body.bottom, footTop: foot.top, footBottom: foot.bottom, chartBottom: chart?.bottom ?? null, chartTop: chart?.top ?? null,
      factorsBottom: fac?.bottom ?? null, firstFactorBottom: f1?.bottom ?? null, hotBottom: hot?.bottom ?? null, scrollable: b.scrollHeight > b.clientHeight + 1, vh: innerHeight };
  });
}

for (const vp of [{ width: 1440, height: 900 }, { width: 1280, height: 720 }]) {
  test.describe(`${vp.width}×${vp.height}`, () => {
    test.use({ viewport: vp, colorScheme: 'dark' });
    test.describe.configure({ timeout: 150_000 });
    for (const zone of ZONES) {
      test(`${zone}: chart above the fold, footer buttons visible, the rest one scroll away`, async ({ page }) => {
        await page.goto(`/?zone=${zone}`);
        await expect(page.getByTestId('answer').getByTestId('linechart')).toBeVisible({ timeout: 120_000 });
        await page.waitForTimeout(400);
        const b = await boxes(page);
        console.log(`FOLD ${vp.width} ${zone} ${JSON.stringify(b)}`);
        if (SHOTS) await page.screenshot({ path: `${SHOTS}/fold-${zone}-${vp.width}.png` });
        expect(b.footBottom).toBeLessThanOrEqual(vp.height);
        expect(b.chartBottom!).toBeLessThanOrEqual(b.bodyBottom + 0.5); // whole chart, not under the footer
        await expect(page.getByTestId('open-details')).toBeInViewport({ ratio: 1 });
        await expect(page.getByTestId('export-btn')).toBeInViewport({ ratio: 1 });
        // R7-2: at 1440×900 «Що гріє» with its first line and the hotspot row fit (further factor lines may scroll)
        if (vp.height >= 900) {
          expect(b.firstFactorBottom ?? 0).toBeLessThanOrEqual(b.bodyBottom + 0.5);
          if (b.hotBottom != null) expect(b.hotBottom).toBeLessThanOrEqual(b.bodyBottom + 0.5);
        }
        // anything below is reachable by the card's own scroll, signalled by the fade above the footer
        if ((b.hotBottom ?? 0) > b.bodyBottom || (b.factorsBottom ?? 0) > b.bodyBottom) {
          expect(b.scrollable).toBe(true);
          await expect(page.getByTestId('answer')).toHaveClass(/\bmore\b/);
          await page.locator('.answer-body').evaluate((e) => { e.scrollTop = e.scrollHeight; });
          const last = page.getByTestId('hotspots').or(page.getByTestId('factors')).last();
          await expect(last).toBeInViewport();
        }
      });
    }
  });
}
