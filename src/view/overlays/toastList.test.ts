import { describe, expect, it } from 'vitest';
import { appendToast, type Toast } from './toastList';

const MAX = 3;

describe('appendToast', () => {
  it('adds a toast', () => {
    expect(appendToast([], { id: 1, message: 'Opened: Starter' }, MAX)).toEqual([
      { id: 1, message: 'Opened: Starter' },
    ]);
  });

  it('is idempotent — React may call a state updater more than once', () => {
    // The whole of ticket 26. An updater that is not safe to run twice is what
    // turned every deep-link message into a toast that appeared and vanished
    // in the same render.
    const toast: Toast = { id: 1, message: 'Opened: Starter' };
    const once = appendToast([], toast, MAX);
    const twice = appendToast(once, toast, MAX);
    expect(twice).toEqual(once);
    expect(twice).toBe(once);
  });

  it('does not mutate what it was given', () => {
    const current: readonly Toast[] = [{ id: 1, message: 'first' }];
    appendToast(current, { id: 2, message: 'second' }, MAX);
    expect(current).toEqual([{ id: 1, message: 'first' }]);
  });

  it('deduplicates by message, not by id', () => {
    const current: readonly Toast[] = [{ id: 1, message: 'same' }];
    expect(appendToast(current, { id: 2, message: 'same' }, MAX)).toBe(current);
  });

  it('drops the oldest beyond the ceiling', () => {
    const current: readonly Toast[] = [
      { id: 1, message: 'a' },
      { id: 2, message: 'b' },
      { id: 3, message: 'c' },
    ];
    expect(appendToast(current, { id: 4, message: 'd' }, MAX)).toEqual([
      { id: 2, message: 'b' },
      { id: 3, message: 'c' },
      { id: 4, message: 'd' },
    ]);
  });
});
