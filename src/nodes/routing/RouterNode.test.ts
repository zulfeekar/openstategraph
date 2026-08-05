import { beforeEach, describe, expect, it } from 'vitest';
import { defaultsFrom } from '@core/model/contracts/fields';
import { maxConnectionsOf } from '@core/model/contracts/ports';
import { makeWorkbench } from '@core/testing/fixtures';
import type { Workbench } from '@app/Workbench';
import { branchesOf, routerNode, ROUTER_TYPE } from './RouterNode';

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
  it('parses one branch per line', () => {
    expect(branchesOf({ branches: 'dataquery\nhelp\ngreeting' })).toEqual([
      'dataquery',
      'help',
      'greeting',
    ]);
  });

  it('ignores blank lines and surrounding whitespace', () => {
    expect(branchesOf({ branches: '  a  \n\n\n  b \n ' })).toEqual(['a', 'b']);
  });

  it('deduplicates, because two ports cannot share an id', () => {
    expect(branchesOf({ branches: 'a\nb\na' })).toEqual(['a', 'b']);
  });

  it('is case-insensitive when deduplicating, since ids are slugified', () => {
    expect(branchesOf({ branches: 'Help\nhelp' })).toEqual(['Help']);
  });

  it('falls back to a single branch rather than a node with no outputs', () => {
    // A router with zero outputs is unwireable and looks broken. One default
    // output is recoverable; none is a dead end.
    expect(branchesOf({ branches: '' }).length).toBe(1);
  });

  it('caps the branch count so the card stays readable', () => {
    const many = Array.from({ length: 30 }, (_, i) => `b${i}`).join('\n');
    expect(branchesOf({ branches: many }).length).toBeLessThanOrEqual(12);
  });
});

describe('routerNode ports', () => {
  const portsFor = (data: Record<string, unknown>) =>
    routerNode.ports({ ...defaultsFrom(routerNode.fields), ...data } as never);

  it('exposes exactly one output per branch', () => {
    const ports = portsFor({ branches: 'dataquery\nhelp\noff_topic' });
    const outs = ports.filter((p) => p.direction === 'out');
    expect(outs.map((p) => p.label)).toEqual(['dataquery', 'help', 'off_topic']);
  });

  it('changes its port count when the branch list changes', () => {
    const before = portsFor({ branches: 'a\nb' }).filter((p) => p.direction === 'out');
    const after = portsFor({ branches: 'a\nb\nc' }).filter((p) => p.direction === 'out');
    expect(before).toHaveLength(2);
    expect(after).toHaveLength(3);
  });

  it('takes exactly one input — a router classifies one thing at a time', () => {
    const ins = portsFor({}).filter((p) => p.direction === 'in');
    expect(ins).toHaveLength(1);
    expect(maxConnectionsOf(ins[0]!)).toBe(1);
  });

  it('slugifies a branch name into a port id but keeps the label readable', () => {
    const ports = portsFor({ branches: 'Data Query' });
    const out = ports.find((p) => p.direction === 'out');
    expect(out?.id).toBe('branch:data-query');
    expect(out?.label).toBe('Data Query');
  });

  it('gives every port a unique id even for names that slugify alike', () => {
    const ports = portsFor({ branches: 'a b\na-b' });
    const ids = ports.filter((p) => p.direction === 'out').map((p) => p.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('lets a branch fan out to several nodes', () => {
    // One branch legitimately feeds two downstream nodes; capping it at one
    // would force a pointless pass-through node.
    const out = portsFor({ branches: 'a' }).find((p) => p.direction === 'out');
    expect(maxConnectionsOf(out!)).toBeNull();
  });

  it('marks the fallback branch, so an unmatched question is visibly handled', () => {
    const ports = portsFor({ branches: 'dataquery\nhelp', fallback: 'help' });
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

    workbench.controller.nodes.setField(node.id, 'branches', 'one\ntwo\nthree\nfour');

    const fresh = workbench.model.node(node.id)!;
    expect(fresh.ports.filter((p) => p.direction === 'out')).toHaveLength(4);
  });
});
