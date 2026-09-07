import { describe, expect, it, vi } from 'vitest';
import { RunViewStore, type RunView } from './runView';
import type { ActivityRow } from '../ask/traceTree';

const rows = [{ node: 'plan', taskId: null, internal: false }] as unknown as ActivityRow[];

const live = (over: Partial<RunView> = {}): RunView => ({
  source: 'live',
  question: 'who bought the most',
  rows,
  running: true,
  threadId: 'th-1',
  usage: null,
  ...over,
});

/**
 * The seam that makes the dock one component with two data sources.
 *
 * 51 settled that live and finished are not two products, and 37 said the same
 * about replay: *"that view, fed from storage instead of a stream."* What has
 * to be true for that to hold is that nothing downstream of here can tell the
 * difference except by reading `source` — which is exactly what decides
 * whether a run has an end to offer a transport for.
 */
describe('the run on show', () => {
  it('has nothing to draw before anything has run', () => {
    const store = new RunViewStore();
    expect(store.read().rows).toEqual([]);
    expect(store.read().running).toBe(false);
  });

  it('hands back the same snapshot until something changes', () => {
    // The property `useSyncExternalStore` is entitled to: a snapshot that is a
    // fresh object every read renders forever.
    const store = new RunViewStore();
    expect(store.read()).toBe(store.read());
    store.publish(live());
    expect(store.read()).toBe(store.read());
  });

  it('says nothing when told what it already holds', () => {
    // Load-bearing rather than tidy. The writer is an effect in a panel that
    // re-renders per stream frame *and* per keystroke in the composer, so an
    // unconditional notify would re-render the dock on every letter typed.
    const store = new RunViewStore();
    const heard = vi.fn();
    store.subscribe(heard);

    store.publish(live());
    store.publish(live());
    expect(heard).toHaveBeenCalledTimes(1);
  });

  it('notices a run ending, which is the only thing that changed', () => {
    const store = new RunViewStore();
    const heard = vi.fn();
    store.subscribe(heard);

    store.publish(live());
    store.publish(live({ running: false }));
    expect(heard).toHaveBeenCalledTimes(2);
    expect(store.read().running).toBe(false);
  });

  it('notices new frames by the identity of the row array', () => {
    // The rows grow by replacement, never in place — the same contract
    // `Activity` and `RunTimeline` already memoise on.
    const store = new RunViewStore();
    const heard = vi.fn();
    store.subscribe(heard);

    store.publish(live());
    store.publish(live({ rows: [...rows] }));
    expect(heard).toHaveBeenCalledTimes(2);
  });

  it('carries where the rows came from, because that is what has an end', () => {
    // Not decoration: it is what lets one component be honest about a live run
    // having no right-hand edge to scrub to.
    const store = new RunViewStore();
    store.publish(live({ source: 'stored', running: false }));
    expect(store.read().source).toBe('stored');
  });

  it('goes quiet again', () => {
    const store = new RunViewStore();
    store.publish(live());
    store.clear();
    expect(store.read().rows).toEqual([]);
  });

  it('stops telling a listener that has gone', () => {
    const store = new RunViewStore();
    const heard = vi.fn();
    store.subscribe(heard)();
    store.publish(live());
    expect(heard).not.toHaveBeenCalled();
  });
});

/**
 * `memory-and-replay` 61 — the dock is outside the conversation, so the run
 * has to say which one it is and what it cost from the snapshot itself.
 */
describe('which run this is, and what it cost', () => {
  it('starts with nothing to identify and nothing to bill', () => {
    const store = new RunViewStore();
    expect(store.read().threadId).toBe('');
    expect(store.read().usage).toBeNull();
  });

  it('notices a run that has learned its thread', () => {
    const store = new RunViewStore();
    const listener = vi.fn();
    store.subscribe(listener);
    store.publish(live({ threadId: '' }));
    store.publish(live({ threadId: 'th-9' }));
    expect(store.read().threadId).toBe('th-9');
    expect(listener).toHaveBeenCalledTimes(2);
  });

  /**
   * The whole reason these two fields are on the snapshot and not on a second
   * store: usage arrives on the *terminal* frame, so the publish that carries
   * it is the same publish that flips `running` — one object, one identity
   * change, one render.
   */
  it('notices a run that has reported what it spent', () => {
    const store = new RunViewStore();
    const listener = vi.fn();
    store.subscribe(listener);
    store.publish(live({ running: true }));
    store.publish(
      live({
        running: false,
        usage: [{ model: 'gpt-oss:120b-cloud', inputTokens: 10, outputTokens: 5, totalTokens: 15 }],
      }),
    );
    expect(store.read().usage).toHaveLength(1);
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it('stays silent when neither changed', () => {
    const store = new RunViewStore();
    const view = live();
    store.publish(view);
    const listener = vi.fn();
    store.subscribe(listener);
    store.publish({ ...view });
    expect(listener).not.toHaveBeenCalled();
  });
});
