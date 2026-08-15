import { describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { CATEGORY } from '../vocabulary';
import { ASSEMBLIES, assemblyById } from './index';
import { STARTER_ASSEMBLY_ID, starterAssembly } from './starter';

/**
 * production-ready ticket 22 — the canvas teaches its own first flow.
 *
 * A new user faces an empty canvas and ~20 node types with nothing saying
 * which comes first. The owner's decision: the taught starter is
 * **Input → Agent → Output**, and the cheapest honest way to hand it over is
 * the mechanism ticket 21 already built — an assembly, dropped by one drag as
 * ordinary nodes and ordinary edges.
 *
 * **Not a rule.** Nothing in this repository requires a flow to begin at an
 * input or end at `output.formatted` (see `emptyStateCopy.test.ts`), so this
 * is a starting point, not a scaffold anybody is made to accept.
 */
describe('the starter assembly', () => {
  const { fragment } = starterAssembly;

  it('is findable by the id a palette drag carries', () => {
    expect(assemblyById(STARTER_ASSEMBLY_ID)).toBe(starterAssembly);
  });

  it('is the three nodes the owner named, in that order', () => {
    expect(fragment.nodes.map((node) => node.type)).toEqual([
      'input.text',
      'agent.llm',
      'output.formatted',
    ]);
  });

  it('arrives already wired, which is the whole reason it is one drag', () => {
    expect(fragment.edges).toHaveLength(2);
    expect(fragment.edges[0]?.source.portId).toBe('text');
    expect(fragment.edges[0]?.target.portId).toBe('prompt');
    expect(fragment.edges[1]?.source.portId).toBe('result');
    expect(fragment.edges[1]?.target.portId).toBe('result');
  });

  it('reads left to right, the way the canvas does', () => {
    const xs = fragment.nodes.map((node) => node.position.x);
    expect([...xs].sort((a, b) => a - b)).toEqual(xs);
  });

  it('sits with the organisms — it is an assembly, not an atom', () => {
    expect(starterAssembly.category).toBe(CATEGORY.compose);
  });

  it('carries no prompt of its own', () => {
    // A seeded question would be someone else's question, and the Run button
    // reads this field: a starter that ships text would run *that* on the
    // first press. The Input is the one thing the user must supply.
    const input = fragment.nodes[0];
    expect(String(input?.data?.['prompt'] ?? '')).toBe('');
  });

  it('joins the revision loop rather than replacing it', () => {
    expect(ASSEMBLIES).toHaveLength(2);
    expect(ASSEMBLIES.map((assembly) => assembly.id)).toContain(STARTER_ASSEMBLY_ID);
  });

  it('is findable by the words a beginner types', () => {
    expect(starterAssembly.keywords).toEqual(
      expect.arrayContaining(['start', 'first', 'basic', 'input', 'output']),
    );
  });
});

describe('every node and port the starter names really exists', () => {
  /**
   * The failure this guards is silent: a fragment naming a port id that was
   * renamed inserts nodes with no edge between them, and the drop still looks
   * like it worked.
   */
  const workbench = new Workbench();

  it('names registered node types', () => {
    for (const node of starterAssembly.fragment.nodes) {
      expect(workbench.registry.nodeTypes.get(node.type), node.type).toBeDefined();
    }
  });

  it('names ports those node types actually declare', () => {
    const portsOf = (typeId: string): string[] => {
      const definition = workbench.registry.nodeTypes.get(typeId);
      const ports =
        typeof definition?.ports === 'function' ? definition.ports({}) : definition?.ports;
      return (ports ?? []).map((port) => port.id);
    };
    const typeOf = new Map(starterAssembly.fragment.nodes.map((node) => [node.id, node.type]));

    for (const edge of starterAssembly.fragment.edges) {
      expect(portsOf(typeOf.get(edge.source.nodeId)!)).toContain(edge.source.portId);
      expect(portsOf(typeOf.get(edge.target.nodeId)!)).toContain(edge.target.portId);
    }
  });
});

describe('dropping the starter onto a canvas', () => {
  const insert = (workbench: Workbench) =>
    workbench.controller.clipboard.insertFragment(starterAssembly.fragment, { x: 80, y: 80 });

  it('lands as ordinary nodes and ordinary edges', () => {
    const workbench = new Workbench();
    expect(insert(workbench).ok).toBe(true);

    const document = JSON.parse(workbench.controller.document.exportJSON()) as {
      nodes: { type: string }[];
      edges: unknown[];
    };
    expect(document.nodes).toHaveLength(3);
    expect(document.edges).toHaveLength(2);
    // Afterwards nothing in the document remembers an assembly was involved —
    // the property that keeps `workflow.json` portable.
    expect(JSON.stringify(document)).not.toContain('assembly');
  });

  it('produces a graph the compiler can walk end to end', () => {
    const workbench = new Workbench();
    insert(workbench);
    const document = JSON.parse(workbench.controller.document.exportJSON()) as {
      nodes: { id: string; type: string }[];
      edges: { source: { nodeId: string }; target: { nodeId: string } }[];
    };
    const incoming = new Set(document.edges.map((edge) => edge.target.nodeId));
    const outgoing = new Set(document.edges.map((edge) => edge.source.nodeId));
    // Structurally an entry and an exit — which is the only thing the compiler
    // actually asks for.
    expect(document.nodes.filter((node) => !incoming.has(node.id))).toHaveLength(1);
    expect(document.nodes.filter((node) => !outgoing.has(node.id))).toHaveLength(1);
  });

  it('is one undo, not five', () => {
    const workbench = new Workbench();
    insert(workbench);
    workbench.controller.history.undo();

    const document = JSON.parse(workbench.controller.document.exportJSON()) as {
      nodes: unknown[];
      edges: unknown[];
    };
    expect(document.nodes).toHaveLength(0);
    expect(document.edges).toHaveLength(0);
  });

  it('mints fresh ids, so a second drop does not collide with the first', () => {
    const workbench = new Workbench();
    insert(workbench);
    insert(workbench);

    const document = JSON.parse(workbench.controller.document.exportJSON()) as {
      nodes: { id: string }[];
    };
    expect(document.nodes).toHaveLength(6);
    expect(new Set(document.nodes.map((node) => node.id)).size).toBe(6);
  });
});
