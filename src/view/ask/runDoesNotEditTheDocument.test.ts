import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * Asking a question must not write the document (ticket 42).
 *
 * `AskPanel.ask` wrote the typed question onto the open document's entry Text
 * Input — `controller.nodes.setField(entry.id, 'prompt', trimmed)` — so that
 * "the chat and the canvas agree about what was asked". The canvas did agree.
 * So did autosave: `WorkbenchContext` schedules on `controller.onChange`, which
 * reaches `writeOpenWorkflowToDisk` and `WorkflowStore._write`. **Running a
 * workflow rewrote the vendor-neutral source artifact** — the copy `git diff`
 * and the CLI read.
 *
 * The cost is not theoretical and it is not one developer's: two people sharing
 * a repository each produce a dirty `workflow.json` by asking a question, and
 * neither can say what they changed. The working tree at review time was
 * carrying an instance of exactly that.
 *
 * The codebase already held the principle and applied it to *children* only —
 * `liveInputValue.ts`: a run's question "must not be written even when the
 * child *is* opened, because that would edit a saved document to display a
 * fact about a run". The open parent was the exception nobody argued for.
 *
 * It is now the same rule on both sides: the question rides in run state
 * (`node.runtime.output`, written from the SSE `update` frame) and the card
 * projects it through `LiveInputBody`. Nothing in the ask path writes a field.
 *
 * Pinned structurally rather than by rendering the panel, for the reason
 * `nodeWriteSeam.test.ts` gives about its own seam: the enforcement here was a
 * *comment* explaining why the write was desirable, and a rule defended by a
 * comment is a rule that holds until somebody is in a hurry.
 */
const ASK = fileURLToPath(new URL('.', import.meta.url));

/** Every non-test `.ts`/`.tsx` under `view/ask/`, path relative to it. */
function askSources(dir = ASK, prefix = ''): { path: string; text: string }[] {
  const found: { path: string; text: string }[] = [];
  for (const entry of readdirSync(dir)) {
    const full = `${dir}${entry}`;
    if (statSync(full).isDirectory()) {
      found.push(...askSources(`${full}/`, `${prefix}${entry}/`));
    } else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
      found.push({ path: `${prefix}${entry}`, text: readFileSync(full, 'utf8') });
    }
  }
  return found;
}

describe('the ask path is read-only with respect to the document', () => {
  it('finds sources to check', () => {
    // A walker that silently matches nothing would pass every assertion below.
    const paths = askSources().map((s) => s.path);
    expect(paths).toContain('AskPanel.tsx');
    expect(paths.length).toBeGreaterThan(3);
  });

  it('writes no node field anywhere in the ask path', () => {
    const offenders = askSources()
      .filter((s) => /\.setField\s*\(/.test(s.text))
      .map((s) => s.path);
    expect(offenders).toEqual([]);
  });

  it('issues no command that would mutate the document', () => {
    // `setField` was the instance. These are the neighbouring doors to the
    // same room — a run reports, it does not edit, whichever verb it reaches
    // for. `setNodeRuntime` is deliberately absent from this list: run state
    // is exactly what the ask path is *supposed* to write.
    const forbidden = /\.(setNodeData|setNodeTitle|addNode|removeNode|setNodeParent)\s*\(/;
    const offenders = askSources()
      .filter((s) => forbidden.test(s.text))
      .map((s) => s.path);
    expect(offenders).toEqual([]);
  });
});
