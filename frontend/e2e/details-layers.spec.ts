import { expect, test } from '@playwright/test';

// item 17 C: internal layers (gap_fill, nonbuilt) never reach the UI — the fixtures meta carries both on purpose.
for (const url of ['/?view=details', '/?layer=gap_fill&view=details']) {
  test(`Details «Шар мапи» and the strip offer only the 4 layers, no internal ids in the DOM (${url})`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(url);
    await expect(page.getByTestId('close-details')).toBeVisible({ timeout: 30_000 });
    await page.locator('.map[data-ready]').waitFor();
    const det = page.getByRole('group', { name: 'Шар мапи' }).first();
    await expect(det.getByRole('button')).toHaveText(['Розрив з лісом', 'Температура поверхні', 'Зелень (NDVI)', 'Зміна зелені']);
    await expect(det.locator('[aria-pressed=true]')).toHaveCount(1);
    const html = await page.content();
    expect(html).not.toContain('gap_fill');
    expect(html).not.toContain('nonbuilt');
    await page.getByTestId('close-details').click();
    await expect(page.getByTestId('quick-layers').getByRole('button')).toHaveText(['Розрив', 'Температура', 'Зелень', 'Зміна зелені']);
    expect(await page.content()).not.toContain('gap_fill');
  });
}
