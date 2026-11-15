import { defineConfig } from '@playwright/test';
import base from './playwright.config';

// Visual check: `npm run shots` writes PNGs to ./shots (dark, card + details + chat).
export default defineConfig({ ...base, testIgnore: [], testMatch: /shots\.spec\.ts/ });
