// Lean by design: strict tsc already covers unused locals/params and type
// safety, so ESLint carries only what the compiler cannot — hook rules and
// the recommended correctness set. Widening is a deliberate future step.
import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';

export default tseslint.config(
  { ignores: ['dist/', 'coverage/', 'node_modules/'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    plugins: { 'react-hooks': reactHooks },
    rules: {
      // rules-of-hooks violations are genuine bugs; the v6 compiler-adjacent
      // additions (purity, refs, set-state-in-effect, ...) are advisory
      // opinions on code that demonstrably works — warnings, not gates.
      ...Object.fromEntries(
        Object.entries(reactHooks.configs.recommended.rules).map(([rule, level]) => [
          rule,
          rule.endsWith('rules-of-hooks') || rule.endsWith('set-state-in-render') ? level : 'warn',
        ]),
      ),
      // tsc's noUnusedLocals owns this; double-reporting is noise.
      '@typescript-eslint/no-unused-vars': 'off',
      // The codebase deliberately uses `any` at LangChain seams.
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
  // Half the gate for CLAUDE.md's "the one rule that makes it work": `core/`
  // is framework-free TypeScript that could run in Node or a worker, so it
  // imports neither React nor JointJS, and never reaches sideways into the
  // view or canvas layers. This was review-only until this block existed —
  // `import { useState } from 'react'` inside `src/core/` passed every CI job.
  //
  // It is an ERROR, not a warning: the whole value of the rule is that the
  // dependency never lands, and a warning is a dependency that landed. If it
  // fires on something you are writing, the import is the thing to change,
  // not this block. Depend on an abstraction (`core/` owns the interfaces
  // both other layers implement) or move the code out of `core/`.
  //
  // The *other* half — the sideways rule — lived here too until 2026-08-30, as
  // a third group matching `['**/canvas/**', '**/view/**', '**/app/**',
  // '**/controller/**']`. It matched a path, and this codebase writes aliases:
  // `../view/AppShell` errored, `@view/AppShell` on the next line was silent,
  // and one module (`core/testing/fixtures.ts`) was already through. Restating
  // the four aliases here would have closed today's hole and kept the shape
  // that made it — this block and `tsconfig.app.json`'s `paths` would still be
  // two descriptions of one directory set, so the next alias would be outside
  // the gate again. It moved to `src/layerBoundaries.test.ts`, which reads the
  // alias table and asks about the file an import lands on rather than about
  // how it was spelled.
  //
  // The split is the point, not a leftover: a package restriction is by NAME,
  // and a name has one spelling, so it belongs in a rule that fires on the
  // keystroke. A path restriction has at least two spellings and needs a
  // resolver. Do not add a path group back here.
  {
    files: ['src/core/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['react', 'react-dom', 'react/*', 'react-dom/*'],
              message:
                'core/ imports neither React nor JointJS (CLAUDE.md § Layering). Keep React in view/.',
            },
            {
              group: ['@joint/*', 'jointjs'],
              message:
                'core/ imports neither React nor JointJS (CLAUDE.md § Layering). Keep JointJS in canvas/.',
            },
          ],
        },
      ],
    },
  },
);
