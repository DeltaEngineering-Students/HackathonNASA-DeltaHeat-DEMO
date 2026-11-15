import { defineConfig, devices } from '@playwright/test';
import { ukState } from './e2e/lang';

// E2E runs against the dev server in fixtures mode (deterministic, no backend needed).
// Set E2E_LIVE=1 and UHD_API_TARGET to run the same flows against a live backend.
const live = !!process.env.E2E_LIVE;
const port = live ? 5176 : 5174;
export const BASE_URL = `http://localhost:${port}`;
export default defineConfig({
  testDir: 'e2e',
  testIgnore: /shots\.spec\.ts/,
  timeout: 30_000,
  fullyParallel: true,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: BASE_URL,
    locale: 'uk-UA',
    storageState: ukState(BASE_URL), // specs assert Ukrainian copy; English is the app default (e2e/lang.ts)
    ...devices['Desktop Chrome'],
    viewport: { width: 1440, height: 900 },
  },
  webServer: {
    command: `VITE_API_MODE=${live ? 'live' : 'fixtures'} npx vite --port ${port} --strictPort`,
    url: `http://localhost:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
