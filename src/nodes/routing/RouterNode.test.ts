import { beforeEach, describe, expect, it } from 'vitest';
import { defaultsFrom } from '@core/model/contracts/fields';
import { maxConnectionsOf } from '@core/model/contracts/ports';
import { makeWorkbench } from '@core/testing/fixtures';
import type { Workbench } from '@app/Workbench';
import {
  branchesOf,
  createRouterNode,
  ROUTER_OUTPUT_CONTRACT,
  ROUTER_PREAMBLE,
  ROUTER_TYPE,
  type RouterNodeModel,
} from './RouterNode';
import { CredentialStore, ProviderRegistry } from '@core/providers/ProviderRegistry';

/**
 * Materialised once per file. The definition is now built from the
 * `ProviderRegistry` — every model-driven family carries the shared model
 * picker (`../modelField`) — so the tests build one the same way the
 * catalogue does rather than asserting against a shape nothing registers.
 */
const routerNode = createRouterNode(new ProviderRegistry(new CredentialStore(false)));

/**
 * The Router — the first *role* preset (ticket 28).
 *
 * It exists to prove one mechanism: **N output ports derived from config**. That
 * is what makes "drag a router, name your branches, wire them" possible without
 * any new engine concept — `ports` is already a function of node data, so the
 * branch list drives the port list.
 *
 * The property that matters most here is the one CLAUDE.md calls out: prefer
 * varying the *number* of ports over toggling one port's cardinality. A router
 * with one multi-output port would need the compiler to guess which link is
 * which branch; N single-purpose ports make the destination set explicit, which
 * is exactly what ticket 03 requires the canvas to capture.
 */
describe('branchesOf', () => {
  it('parses branches from an array with stable ids', () => {
    expect(
      branchesOf({
        branches: [
          { id: 'x', name: 'dataquery' },
          { id: 'y', name: 'help' },
          { id: 'z', name: 'greeting' },
        ],
      }),
    ).toEqual([
      { id: 'x', name: 'dataquery' },
      { id: 'y', name: 'help' },
      { id: 'z', name: 'greeting' },
    ]);
  });

  it('ignores blank entries', () => {
    expect(
      branchesOf({
        branches: [
          { id: 'a', name: 'a' },
          { id: 'b', name: '' },
          { id: 'c', name: 'b' },
        ],
      }),
    ).toEqual([
      { id: 'a', name: 'a' },
      { id: 'c', name: 'b' },
    ]);
  });

  it('deduplicates by id, because two ports cannot share an id', () => {
    expect(
      branchesOf({
        branches: [
          { id: 'x', name: 'a' },
          { id: 'y', name: 'b' },
          { id: 'x', name: 'a-duplicate' },
        ],
      }),
    ).toEqual([
      { id: 'x', name: 'a' },
      { id: 'y', name: 'b' },
    ]);
  });

  it('falls back to a single branch rather than a node with no outputs', () => {
    // A router with zero outputs is unwireable and looks broken. One default
    // output is recoverable; none is a dead end.
    expect(branchesOf({ branches: [] }).length).toBe(1);
  });

  it('caps the branch count so the card stays readable', () => {
    const many = Array.from({ length: 30 }, (_, i) => ({ id: `b${i}`, name: `b${i}` }));
    expect(branchesOf({ branches: many }).length).toBeLessThanOrEqual(12);
  });

  it('migrates from old newline-separated text format', () => {
    // Backward compatibility: old documents have branches as newline-separated text
    const result = branchesOf({ branches: 'dataquery\nhelp\ngreeting' });
    // Should parse the text and assign stable ids
    expect(result).toHaveLength(3);
    expect(result.map((r) => r.name)).toEqual(['dataquery', 'help', 'greeting']);
    expect(result.every((r) => r.id)).toBe(true);
  });
});

