import { defineConfig } from '@playwright/test';

/**
 * The recording rig, kept apart from `playwright.config.ts` on purpose.
 *
 * The smoke suite proves behaviour; this one produces a film. They disagree on
 * almost every setting a config holds — video on, one worker, no retries, a
 * fixed 1280x720 frame, and its own server on its own port so a recording
 * never competes with the supervised stack on :5273 or the owner's :8123.
 *
 * The server is started here rather than by hand, because the recording needs
 * an environment the shared launch configuration does not have: `OLLAMA_HOST`
 * and `OLLAMA_ENDPOINT` blanked so the run reaches Ollama **cloud**. A blank
 * value is skipped by `_endpoint_source`, and `load_env_file` never overwrites
 * a variable that is already set, so blanking here beats the `.env` on disk
 * without editing it. `OLLAMA_API_KEY` is deliberately not named: the CLI
 * loads it from `.env` itself, so no key passes through this file.
 */
const PORT = Number(process.env.DEMO_PORT ?? 8126);

export default defineConfig({
  globalSetup: './e2e/demo/support/globalSetup.ts',
  testDir: process.env.DEMO_DIR ?? 'e2e/demo',
  // A scene runs a real model call. The default 30s is a smoke-test number.
  timeout: 180_000,
  // Order is the film. Parallel scenes would record four browsers at once.
  workers: 1,
  fullyParallel: false,
  // A retried scene records a second video and the stitch would take the wrong
  // one. A failed scene is re-recorded on purpose.
  retries: 0,
  use: {
    baseURL: `http://localhost:${PORT}`,
    // 720p. The video frame is the viewport, so this number is the output.
    viewport: { width: 1280, height: 720 },
    video: { mode: 'on', size: { width: 1280, height: 720 } },
    // Every gesture is a demonstration. A jump cut reads as a glitch.
    launchOptions: { slowMo: 120 },
  },
  webServer: {
    command: `python3 -m openstategraph.cli serve --port ${PORT}`,
    cwd: 'backend',
    url: `http://localhost:${PORT}/api/health`,
    reuseExistingServer: true,
    timeout: 120_000,
    env: {
      OLLAMA_HOST: '',
      OLLAMA_ENDPOINT: '',
      OPENSTATEGRAPH_KANBAN_URL: '',
      OPENSTATEGRAPH_STATE_DIR: '/private/tmp/osg-demo-state',
      // A copy, never the tracked tree. `globalSetup` says why.
      OPENSTATEGRAPH_WORKFLOWS_ROOT: '/private/tmp/osg-demo-workflows',
    },
  },
  outputDir: 'demo-out/raw',
});
