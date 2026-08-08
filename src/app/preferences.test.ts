import { describe, expect, it } from 'vitest';
import { PreferencesStore } from '@app/preferences';

/** In-memory Storage, mirroring workflowStore's injectable-storage pattern. */
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

describe('PreferencesStore', () => {
  it('defaults to horizontal flow', () => {
    expect(new PreferencesStore(memoryStorage()).flowDirection).toBe('horizontal');
  });

  it('persists a change and reads it back on the next session', () => {
    const storage = memoryStorage();
    new PreferencesStore(storage).setFlowDirection('vertical');
    expect(new PreferencesStore(storage).flowDirection).toBe('vertical');
  });

  it('treats a corrupt stored value as the default, not an error', () => {
    const storage = memoryStorage();
    storage.setItem('openstategraph.flow-direction', 'diagonal');
    expect(new PreferencesStore(storage).flowDirection).toBe('horizontal');
  });

  it('notifies subscribers exactly on change', () => {
    const store = new PreferencesStore(memoryStorage());
    const seen: string[] = [];
    store.onChange(() => seen.push(store.flowDirection));
    store.setFlowDirection('vertical');
    store.setFlowDirection('vertical'); // no-op — same value
    store.setFlowDirection('horizontal');
    expect(seen).toEqual(['vertical', 'horizontal']);
  });

  it('survives a storage that throws (private browsing)', () => {
    const broken = {
      ...memoryStorage(),
      getItem: () => {
        throw new Error('denied');
      },
      setItem: () => {
        throw new Error('denied');
      },
    } as Storage;
    const store = new PreferencesStore(broken);
    expect(store.flowDirection).toBe('horizontal');
    expect(() => store.setFlowDirection('vertical')).not.toThrow();
    expect(store.flowDirection).toBe('vertical'); // held in memory for the session
  });
});
