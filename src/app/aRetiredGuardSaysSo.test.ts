import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

/**
 * A guard whose docstring described a call site that did not exist —
 * `osg-agent-experience/70`.
 *
 * `src/app/staleDraft.ts` exports two functions. `draftIsAhead` has a
 * production caller (`view/topbar/usePublishState.ts`). `draftIsStale` has
 * none outside its own test, and its docstring opened by describing the fix it
 * performs — *"`restoreDraftFor` restored a draft whenever it differed from
 * the file, and never asked which came first […] The rule is a comparison, not
 * a guess."* `restoreDraftFor` does no such thing and never called it. A
 * reader checking whether this repository guards against a stale draft found a
 * function that says it does, is tested, and is wired to nothing, which is
 * worse than an absence because an absence is legible.
 *
 * ## Why it is retired rather than wired in
 *
 * `68` deliberately did not use it, and `69` — which is where a base revision
 * for a draft actually landed — did not either. Both compare **bytes**:
 * `restoreDraftFor`'s own docstring records the argument, that a browser with
 * a wrong clock must not silently win or silently lose, and `69` went further
 * by recording the *digest* a draft was taken from, which answers the same
 * question this function asks and answers it without a clock. So the clock
 * comparison has no remaining job.
 *
 * ## Why it is retired rather than deleted
 *
 * The owner's standing rule is that nothing is removed by deletion — a
 * retirement is a commit, not an absence. The argument written into
 * `draftIsStale` is also worth keeping legible: it is the record of
 * `every-workflow-green` 25, where three correct fixes appeared to do nothing
 * because each corrected file was masked on load by a stale draft. Deleting
 * the function deletes the account of that.
 *
 * ## What this file is for
 *
 * The ticket asks for a test that fails if a second exported function in that
 * module loses its last caller — the census shape `install-experience 21`
 * used, and the one a unit test structurally cannot provide, because the
 * defect is a *missing* caller and an absence has no call site to assert on.
 *
 * So this counts callers across the whole of `src/`, from the AST rather than
 * by regex, because these modules discuss each other's function names in their
 * own prose — this docstring does — and a comment is not a call site. Two
 * assertions, and they point in opposite directions on purpose: a **live**
 * guard must keep at least one shipped caller, and a **retired** one must keep
 * none. Wiring `draftIsStale` back in is then a red test that says to move it
 * across this table and say why, rather than a silent second guard.
 */
const SRC = fileURLToPath(new URL('..', import.meta.url));

/**
 * The guards this module ships, and which side of the line each is on.
 *
 * A table rather than two hardcoded names so a third export of
 * `staleDraft.ts` — live or retired — is one row.
 */
const GUARDS = {
  /** `ship-it/39`: Publish ships the *saved* version, so the toolbar owes a warning. */
  draftIsAhead: 'live',
  /** `osg-agent-experience/70`: superseded by the byte and digest comparisons. */
  draftIsStale: 'retired',
} as const;

type Guard = keyof typeof GUARDS;

const MODULE = 'app/staleDraft.ts';

/** Every shipped module — a test is not the app, and may call whatever it likes. */
function shippedModules(): readonly string[] {
  const modules: string[] = [];
  for (const entry of readdirSync(SRC, { recursive: true, encoding: 'utf8' })) {
    const relative = entry.split('\\').join('/');
    if (!/\.tsx?$/.test(relative) || /\.(test|spec)\.tsx?$/.test(relative)) continue;
    if (relative.endsWith('.d.ts')) continue;
    modules.push(relative);
  }
  return modules;
}

/** Which shipped modules call each guard, excluding the one that defines it. */
function callers(): ReadonlyMap<Guard, readonly string[]> {
  const found = new Map<Guard, Set<string>>(
    (Object.keys(GUARDS) as Guard[]).map((name) => [name, new Set<string>()]),
  );
  for (const relative of shippedModules()) {
    if (relative === MODULE) continue;
    const text = readFileSync(SRC + relative, 'utf8');
    const source = ts.createSourceFile(relative, text, ts.ScriptTarget.Latest, true);
    const walk = (node: ts.Node): void => {
      if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
        const name = node.expression.text as Guard;
        if (name in GUARDS) found.get(name)!.add(relative);
      }
      node.forEachChild(walk);
    };
    source.forEachChild(walk);
  }
  return new Map(
    (Object.keys(GUARDS) as Guard[]).map((name) => [name, [...found.get(name)!].sort()]),
  );
}

describe('osg-agent-experience 70 — every guard in staleDraft.ts is on the right side of the line', () => {
  it('can see a call at all', () => {
    // The self-check every census owes: an assertion that something has no
    // callers is worthless from a census that finds none anywhere.
    expect([...callers().values()].flat().length).toBeGreaterThan(0);
  });

  it.each((Object.keys(GUARDS) as Guard[]).filter((name) => GUARDS[name] === 'live'))(
    '%s is called by a shipped module',
    (name) => {
      expect(callers().get(name)).not.toEqual([]);
    },
  );

  it.each((Object.keys(GUARDS) as Guard[]).filter((name) => GUARDS[name] === 'retired'))(
    '%s is retired, so nothing shipped calls it',
    (name) => {
      // If this fails, the function was wired back in. That is allowed — but it
      // has to move to `live` in the table above with the argument beside it,
      // because a retired guard with a caller is exactly the disagreement
      // between a docstring and the code that produced this ticket.
      expect(callers().get(name)).toEqual([]);
    },
  );

  it('says in the module itself that a retired guard is retired', () => {
    // The docstring is the thing a reader meets first, and its disagreement
    // with the code *was* the defect. A census that checked only call sites
    // would have left the sentence standing.
    const text = readFileSync(SRC + MODULE, 'utf8');
    for (const name of Object.keys(GUARDS) as Guard[]) {
      if (GUARDS[name] !== 'retired') continue;
      const declaration = text.indexOf(`export function ${name}(`);
      expect(declaration).toBeGreaterThan(-1);
      expect(text.slice(0, declaration)).toContain('@deprecated');
    }
  });
});
