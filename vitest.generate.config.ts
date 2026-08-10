// The generator's runner. Standalone rather than a merge over `vite.config.ts`
// so `include` genuinely *replaces* the app's test glob — `mergeConfig`
// concatenates arrays, which would run the whole suite and let a normal-looking
// command rewrite the artifact it is supposed to be checking.
import { defineConfig } from 'vitest/config';

export default defineConfig({
  resolve: { tsconfigPaths: true },
  test: {
    environment: 'node',
    include: ['src/nodes/portSpecs.emit.spec.ts'],
  },
});
