import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

/**
 * CLAUDE.md's "one rule that makes it work", pinned by resolution rather than
 * by spelling.
 *
 * `core/` is framework-free TypeScript, and `canvas/` + `view/` are one-way
 * projections of it, so the dependency never runs sideways or back. Until this
 * file that half of the rule was a `no-restricted-imports` group in
 * `eslint.config.js` matching `['**\/canvas/**', '**\/view/**', '**\/app/**',
 * '**\/controller/**']` — a list of **paths**, in a codebase that writes
 * **aliases**. `import { AppShell } from '@view/AppShell'` inside `src/core/`
 * has no path segment called `view`, so it passed every CI job that has ever
 * run; `../view/AppShell` on the next line did not. One module was already
 * through (`core/testing/fixtures.ts`), and 227 aliased imports of the four
 * restricted directories existed repo-wide for the gate to have never once
 * seen.
 *
 * The obvious repair — add `'@view/*', '@app/*', …` to the group — closes
 * today's hole and leaves the shape that made it: the ESLint group and
 * `tsconfig.app.json`'s `paths` table would still be **two descriptions of one
 * directory set**, so the eighth alias somebody adds is silently outside the
 * gate again. That is this repository's named recurring defect, and it is what
 * this map exists to stop restating.
 *
 * So the gate resolves instead of matching. It reads the alias table out of
 * `tsconfig.app.json`, applies it the way `tsc` does, and asks a question about
 * the **file the import lands on** — which has exactly one answer however the
 * specifier was spelled. A new alias cannot widen it: `@whatever/*` resolving
 * to `src/view/*` produces `view`, and `view` is not in the table below.
 *
 * The division of labour with ESLint is deliberate rather than a leftover.
 * ESLint keeps the React and JointJS groups, because those restrict **package
 * names**, a name has one spelling, and a rule that fires on the keystroke is
 * worth more than a rule that fires in CI. This file owns everything that
 * restricts a **path**, because a path in this repository has at least two.
 *
 * Those two groups were checked for the same defect rather than assumed clean,
 * and they hold. Both match bare specifiers, which have one spelling and no
 * alias — nothing in `tsconfig.app.json` points at a package. The one thing
 * worth measuring was depth, since `@joint/*` reads like a single segment:
 * `no-restricted-imports` does not treat its patterns as strict pathnames, and
 * a probe importing `@joint/core/dist/joint.core.mjs` and `react-dom/client`
 * inside `src/core/` errored on both. No third group is needed and no fourth
 * one should be added.
 */

/** Which layer may import which. Every layer may import packages; that is ESLint's half. */
const MAY_IMPORT: Readonly<Record<string, readonly string[]>> = {
  // The model. `design/` is tokens and primitives with no app logic, so a
  // dependency on it cannot pull a projection in behind it.
  core: ['core', 'design'],
  // Tokens and primitives, reusable by construction: it may know about itself
  // and nothing else in `src/`. Lower consequence than `core/`'s row — a leak
  // here costs reusability rather than the model/projection split — which is
  // why it was fog rather than a gate until the shape of a gate existed.
  design: ['design'],
};

const SRC = fileURLToPath(new URL('.', import.meta.url));
const ROOT = fileURLToPath(new URL('..', import.meta.url));

/**
 * Test code, which the table above does not bind.
 *
 * A test is not shipped and cannot be loaded by a worker, so it cannot carry a
 * framework into a runtime — and `src/core/extendability.test.ts`, the walk
 * that *proves* "extend by registering", needs a real `Workbench` to walk.
 * Thirteen `.test.ts` files under `src/core/` import `@app/Workbench` for that
 * reason. The rule protects what runs, not what proves it.
 *
 * `core/testing/` is the same exemption spent on a module that is not itself a
 * test: `fixtures.ts` builds the `Workbench` those tests share. It is a
 * **declared** exception rather than an accidental one, and it is not free —
 * `it('keeps the fixture exemption test-only')` below fails the day a shipped
 * module imports from that directory, which is the only thing that made the
 * exemption safe to grant. The alternative considered was moving the directory
 * to `src/testing/`, which removes the exception outright at the cost of
 * rewriting 55 import lines; it is the better shape and the worse trade today,
 * and it stays available because nothing here depends on the address.
 */
const IS_TEST_FILE = /\.(test|spec)\.tsx?$/;
const FIXTURES = 'core/testing/';
const isTestCode = (relative: string): boolean =>
  IS_TEST_FILE.test(relative) || relative.startsWith(FIXTURES);

/** `tsconfig.app.json`'s alias table — read, never restated. */
function aliasTable(): [string, string][] {
  const text = readFileSync(ROOT + 'tsconfig.app.json', 'utf8');
  const parsed = ts.parseConfigFileTextToJson('tsconfig.app.json', text);
  const paths = (parsed.config as { compilerOptions?: { paths?: Record<string, string[]> } })
    .compilerOptions?.paths;
  if (!paths)
    throw new Error('tsconfig.app.json declares no paths — the gate has nothing to read.');
  // Longest pattern first, which is how tsc breaks ties between `@/*` and `@core/*`.
  return Object.entries(paths)
    .map(([pattern, targets]) => [pattern, targets[0] as string] as [string, string])
    .sort((a, b) => b[0].length - a[0].length);
}

