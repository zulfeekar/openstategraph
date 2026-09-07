import { describe, expect, it } from 'vitest';
import {
  addressEquals,
  childAddress,
  formatMountAddress,
  isInstance,
  mountLabel,
  parentAddress,
  parseMountAddress,
} from './MountAddress';

/**
 * The unit of addressing is the **mount node id**, not the workflow slug, and
 * every test here exists to hold that line — see ticket 42.
 *
 * A slug names the *class* (`chinook-assistant`, the package on disk). A mount
 * node id names the *instance* (`wf-music`, whose `data.overrides` are its
 * own props). Address by slug and two mounts of one package are the same
 * address, which is precisely the distinction that makes an instance an
 * instance.
 */
describe('MountAddress — naming one instance of a reusable workflow', () => {
  it('reads a bare slug as the class itself', () => {
    // `?w=chinook-assistant` must keep meaning exactly what it means today:
    // open the shared definition. Every existing bookmark depends on it.
    const address = parseMountAddress('chinook-assistant');
    expect(address).toEqual({ root: 'chinook-assistant', mountPath: [] });
    expect(isInstance(address!)).toBe(false);
  });

  it('reads a mount path as an instance inside a root', () => {
    const address = parseMountAddress('concierge/wf-music');
    expect(address).toEqual({ root: 'concierge', mountPath: ['wf-music'] });
    expect(isInstance(address!)).toBe(true);
  });

  it('tells two mounts of one package apart', () => {
    // The whole reason the unit is the mount id. Under slug addressing these
    // two are indistinguishable, and an override written to one would appear
    // to belong to the other.
    const music = parseMountAddress('concierge/wf-music')!;
    const other = parseMountAddress('concierge/wf-other')!;
    expect(addressEquals(music, other)).toBe(false);
    expect(formatMountAddress(music)).not.toBe(formatMountAddress(other));
  });

  it('nests to any depth, for a grandchild mount', () => {
    expect(parseMountAddress('concierge/wf-music/wf-inner')).toEqual({
      root: 'concierge',
      mountPath: ['wf-music', 'wf-inner'],
    });
  });

  it('round-trips at every depth', () => {
    for (const raw of ['concierge', 'concierge/wf-music', 'concierge/wf-music/wf-inner']) {
      expect(formatMountAddress(parseMountAddress(raw)!)).toBe(raw);
    }
  });

  it('accepts the punctuation a minted node id actually contains', () => {
    // `nextId('node', 'agent.llm')` → `node:agent.llm-1` (see `kernel/id.ts`),
    // so colons and dots are ordinary inside a segment. Only the separator is
    // special.
    expect(parseMountAddress('concierge/node:workflow.subgraph-1')).toEqual({
      root: 'concierge',
      mountPath: ['node:workflow.subgraph-1'],
    });
  });

  describe('refuses rather than repairs', () => {
    // A repaired address is a link that silently opens the *wrong instance*,
    // which is worse than a link that does not open. Each of these is `null`.
    it.each([
      ['empty', ''],
      ['blank', '   '],
      ['a lone separator', '/'],
      ['an empty inner segment', 'concierge//wf-music'],
      ['a trailing separator', 'concierge/'],
      ['a leading separator', '/concierge'],
      ['a traversal attempt', 'concierge/../secrets'],
      ['a dot segment', 'concierge/.'],
      ['a backslash', 'concierge\\wf-music'],
      ['whitespace inside a segment', 'concierge/wf music'],
    ])('rejects %s', (_why, raw) => {
      expect(parseMountAddress(raw)).toBeNull();
    });

    it('rejects a root that is not a slug', () => {
      // The backend's own rule: a slug equals its own `slugify`, and contains
      // no separator (`api/workflow_store.py`, `directory_for`). Refusing here
      // means a bad address never becomes a request.
      expect(parseMountAddress('Concierge/wf-music')).toBeNull();
      expect(parseMountAddress('con cierge')).toBeNull();
    });

    it('trims surrounding whitespace before deciding', () => {
      expect(parseMountAddress('  concierge/wf-music  ')).toEqual({
        root: 'concierge',
        mountPath: ['wf-music'],
      });
    });
  });

  describe('parentAddress — the trail, derived rather than remembered', () => {
    it('walks a grandchild back one level at a time', () => {
      const deep = parseMountAddress('concierge/wf-music/wf-inner')!;
      const mid = parentAddress(deep)!;
      expect(formatMountAddress(mid)).toBe('concierge/wf-music');
      expect(formatMountAddress(parentAddress(mid)!)).toBe('concierge');
    });

    it('stops at the root, which has no parent', () => {
      expect(parentAddress(parseMountAddress('concierge')!)).toBeNull();
    });

    it('keeps two sibling instances on separate trails', () => {
      // `drillStack` deduped by slug, so a chain through two mounts of one
      // package collapsed into one frame. A derived trail cannot.
      const a = parentAddress(parseMountAddress('concierge/wf-music')!)!;
      const b = parentAddress(parseMountAddress('concierge/wf-other')!)!;
      expect(addressEquals(a, b)).toBe(true);
    });
  });

  describe('childAddress — drilling in by one level', () => {
    it('appends a mount id to a class address', () => {
      const child = childAddress(parseMountAddress('concierge')!, 'wf-music')!;
      expect(formatMountAddress(child)).toBe('concierge/wf-music');
    });

    it('appends to an instance address, for a grandchild', () => {
      const child = childAddress(parseMountAddress('concierge/wf-music')!, 'wf-inner')!;
      expect(formatMountAddress(child)).toBe('concierge/wf-music/wf-inner');
    });

    it('accepts a minted id with its colon and dot', () => {
      const child = childAddress(parseMountAddress('concierge')!, 'node:workflow.subgraph-1')!;
      expect(child.mountPath).toEqual(['node:workflow.subgraph-1']);
    });

    it('refuses an id that could not be a segment', () => {
      // Fails at the click rather than producing a link that resolves
      // somewhere else — the same stance as parsing.
      const root = parseMountAddress('concierge')!;
      expect(childAddress(root, '')).toBeNull();
      expect(childAddress(root, '..')).toBeNull();
      expect(childAddress(root, 'a/b')).toBeNull();
    });
  });

  it('survives a round trip through URLSearchParams unchanged', () => {
    // `/` is legal in a query *value*, so no escaping is needed — and this
    // test is what stops a later "fix" wrapping it in `encodeURIComponent`
    // and breaking every link already in someone's browser history.
    const params = new URLSearchParams();
    params.set('w', 'concierge/wf-music');
    expect(new URLSearchParams(params.toString()).get('w')).toBe('concierge/wf-music');
  });
});

/**
 * consistency-sweep ticket 10. The drill-in banner rendered a mount-path
 * segment raw, so the strip whose entire job is saying where you are read
 * `Editing Untitled node:workflow.subgraph-1` — an internal canvas id and a
 * LangGraph name the lexicon reserves for nothing.
 */
describe('mountLabel', () => {
  it('names a minted mount by its ordinal, not its node id', () => {
    expect(mountLabel('node:workflow.subgraph-1')).toBe('mount 1');
  });

  it('keeps two mounts of one package apart, which is the only job', () => {
    expect(mountLabel('node:workflow.subgraph-2')).not.toBe(mountLabel('node:workflow.subgraph-1'));
  });

  it('never says "subgraph"', () => {
    expect(mountLabel('node:workflow.subgraph-7')).not.toContain('subgraph');
  });

  it('leaves a hand-authored id alone rather than inventing a number', () => {
    // Shipped packages address their mounts with words (`wf-music`), and a
    // label that guessed an ordinal would be worse than the raw id.
    expect(mountLabel('wf-music')).toBe('wf-music');
  });

  it('is stable under whitespace', () => {
    expect(mountLabel('  node:workflow.subgraph-3  ')).toBe('mount 3');
  });
});
