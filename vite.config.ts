// Vitest's `defineConfig` rather than Vite's — it is the same function widened
// to accept the `test` block. Importing from 'vite' typechecks everything
// except `test`, which then fails as an unknown property.
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // Native tsconfig path resolution — replaces the vite-tsconfig-paths
  // plugin, so `tsconfig.app.json` stays the single place aliases are
  // declared and tests import exactly what the app imports.
  resolve: { tsconfigPaths: true },
  server: { port: 5273, strictPort: false },
  build: { target: 'es2022', sourcemap: true },

  test: {
    // `node`, not a DOM shim, on purpose. `core/` is framework-free
    // TypeScript and is where the logic worth testing lives — the canvas is
    // a projection of it. A DOM environment would be dead weight for the
    // vast majority of tests and would let view concerns leak into them.
    environment: 'node',
    include: ['src/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      include: ['src/core/**', 'src/controller/**', 'src/nodes/**'],
      // The view and canvas layers are excluded from the coverage figure
      // rather than untested — they are verified in the browser. Counting
      // them would produce a number that rewards the wrong tests.
      // `portSpecs.emit.spec.ts` is the artifact generator, run only by
      // `npm run generate:ports` under its own config — counting it here would
      // penalise the ratchet for a file the test run deliberately never loads.
      exclude: ['src/**/*.test.ts', 'src/**/index.ts', 'src/**/*.emit.spec.ts'],
      // A ratchet, not a target: raised as waves of tests land (58% -> 73%
      // statements in the 2026-08-09 push). CI fails if coverage regresses
      // below the highest level already achieved.
      thresholds: {
        statements: 72,
        lines: 75,
        functions: 65,
        branches: 50,
      },
    },
  },
});
