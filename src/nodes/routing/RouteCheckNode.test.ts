import { beforeEach, describe, expect, it } from 'vitest';
import { addNode, connect, makeWorkbench, TYPE } from '@core/testing/fixtures';
import type { Workbench } from '@app/Workbench';
import { maxConnectionsOf } from '@core/model/contracts/ports';
import { PORT } from '../vocabulary';
import { ROUTE_CHECK_TYPE, type RouteCheckNodeModel } from './RouteCheckNode';

/**
 * `osg-agent-experience/42`. A classifier's mechanical sibling: one branch per
 * row, decided by a package function instead of a model, and — the whole
 * point — every way out typed `result`, so an `output.formatted` may take one.
 * A grader's and a guard's `revise` is `feedback`-typed, which an output does
 * not accept, and that is why an ask-back had no deterministic edge to ride.
 */
describe('route check — the shape a fork has', () => {
  let workbench: Workbench;

  const fork = (): RouteCheckNodeModel => {
    workbench.controller.nodes.add(ROUTE_CHECK_TYPE, { x: 0, y: 0 });
    return workbench.model.nodes().find((n) => n.type === ROUTE_CHECK_TYPE) as RouteCheckNodeModel;
  };

  beforeEach(() => {
    workbench = makeWorkbench();
  });

  it('names the check on the card, or says none is named', () => {
    const node = fork();
    expect(node.subtitle).toBe('No check named yet.');
    workbench.controller.nodes.setField(node.id, 'check', 'needs_a_date_range');
    const reread = workbench.model.node(node.id) as RouteCheckNodeModel;
    expect(reread.subtitle).toBe('checks: needs_a_date_range');
  });

  it('declares one `branch:<id>` out-port per configured branch, plus a fallback', () => {
    const node = fork();
    const outputs = node.ports.filter((port) => port.direction === 'out');

    expect(outputs.map((port) => port.id)).toContain('fallback');
    for (const entry of node.branches) {
      expect(outputs.map((port) => port.id)).toContain(`branch:${entry.id}`);
    }
  });

  it('types every way out `result`, so an output or an agent may hang off any of them', () => {
    const node = fork();
    for (const port of node.ports.filter((p) => p.direction === 'out')) {
      expect(port.type).toBe(PORT.result);
    }
  });

  it('carries one edge per branch, derived from `branch` rather than written out', () => {
    const node = fork();
    for (const port of node.ports.filter((p) => p.direction === 'out')) {
      expect(port.branch).toBe(true);
      expect(maxConnectionsOf(port)).toBe(1);
    }
  });

  it('drives no model — it declares no model field', () => {
    const definition = workbench.registry.nodeTypes.get(ROUTE_CHECK_TYPE);
    expect(definition?.fields.some((field) => field.key === 'model')).toBe(false);
  });
});

describe('route check — what it may be wired to', () => {
  let workbench: Workbench;

  beforeEach(() => {
    workbench = makeWorkbench();
  });

  it('lets an output hang off a branch — the edge the ticket exists for', () => {
    const input = addNode(workbench, TYPE.textInput);
    const node = addNode(workbench, ROUTE_CHECK_TYPE);
    const output = addNode(workbench, TYPE.output);
    connect(workbench, input, 'text', node, 'candidate');

    const branch = (node as RouteCheckNodeModel).branches[0]!;
    const verdict = workbench.controller.edges.connect(
      { nodeId: node.id, portId: `branch:${branch.id}` },
      { nodeId: output.id, portId: 'result' },
    );

    expect(verdict.ok).toBe(true);
  });

  it('refuses a second edge out of one branch — a fork has one way out per branch', () => {
    const node = addNode(workbench, ROUTE_CHECK_TYPE);
    const first = addNode(workbench, TYPE.output);
    const second = addNode(workbench, TYPE.output);
    const branch = (node as RouteCheckNodeModel).branches[0]!;

    workbench.controller.edges.connect(
      { nodeId: node.id, portId: `branch:${branch.id}` },
      { nodeId: first.id, portId: 'result' },
    );
    const verdict = workbench.controller.edges.connect(
      { nodeId: node.id, portId: `branch:${branch.id}` },
      { nodeId: second.id, portId: 'result' },
    );

    expect(verdict.ok).toBe(false);
  });
});
