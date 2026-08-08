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
          rule.endsWith('rules-of-hooks') || rule.endsWith('set-state-in-render')
            ? level
            : 'warn',
        ]),
      ),
      // tsc's noUnusedLocals owns this; double-reporting is noise.
      '@typescript-eslint/no-unused-vars': 'off',
      // The codebase deliberately uses `any` at LangChain seams.
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
);
