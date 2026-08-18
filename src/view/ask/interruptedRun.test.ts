import { describe, expect, it } from 'vitest';
import {
  clearRunInFlight,
  interruptedRunNotice,
  markRunInFlight,
  takeInterruptedRun,
  type MarkStorage,
} from './interruptedRun';

function fakeStorage(seed: Record<string, string> = {}): MarkStorage {
  const values = new Map(Object.entries(seed));
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => void values.set(key, value),
    removeItem: (key) => void values.delete(key),
  };
}

describe('the run-in-flight mark', () => {
  it('is nothing when no run was under way', () => {
    expect(takeInterruptedRun(fakeStorage())).toBeNull();
  });

  it('survives to the next load and names the workflow', () => {
    const storage = fakeStorage();
    markRunInFlight({ slug: 'chinook-assistant', at: 1_700_000_000_000 }, storage);

    expect(takeInterruptedRun(storage)).toEqual({
      slug: 'chinook-assistant',
      at: 1_700_000_000_000,
    });
  });

  it('is gone once a run settles', () => {
    const storage = fakeStorage();
    markRunInFlight({ at: 1 }, storage);
    clearRunInFlight(storage);

    expect(takeInterruptedRun(storage)).toBeNull();
  });

  it('announces itself once, not on every reload after', () => {
    const storage = fakeStorage();
    markRunInFlight({ at: 1 }, storage);

    expect(takeInterruptedRun(storage)).not.toBeNull();
    expect(takeInterruptedRun(storage)).toBeNull();
  });

  it('treats a half-written value as no run', () => {
    expect(takeInterruptedRun(fakeStorage({ 'openstategraph.run-in-flight': '{"at":' }))).toBeNull();
  });

  it('survives an unusable store rather than throwing', () => {
    const hostile: MarkStorage = {
      getItem: () => {
        throw new Error('denied');
      },
      setItem: () => {
        throw new Error('denied');
      },
      removeItem: () => {
        throw new Error('denied');
      },
    };

    expect(() => markRunInFlight({ at: 1 }, hostile)).not.toThrow();
    expect(takeInterruptedRun(hostile)).toBeNull();
  });
});

describe('interruptedRunNotice', () => {
  it('names the workflow when there was one', () => {
    expect(interruptedRunNotice({ slug: 'chinook-assistant', at: 1 })).toContain(
      'of chinook-assistant',
    );
  });

  it('reads without one', () => {
    const notice = interruptedRunNotice({ at: 1 });

    expect(notice).toContain('A run was under way');
    expect(notice).not.toContain('undefined');
  });

  it('claims only what the editor can know', () => {
    // It stopped watching. Whether the run *finished* is the server's to say,
    // and the notice sends the reader to where that answer is.
    const notice = interruptedRunNotice({ at: 1 });

    expect(notice).toContain('stopped following it');
    expect(notice).toContain('Past runs');
  });
});
