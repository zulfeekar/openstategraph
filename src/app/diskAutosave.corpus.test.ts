import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Ok } from '@core/kernel/Result';
import type { IWorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import { Workbench } from '@app/Workbench';
import { registerNodeTypesForRawDocument } from '@nodes/workflowScoped';
import { forgetDiskDocument, rememberDiskDocument, writeOpenWorkflowToDisk } from './diskAutosave';
import { CURRENT_SLUG_KEY } from './workflowFileWatch';

/**
 * production-ready ticket 27 — **opening a committed package must not rewrite
 * it**, asserted at the autosave seam against the real corpus.
 *
 * The defect this pins was reported three times and finally caught with bytes:
 * `workflows/concierge/workflow.json` came back with 256 changed lines and a
 * fresh `savedAt` after an agent merely drilled into `concierge/wf-music`.
 * Nothing authored had changed — a field-by-field comparison of the file
 * against what the editor wrote found **zero keys lost and zero values
 * altered**. All 256 lines were mechanical:
 *
 * - the `nodes` and `edges` arrays reordered into `WorkflowModel.toJSON`'s
 *   canonical sort, where the file held authoring order;
 * - `"parentId": null` added to every node, which the file omits;
 * - schema defaults materialised into `data` — 51 keys on `concierge`, 53 on
 *   `chinook-assistant`, every one of them a default (`maxRetries: ""`,
 *   `rulesMode: "extend"`, `tier: "react"`, `tokenBudget: 500`, …).
 *
 * `size` was added too, and is *not* implicated: `comparable()` strips it, and
 * that exclusion still holds. The trigger was the other three.
 *
 * So the baseline was comparing two different normal forms of the same
 * document — the file's authored one against the model's canonical one — and
 * could never match. `rememberDiskDocument` called that "one normalising
 * write" that converges. It converges in a working copy; for a git-tracked
 * corpus it converges never, because the committed file is always the authored
 * form, so **every developer, on every fresh checkout, dirties every package
 * they open**.
 *
 * The existing unit tests missed it by seeding the baseline from
 * `serializer.serialize(model)` — already canonical, both sides normal — while
 * the load path seeds from the raw file. This suite seeds the way production
 * seeds, and does it over every document the repository actually ships.
 */

interface Fixture {
  readonly label: string;
  readonly document: Record<string, unknown>;
}

const corpus = (): Fixture[] => {
  const roots: readonly (readonly [string, string])[] = [
    ['workflows', join(process.cwd(), 'workflows')],
    ['examples', join(process.cwd(), 'backend', 'openstategraph', 'examples')],
  ];
  const found: Fixture[] = [];
  for (const [area, root] of roots) {
    if (!existsSync(root)) continue;
    for (const entry of readdirSync(root, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const file = join(root, entry.name, 'workflow.json');
      if (!existsSync(file)) continue;
      const envelope = JSON.parse(readFileSync(file, 'utf8')) as Record<string, unknown>;
      // Each file is a package envelope (`version`, `name`, `savedAt`,
      // `document`); the editor round-trips the inner document.
      const document = (envelope['document'] ?? envelope) as Record<string, unknown>;
      found.push({ label: `${area}/${entry.name}`, document });
    }
  }
  return found;
};

const fixtures = corpus();

// The suite runs in node, so there is no DOM storage — the same stub
// `diskAutosave.test.ts` uses, for the same reason.
const store = new Map<string, string>();
(globalThis as { sessionStorage?: unknown }).sessionStorage = {
  getItem: (key: string) => store.get(key) ?? null,
  setItem: (key: string, value: string) => void store.set(key, value),
  removeItem: (key: string) => void store.delete(key),
  clear: () => store.clear(),
  key: () => null,
  length: 0,
} satisfies Storage;

const storageWith = (slug: string): Pick<Storage, 'getItem'> => ({
  getItem: (key: string) => (key === CURRENT_SLUG_KEY ? slug : null),
});

afterEach(() => {
  store.clear();
  forgetDiskDocument('corpus-slug');
});

describe('opening a shipped package writes nothing to its file', () => {
  it('finds the shipped corpus', () => {
    // Both halves, so a moved directory degrades to a failure rather than to a
    // green run over nothing.
    expect(fixtures.filter((f) => f.label.startsWith('workflows/')).length).toBeGreaterThan(0);
    expect(fixtures.filter((f) => f.label.startsWith('examples/')).length).toBeGreaterThan(0);
  });

  it.each(fixtures.map((f) => [f.label, f] as const))('%s', async (_label, fixture) => {
    const save = vi.fn(async () => Ok({ digest: 'sha-written' }));
    const workbench = new Workbench();
    // The same pre-registration the load path performs, so a package whose own
    // hand-authored family exists is measured against its real cards rather
    // than against the unknown-node placeholder — the placeholder materialises
    // no defaults, which would hide the very difference under test.
    registerNodeTypesForRawDocument(
      fixture.document,
      workbench.registry,
      workbench.engine.executors,
    );

    // Exactly the order `loadWorkflowIntoEditor` uses: import the file, then
    // record what disk holds. The baseline is seeded from the **raw file**,
    // because that is what production does and what the old unit tests did not.
    const imported = workbench.controller.document.importJSON(JSON.stringify(fixture.document));
    expect(imported.ok).toBe(true);
    rememberDiskDocument(
      'corpus-slug',
      workbench.model.name,
      fixture.document,
      workbench.serializer,
    );

    // Nothing has been touched since. The autosave tick that the import's own
    // `onChange` scheduled must find nothing to write.
    const outcome = await writeOpenWorkflowToDisk(
      { save } as unknown as Pick<IWorkflowFileClient, 'save'>,
      workbench.model,
      workbench.serializer,
      storageWith('corpus-slug'),
    );

    expect(outcome).toEqual({ kind: 'unchanged' });
    expect(save).not.toHaveBeenCalled();
  });
});

describe('the canonical form is a fixed point', () => {
  // What makes the comparison above sound. Two documents are compared by
  // canonicalising both; if canonicalising were not idempotent, the model's own
  // output would canonicalise to something else again and the baseline would
  // drift on the second tick instead of the first.
  it.each(fixtures.map((f) => [f.label, f] as const))('%s', (_label, fixture) => {
    const workbench = new Workbench();
    registerNodeTypesForRawDocument(
      fixture.document,
      workbench.registry,
      workbench.engine.executors,
    );

    const once = workbench.serializer.canonicalise(fixture.document);
    const twice = workbench.serializer.canonicalise(once);
    expect(twice).toEqual(once);

    // And it loses nothing: every node by id and type, every link by its
    // endpoints. Canonicalising is a normalisation, not an edit.
    const before = fixture.document as {
      nodes: readonly { id: string; type: string }[];
      edges: readonly {
        source: { nodeId: string; portId: string };
        target: { nodeId: string; portId: string };
      }[];
    };
    const after = once as typeof before;
    expect(after.nodes.map((n) => `${n.id}:${n.type}`).sort()).toEqual(
      before.nodes.map((n) => `${n.id}:${n.type}`).sort(),
    );
    const key = (e: (typeof before.edges)[number]): string =>
      `${e.source.nodeId}/${e.source.portId} -> ${e.target.nodeId}/${e.target.portId}`;
    expect(after.edges.map(key).sort()).toEqual(before.edges.map(key).sort());
  });
});
