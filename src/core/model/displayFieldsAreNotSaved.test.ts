import { describe, expect, it } from 'vitest';

import { allNodeDefinitions } from '@nodes/portSpecs';
import { defaultsFrom, displayOnlyKeys } from '@core/model/contracts/fields';
import type { INodeDefinition } from '@core/model/contracts/node';

/**
 * The editor's own help text was being saved into the user's repository
 * (production-ready 52).
 *
 * `workflow.json` is the vendor-neutral compile input a developer versions in
 * git. Saving a workflow containing one `tool.mcp` node wrote ~1.5 KB of the
 * inspector's read-only prose into it — the **ONE NODE, ONE CONSUMER** and
 * **WHAT THE MACHINERY ALREADY DOES** blocks, verbatim. They are not
 * configuration, they compile to nothing, and no shipped example carries them,
 * so an editor-saved package and a hand-written one of the same graph did not
 * compare equal.
 *
 * **Fixed at the contract, not at the two keys.** `mcpGuide` and `mcpNote` are
 * simply the two that were noticed; `segmentNote` and the guardrail's policy
 * note are the same field kind used the same way, and the next family to add a
 * note block would have reintroduced it. A `readonly` field is a *display* of
 * text the schema already holds, so `defaultsFrom` no longer seeds one and a
 * node model no longer carries one — which makes this a property of every node
 * type at once rather than a rule someone has to remember.
 */
const definitions: readonly INodeDefinition[] = allNodeDefinitions();

const byId = (id: string): INodeDefinition => {
  const found = definitions.find((definition) => definition.id === id);
  expect(found, `${id} is not in the catalogue`).toBeDefined();
  return found as INodeDefinition;
};

describe('read-only fields are display, not data', () => {
  it('finds the node types that have one at all', () => {
    // Anti-vacuity: every assertion below is over "definitions with a
    // read-only field", and a probe that found none would make them all
    // trivially true. Four exist today, across three different families.
    const withDisplay = definitions.filter((d) => displayOnlyKeys(d.fields).length > 0);

    expect(withDisplay.length).toBeGreaterThanOrEqual(3);
    expect(withDisplay.map((d) => d.id)).toContain('tool.mcp');
  });

  it('never seeds one into a node type is defaults', () => {
    for (const definition of definitions) {
      const seeded = Object.keys(defaultsFrom(definition.fields));
      for (const key of displayOnlyKeys(definition.fields)) {
        expect(seeded, `${definition.id} seeds ${key} into its data`).not.toContain(key);
      }
    }
  });

  it('drops one that a document saved before the fix still carries', () => {
    // The migration case, and it needs no migration step: an old document
    // opens, the model refuses the key, and the next save is clean. A schema
    // migration would have been a version bump for a key that means nothing.
    const node = byId('tool.mcp').create({
      position: { x: 0, y: 0 },
      data: { mcpGuide: 'stale help text', mcpNote: 'more stale help text' },
    });

    expect(Object.keys(node.data)).not.toContain('mcpGuide');
    expect(Object.keys(node.toJSON().data)).not.toContain('mcpNote');
  });

  it('keeps every key that is actually configuration', () => {
    // The other half, and the one a careless fix would break: a node with a
    // read-only field also has real fields, and they must survive.
    const node = byId('tool.mcp').create({ position: { x: 0, y: 0 } });

    expect(Object.keys(node.data)).toContain('servers');
  });

  it('leaves the text on the schema, where the inspector reads it', () => {
    // Not persisted is not deleted. The prose is still declared, still shown
    // read-only beside the editable field, and still what the ticket that
    // added it wanted — a developer can see what the machinery already says
    // instead of duplicating or contradicting it.
    const guide = byId('tool.mcp').fields.find((field) => field.key === 'mcpGuide');

    expect(guide?.kind).toBe('readonly');
    expect(String(guide?.defaultValue ?? '')).toContain('One node per group of servers');
  });
});

describe('a saved node carries only configurable keys', () => {
  it('holds for every node type in the catalogue', () => {
    // The assertion the ticket asks for, over the whole registry rather than
    // over the one node that happened to be reported.
    for (const definition of definitions) {
      const configurable = new Set(Object.keys(defaultsFrom(definition.fields)));
      const saved = Object.keys(definition.create({ position: { x: 0, y: 0 } }).toJSON().data);
      const extra = saved.filter((key) => !configurable.has(key));

      expect(extra, `${definition.id} saves ${extra.join(', ')} which no field declares`).toEqual(
        [],
      );
    }
  });
});
