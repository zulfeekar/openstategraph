import { describe, expect, it } from 'vitest';
import {
  EXAMPLES_SHELF_KEY,
  examplesShelfStartsOpen,
  rememberExamplesShelf,
  type ShelfStorage,
} from './examplesShelf';

/**
 * install-experience T9 — the Examples shelf starts closed and remembers.
 *
 * The decision lives in its own module rather than inline in
 * `WorkflowManager` for the reason `consequences.ts` does: this *is* the
 * feature. "Opt-in" was already true of the packaging and false of the
 * prominence, and a default that quietly flips back is a default nobody has.
 */

function fakeStorage(initial: Record<string, string> = {}): ShelfStorage & {
  values: Record<string, string>;
} {
  const values = { ...initial };
  return {
    values,
    getItem: (key) => values[key] ?? null,
    setItem: (key, value) => {
      values[key] = value;
    },
  };
}

describe('examplesShelfStartsOpen', () => {
  it('is closed on a browser that has never answered', () => {
    expect(examplesShelfStartsOpen(fakeStorage())).toBe(false);
  });

  it('is open when this browser opened it before', () => {
    const storage = fakeStorage();
    rememberExamplesShelf(true, storage);
    expect(examplesShelfStartsOpen(storage)).toBe(true);
  });

  it('stays closed when this browser closed it before', () => {
    const storage = fakeStorage();
    rememberExamplesShelf(true, storage);
    rememberExamplesShelf(false, storage);
    expect(examplesShelfStartsOpen(storage)).toBe(false);
  });

  it('is closed rather than broken when there is no storage at all', () => {
    // Private mode, a sandboxed iframe. A shelf that throws on render is worse
    // than a shelf that forgets.
    expect(examplesShelfStartsOpen(null)).toBe(false);
    expect(() => rememberExamplesShelf(true, null)).not.toThrow();
  });

  it('is closed rather than broken when storage throws', () => {
    const hostile: ShelfStorage = {
      getItem: () => {
        throw new Error('denied');
      },
      setItem: () => {
        throw new Error('denied');
      },
    };
    expect(examplesShelfStartsOpen(hostile)).toBe(false);
    expect(() => rememberExamplesShelf(true, hostile)).not.toThrow();
  });

  it('namespaces its key like everything else this app stores', () => {
    expect(EXAMPLES_SHELF_KEY.startsWith('openstategraph.')).toBe(true);
  });

  it('does not collide with the onboarding flag', () => {
    expect(EXAMPLES_SHELF_KEY).not.toBe('openstategraph.onboarded');
  });
});
