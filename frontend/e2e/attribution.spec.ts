import { expect, test } from '@playwright/test';

// The map credit is MapLibre's compact one: an ⓘ button, collapsed by default, expanding on click; the satellite caption stays above it.
test('attribution is compact and collapsed; the ⓘ button expands it', async ({ page }) => {
  await page.goto('/?lang=en');
  await expect(page.getByTestId('answer')).toBeVisible({ timeout: 30_000 });
  await page.locator('.map[data-ready]').waitFor();
  const attr = page.locator('.maplibregl-ctrl-attrib');
  await expect(attr).toHaveClass(/maplibregl-compact/);
  await expect(attr).not.toHaveAttribute('open', '');
  expect((await attr.boundingBox())!.height).toBeLessThan(40);
  expect((await attr.boundingBox())!.width).toBeLessThan(60);
  await attr.locator('.maplibregl-ctrl-attrib-button').click();
  await expect(attr).toHaveAttribute('open', '');
  await expect(attr).toContainText('OpenStreetMap');
  await expect(attr).toContainText('OpenFreeMap');
  await expect(attr).not.toContainText('zakon.rada.gov.ua');
});
