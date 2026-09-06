import { describe, expect, it } from 'vitest';
import { parseMountAddress } from './MountAddress';
import { MountContext } from './MountContext';

/**
 * Where an instance's edits actually land — ticket 42, tranche 4.
 *
 * Editing a field while `concierge/wf-music` is on screen must change *that
 * mount* and nothing else: not the `chinook-assistant` package, and not the
 * `wf-other` mount of the same package. The place that expresses it is the
 * mount node's `data.overrides` in the **root** document, which is why only
 * that one document is retained.
 *
 * ## Nesting composes as JSON, so one document is enough
 *
 * The tempting design is to retain each level's effective document and write
 * to the nearest one. It is also wrong, and expensive: an intermediate
 * effective document is derived, so it is not a thing that can be saved.
 *
 * The backend already showed the shape. `apply_mount_overrides` applies a
 * mount's overrides to the child *before* the child's own mounts are resolved,
 * so a grandparent expresses a grandchild's override as an override of the
 * parent's `overrides` field:
 *
 *     concierge.wf-music.overrides = { "wf-inner": { "overrides": { … } } }
 *
 * That is one nested JSON write into the root package, and it is pinned on the
 * backend by `test_mount_effective_document`'s composition-order test. So the
 * path here descends `[segment].overrides` per level and the two ends agree by
 * construction rather than by comment.
 */
const CHILD_FIELD = { 'agent-sql': { rules: 'stricter here' } };

function rootDocument(): Record<string, unknown> {
  return {
    version: 2,
    name: 'concierge',
    nodes: [
      { id: 'in1', type: 'input.text', data: {} },
      { id: 'wf-music', type: 'workflow.subgraph', data: { workflow: 'chinook-assistant' } },
      { id: 'wf-other', type: 'workflow.subgraph', data: { workflow: 'chinook-assistant' } },
    ],
    edges: [],
  };
}

const context = (raw: string, document = rootDocument()) =>
  new MountContext(parseMountAddress(raw)!, document);

/** The overrides blob on a mount node, parsed. */
function overridesOf(document: Record<string, unknown>, mountId: string): unknown {
  const nodes = document['nodes'] as { id: string; data: Record<string, unknown> }[];
  const raw = nodes.find((node) => node.id === mountId)?.data['overrides'];
  return typeof raw === 'string' ? JSON.parse(raw) : raw;
}

describe('MountContext — an instance edit writes an override on its parent', () => {
  it('writes the field under the mount it is displaying', () => {
    const ctx = context('concierge/wf-music');
    ctx.writeOverride('agent-sql', 'rules', 'stricter here');
    expect(overridesOf(ctx.rootDocument, 'wf-music')).toEqual(CHILD_FIELD);
  });

  it('leaves a sibling mount of the same package alone', () => {
    // The instance property, at the place that could most easily break it.
    const ctx = context('concierge/wf-music');
    ctx.writeOverride('agent-sql', 'rules', 'stricter here');
    expect(overridesOf(ctx.rootDocument, 'wf-other')).toBeUndefined();
  });

  it('stores the blob as the string the inspector and the card both read', () => {
    // `OVERRIDES_FIELD` is a textarea and `CompositionBody.overriddenCount`
    // JSON.parses it. One spelling, or the card's "n overridden" badge stops
    // counting the overrides this command writes.
    const ctx = context('concierge/wf-music');
    ctx.writeOverride('agent-sql', 'rules', 'x');
    const nodes = ctx.rootDocument['nodes'] as { id: string; data: Record<string, unknown> }[];
    expect(typeof nodes.find((n) => n.id === 'wf-music')!.data['overrides']).toBe('string');
  });

  it('merges into overrides that are already there', () => {
    const ctx = context('concierge/wf-music');
    ctx.writeOverride('agent-sql', 'rules', 'one');
    ctx.writeOverride('agent-sql', 'model', 'two');
    ctx.writeOverride('grader-sql', 'maxAttempts', 3);
    expect(overridesOf(ctx.rootDocument, 'wf-music')).toEqual({
      'agent-sql': { rules: 'one', model: 'two' },
      'grader-sql': { maxAttempts: 3 },
    });
  });

  describe('reading back, which is what undo restores', () => {
    it('reports the absence of an override as undefined, not null', () => {
      // The distinction undo depends on: restoring `null` where there was
      // nothing would leave a key behind, and `apply_mount_overrides` would
      // then apply `null` over the package's real value.
      expect(context('concierge/wf-music').readOverride('agent-sql', 'rules')).toBeUndefined();
    });

    it('reports a value that is there', () => {
      const ctx = context('concierge/wf-music');
      ctx.writeOverride('agent-sql', 'rules', 'stricter here');
      expect(ctx.readOverride('agent-sql', 'rules')).toBe('stricter here');
    });
  });

  describe('clearOverride — back to the package default', () => {
    it('removes the key rather than writing an empty value', () => {
      const ctx = context('concierge/wf-music');
      ctx.writeOverride('agent-sql', 'rules', 'x');
      ctx.clearOverride('agent-sql', 'rules');
      expect(ctx.readOverride('agent-sql', 'rules')).toBeUndefined();
    });

    it('drops the whole mount blob once nothing is overridden', () => {
      // Otherwise the card would read "1 overridden" over an empty object, and
      // the document would carry noise that means nothing.
      const ctx = context('concierge/wf-music');
      ctx.writeOverride('agent-sql', 'rules', 'x');
      ctx.clearOverride('agent-sql', 'rules');
      expect(overridesOf(ctx.rootDocument, 'wf-music')).toBeUndefined();
    });
  });

  describe('a grandchild, which composes rather than needing a second document', () => {
    it('writes through the parent mount as an override of its overrides', () => {
      const ctx = context('concierge/wf-music/wf-inner');
      ctx.writeOverride('deep', 'rules', 'set from the grandparent');
      expect(overridesOf(ctx.rootDocument, 'wf-music')).toEqual({
        'wf-inner': { overrides: { deep: { rules: 'set from the grandparent' } } },
      });
    });

    it('reads its own value back through the same path', () => {
      const ctx = context('concierge/wf-music/wf-inner');
      ctx.writeOverride('deep', 'rules', 'set from the grandparent');
      expect(ctx.readOverride('deep', 'rules')).toBe('set from the grandparent');
    });

    it('does not disturb an override the parent level already had', () => {
      const ctx = context('concierge/wf-music/wf-inner');
      const sibling = context('concierge/wf-music', ctx.rootDocument);
      sibling.writeOverride('agent-sql', 'rules', 'parent level');
      ctx.writeOverride('deep', 'rules', 'grandchild level');
      expect(overridesOf(ctx.rootDocument, 'wf-music')).toEqual({
        'agent-sql': { rules: 'parent level' },
        'wf-inner': { overrides: { deep: { rules: 'grandchild level' } } },
      });
    });
  });

  it('refuses an address that names no mount', () => {
    // A class address has no instance to write to; constructing a context for
    // one is a programming error, not a runtime condition to paper over.
    expect(() => context('concierge')).toThrow();
  });

  it('survives a mount node that is not in the document', () => {
    // The root package changed under an open instance — a stale address. It
    // must not corrupt the document by inventing the node.
    const ctx = context('concierge/wf-gone');
    expect(() => ctx.writeOverride('a', 'b', 'c')).toThrow();
  });
});
