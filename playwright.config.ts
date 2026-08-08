import { defineConfig } from '@playwright/test';

/**
 * Smoke-level browser coverage for the canvas (ticket 51) — the one layer
 * unit tests structurally cannot see: real drags, real port clicks, the
 * measurement feedback loop, undo through actual gestures.
 *
 * Runs against the dev server; `webServer` reuses a running instance (the
 * supervised stack) or starts its own for CI.
 */
export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: 'http://localhost:5273',
    viewport: { width: 1400, height: 900 },
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5273',
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
