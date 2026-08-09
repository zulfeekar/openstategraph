import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  DRILL_STACK_KEY,
  clearDrillStack,
  peekDrillFrame,
  popDrillFrame,
  pushDrillFrame,
  readDrillStack,
  subscribeDrillStack,
} from './drillStack';

/**
 * The suite runs in `node`, which has no `sessionStorage` — and installing a
 * DOM shim for one module would undo the deliberate `environment: 'node'`
 * choice in `vite.config.ts`. A Map-backed stand-in is enough: the module uses
 * exactly three methods of the Storage contract, and the round-trip assertions
 * below read the stored *string*, so persistence is still really exercised.
 */
class MemoryStorage {
  private readonly entries = new Map<string, string>();
  getItem(key: string): string | null {
    return this.entries.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.entries.set(key, value);
  }
  removeItem(key: string): void {
    this.entries.delete(key);
  }
  clear(): void {
    this.entries.clear();
  }
}

describe('drillStack', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'sessionStorage', {
      value: new MemoryStorage(),
      configurable: true,
      writable: true,
    });
  });

  it('starts empty', () => {
    expect(readDrillStack()).toEqual([]);
    expect(peekDrillFrame()).toBeUndefined();
  });

  it('round-trips through sessionStorage', () => {
    pushDrillFrame({ slug: 'page-analytics', name: 'Page Analytics' });
    expect(JSON.parse(sessionStorage.getItem(DRILL_STACK_KEY) ?? 'null')).toEqual([
      { slug: 'page-analytics', name: 'Page Analytics' },
    ]);
    expect(readDrillStack()).toEqual([{ slug: 'page-analytics', name: 'Page Analytics' }]);
  });

  it('nests, and pops one level at a time', () => {
    pushDrillFrame({ slug: 'a', name: 'A' });
    pushDrillFrame({ slug: 'b', name: 'B' });
    expect(peekDrillFrame()).toEqual({ slug: 'b', name: 'B' });

    expect(popDrillFrame()).toEqual({ slug: 'b', name: 'B' });
    expect(peekDrillFrame()).toEqual({ slug: 'a', name: 'A' });

    expect(popDrillFrame()).toEqual({ slug: 'a', name: 'A' });
    expect(readDrillStack()).toEqual([]);
    expect(popDrillFrame()).toBeUndefined();
  });

  it('truncates rather than duplicating when re-entering a workflow already on the trail', () => {
    pushDrillFrame({ slug: 'a', name: 'A' });
    pushDrillFrame({ slug: 'b', name: 'B' });
    pushDrillFrame({ slug: 'a', name: 'A' });
    expect(readDrillStack()).toEqual([{ slug: 'a', name: 'A' }]);
  });

  it('clears the whole trail, and removes the key', () => {
    pushDrillFrame({ slug: 'a', name: 'A' });
    pushDrillFrame({ slug: 'b', name: 'B' });
    clearDrillStack();
    expect(readDrillStack()).toEqual([]);
    expect(sessionStorage.getItem(DRILL_STACK_KEY)).toBeNull();
  });

  it('survives malformed storage by keeping only well-formed frames', () => {
    sessionStorage.setItem(
      DRILL_STACK_KEY,
      JSON.stringify([{ slug: 'a', name: 'A' }, { slug: 42 }, null, 'nope', { name: 'no slug' }]),
    );
    expect(readDrillStack()).toEqual([{ slug: 'a', name: 'A' }]);

    sessionStorage.setItem(DRILL_STACK_KEY, '{not json');
    expect(readDrillStack()).toEqual([]);

    sessionStorage.setItem(DRILL_STACK_KEY, '{"slug":"a"}');
    expect(readDrillStack()).toEqual([]);
  });

  it('notifies subscribers on every mutation, until unsubscribed', () => {
    const listener = vi.fn();
    const off = subscribeDrillStack(listener);

    pushDrillFrame({ slug: 'a', name: 'A' });
    popDrillFrame();
    clearDrillStack();
    expect(listener).toHaveBeenCalledTimes(3);

    off();
    pushDrillFrame({ slug: 'b', name: 'B' });
    expect(listener).toHaveBeenCalledTimes(3);
  });
});
