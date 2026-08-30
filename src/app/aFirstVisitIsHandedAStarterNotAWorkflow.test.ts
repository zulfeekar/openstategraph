import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { beforeEach, describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import {
  mostRecentWorkflowId,
  newWriteGuard,
  resolveSession,
  type KeyValueStore,
} from '@app/workflowStore';
import { restoreSessionDraft } from '@app/workflowDrafts';
import { readSlugFromSearch, resolveOpenRequest } from '@app/openWorkflow';
import { UNNAMED_DOCUMENT } from '@core/model/documentName';
import { starterAssembly } from '@nodes/assemblies';
import { EMPTY_CANVAS_HINT } from '@view/canvas/emptyStateCopy';
import {
  FIRST_RUN_NOTE,
  STARTER_PLACED_KEY,
  firstRunFragment,
  hasPlacedStarter,
  placeFirstRunStarter,
  shouldPlaceStarter,
} from '@app/firstRunStarter';

/**
 * `install-experience` 24 — **the first visit is handed a starter, and it is
 * the opposite of what 23 deleted.**
 *
 * 23 (`be3af73`) removed two things that put a document on a canvas nobody had
 * asked for: a 13-node package compiled into the dev bundle, and the adoption
 * of whatever draft this *origin* held last. Both wore a name, both looked
 * saved, and neither announced itself. This ticket puts three nodes back — and
 * the whole of its argument is in the ways it is not that.
 *
 * | 23's defect | this |
 * | --- | --- |
 * | somebody's **named package**, 13 nodes | a starter, three nodes and a note |
 * | a plausible title and a `Draft` badge | `Untitled`, unsaved, no slug minted |
 * | silent | a Note on the canvas saying what it is and how to delete it |
 * | on **every** load with no session draft | once, ever, in a browser that has never held work |
 *
 * The last row is the one that matters most, and it is the one asserted hardest
 * below. 23's adoption fired for *every genuinely new tab* — a browser restart
 * was enough. This fires when `localStorage` holds **no draft at all** and no
 * marker, which is a state a browser is in exactly once.
 *
 * ## Not a second definition of the starter
 *
 * `starterAssembly` (production-ready 22) already *is* Input → Agent → Output,
 * wired, in the clipboard's fragment shape. A first-run document that spelled
 * those three nodes out again would be two descriptions of one thing, drifting
 * from the first time either changed. `firstRunFragment` composes the shipped
 * assembly and adds a Note; the assertions below are written against
 * `starterAssembly.fragment` rather than against literals, so they fail if the
 * composition is ever replaced by a copy.
 *
 * ## Not saved, and deliberately
 *
 * `the-look-has-an-author-now` (`91f37a2`) made a first save **ask for a
 * name**, because the backend mints the slug from that name and freezes it — a
 * slug is a directory. Auto-saving a starter would mint `workflows/untitled/`
 * permanently from a word nobody chose, which is the defect that work removed
 * arriving through a different door. The document keeps `WorkflowModel`'s own
 * unnamed name; the top bar already says `Untitled`; nothing is written to
 * disk until the user saves and is asked.
 */

class FakeStore implements KeyValueStore {
  private readonly map = new Map<string, string>();
  get length(): number {
    return this.map.size;
  }
  key(index: number): string | null {
    return [...this.map.keys()][index] ?? null;
  }
  getItem(key: string): string | null {
    return this.map.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.map.set(key, value);
  }
  removeItem(key: string): void {
    this.map.delete(key);
  }
}

/** A store whose every access throws, the way a locked-down browser's does. */
class ThrowingStore implements KeyValueStore {
  get length(): number {
    throw new Error('storage is not available');
  }
  key(): string | null {
    throw new Error('storage is not available');
  }
  getItem(): string | null {
    throw new Error('storage is not available');
  }
  setItem(): void {
    throw new Error('storage is not available');
  }
  removeItem(): void {
    throw new Error('storage is not available');
  }
}

/** The state a browser that has never opened this editor is in. */
const freshInstall = {
  opening: 'restore' as const,
  restored: false,
  nodeCount: 0,
  mostRecentId: null,
  alreadyPlaced: false,
};

describe('when the starter is placed', () => {
  it('is placed on a first visit — no draft, no marker, no URL', () => {
    expect(shouldPlaceStarter(freshInstall)).toBe(true);
  });

  it('is not placed a second time, which is how deleting it sticks', () => {
    expect(shouldPlaceStarter({ ...freshInstall, alreadyPlaced: true })).toBe(false);
  });

  /**
   * The row of the table above that separates this from 23. 23's adoption fired
   * for every tab whose own `sessionStorage` was empty, so a browser restart
   * re-served somebody's graph. One draft in this browser — anybody's, under any
   * key — means this browser has been worked in, and a starter would be teaching
   * somebody who is past the lesson.
   */
  it('is not placed in a browser that already holds work', () => {
    expect(shouldPlaceStarter({ ...freshInstall, mostRecentId: 'wf-1788075804900' })).toBe(false);
  });

  it('is not placed when the URL named a workflow', () => {
    expect(shouldPlaceStarter({ ...freshInstall, opening: 'fetch' })).toBe(false);
  });

  it('is not placed over a document the session restored', () => {
    expect(shouldPlaceStarter({ ...freshInstall, restored: true })).toBe(false);
  });

  /**
   * The belt to the restore branch's braces, and it is not redundant: `?demo=1`
   * seeds the canvas in `main.tsx`, before React exists and before any of the
   * inputs above can see it. A non-empty model is the only evidence of that seed
   * this decision can read.
   */
  it('is not placed onto a canvas that already has nodes', () => {
    expect(shouldPlaceStarter({ ...freshInstall, nodeCount: 13 })).toBe(false);
  });
});

describe('remembering that it was placed', () => {
  let store: FakeStore;
  beforeEach(() => {
    store = new FakeStore();
  });

  it('says no before anything happened, and yes afterwards', () => {
    expect(hasPlacedStarter(store)).toBe(false);
    placeFirstRunStarter(new Workbench(), store);
    expect(hasPlacedStarter(store)).toBe(true);
    expect(store.getItem(STARTER_PLACED_KEY)).not.toBeNull();
  });

  /**
   * Fails **safe**, and the safe direction is *do not place*. A store that
   * throws cannot remember a dismissal, so the other direction would put the
   * starter back on every single load with no way to be rid of it — which is
   * precisely 23's symptom, rebuilt out of an exception handler.
   */
  it('reports placed when the store cannot be read at all', () => {
    expect(hasPlacedStarter(new ThrowingStore())).toBe(true);
  });

  it('places without throwing when the store cannot be written', () => {
    const workbench = new Workbench();
    expect(() => placeFirstRunStarter(workbench, new ThrowingStore())).not.toThrow();
    expect(workbench.model.nodeCount).toBe(4);
  });
});

describe('what is placed', () => {
  it('is the shipped assembly, not a second copy of it', () => {
    const types = firstRunFragment().nodes.map((node) => node.type);
    const assemblyTypes = starterAssembly.fragment.nodes.map((node) => node.type);
    expect(types).toEqual(['annotate.note', ...assemblyTypes]);
    expect(firstRunFragment().edges).toEqual(starterAssembly.fragment.edges);
  });

  it('reads top to bottom: the note first, then the flow it describes', () => {
    const nodes = firstRunFragment().nodes;
    const note = nodes[0]!;
    for (const node of nodes.slice(1)) {
      expect(node.position.y).toBeGreaterThan(note.position.y);
    }
  });

  it('starts at its own origin, so a paste at that point lands where it was drawn', () => {
    const fragment = firstRunFragment();
    expect(fragment.origin.x).toBe(Math.min(...fragment.nodes.map((node) => node.position.x)));
    expect(fragment.origin.y).toBe(Math.min(...fragment.nodes.map((node) => node.position.y)));
  });

  it('lands as ordinary nodes and ordinary edges', () => {
    const workbench = new Workbench();
    placeFirstRunStarter(workbench, new FakeStore());

    const document = JSON.parse(workbench.controller.document.exportJSON()) as {
      nodes: { type: string }[];
      edges: unknown[];
    };
    expect(document.nodes.map((node) => node.type)).toContain('annotate.note');
    expect(document.edges).toHaveLength(2);
    // Nothing in the document remembers a starter was involved — the property
    // that keeps `workflow.json` portable, and the property that makes deleting
    // the four nodes a complete removal.
    expect(JSON.stringify(document)).not.toContain('firstRun');
  });

  it('carries no question of its own', () => {
    // The starter assembly's own rule, inherited rather than restated: Run reads
    // the Input, and a seeded question is one the user never asked being spent
    // on the first press.
    const input = firstRunFragment().nodes.find((node) => node.type === 'input.text');
    expect(String(input?.data?.['prompt'] ?? '')).toBe('');
  });

  it('leaves the document unnamed, so no slug is minted from a word nobody chose', () => {
    const workbench = new Workbench();
    placeFirstRunStarter(workbench, new FakeStore());
    expect(workbench.model.name).toContain(UNNAMED_DOCUMENT);
  });

  it('selects nothing, so the first Backspace does not empty the canvas', () => {
    // The note says deleting it leaves the three nodes; four selected nodes and
    // one keystroke would make that sentence false.
    const workbench = new Workbench();
    placeFirstRunStarter(workbench, new FakeStore());
    expect(workbench.controller.selection.nodes).toEqual([]);
  });

  it('is one undo', () => {
    const workbench = new Workbench();
    placeFirstRunStarter(workbench, new FakeStore());
    workbench.controller.history.undo();
    expect(workbench.model.nodeCount).toBe(0);
  });
});

describe('what the note says', () => {
  it('names the three nodes, in the order they are wired', () => {
    expect(FIRST_RUN_NOTE.indexOf('Input')).toBeGreaterThanOrEqual(0);
    expect(FIRST_RUN_NOTE.indexOf('Input')).toBeLessThan(FIRST_RUN_NOTE.indexOf('Agent'));
    expect(FIRST_RUN_NOTE.indexOf('Agent')).toBeLessThan(FIRST_RUN_NOTE.indexOf('Output'));
  });

  it('says what to do next, and it is one gesture', () => {
    expect(FIRST_RUN_NOTE).toMatch(/press Run/i);
  });

  /** The half a stranger cannot deduce: this is a starting point, not a save. */
  it('says nothing is saved yet, in the word the top bar uses', () => {
    expect(FIRST_RUN_NOTE).toContain(UNNAMED_DOCUMENT);
  });

  it('says it can be deleted, and that deleting it costs nothing else', () => {
    expect(FIRST_RUN_NOTE).toMatch(/delete/i);
  });

  /**
   * The canvas is not a manual — and this is the assertion that stops the next
   * session answering a support question by adding a paragraph here.
   */
  it('is short', () => {
    expect(FIRST_RUN_NOTE.length).toBeLessThan(400);
  });
});

/**
 * Two teachers saying the same thing at once is worse than one.
 *
 * `emptyStateCopy` (production-ready 22/23) already teaches Input → Agent →
 * Output on the empty canvas. It survives unchanged, and nothing here competes
 * with it, because the two are **mutually exclusive by construction**:
 * `CanvasStage`'s `EmptyState` renders only while `model.nodeCount === 0`, and
 * `shouldPlaceStarter` is true only while the same count is zero. Place the
 * starter and the empty state is gone; delete the starter and it is back,
 * which is the right teacher for a canvas somebody emptied on purpose.
 *
 * So the division of labour is: the empty state says *how to get the three
 * nodes*; the note says *what the three nodes in front of you are*. The
 * assertion is that the note does not repeat the sentence whose whole job is
 * the other case.
 */
describe('beside the empty-canvas guidance, not on top of it', () => {
  it('does not tell a user holding the starter how to drag the starter', () => {
    expect(FIRST_RUN_NOTE).not.toContain(EMPTY_CANVAS_HINT);
    expect(FIRST_RUN_NOTE).not.toContain('palette');
  });

  it('is offered only where the empty state would be showing', () => {
    // The one true case has `nodeCount: 0` — the exact condition `EmptyState`
    // renders on. There is no arrangement in which both speak.
    expect(shouldPlaceStarter(freshInstall)).toBe(true);
    expect(freshInstall.nodeCount).toBe(0);
  });
});

/**
 * The page load itself, run in the hook's own order.
 *
 * `useWorkflowSession` cannot be reached without a DOM, so this drives the same
 * functions in the same sequence — which is exactly how
 * `aBareUrlOpensNobodysWorkflow.test.ts` reaches the decisions it is about, and
 * for the same reason. The shape of the call in `WorkbenchContext.tsx` is
 * pinned separately below, so a rewiring cannot leave this file passing about
 * a sequence the app no longer runs.
 */
describe('a page load, in the hook’s order', () => {
  let local: FakeStore;

  beforeEach(() => {
    local = new FakeStore();
  });

  function pageLoad(search: string): Workbench {
    const workbench = new Workbench();
    const request = resolveOpenRequest({
      urlSlug: readSlugFromSearch(search),
      openSlug: null,
      hasDraft: false,
    });
    const mostRecentId = mostRecentWorkflowId(local);
    const session = resolveSession({
      sessionId: null,
      mostRecentId,
      mintId: () => 'wf-minted',
    });
    const restore = restoreSessionDraft(session, workbench, newWriteGuard(), local);
    if (
      shouldPlaceStarter({
        opening: request.action,
        restored: restore.restored,
        nodeCount: workbench.model.nodeCount,
        mostRecentId,
        alreadyPlaced: hasPlacedStarter(local),
      })
    ) {
      placeFirstRunStarter(workbench, local);
    }
    return workbench;
  }

  it('hands the stranger four nodes and a note', () => {
    const workbench = pageLoad('');
    expect(workbench.model.nodeCount).toBe(4);
    expect(workbench.model.name).toContain(UNNAMED_DOCUMENT);
  });

  /**
   * The walk the ticket asks for, as a test: see it, delete it, come back.
   * Nothing about the deletion is recorded anywhere — the marker was written
   * when it was *placed*, which is what makes an ordinary delete permanent.
   */
  it('stays gone once it is deleted', () => {
    const first = pageLoad('');
    first.model.nodes().forEach((node) => first.model.removeNode(node.id));
    expect(first.model.nodeCount).toBe(0);

    expect(pageLoad('').model.nodeCount).toBe(0);
  });

  it('writes nothing to storage but the marker, so no draft is invented', () => {
    pageLoad('');
    const keys = [...Array(local.length).keys()].map((index) => local.key(index));
    expect(keys).toEqual([STARTER_PLACED_KEY]);
  });

  it('leaves a deep link alone', () => {
    expect(pageLoad('?w=chinook-assistant').model.nodeCount).toBe(0);
  });
});

describe('the wiring, read from the source', () => {
  /**
   * `WorkbenchContext.tsx` needs a DOM and a React tree, so the sequence above
   * is a model of it rather than a run of it. What can be checked without one
   * is that the app still asks the question — and asks it with the inputs the
   * decision was designed around, `mostRecentId` most of all. Read rather than
   * executed, the way `seedDemo.test.ts` pins `main.tsx`'s one line.
   */
  it('asks before it places, with the browser’s own draft state in hand', () => {
    const source = readFileSync(
      join(fileURLToPath(new URL('.', import.meta.url)), 'WorkbenchContext.tsx'),
      'utf8',
    );
    expect(source).toMatch(/if \(\s*shouldPlaceStarter\(\{/);
    expect(source).toMatch(/alreadyPlaced: hasPlacedStarter\(localStorage\)/);
    expect(source).toMatch(/placeFirstRunStarter\(workbench, localStorage\)/);
    // Read once, before anything below it can write — otherwise a browser that
    // has just been handed a starter looks, on the next line, like one that
    // always had work in it.
    expect(source.indexOf('const mostRecentId = mostRecentWorkflowId(localStorage)')).toBeLessThan(
      source.indexOf('shouldPlaceStarter({'),
    );
  });
});
