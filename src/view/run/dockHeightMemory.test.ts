import { describe, expect, it } from 'vitest';
import { readDockHeight, rememberDockHeight } from './dockHeightMemory';
import { clampDockHeight, DOCK_DEFAULT_HEIGHT } from '../layout/dockFit';

/** In-memory Storage, mirroring `preferences.test.ts`'s injectable pattern. */
const memoryStorage = (): Storage => {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (k) => map.get(k) ?? null,
    key: (i) => [...map.keys()][i] ?? null,
    removeItem: (k) => void map.delete(k),
    setItem: (k, v) => void map.set(k, String(v)),
  };
};

/** A browser that has decided you may not store anything. */
const hostileStorage = (): Storage =>
  new Proxy(memoryStorage(), {
    get() {
      throw new DOMException('The operation is insecure.', 'SecurityError');
    },
  });

const TALL = 1000;

/**
 * A dock height is a preference about a screen, not a fact about a document.
 *
 * So it is remembered per viewer. What these tests are really pinning is the
 * second half of that sentence: `localStorage` throws — a private window, a
 * browser set to block site data, a thumbnail capture — and a preference that
 * crashes the shell on a drag is worse than no preference at all.
 */
describe('the remembered dock height', () => {
  it('opens at the default the first time anyone opens it', () => {
    expect(readDockHeight(memoryStorage(), TALL)).toBe(DOCK_DEFAULT_HEIGHT);
  });

  it('comes back the way it was left', () => {
    const storage = memoryStorage();
    rememberDockHeight(312, storage);
    expect(readDockHeight(storage, TALL)).toBe(312);
  });

  it('survives a browser that refuses to store anything', () => {
    expect(() => rememberDockHeight(312, hostileStorage())).not.toThrow();
  });

  it('survives a browser that refuses to be read', () => {
    expect(readDockHeight(hostileStorage(), TALL)).toBe(DOCK_DEFAULT_HEIGHT);
  });

  it('survives having no storage at all', () => {
    expect(readDockHeight(null, TALL)).toBe(DOCK_DEFAULT_HEIGHT);
    expect(() => rememberDockHeight(312, null)).not.toThrow();
  });

  it('ignores a value that is not a number', () => {
    const storage = memoryStorage();
    storage.setItem('openstategraph.run-dock-height', 'tall');
    expect(readDockHeight(storage, TALL)).toBe(DOCK_DEFAULT_HEIGHT);
  });

  it('ignores an empty string, which `Number` would read as zero', () => {
    const storage = memoryStorage();
    storage.setItem('openstategraph.run-dock-height', '');
    expect(readDockHeight(storage, TALL)).toBe(DOCK_DEFAULT_HEIGHT);
  });

  it('clamps a height set on a screen this one is not', () => {
    // A laptop undocked from a large monitor. The stored number is honest
    // about the window it was set in and useless in this one, and a dock
    // taller than the screen is a canvas nobody can see.
    const storage = memoryStorage();
    rememberDockHeight(4000, storage);
    expect(readDockHeight(storage, TALL)).toBe(clampDockHeight(4000, TALL));
    expect(readDockHeight(storage, TALL)).toBeLessThan(4000);
  });
});
