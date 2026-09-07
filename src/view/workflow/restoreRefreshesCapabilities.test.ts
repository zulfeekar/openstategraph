import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * A warm reload must not run on the previous load's capabilities
 * (`every-workflow-green` 07).
 *
 * **Measured**, same URL, same backend, same second:
 *
 * | tab | `GET …/capabilities` |
 * | --- | --- |
 * | cold — fresh, storage cleared | fires, 200 |
 * | warm — already had this workflow open | never requested |
 *
 * `useDeepLinkedWorkflow`'s restore branch is **right** not to refetch the
 * document: this tab's autosave holds unsaved edits and refetching over them
 * discards work. That guard stays.
 *
 * But capabilities were fetched *inside* `loadWorkflowIntoEditor` — the very
 * function restore skips — so the two were welded together by accident. Every
 * plain reload therefore ran on whatever capability picture the last cold load
 * left behind: a tool added to `tools/` since then invisible, a `pip install`
 * invisible, and the capability **warnings** — the channel built so a
 * half-authored tool is never silent — stale.
 *
 * **The separation is the fix.** The document and the capability picture have
 * different staleness rules: one must not be refetched over local edits, the
 * other has no local edits to protect and can always be refreshed.
 *
 * A source assertion, for the reason the other deep-link tests record: this is
 * a wiring fact between two modules, and there is no seam in a `node`
 * environment that would catch the call going missing.
 */
const hook = readFileSync(
  fileURLToPath(new URL('./useDeepLinkedWorkflow.ts', import.meta.url)),
  'utf8',
);

/** The restore branch's source, from its `if` to the end of that block. */
function restoreBranch(): string {
  const at = hook.indexOf("if (request.action === 'restore')");
  expect(at, 'restore branch not found').toBeGreaterThan(-1);
  const rest = hook.slice(at);
  const end = rest.indexOf('\n    }\n');
  return end === -1 ? rest : rest.slice(0, end);
}

describe('a restored reload', () => {
  it('refreshes capabilities', () => {
    expect(restoreBranch()).toContain('refreshWorkflowCapabilities');
  });

  it('still does not refetch the document', () => {
    // The guard this ticket must not weaken. `loadWorkflowIntoEditor` is the
    // document fetch; restore must never call it, or a reload discards the
    // unsaved edits the branch exists to protect.
    expect(restoreBranch()).not.toContain('loadWorkflowIntoEditor(');
  });

  it('imports the refresh from the one module that owns it', () => {
    // Not a second capabilities fetch written here — `refreshWorkflowCapabilities`
    // already unregisters what disappeared and keeps the Refresh baseline
    // honest, and a private copy would drift from it.
    expect(hook).toMatch(
      /import \{[^}]*refreshWorkflowCapabilities[^}]*\} from '@app\/capabilityRefresh'/s,
    );
  });
});