describe('routerNode ports', () => {
  const portsFor = (data: Record<string, unknown>) =>
    routerNode.ports({ ...defaultsFrom(routerNode.fields), ...data } as never);

  it('exposes exactly one output per branch', () => {
    const ports = portsFor({
      branches: [
        { id: 'x', name: 'dataquery' },
        { id: 'y', name: 'help' },
        { id: 'z', name: 'off_topic' },
      ],
    });
    const outs = ports.filter((p) => p.direction === 'out');
    expect(outs.map((p) => p.label)).toEqual(['dataquery', 'help', 'off_topic']);
  });

  it('changes its port count when the branch list changes', () => {
    const before = portsFor({
      branches: [
        { id: 'a', name: 'a' },
        { id: 'b', name: 'b' },
      ],
    }).filter((p) => p.direction === 'out');
    const after = portsFor({
      branches: [
        { id: 'a', name: 'a' },
        { id: 'b', name: 'b' },
        { id: 'c', name: 'c' },
      ],
    }).filter((p) => p.direction === 'out');
    expect(before).toHaveLength(2);
    expect(after).toHaveLength(3);
  });

  it('takes exactly one input — a router classifies one thing at a time', () => {
    // One *flow* input. The `skill` port is a binding, not a stage: it is
    // equipment attached to the step, drawn across the reading axis, and it
    // carries no text to classify.
    const ins = portsFor({}).filter((p) => p.direction === 'in' && p.id !== 'skill');
    expect(ins).toHaveLength(1);
    expect(maxConnectionsOf(ins[0]!)).toBe(1);
  });

  it('uses the stable id for the port id, not the slugified name', () => {
    const ports = portsFor({ branches: [{ id: 'my-stable-id', name: 'Data Query' }] });
    const out = ports.find((p) => p.direction === 'out');
    // Port id now uses the stable id directly, not a slugified version
    expect(out?.id).toBe('branch:my-stable-id');
    expect(out?.label).toBe('Data Query');
  });

  it('preserves the port id even when the branch name changes', () => {
    const before = portsFor({ branches: [{ id: 'b1', name: 'off_topic' }] });
    const after = portsFor({ branches: [{ id: 'b1', name: 'off-topic-renamed' }] });
    const beforeOut = before.find((p) => p.direction === 'out');
    const afterOut = after.find((p) => p.direction === 'out');
    // The port id stays the same because the id is stable
    expect(beforeOut?.id).toBe(afterOut?.id);
    expect(beforeOut?.label).not.toBe(afterOut?.label);
  });

  it('gives every port a unique id even for names that slugify alike', () => {
    const ports = portsFor({
      branches: [
        { id: 'x', name: 'a b' },
        { id: 'y', name: 'a-b' },
      ],
    });
    const ids = ports.filter((p) => p.direction === 'out').map((p) => p.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('lets a branch fan out to several nodes', () => {
    // One branch legitimately feeds two downstream nodes; capping it at one
    // would force a pointless pass-through node.
    const out = portsFor({ branches: [{ id: 'x', name: 'a' }] }).find((p) => p.direction === 'out');
    expect(maxConnectionsOf(out!)).toBeNull();
  });

  it('marks the fallback branch, so an unmatched question is visibly handled', () => {
    const ports = portsFor({
      branches: [
        { id: 'x', name: 'dataquery' },
        { id: 'y', name: 'help' },
      ],
      fallback: 'help',
    });
    const fallback = ports.find((p) => p.label === 'help');
    expect(fallback?.description).toMatch(/fallback|unmatched/i);
  });
});

describe('routerNode registration', () => {
  let workbench: Workbench;

  beforeEach(() => {
    workbench = makeWorkbench();
  });

  it('is in the catalogue as a generic node, not a workflow-scoped one', () => {
    // Routing is the editor's *grammar* — every workflow composes with it — so
    // it ships globally, unlike the Chinook tools (ticket 08 scoping rule).
    expect(workbench.registry.nodeTypes.get(ROUTER_TYPE)).toBeDefined();
  });

  it('declares a tier field rather than a tier per node type', () => {
    // Ticket 28: role is the node type, tier is a field. Making both node types
    // would give role x tier palette entries.
    const tier = routerNode.fields.find((f) => f.key === 'tier');
    expect(tier).toBeDefined();
    expect(tier?.kind).toBe('select');
  });

  it('can be added to a workflow and wired from its branches', () => {
    const router = workbench.controller.nodes.add(ROUTER_TYPE, { x: 0, y: 0 });
    expect(router.ok).toBe(true);
    const node = workbench.model.nodes().find((n) => n.type === ROUTER_TYPE);
    expect(node).toBeDefined();
    expect(node!.ports.filter((p) => p.direction === 'out').length).toBeGreaterThan(0);
  });

  it('re-derives its ports after the branch list is edited', () => {
    workbench.controller.nodes.add(ROUTER_TYPE, { x: 0, y: 0 });
    const node = workbench.model.nodes().find((n) => n.type === ROUTER_TYPE)!;

    workbench.controller.nodes.setField(node.id, 'branches', [
      { id: '1', name: 'one' },
      { id: '2', name: 'two' },
      { id: '3', name: 'three' },
      { id: '4', name: 'four' },
    ]);

    const fresh = workbench.model.node(node.id)!;
    expect(fresh.ports.filter((p) => p.direction === 'out')).toHaveLength(4);
  });
});

/**
 * Prompt composition — the base owns the machinery, the developer owns the rules.
 *
 * This is the mental model for **every** node that drives a model, not just the
 * router: whatever must be true for the node to work at all is locked on the
 * base and is not a field. Before this, the router shipped one editable
 * `instruction` textarea pre-filled with the output contract — so clearing it,
 * which is the first thing anyone does when writing their own rules, produced a
 * router whose answer could not be parsed.
 */
describe('router prompt composition', () => {
  let workbench: Workbench;

  const router = (): RouterNodeModel => {
    workbench.controller.nodes.add(ROUTER_TYPE, { x: 0, y: 0 });
    return workbench.model.nodes().find((n) => n.type === ROUTER_TYPE) as RouterNodeModel;
  };

  beforeEach(() => {
    workbench = makeWorkbench();
  });

  it("starts with no rules, because rules are the developer's to write", () => {
    expect(router().rules).toBe('');
  });

  it('still produces a complete prompt with no rules at all', () => {
    const prompt = router().systemPrompt;
    expect(prompt).toContain(ROUTER_PREAMBLE);
    expect(prompt).toContain(ROUTER_OUTPUT_CONTRACT);
    expect(prompt).toContain('dataquery');
  });

  it('includes the developer rules verbatim', () => {
    const node = router();
    workbench.controller.nodes.setField(node.id, 'rules', 'Revenue questions are dataquery.');
    const fresh = workbench.model.node(node.id) as RouterNodeModel;
    expect(fresh.systemPrompt).toContain('Revenue questions are dataquery.');
  });

  it('keeps the output contract even when the rules field is cleared', () => {
    const node = router();
    workbench.controller.nodes.setField(node.id, 'rules', '');
    const fresh = workbench.model.node(node.id) as RouterNodeModel;
    // The reason the contract is not a field at all.
    expect(fresh.systemPrompt).toContain(ROUTER_OUTPUT_CONTRACT);
  });

  it('puts the output contract AFTER the rules, so rules cannot countermand it', () => {
    const node = router();
    workbench.controller.nodes.setField(node.id, 'rules', 'Explain your reasoning at length.');
    const prompt = (workbench.model.node(node.id) as RouterNodeModel).systemPrompt;

    // Later instructions win ties. Contract last, or that rule breaks parsing.
    expect(prompt.indexOf('Explain your reasoning')).toBeLessThan(
      prompt.indexOf(ROUTER_OUTPUT_CONTRACT),
    );
  });

  it('names the fallback in the prompt so the model knows the escape hatch', () => {
    expect(router().systemPrompt).toContain('nothing else matches');
  });

  it('exposes no field that can delete the machinery', () => {
    const editable = routerNode.fields.map((f) => f.key);
    expect(editable).toContain('rules');
    // Nothing named for the preamble or contract — they are not authorable.
    expect(editable).not.toContain('instruction');
    expect(editable).not.toContain('preamble');
    expect(editable).not.toContain('outputContract');
  });
});
