import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import { ConversationStore } from './conversationStore';

interface Turn {
  readonly id: string;
}

/**
 * The two doors of `memory-and-replay` 35.
 *
 * A canvas **Run** and a chat **Send** are the same conversation, so both are
 * written here as what they actually are at the seam: ask the store what
 * thread the next question carries, then hand it back what the server named.
 * Nothing in between tells the store that a panel closed — that is the whole
 * defect, and a test that called a reset in the middle would pass over it.
 */
function send(store: ConversationStore<Turn>, subject: string, slug: string, named: string) {
  const carried = store.continuing(subject, slug);
  store.remember(subject, slug, named);
  return carried;
}

describe('ConversationStore', () => {
  it('carries the thread a canvas Run opened into a chat Send', () => {
    const store = new ConversationStore<Turn>();

    expect(send(store, 'chinook-assistant', 'chinook-assistant', 'th-1')).toBeUndefined();
    expect(send(store, 'chinook-assistant', 'chinook-assistant', 'th-1')).toBe('th-1');
  });

  it('survives a panel that unmounted — the store is not the component', () => {
    const store = new ConversationStore<Turn>();
    store.remember('chinook-assistant', 'chinook-assistant', 'th-1');
    store.setTurns('chinook-assistant', () => [{ id: 'turn-1' }]);

    // Closing the Ask panel tells the store nothing at all. Reading again is
    // exactly what a remount does.
    expect(store.read('chinook-assistant').thread?.id).toBe('th-1');
    expect(store.read('chinook-assistant').turns).toHaveLength(1);
  });

  it('keeps two instances of one package apart', () => {
    const store = new ConversationStore<Turn>();
    store.remember('concierge/wf-music', 'chinook-assistant', 'th-music');

    // The *address* is the subject: `concierge/wf-other` is the same package
    // and a different conversation, which is `production-ready` 07's lesson
    // read the other way round.
    expect(store.continuing('concierge/wf-other', 'chinook-assistant')).toBeUndefined();
    expect(store.continuing('concierge/wf-music', 'chinook-assistant')).toBe('th-music');
  });

  it('starts a new session for both doors at once', () => {
    const store = new ConversationStore<Turn>();
    send(store, 'chinook-assistant', 'chinook-assistant', 'th-1');
    send(store, 'chinook-assistant', 'chinook-assistant', 'th-1');

    store.newSession('chinook-assistant');

    // Forgotten for whichever door asks next, and the transcript is kept —
    // "start a new conversation" is not "throw away what the last one showed".
    expect(store.continuing('chinook-assistant', 'chinook-assistant')).toBeUndefined();
    expect(store.read('chinook-assistant').turns).toEqual([]);
  });

  it('keeps the transcript across a new session', () => {
    const store = new ConversationStore<Turn>();
    store.setTurns('chinook-assistant', () => [{ id: 'turn-1' }]);
    store.newSession('chinook-assistant');
    expect(store.read('chinook-assistant').turns).toHaveLength(1);
  });

  it('will not continue a thread into a different document', () => {
    const store = new ConversationStore<Turn>();
    store.remember('chinook-assistant', 'chinook-assistant', 'th-1');
    // Belt and braces with the subject key: the checkpointer is keyed by
    // thread id alone, so a slug that has moved under one subject is still a
    // different conversation (`thread.ts`).
    expect(store.continuing('chinook-assistant', 'starter')).toBeUndefined();
  });

  it('leaves what it holds alone when a run names no thread', () => {
    const store = new ConversationStore<Turn>();
    store.remember('chinook-assistant', 'chinook-assistant', 'th-1');
    store.remember('chinook-assistant', 'chinook-assistant', '');
    expect(store.continuing('chinook-assistant', 'chinook-assistant')).toBe('th-1');
  });

  it('gives a stable snapshot until something changes', () => {
    const store = new ConversationStore<Turn>();
    const before = store.read('chinook-assistant');
    expect(store.read('chinook-assistant')).toBe(before);
    store.remember('chinook-assistant', 'chinook-assistant', 'th-1');
    expect(store.read('chinook-assistant')).not.toBe(before);
  });

  it('tells subscribers when a conversation moves', () => {
    const store = new ConversationStore<Turn>();
    const listener = vi.fn();
    const stop = store.subscribe(listener);
    store.remember('chinook-assistant', 'chinook-assistant', 'th-1');
    expect(listener).toHaveBeenCalledTimes(1);
    stop();
    store.newSession('chinook-assistant');
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it('treats an unsaved canvas as one subject', () => {
    const store = new ConversationStore<Turn>();
    store.remember(null, undefined, 'th-1');
    expect(store.continuing(null, undefined)).toBe('th-1');
  });
});

/**
 * The store being right is not the fix.
 *
 * Everything above would stay green if `AskPanel` kept its own `useState`
 * beside it, which is the exact shape of the defect: one memory per door.
 * vitest runs in `environment: 'node'`, so the panel cannot be mounted here —
 * what can be checked is that it has no second memory to drift from, and that
 * its send path asks this store rather than a captured value.
 */
describe('AskPanel holds no conversation of its own', () => {
  const source = readFileSync(new URL('./AskPanel.tsx', import.meta.url), 'utf8');

  it('keeps neither the thread nor the transcript in component state', () => {
    expect(source).not.toMatch(/useState<ThreadBinding/);
    expect(source).not.toMatch(/useState<readonly ChatTurn\[\]>/);
  });

  it('asks the store what the next question continues', () => {
    expect(source).toContain('conversations.continuing(currentSubject()');
    expect(source).toContain('conversations.remember(currentSubject()');
    expect(source).toContain('conversations.newSession(currentSubject())');
  });
});
