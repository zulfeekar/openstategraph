import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

/**
 * A listener on an event nothing can emit, found by census.
 *
 * `stable-beta-public/14`. `AppShell.tsx` and `TopBar.tsx` both subscribed to
 * `workbench.engine`'s `run:finish` — for the toast, the token bar's refresh
 * and, briefly, the starter's note — and nothing in the shipped app calls
 * `engine.run()` any more: the toolbar's Run opens the chat and streams a
 * backend run. So three features were wired to an event that could not fire.
 * Every listener read correctly, every test that faked the engine stayed
 * green, and the product simply did not do what the code said.
 *
 * That is the failure shape a grep-shaped pin catches and a unit test cannot:
 * the defect is a *missing* caller, and an absence has no call site to assert
 * on. So this counts both ends across the whole of `src/` and asserts the
 * relationship between them — subscribers are allowed only while a caller
 * exists. Restoring an `engine.run()` caller makes the listeners legal again
 * on the same run that restores them.
 *
 * Read from the AST rather than by regex, because the modules this counts
 * discuss `engine.run()` in their own prose — including the docstring above —
 * and a comment is not a call site.
 */
const SRC = fileURLToPath(new URL('.', import.meta.url));

const EVENT = 'run:finish';

/** Every shipped module — a test is not the app, and may fake whatever it likes. */
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

/** `<something>.<method>(...)`, or `null` when the call is not one. */
function methodCalled(
  node: ts.Node,
): { readonly receiver: string; readonly method: string } | null {
  if (!ts.isCallExpression(node)) return null;
  const target = node.expression;
  if (!ts.isPropertyAccessExpression(target)) return null;
  const receiver = target.expression;
  const name = ts.isPropertyAccessExpression(receiver)
    ? receiver.name.text
    : ts.isIdentifier(receiver)
      ? receiver.text
      : '';
  return { receiver: name, method: target.name.text };
}

/** The first argument, when it is a plain string literal. */
function firstStringArgument(node: ts.CallExpression): string | null {
  const argument = node.arguments[0];
  if (argument === undefined) return null;
  if (ts.isStringLiteral(argument)) return argument.text;
  if (ts.isNoSubstitutionTemplateLiteral(argument)) return argument.text;
  return null;
}

interface Census {
  /** Modules containing a call of the form `…engine.run(…)`. */
  readonly callers: readonly string[];
  /** Modules subscribing with `…on('run:finish', …)`. */
  readonly subscribers: readonly string[];
  /** Modules emitting it — the self-check that this census can see anything at all. */
  readonly emitters: readonly string[];
}

function census(): Census {
  const callers = new Set<string>();
  const subscribers = new Set<string>();
  const emitters = new Set<string>();
  for (const relative of shippedModules()) {
    const text = readFileSync(SRC + relative, 'utf8');
    const source = ts.createSourceFile(relative, text, ts.ScriptTarget.Latest, true);
    const walk = (node: ts.Node): void => {
      const call = methodCalled(node);
      if (call !== null && ts.isCallExpression(node)) {
        if (call.receiver === 'engine' && call.method === 'run') callers.add(relative);
        if (firstStringArgument(node) === EVENT) {
          if (call.method === 'on') subscribers.add(relative);
          if (call.method === 'emit') emitters.add(relative);
        }
      }
      node.forEachChild(walk);
    };
    source.forEachChild(walk);
  }
  return {
    callers: [...callers].sort(),
    subscribers: [...subscribers].sort(),
    emitters: [...emitters].sort(),
  };
}

describe(`no shipped module listens for ${EVENT} while nothing can fire it`, () => {
  const counted = census();

  it('can see the event at all — the emitter is still there under this name', () => {
    // Without this, a renamed event would make the whole census vacuous and
    // the assertion below would pass by matching nothing.
    expect(counted.emitters).toContain('core/execution/ExecutionEngine.ts');
  });

  it('has no subscriber unless some shipped module calls engine.run()', () => {
    // One assertion either way: with a caller the subscribers are legal and
    // the census names none, without one every subscriber is named.
    const dead = counted.callers.length > 0 ? [] : counted.subscribers;

    expect(dead).toEqual([]);
  });
});
