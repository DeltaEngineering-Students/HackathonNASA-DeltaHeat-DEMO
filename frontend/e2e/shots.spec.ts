import { test } from '@playwright/test';

for (const theme of ['dark'] as const) {
  test(`shots ${theme}`, async ({ page }) => {
    test.setTimeout(60_000);
    await page.emulateMedia({ colorScheme: theme });
    await page.goto('/');
    await page.getByTestId('answer').waitFor();
    await page.locator('.map[data-ready]').waitFor();
    await page.waitForTimeout(4000);
    await page.screenshot({ path: `shots/${process.env.E2E_LIVE ? 'live_' : ''}s1_${theme}.png` });
    await page.getByTestId('open-details').click();
    await page.getByTestId('climate').waitFor();
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `shots/${process.env.E2E_LIVE ? 'live_' : ''}s2_${theme}.png` });
    await page.getByTestId('close-details').click();
    await page.getByRole('combobox').click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: `shots/${process.env.E2E_LIVE ? 'live_' : ''}s3_search_${theme}.png` });
    await page.keyboard.press('Escape');
    await page.getByTestId('ask').click();
    await page.getByText('Чому 2020 рік вибивається?').click();
    await page.getByTestId('agent-offline').waitFor();
    await page.screenshot({ path: `shots/${process.env.E2E_LIVE ? 'live_' : ''}s4_chat_${theme}.png` });
  });
}
