import { describe, expect, it, vi, beforeEach } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join, relative } from 'node:path';
import { Ok, Err } from '@core/kernel/Result';
import { writeHostPackage } from '@app/hostPackageWrite';
import { draftIdForSlug } from '@app/workflowDrafts';
import {
  newWriteGuard,
  readWorkflow,
  saveWorkflow as writeDraft,
  type KeyValueStore,
} from '@app/workflowStore';
import { recordKnownSavedAt } from '@app/workflowFileWatch';
import { Workbench } from '@app/Workbench';

/**
 * **A third writer of a host package cannot forget** — `production-ready` 102.
 *
 * 101 was data loss: the parent of an open mount is written while it is not
 * the document on screen, so this browser's draft of the parent becomes a
 * mirror of a version this browser has itself superseded, and Back restores it
 * over the fresh file. The fix — `supersedeDraftAfterHostWrite` — was called
 * from the two writers that existed, and 101 said in its own commit what that
 * did not achieve: *a third future host writer would compile and reintroduce
 * the deletion.*
 *
 * **Measured before anything was changed rather than assumed.** A third writer
 * was added to `src/app/`, saving `mounts.rootDocument` and superseding
 * nothing. It typechecked, and the whole suite — 2495 tests, 198 files —
 * stayed green.
 *
 * The protocol now lives in one place (`app/hostPackageWrite.ts`), which is
 * what makes a third writer *likely* to be right. This file is what makes it
 * *noisy* when it is not, because no signature can stop code calling
 * `client.save` directly.
 */

const SRC = new URL('../', import.meta.url).pathname;

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sourceFiles(path));
    else if (/\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) out.push(path);
  }
  return out;
}

/** The argument list of every `.save(` call in `text`, brackets balanced. */
function saveCallArguments(text: string): string[] {
  const calls: string[] = [];
  const marker = /\.save\(/g;
  let hit: RegExpExecArray | null;
  while ((hit = marker.exec(text)) !== null) {
    let depth = 1;
    let i = hit.index + hit[0].length;
    const from = i;
    while (i < text.length && depth > 0) {
      if (text[i] === '(') depth += 1;
      else if (text[i] === ')') depth -= 1;
      i += 1;
    }
    calls.push(text.slice(from, i - 1));
  }
  return calls;
}

/**
 * The one module allowed to hand a host document to a `save`, and the one
 * module allowed to call the supersede rule. Both are the seam.
 */
const THE_SEAM = 'app/hostPackageWrite.ts';
/** Where the rule is *defined*; a definition is not a call site. */
const WHERE_THE_RULE_LIVES = 'app/workflowDrafts.ts';

describe('the host-write seam', () => {
  it('is the only place a host document reaches a save call', () => {
    const offenders = sourceFiles(SRC)
      .filter((path) => {
        const text = readFileSync(path, 'utf8');
        return saveCallArguments(text).some((args) => args.includes('rootDocument'));
      })
      .map((path) => relative(SRC, path));

    expect(offenders).toEqual([THE_SEAM]);
  });

  it('is the only place the draft-supersede rule is called', () => {
    const callers = sourceFiles(SRC)
      .filter((path) => readFileSync(path, 'utf8').includes('supersedeDraftAfterHostWrite('))
      .map((path) => relative(SRC, path));

    // `workflowDrafts` declares it — `export function supersedeDraftAfterHostWrite(`
    // matches the same needle, and a definition is not a second call site.
    expect(callers.sort()).toEqual([THE_SEAM, WHERE_THE_RULE_LIVES].sort());
  });
});

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

describe('what the seam does with a draft', () => {
  let store: FakeStore;

  beforeEach(() => {
    store = new FakeStore();
    vi.stubGlobal('localStorage', store);
    vi.stubGlobal('sessionStorage', new FakeStore());
  });

  function aDraftOfTheParent(): void {
    const editor = new Workbench();
    editor.model.setName('Front Desk');
    expect(
      writeDraft(
        store,
        draftIdForSlug('front-desk'),
        editor.model,
        editor.serializer,
        newWriteGuard(),
      ).ok,
    ).toBe(true);
  }

  const subject = {
    address: { root: 'front-desk' },
    rootDocument: { name: 'Front Desk', nodes: [], edges: [] } as Record<string, unknown>,
  };

  it('supersedes it when the write lands', async () => {
    aDraftOfTheParent();
    const outcome = await writeHostPackage(
      { summary: async () => Ok(null), save: async () => Ok(undefined) },
      subject,
    );
    expect(outcome).toEqual({ kind: 'written', root: 'front-desk' });
    expect(readWorkflow(store, draftIdForSlug('front-desk')).status).not.toBe('ok');
  });

  /**
   * **The other face of the same data loss.** A write that never landed leaves
   * the file exactly where it was, so the draft is still this browser's
   * unsaved work — deleting it would throw away edits that exist nowhere else.
   * Neither hand-written copy of this protocol had a test saying so.
   */
  it('keeps it when the write is refused for a conflict', async () => {
    aDraftOfTheParent();
    recordKnownSavedAt('front-desk', 'yesterday');
    const outcome = await writeHostPackage(
      {
        summary: async () =>
          Ok({
            slug: 'front-desk',
            name: 'Front Desk',
            savedAt: 'today',
            nodeCount: 0,
            edgeCount: 0,
            published: true,
            hidden: false,
            findings: [],
          }),
        save: async () => {
          throw new Error('a refused host write must not reach the backend at all');
        },
      },
      subject,
    );
    expect(outcome.kind).toBe('refused');
    expect(readWorkflow(store, draftIdForSlug('front-desk')).status).toBe('ok');
  });

  it('keeps it when the backend refuses the write', async () => {
    aDraftOfTheParent();
    const outcome = await writeHostPackage(
      { summary: async () => Ok(null), save: async () => Err('disk is full') },
      subject,
    );
    expect(outcome).toEqual({ kind: 'failed', error: 'disk is full' });
    expect(readWorkflow(store, draftIdForSlug('front-desk')).status).toBe('ok');
  });
});
