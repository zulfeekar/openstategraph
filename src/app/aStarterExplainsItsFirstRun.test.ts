import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { beforeEach, describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import type { KeyValueStore } from '@app/workflowStore';
import {
  BEFORE_RUN_MARKER,
  FIRST_RUN_NOTE,
  afterRunNote,
  explainFirstRun,
  placeFirstRunStarter,
  starterNoteAwaitingRun,
} from '@app/firstRunStarter';

/**
 * `stable-beta-public/06`, slice 2 — **the note explains the run it just
 * watched.**
 *
 * Slice 1 put a question in the Input and a note saying *press Run*. A note
 * that still says "press Run" after the run is a note that has stopped being
 * true, and the whole promise of the first visit is one press to a real
 * answer that is then **accounted for**: which model answered, what it cost,
 * and what to change next.
 *
 * Three properties are asserted here and each of them is a way the rewrite
 * could go wrong:
 *
 * - **Once.** The marker (`BEFORE_RUN_MARKER`, a zero-width last line) is the
 *   only record of "this note is still waiting". The rewrite drops it, so a
 *   second run finds nothing to write and leaves the user's note — which by
 *   then they may have edited — alone.
 * - **Undoable.** It goes through `controller.nodes.setField`, a
 *   `SetFieldCommand`, so one Cmd-Z puts the before-run text back. Anything
 *   that wrote to the node model directly would be a canvas the history
 *   cannot account for.
 * - **Theirs to delete.** The before-run note says deleting it costs nothing
 *   else. A rewrite that re-created a deleted note would make that sentence
 *   false.
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

/** The starter, placed, exactly as a first visit leaves it. */
function placed(): Workbench {
  const workbench = new Workbench();
  placeFirstRunStarter(workbench, new FakeStore());
  return workbench;
}

/**
 * The note's id **in the placed document**, which is not `NOTE_ID`.
 * `insertFragment` routes through `pasteCommand`, so every node arrives with a
 * freshly minted id — the fragment's `NOTE_ID` is the source id and nothing
 * more. That is exactly why the marker exists rather than a lookup by id.
 */
function noteId(workbench: Workbench) {
  const found = starterNoteAwaitingRun(workbench);
  if (found == null) throw new Error('no awaiting note');
  return found;
}

function noteBody(workbench: Workbench): string {
  const note = workbench.model.nodes().find((node) => node.type === 'annotate.note') as
    { data: Record<string, unknown> } | undefined;
  return String(note?.data['body'] ?? '');
}

const A_RUN = { ok: true as const, models: ['mock-offline'], totalTokens: 1522 };

describe('finding the note that is still waiting', () => {
  it('is the placed note, by its own id', () => {
    const workbench = placed();
    const found = starterNoteAwaitingRun(workbench);
    expect(found).not.toBeNull();
    expect(workbench.model.node(found!)?.type).toBe('annotate.note');
  });

  it('is nobody once the note has been rewritten', () => {
    const workbench = placed();
    explainFirstRun(workbench, A_RUN);
    expect(starterNoteAwaitingRun(workbench)).toBeNull();
  });

  it('is nobody on a canvas that never held a starter', () => {
    expect(starterNoteAwaitingRun(new Workbench())).toBeNull();
  });

  /**
   * A note the user wrote themselves, at the starter's own id, would still be
   * found by id — the marker is what says *this is still the note we wrote*.
   * Editing it is enough to be left alone.
   */
  it('is nobody once the user has edited the note', () => {
    const workbench = placed();
    workbench.controller.nodes.setField(noteId(workbench), 'body', 'my own notes');
    expect(starterNoteAwaitingRun(workbench)).toBeNull();
  });
});

describe('a finished run rewrites the note once', () => {
  let workbench: Workbench;
  beforeEach(() => {
    workbench = placed();
  });

  it('names the model and what it spent', () => {
    expect(explainFirstRun(workbench, A_RUN)).toBe(true);
    const body = noteBody(workbench);
    expect(body).toContain('mock-offline');
    expect(body).toContain((1522).toLocaleString());
  });

  it('stops saying press Run, and stops carrying the marker', () => {
    explainFirstRun(workbench, A_RUN);
    const body = noteBody(workbench);
    expect(body).not.toMatch(/press Run to see it answered/i);
    expect(body.endsWith(BEFORE_RUN_MARKER)).toBe(false);
  });

  it('says what to change next', () => {
    explainFirstRun(workbench, A_RUN);
    expect(noteBody(workbench)).toMatch(/Input/);
  });

  it('leaves the second run alone — the note may be the user’s by then', () => {
    explainFirstRun(workbench, A_RUN);
    const afterFirst = noteBody(workbench);
    expect(explainFirstRun(workbench, { ok: true, models: ['other'], totalTokens: 9 })).toBe(false);
    expect(noteBody(workbench)).toBe(afterFirst);
  });

  /**
   * Program design, least-confident decision 3: a run touching several models
   * names the first and counts the rest, rather than printing a list into a
   * note whose whole argument is that it is short.
   */
  it('names the first model and counts the others', () => {
    explainFirstRun(workbench, { ok: true, models: ['a-model', 'b-model'], totalTokens: 10 });
    const body = noteBody(workbench);
    expect(body).toContain('a-model');
    expect(body).toMatch(/1 more/);
    expect(body).not.toContain('b-model');
  });

  it('still reads as a sentence when no model can be named', () => {
    explainFirstRun(workbench, { ok: true, models: [], totalTokens: 10 });
    expect(noteBody(workbench)).toContain((10).toLocaleString());
  });
});

describe('a failed run names the reason', () => {
  it('quotes the reason the run gave, not a generic failure', () => {
    const workbench = placed();
    expect(explainFirstRun(workbench, { ok: false, reason: 'No model is configured.' })).toBe(true);
    expect(noteBody(workbench)).toContain('No model is configured.');
  });

  it('stays under the ceiling even when the reason is enormous', () => {
    const note = afterRunNote({ ok: false, reason: 'x'.repeat(2000) });
    expect(note.length).toBeLessThan(400);
  });
});

describe('a deleted note is left alone', () => {
  it('writes nothing and pushes no command', () => {
    const workbench = placed();
    const id = noteId(workbench);
    workbench.controller.nodes.delete([id]);
    const before = workbench.controller.history.canUndo;
    workbench.controller.history.undo();
    workbench.controller.history.redo();
    expect(before).toBe(true);

    expect(explainFirstRun(workbench, A_RUN)).toBe(false);
    // Nothing was pushed, so the top of the stack is still the delete.
    workbench.controller.history.undo();
    expect(workbench.model.hasNode(id)).toBe(true);
    expect(noteBody(workbench)).toBe(FIRST_RUN_NOTE);
  });
});

describe('the rewrite is one undoable step', () => {
  it('one undo puts the before-run note back', () => {
    const workbench = placed();
    explainFirstRun(workbench, A_RUN);
    expect(noteBody(workbench)).not.toBe(FIRST_RUN_NOTE);

    workbench.controller.history.undo();
    expect(noteBody(workbench)).toBe(FIRST_RUN_NOTE);
    // And the starter itself is still one further undo away — the rewrite did
    // not merge into the paste that placed it.
    workbench.controller.history.undo();
    expect(workbench.model.nodeCount).toBe(0);
  });
});

describe('the after-run wordings are as short as the before-run one', () => {
  const wordings = [
    afterRunNote({ ok: true, models: ['gpt-oss:120b-cloud'], totalTokens: 1522 }),
    afterRunNote({ ok: true, models: ['a', 'b', 'c'], totalTokens: 999999 }),
    afterRunNote({ ok: true, models: [], totalTokens: 0 }),
    afterRunNote({ ok: false, reason: 'The provider refused the request.' }),
  ];

  it('every one of them is under 400 characters', () => {
    for (const wording of wordings) expect(wording.length).toBeLessThan(400);
  });

  it('none of them still carries the before-run marker', () => {
    for (const wording of wordings) expect(wording.endsWith(BEFORE_RUN_MARKER)).toBe(false);
  });
});

/**
 * Where the rewrite is wired, read from the source.
 *
 * The plan put it in `AppShell.tsx`'s `run:finish` handler. That handler
 * belongs to `workbench.engine` — the canvas's own preview walk — and nothing
 * in the shipped app calls `engine.run()` any more: the toolbar's Run opens
 * the chat and streams a backend run. Found by pressing Run in the browser: a
 * run finished, spent 2,455 tokens, and the note did not move. So the rewrite
 * reads the `runView` snapshot the run dock is already drawn from, and this
 * pins that it is still read from a *finished* run rather than from every
 * frame of a live one.
 */
describe('the wiring, read from the source', () => {
  const source = readFileSync(
    join(fileURLToPath(new URL('.', import.meta.url)), '..', 'view', 'AppShell.tsx'),
    'utf8',
  );

  it('rewrites from a finished run, never mid-stream', () => {
    expect(source).toMatch(/if \(shownRun\.source !== 'live' \|\| shownRun\.running\) return;/);
    expect(source).toMatch(/explainFirstRun\(workbench, \{/);
  });

  it('names the models the run itself reported, one row per model', () => {
    expect(source).toMatch(/models: usage\.map\(\(row\) => row\.model\)/);
  });
});
