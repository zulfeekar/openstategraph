import { defineConfig } from '@playwright/test';

/**
 * Smoke-level browser coverage for the canvas (ticket 51) — the one layer
 * unit tests structurally cannot see: real drags, real port clicks, the
 * measurement feedback loop, undo through actual gestures.
 *
 * Runs against the dev server; `webServer` reuses a running instance (the
 * supervised stack) or starts its own for CI.
 */
/**
 * An already-running build to run against, instead of :5273 —
 * `team-board-and-gap-reports/11`.
 *
 * Unset, nothing below changes: CI starts its own `npm run dev` and a
 * developer attaches to the supervised stack, exactly as before. Set, the
 * suite runs against that origin and starts no server at all — which is how a
 * session that must not touch :5273 (because the port belongs to somebody
 * else's dev server) can still prove a spec against a real browser, by
 * pointing this at its own build on its own port.
 *
 * Deliberately not a second `projects` entry: a project cannot carry its own
 * `webServer`, so the choice is *which origin the whole run uses*, and that is
 * one variable rather than a second copy of every setting here.
 */
const externalBaseUrl = process.env.OSG_E2E_BASE_URL?.trim();

export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: externalBaseUrl || 'http://localhost:5273',
    viewport: { width: 1400, height: 900 },
  },
  webServer: externalBaseUrl
    ? undefined
    : {
        command: 'npm run dev',
        url: 'http://localhost:5273',
        // Never in CI. Attaching to whatever is already on :5273 is right on a
        // developer's machine — the supervised stack is usually up — and wrong on
        // a runner, where it means the suite could silently pass against a server
        // that is not the code under test (reviews-2026-08-14 ticket 10).
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
      },
});