/** Every module specifier in a file: static, type-only, dynamic and re-export. */
export function importedSpecifiers(fileName: string, text: string): string[] {
  const source = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true);
  const found: string[] = [];
  const record = (node: ts.Node | undefined): void => {
    if (node && ts.isStringLiteralLike(node)) found.push(node.text);
  };
  const walk = (node: ts.Node): void => {
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) record(node.moduleSpecifier);
    else if (ts.isImportTypeNode(node) && ts.isLiteralTypeNode(node.argument))
      record(node.argument.literal);
    else if (
      ts.isImportEqualsDeclaration(node) &&
      ts.isExternalModuleReference(node.moduleReference)
    )
      record(node.moduleReference.expression);
    else if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword)
      record(node.arguments[0]);
    node.forEachChild(walk);
  };
  source.forEachChild(walk);
  return found;
}

/**
 * The `src/`-relative path an import lands on, or `null` for a package.
 *
 * This is the whole trick: a specifier has many spellings and a landing site
 * has one, so the gate never has to know which spellings exist.
 */
export function landsOn(
  fromRelative: string,
  specifier: string,
  aliases: readonly [string, string][],
): string | null {
  let resolved: string | null = null;
  if (specifier.startsWith('.')) {
    const dir = fromRelative.includes('/')
      ? fromRelative.slice(0, fromRelative.lastIndexOf('/'))
      : '';
    const parts: string[] = [];
    for (const part of `${dir}/${specifier}`.split('/')) {
      if (part === '' || part === '.') continue;
      if (part === '..') parts.pop();
      else parts.push(part);
    }
    return parts.join('/');
  }
  for (const [pattern, target] of aliases) {
    const star = pattern.indexOf('*');
    if (star === -1) {
      if (specifier === pattern) resolved = target;
    } else {
      const prefix = pattern.slice(0, star);
      const suffix = pattern.slice(star + 1);
      if (
        specifier.length >= prefix.length + suffix.length &&
        specifier.startsWith(prefix) &&
        specifier.endsWith(suffix)
      ) {
        resolved = target.replace(
          '*',
          specifier.slice(prefix.length, specifier.length - suffix.length),
        );
      }
    }
    if (resolved !== null) break;
  }
  if (resolved === null) return null;
  // An alias may point outside `src/` — `@workflows/*` is package documents,
  // not a layer — and this rule has nothing to say about those.
  return resolved.startsWith('src/') ? resolved.slice('src/'.length) : null;
}

function modulesUnder(prefix: string): string[] {
  return readdirSync(SRC + prefix, { recursive: true, encoding: 'utf8' })
    .map((entry) => prefix + entry.split('\\').join('/'))
    .filter((relative) => /\.tsx?$/.test(relative) && !relative.endsWith('.d.ts'));
}

describe('the layering rule', () => {
  const aliases = aliasTable();

  it.each(Object.keys(MAY_IMPORT))('holds for %s/, however an import is spelled', (layer) => {
    const permitted = new Set(MAY_IMPORT[layer]);
    const breaches: string[] = [];
    for (const relative of modulesUnder(`${layer}/`)) {
      if (isTestCode(relative)) continue;
      for (const specifier of importedSpecifiers(relative, readFileSync(SRC + relative, 'utf8'))) {
        const target = landsOn(relative, specifier, aliases);
        if (target === null) continue;
        const reached = target.includes('/') ? target.slice(0, target.indexOf('/')) : target;
        if (!permitted.has(reached)) breaches.push(`${relative}  ->  ${specifier}  (${target})`);
      }
    }
    expect(
      breaches,
      `${layer}/ may import ${[...permitted].join(', ')} and nothing else in src/`,
    ).toEqual([]);
  });

  it('keeps the fixture exemption test-only', () => {
    // What `core/testing/` costs. The exemption above is granted on the claim
    // that the directory is test code; this is the claim, checked.
    const leaks: string[] = [];
    for (const relative of modulesUnder('')) {
      if (IS_TEST_FILE.test(relative)) continue;
      for (const specifier of importedSpecifiers(relative, readFileSync(SRC + relative, 'utf8'))) {
        const target = landsOn(relative, specifier, aliases);
        if (target?.startsWith(FIXTURES)) leaks.push(`${relative}  ->  ${specifier}`);
      }
    }
    expect(
      leaks,
      'core/testing/ is exempt from the layering rule because nothing shipped imports it',
    ).toEqual([]);
  });

  it('reads the alias table rather than restating it', () => {
    // The property that makes an eighth alias harmless. `@view/*` is resolved
    // by the table, not recognised by this file: rename it, add a synonym, or
    // point a brand-new alias at `src/view/` — all three land on `view/` and
    // all three are caught.
    expect(landsOn('core/x.ts', '@view/AppShell', aliases)).toBe('view/AppShell');
    expect(landsOn('core/x.ts', '@view/AppShell', [['@later/*', 'src/view/*']])).toBe(null);
    expect(landsOn('core/x.ts', '@later/AppShell', [['@later/*', 'src/view/*']])).toBe(
      'view/AppShell',
    );
    expect(landsOn('core/model/x.ts', '../../app/Workbench', aliases)).toBe('app/Workbench');
    expect(landsOn('core/x.ts', 'react', aliases)).toBe(null);
  });
});
