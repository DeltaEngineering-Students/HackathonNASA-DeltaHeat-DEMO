import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';

// Board item 32 (uhd/docs/I18N.md §8): «EN | УКР» switch, persistence, shared links, and no leftovers of the other
// script on every surface. Written against DEFAULT_LOCALE (read from src/i18n/locale.ts), so it holds before and after
// the flip. Rule: in EN mode, Cyrillic is allowed ONLY inside an element marked lang="uk" (place names and server texts
// the backend could not provide in English); in UK mode, Latin only in names/units (allow-list) or lang="en".
// The other specs pin «uk» in storage (e2e/lang.ts); this one starts with EMPTY storage — the real first visit.

const DEFAULT = readFileSync(new URL('../src/i18n/locale.ts', import.meta.url), 'utf8').match(/DEFAULT_LOCALE: Locale = '(\w+)'/)![1] as 'en' | 'uk';
const OTHER = DEFAULT === 'en' ? 'uk' : 'en';
const NAME = { en: 'DELTAHEAT', uk: 'DELTAHEAT' } as const;
test.use({ storageState: { cookies: [], origins: [] }, locale: 'uk-UA' }); // a Ukrainian browser does not pick the language

const CYR = /[А-Яа-яІіЇїЄєҐґ]/;
/** Latin words that stay Latin in the Ukrainian UI: names, abbreviations, units (TERMS-UK: «крім назв»). */
// no \b at the ends: the detached clone's text runs cells together («Landsat69», «°C2025»)
const LATIN_OK = /(?<![A-Za-z])(?:DELTAHEAT|NASA|USGS|Landsat|NDVI|ΔNDVI|NDBI|CMIP6|NEX-GDDP-CMIP6|NEX-GDDP|SSP\d‑\d\.\d|SSP\d|Esri|World Imagery|GHSL|Sentinel|EOxCloudless|EOX|ASTER|ERA5|OpenStreetMap|OSM|OpenFreeMap|MapLibre|PDF|Excel|xlsx|CSV|JSON|Esc|Enter|EN|English|id|p|LST|AI|ШІ|°C|km)(?![a-z]{2})/g;

/** Machine ids shown as-is (report id «fx-kyiv-pozniaky»). */
const SLUG = /\b[a-z0-9]+(?:-[a-z0-9]+)+\b/g;

/** Visible text of a locator with every [lang] subtree of the given language removed. */
async function textWithout(page: Page, selector: string, lang: 'uk' | 'en', skip = ''): Promise<string> {
  return page.locator(selector).first().evaluate((el, [l, sk]) => {
    const drop = sk ? `[lang="${l}"], ${sk}` : `[lang="${l}"]`;
    const c = el.cloneNode(true) as HTMLElement;
    c.querySelectorAll(drop).forEach((n) => n.remove());
    const aria = [...el.querySelectorAll('[aria-label],[title],[placeholder]')]
      .filter((n) => !n.closest(drop))
      .map((n) => [n.getAttribute('aria-label'), n.getAttribute('title'), n.getAttribute('placeholder')].filter(Boolean).join(' '));
    return `${c.innerText}\n${aria.join('\n')}`;
  }, [lang, skip] as const);
}

async function expectNoCyrillic(page: Page, selector: string, skip = '') {
  const t = await textWithout(page, selector, 'uk', skip);
  // place names without name_en are allowed anywhere (PM rule): the texts marked lang="uk" elsewhere on the page
  // (card title, search, rank note) are those names, so they are cut out of the text before the check
  const names = await page.locator('[lang="uk"]').evaluateAll((els) => els.map((e) => (e as HTMLElement).innerText.trim())
    .filter((x) => x && x.length <= 60 && !/\s\S+\s\S+\s\S+\s/.test(x)));
  const strip = (line: string) => names.sort((a, b) => b.length - a.length).reduce((l, n) => l.split(n).join(''), line);
  const bad = t.split('\n').map(strip).filter((line) => CYR.test(line));
  expect(bad, `${selector}: untranslated Ukrainian outside lang="uk"`).toEqual([]);
}

async function expectNoLatin(page: Page, selector: string) {
  const t = await textWithout(page, selector, 'en');
  const bad = t.split('\n').map((line) => line.replace(LATIN_OK, '').replace(SLUG, '')).filter((line) => /[A-Za-z]{2,}/.test(line));
  expect(bad, `${selector}: Latin leftovers outside names/units`).toEqual([]);
}

/** Opens the main surfaces one by one and checks each with `check`. */
async function sweep(page: Page, check: (sel: string) => Promise<void>) {
  await expect(page.getByTestId('answer')).toBeVisible({ timeout: 60_000 });
  await check('[data-testid="answer"]');
  await check('[data-testid="strip"]');
  await page.getByTestId('layers-toggle').click();
  await check('[data-testid="layers-panel"]');
  await page.keyboard.press('Escape');
  await page.getByTestId('export-btn').first().click();
  await check('[data-testid="export-menu"]');
  await page.keyboard.press('Escape');
  for (const k of ['gap', 'trend']) {
    await page.getByTestId('answer').locator(`[data-hint="${k}"]`).first().click();
    await check('[data-testid="tip"]');
    await page.keyboard.press('Escape');
  }
  await page.getByTestId('open-details').click();
  await expect(page.getByTestId('details')).toBeVisible();
  await check('[data-testid="details"]');
  await check('header');
}

