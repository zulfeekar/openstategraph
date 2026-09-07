import { describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { CATEGORY } from '../vocabulary';
import { ASSEMBLIES, assemblyById } from './index';
import { REVISION_LOOP_ASSEMBLY_ID, revisionLoopAssembly } from './revisionLoop';

/**
 * production-ready ticket 21 — a revision loop in one drag.
 *
 * The gap: getting `input → agent → grader → output` with `revise` wired back
 * onto the canvas you are *already working in* took four drags and four edges,
 * one of which a user finds by drawing an illegal edge and reading the
 * rejection. Ticket 01 claimed to have closed this and shipped the scaffold
 * instead — `--template loop` starts a **new workflow**.
 *
 * What this is not: a node type (a `Loop` node compiles to nothing new), a
 * template (that produces a document and stops existing), or a mount (that is
 * by reference and isolated). It drops ordinary nodes and ordinary edges.
 */
describe('the revision loop assembly', () => {
  const { fragment } = revisionLoopAssembly;

  it('is findable by the id a palette drag carries', () => {
    expect(assemblyById(REVISION_LOOP_ASSEMBLY_ID)).toBe(revisionLoopAssembly);
    expect(assemblyById('assembly.nope')).toBeNull();
  });

  it('sits with the organisms, not the molecules', () => {
    // Ticket 14 exists because the palette once filed an organism under
    // molecules. An assembly of molecules is an organism.
    expect(revisionLoopAssembly.category).toBe(CATEGORY.compose);
  });

  it('wires revise back to feedback — the one edge this exists for', () => {
    const revise = fragment.edges.find((edge) => edge.source.portId === 'revise');
    expect(revise).toBeDefined();
    expect(revise!.target.portId).toBe('feedback');
  });

  it('sends the agent’s result to the grader for judging', () => {
    const forward = fragment.edges.find((edge) => edge.source.portId === 'result');
    expect(forward?.target.portId).toBe('candidate');
  });

  it('inserts no input or output of its own', () => {
    // `output.formatted` declares no maxInstances, so nothing would stop a
    // second one appearing beside the canvas's existing sink.
    const types = fragment.nodes.map((node) => node.type);
    expect(types.some((type) => type.startsWith('input.'))).toBe(false);
    expect(types.some((type) => type.startsWith('output.'))).toBe(false);
  });

  it('seeds the grader with criteria that say something', () => {
    // A vague grader never passes, so the loop spends its whole attempt
    // budget and emits its best effort regardless.
    const grader = fragment.nodes.find((node) => node.type === 'route.grader');
    expect(String(grader?.data?.['criteria'] ?? '').length).toBeGreaterThan(40);
  });

  it('bounds the loop, so a stranger cannot drop an unbounded one', () => {
    const grader = fragment.nodes.find((node) => node.type === 'route.grader');
    expect(Number(grader?.data?.['maxAttempts'])).toBeGreaterThan(0);
  });

  it('is one of the assemblies the palette offers', () => {
    // It was the only one until ticket 22 added the starter — which is how
    // ticket 21 said a second entry should arrive: because somebody asked,
    // as a data change to this list rather than a new mechanism.
    expect(ASSEMBLIES).toContain(revisionLoopAssembly);
  });
});

describe('every node and port it names really exists', () => {
  /**
   * The failure this guards is silent: a fragment naming a port id that was
   * renamed inserts nodes with no edge between them, and the drop still looks
   * like it worked.
   */
  const workbench = new Workbench();

  it('names registered node types', () => {
    for (const node of revisionLoopAssembly.fragment.nodes) {
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
    const typeOf = new Map(revisionLoopAssembly.fragment.nodes.map((n) => [n.id, n.type]));

    for (const edge of revisionLoopAssembly.fragment.edges) {
      expect(
        portsOf(typeOf.get(edge.source.nodeId)!),
        `${edge.source.nodeId}.${edge.source.portId}`,
      ).toContain(edge.source.portId);
      expect(
        portsOf(typeOf.get(edge.target.nodeId)!),
        `${edge.target.nodeId}.${edge.target.portId}`,
      ).toContain(edge.target.portId);
    }
  });
});

describe('dropping it onto a canvas', () => {
  const insert = (workbench: Workbench) =>
    workbench.controller.clipboard.insertFragment(revisionLoopAssembly.fragment, { x: 100, y: 60 });

  it('lands as ordinary nodes and ordinary edges', () => {
    // The property that keeps `workflow.json` portable: afterwards nothing in
    // the document remembers an assembly was involved.
    const workbench = new Workbench();
    expect(insert(workbench).ok).toBe(true);

    const document = JSON.parse(workbench.controller.document.exportJSON()) as {
      nodes: { type: string }[];
      edges: { source: { portId: string }; target: { portId: string } }[];
    };
    expect(document.nodes.map((n) => n.type).sort()).toEqual(['agent.llm', 'route.grader']);
    expect(JSON.stringify(document)).not.toContain('assembly');
  });

  it('arrives with revise already wired — the whole point', () => {
    const workbench = new Workbench();
    insert(workbench);
    const document = JSON.parse(workbench.controller.document.exportJSON()) as {
      edges: { source: { portId: string }; target: { portId: string } }[];
    };
    expect(
      document.edges.some((e) => e.source.portId === 'revise' && e.target.portId === 'feedback'),
    ).toBe(true);
  });

  it('is one undo, not four', () => {
    // A four-step undo for one drag is the kind of detail that makes an
    // affordance feel broken even when it works.
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

  it('mints fresh ids, so dropping it twice does not collide', () => {
    const workbench = new Workbench();
    insert(workbench);
    insert(workbench);

    const document = JSON.parse(workbench.controller.document.exportJSON()) as {
      nodes: { id: string }[];
      edges: unknown[];
    };
    expect(document.nodes).toHaveLength(4);
    expect(new Set(document.nodes.map((n) => n.id)).size).toBe(4);
    expect(document.edges).toHaveLength(4);
  });

  it('leaves the clipboard alone', () => {
    // Dropping a loop must not overwrite what the developer had copied.
    const workbench = new Workbench();
    insert(workbench);
    expect(workbench.controller.clipboard.paste({ x: 0, y: 0 }).ok).toBe(false);
  });
});
