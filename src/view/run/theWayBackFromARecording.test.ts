import { describe, expect, it, vi } from 'vitest';
import { RunViewStore, type RunView } from './runView';
import type { ActivityRow } from '../ask/traceTree';

const rows = [{ node: 'plan', taskId: null, internal: false }] as unknown as ActivityRow[];

const live = (over: Partial<RunView> = {}): RunView => ({
  source: 'live',
  question: 'who bought the most',
  rows,
  running: false,
  threadId: 'th-1',
  usage: null,
  ...over,
});

const recording = (over: Partial<RunView> = {}): RunView => ({
  ...live(),
  source: 'stored',
  question: 'which genre earned most',
  threadId: 'th-old',
  ...over,
});

/**
 * Opening a recording, and getting back out of one — `memory-and-replay` 73.
 *
 * The owner asked for this in the same breath as the panel: *"there must be a
 * UX way to get back to the selected / current workflow timeline at any
 * time."* It is the part most likely to be skimped, because a store that
 * simply took the newest publish would look right on the first click and
 * strand a reader on the second.
 *
 * The reason it needs a mechanism rather than a second call to `publish` is
 * `AskPanel`: its writer is an effect keyed on the turn list, so a keystroke
 * does not overwrite a recording but an arriving frame does. **A recording is
 * therefore *held*** — the store keeps taking the live view and stops showing
 * it — and letting go puts back whatever the live side had reached in the
 * meantime, rather than whatever it had when the recording was opened.
 */
describe('a recording is held, and the live run keeps arriving underneath it', () => {
  it('shows the recording once it is held', () => {
    const store = new RunViewStore();
    store.publish(live());
    store.hold(recording());
    expect(store.read().source).toBe('stored');
    expect(store.read().question).toBe('which genre earned most');
  });

  it('does not let a live publish take the surface back', () => {
    const store = new RunViewStore();
    store.hold(recording());
    store.publish(live({ question: 'a later question' }));
    expect(store.read().question).toBe('which genre earned most');
  });

  it('says whether a recording is held, so a control can offer the way back', () => {
    const store = new RunViewStore();
    expect(store.held()).toBe(false);
    store.hold(recording());
    expect(store.held()).toBe(true);
  });

  it('goes back to the live run the panel reached while the recording was up', () => {
    // Not to the one that was on screen when the recording was opened. A run
    // that finished behind a held recording is the run a reader is coming back
    // to see.
    const store = new RunViewStore();
    store.publish(live({ question: 'first' }));
    store.hold(recording());
    store.publish(live({ question: 'second' }));
    store.release();
    expect(store.read().question).toBe('second');
  });

  it('goes back to nothing when nothing had run in this tab', () => {
    const store = new RunViewStore();
    store.hold(recording());
    store.release();
    expect(store.read().rows).toEqual([]);
    expect(store.read().source).toBe('live');
  });

  it('lets a second recording replace the first without going home first', () => {
    const store = new RunViewStore();
    store.publish(live());
    store.hold(recording({ threadId: 'th-a' }));
    store.hold(recording({ threadId: 'th-b' }));
    expect(store.read().threadId).toBe('th-b');
    store.release();
    expect(store.read().source).toBe('live');
  });

  it('gives the dock back to a run that has just started', () => {
    // The one publish a hold does not survive, and it is a decision rather
    // than an oversight: a reader who presses Run wants to watch it. Losing
    // the live run behind a recording nobody closed is the worse failure of
    // the two, and it is silent.
    const store = new RunViewStore();
    store.hold(recording());
    store.publish(live({ running: true, question: 'a new run' }));
    expect(store.read().question).toBe('a new run');
    expect(store.held()).toBe(false);
  });

  it('tells its listeners each time the surface changes hands', () => {
    const store = new RunViewStore();
    const heard = vi.fn();
    store.subscribe(heard);
    store.hold(recording());
    store.release();
    expect(heard).toHaveBeenCalledTimes(2);
  });

  it('says nothing when handed the recording it is already showing', () => {
    const store = new RunViewStore();
    const heard = vi.fn();
    store.hold(recording());
    store.subscribe(heard);
    store.hold(recording());
    expect(heard).not.toHaveBeenCalled();
  });

  it('clears back to nothing, recording and all', () => {
    // A fresh canvas has no run on it and no recording either.
    const store = new RunViewStore();
    store.hold(recording());
    store.clear();
    expect(store.held()).toBe(false);
    expect(store.read().rows).toEqual([]);
  });
});
