import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { it } from 'vitest';

import {
  PORT_SPEC_ARTIFACT_PATH,
  buildPortSpecArtifact,
  serializePortSpecArtifact,
} from './portSpecs';

/**
 * The emitter. `npm run generate:ports` runs this file and nothing else.
 *
 * **Why a vitest file rather than a script.** The generator has to import the
 * real editor catalogue, which means TypeScript, `@core/*` path aliases and ESM
 * — and this repo has no TypeScript runner installed. Vitest is already a
 * devDependency and already resolves those aliases through `vite.config.ts`, so
 * using it as the runner costs zero new dependencies. `tsx`/`vite-node` would
 * have added one purely to run four lines.
 *
 * The extension is `.spec.ts`, not `.test.ts`, on purpose: the default vitest
 * `include` is `src/**\/*.test.ts`, so `npm test` never picks this up and can
 * never silently rewrite the artifact it is supposed to be checking. It runs
 * only under `vitest.generate.config.ts`.
 */
it('writes the node/port catalogue artifact', () => {
  const target = resolve(import.meta.dirname, '../..', PORT_SPEC_ARTIFACT_PATH);
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, serializePortSpecArtifact(buildPortSpecArtifact()), 'utf8');
});
