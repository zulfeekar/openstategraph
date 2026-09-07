import { beforeEach, describe, expect, it } from 'vitest';
import { DRILL_STACK_KEY } from './drillStack';
import { OPEN_ADDRESS_KEY } from './openAddress';
import { CURRENT_SLUG_KEY } from './workflowFileWatch';
import { openAncestry } from './openAncestry';

/**
 * The trail the editor's self-mount refusal is measured against — ticket 42.
 *
 * Storage is stubbed rather than shimmed with a DOM, matching `openAddress`'s
 * own tests: what is under test is which keys make which trail, and that needs
 * a Map, not a browser.
 */
let cells: Map<string, string>;

beforeEach(() => {
  cells = new Map<string, string>();
  (globalThis as { sessionStorage?: unknown }).sessionStorage = {
    getItem: (key: string) => cells.get(key) ?? null,
    setItem: (key: string, value: string) => void cells.set(key, value),
    removeItem: (key: string) => void cells.delete(key),
    clear: () => cells.clear(),
  };
});

describe('openAncestry', () => {
  it('is empty for a new document that has never been saved', () => {
    expect(openAncestry()).toEqual([]);
  });

  it('names a plain package once, not three times', () => {
    // The address root and the open class slug are the same string here, and a
    // chain reading `concierge -> concierge -> concierge` would be nonsense.
    cells.set(OPEN_ADDRESS_KEY, 'concierge');
    cells.set(CURRENT_SLUG_KEY, 'concierge');
    expect(openAncestry()).toEqual(['concierge']);
  });

  it('names the parent package when a mount instance is open', () => {
    // `?w=concierge/wf-music` displays `chinook-assistant` from inside
    // `concierge`. Mounting `concierge` here is the cycle drill-in makes easy
    // to create and impossible to see, which is the whole reason for the trail.
    cells.set(OPEN_ADDRESS_KEY, 'concierge/wf-music');
    cells.set(CURRENT_SLUG_KEY, 'chinook-assistant');
    expect(openAncestry()).toEqual(['concierge', 'chinook-assistant']);
  });

  it('puts the drill stack oldest-first, ahead of the address', () => {
    cells.set(DRILL_STACK_KEY, JSON.stringify([{ slug: 'atlas', name: 'Atlas' }]));
    cells.set(OPEN_ADDRESS_KEY, 'concierge/wf-music');
    cells.set(CURRENT_SLUG_KEY, 'chinook-assistant');
    expect(openAncestry()).toEqual(['atlas', 'concierge', 'chinook-assistant']);
  });

  it('carries the address root even before a class slug is recorded', () => {
    cells.set(OPEN_ADDRESS_KEY, 'concierge/wf-music');
    expect(openAncestry()).toEqual(['concierge']);
  });

  it('never guesses a slug from a mount id', () => {
    // `wf-music` is a node id, not a package. Putting it on the trail would
    // refuse a package that happened to share the name — a refusal the
    // compiler would not make, and the one failure this must not have.
    cells.set(OPEN_ADDRESS_KEY, 'concierge/wf-music/wf-inner');
    cells.set(CURRENT_SLUG_KEY, 'sql-analyst');
    expect(openAncestry()).toEqual(['concierge', 'sql-analyst']);
  });

  it('survives storage being unavailable', () => {
    (globalThis as { sessionStorage?: unknown }).sessionStorage = {
      getItem: () => {
        throw new Error('denied');
      },
      setItem: () => undefined,
      removeItem: () => undefined,
      clear: () => undefined,
    };
    expect(openAncestry()).toEqual([]);
  });
});
