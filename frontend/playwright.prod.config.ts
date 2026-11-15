import { defineConfig, devices } from '@playwright/test';
import { ukState } from './e2e/lang';

// QA R8-1: checks that only fail in the production bundle (the dev server ran an uncommitted working tree that hid
// a missing store write). Builds the app (fixtures mode, deterministic) and serves it with `vite preview`.
//   npx playwright test -c playwright.prod.config.ts
const port = Number(process.env.E2E_PROD_PORT ?? 5179);
export default defineConfig({
  testDir: 'e2e',
  testMatch: /\.prod\.ts$/,
  timeout: 30_000,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: `http://localhost:${port}`,
    locale: 'uk-UA',
    storageState: ukState(`http://localhost:${port}`), // Ukrainian copy asserted; English is the app default
    ...devices['Desktop Chrome'],
    viewport: { width: 1440, height: 900 },
  },
  webServer: {
    command: `VITE_API_MODE=fixtures npx vite build --outDir dist/e2e --emptyOutDir && npx vite preview --outDir dist/e2e --port ${port} --strictPort`,
    url: `http://localhost:${port}`,
    reuseExistingServer: false,
    timeout: 180_000,
  },
});