test.describe('language', () => {
  test(`fresh browser: ${DEFAULT} by default, <html lang>, title, switch state`, async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('html')).toHaveAttribute('lang', DEFAULT);
    await expect(page.getByTestId('lang-switch')).toBeVisible();
    await expect(page.getByTestId(`lang-${DEFAULT}`)).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('header')).toContainText(NAME[DEFAULT]);
    if (DEFAULT === 'en') await expect(page).toHaveTitle(/DELTAHEAT/);
    await expect(page).not.toHaveURL(/[?&]lang=/);
  });

  test('brand: header shows DELTAHEAT + tagline, document.title ends with "— DELTAHEAT"', async ({ page }) => {
    await page.goto('/?zone=kyiv-pozniaky&lang=en');
    await expect(page.locator('header .brand-name')).toHaveText('DELTAHEAT');
    await expect(page.getByTestId('brand-tag')).toHaveText('Urban heat detective');
    await expect.poll(() => page.evaluate(() => document.title)).toMatch(/ — DELTAHEAT$/);
    await expect(page.getByTestId('team-credit')).toHaveText('Made by Coaches Team from KSE Delta Engineering');
  });

  test('?lang=en: English header, card and strip — no Cyrillic outside lang="uk"', async ({ page }) => {
    await page.goto('/?zone=kyiv-pozniaky&lang=en');
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.locator('header')).toContainText('DELTAHEAT');
    await expect(page).toHaveTitle(/— DELTAHEAT$/);
    await expect(page.getByTestId('lang-en')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('answer')).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId('strip')).toBeVisible();
    await expectNoCyrillic(page, 'header .brand');
    await expectNoCyrillic(page, 'header .top-right');
    await expectNoCyrillic(page, '[data-testid="answer"]');
    await expectNoCyrillic(page, '[data-testid="strip"]');
  });

  test(`switch to ${OTHER}: persists across reload, lands in the URL, survives a shared link; back to ${DEFAULT} drops it`, async ({ page, browser }) => {
    await page.goto('/?zone=kyiv-pozniaky');
    await expect(page.getByTestId('answer')).toBeVisible({ timeout: 60_000 });
    await page.getByTestId(`lang-${OTHER}`).click();
    await expect(page.locator('html')).toHaveAttribute('lang', OTHER);
    await expect(page).toHaveURL(new RegExp(`[?&]lang=${OTHER}\\b`));
    await expect(page.locator('header')).toContainText(NAME[OTHER]);
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('lang', OTHER);
    await expect(page.getByTestId('map-year')).toContainText(OTHER === 'en' ? 'Map: summer' : 'Мапа: літо');

    // the link opened by someone else (fresh context, no storage) keeps the language
    const url = page.url();
    const ctx = await browser.newContext();
    const other = await ctx.newPage();
    await other.goto(url);
    await expect(other.locator('html')).toHaveAttribute('lang', OTHER);
    await ctx.close();
    // an explicit ?lang=<default> beats the stored choice
    await page.goto(url.replace(`lang=${OTHER}`, `lang=${DEFAULT}`));
    await expect(page.locator('html')).toHaveAttribute('lang', DEFAULT);
    // and switching back to the default removes the parameter
    await page.getByTestId(`lang-${OTHER}`).click();
    await page.getByTestId(`lang-${DEFAULT}`).click();
    await expect(page.locator('header')).toContainText(NAME[DEFAULT]);
    await expect(page).not.toHaveURL(/[?&]lang=/);
  });

  test('numbers: decimal point in EN, comma in UK, same value', async ({ page }) => {
    await page.goto('/?zone=kyiv-pozniaky&lang=uk');
    const uk = await page.getByTestId('gap-mean').innerText({ timeout: 60_000 });
    await page.getByTestId('lang-en').click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    const en = await page.getByTestId('gap-mean').innerText();
    expect(en).toMatch(/\d\.\d/);
    expect(uk).toMatch(/\d,\d/);
    expect(uk.replace(',', '.')).toBe(en);
  });

  test(`share link carries the non-default language (${OTHER})`, async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await page.goto(`/?lang=${OTHER}`);
    await expect(page.getByTestId('answer')).toBeVisible({ timeout: 60_000 });
    await page.getByTestId('export-btn').first().click();
    await page.getByTestId('export-share').click();
    const copied = await page.evaluate(() => navigator.clipboard.readText());
    expect(copied).toMatch(new RegExp(`[?&]lang=${OTHER}\\b`));
  });
});

test.describe('language — full sweep', () => {
  test('EN mode: no untranslated Cyrillic on card, strip, layers, export, tips, Details, header', async ({ page }) => {
    await page.goto('/?zone=kyiv-pozniaky&lang=en');
    await sweep(page, (sel) => expectNoCyrillic(page, sel));
  });

  // the reference-forest label sits in a lang="uk" span, which expectNoCyrillic exempts: check it explicitly
  test('EN mode: Details reference forest and the analyst header are English (no Cyrillic at all)', async ({ page }) => {
    await page.goto('/?zone=kyiv-pozniaky&lang=en');
    await expect(page.getByTestId('answer')).toBeVisible({ timeout: 60_000 });
    await page.getByTestId('open-details').click();
    const details = page.getByTestId('details');
    await expect(details).toContainText('Reference forest — the forest around Kyiv');
    expect(await details.locator('.r').allInnerTexts().then((a) => a.filter((x) => CYR.test(x)))).toEqual([]);
    await page.getByTestId('ask').click();
    const chat = page.getByTestId('chat');
    await expect(chat).toBeVisible();
    const head = await chat.locator('h2, .chat-head + p').allInnerTexts();
    expect(head.filter((x) => CYR.test(x))).toEqual([]);
    await expect(chat).toContainText('Ask about Pozniaky');
  });

  test('UK mode: no Latin leftovers except names and units', async ({ page }) => {
    await page.goto('/?zone=kyiv-pozniaky&lang=uk');
    await sweep(page, (sel) => expectNoLatin(page, sel));
  });
});
