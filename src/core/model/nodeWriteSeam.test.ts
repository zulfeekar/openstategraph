import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * The node's write side is a seam, and it is now a visible one.
 *
 * `AbstractNodeModel` had seven public mutators — `applyPosition`,
 * `applySize`, `applyParent`, `applyField`, `applyData`, `applyTitle`,
 * `applyRuntime` — under a comment reading *"mutators — WorkflowModel only"*.
 * The comment was the whole enforcement. Every one had exactly one caller and
 * all six live callers were in `WorkflowModel.ts`; `applyData` had none at all
 * (reviews-2026-08-14 ticket 14).
 *
 * That matters past the member count, which is why it was worth doing rather
 * than recording as an exception. The layering rule is
 * `gesture → Controller → ICommand → Model → event → Adapter → canvas`, and
 * seven public setters on the node are seven ways for view or canvas code to
 * move a node without a command — which does not fail, it just silently drops
 * out of undo. A rule defended by a comment is a rule that holds until
 * somebody is in a hurry.
 *
 * So they are `node.write.*`, documented once, and this file asserts the thing
 * the comment only asked for.
 */
const SRC = fileURLToPath(new URL('../..', import.meta.url));

/** Every `.ts`/`.tsx` under `src/`, with its path relative to `src/`. */
function sources(dir = SRC, prefix = ''): { path: string; text: string }[] {
  const found: { path: string; text: string }[] = [];
  for (const entry of readdirSync(dir)) {
    const full = `${dir}${entry}`;
    if (statSync(full).isDirectory()) {
      found.push(...sources(`${full}/`, `${prefix}${entry}/`));
    } else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
      found.push({ path: `${prefix}${entry}`, text: readFileSync(full, 'utf8') });
    }
  }
  return found;
}

describe('who may write to a node', () => {
  /**
   * The model owns the write side. `WorkflowModel` is what commands go
   * through, and it is the only thing that emits the change events the canvas
   * projection depends on — a write that skips it moves a node the canvas
   * never hears about.
   */
  const ALLOWED = ['model/AbstractNodeModel.ts', 'model/WorkflowModel.ts'];

  it('is only the model', () => {
    const offenders = sources()
      .filter(({ text }) => /\.write\.(position|size|parent|field|title|runtime)\(/.test(text))
      .map(({ path }) => path)
      .filter((path) => !ALLOWED.some((allowed) => path.endsWith(allowed)));

    expect(
      offenders,
      'a gesture moves a node through a command, never by writing to it — otherwise undo loses the change',
    ).toEqual([]);
  });

  it('has no `apply*` mutator left to write through instead', () => {
    // The old spelling must not survive alongside the new one; two doors is
    // the same as no door.
    const offenders = sources()
      .filter(({ text }) => /\bapply(Position|Size|Parent|Field|Data|Title|Runtime)\b/.test(text))
      .map(({ path }) => path);

    expect(offenders).toEqual([]);
  });
});
