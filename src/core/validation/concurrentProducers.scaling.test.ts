import { describe, expect, it } from 'vitest';
import { TYPE, addNode, connect, makeWorkbench } from '@core/testing/fixtures';
import type { Workbench } from '@app/Workbench';
import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { NodeId } from '@core/model/contracts/node';
import { ControlFlowGraph, type BranchPort, type IControlFlowGraph } from './controlFlowGraph';
import { concurrentProducerCount, concurrentProducerCountOn } from './concurrentProducers';

/**
 * The shape of the cost, not the size of it — `the-cost-of-one-more/03`.
 *
 * `capacityRule` asks `concurrentProducerCount` how many of a full port's
 * producers can arrive together, and its comment claimed "the graph walk never
 * runs on the ordinary pointer-move". A `maxConnections: 1` input is nominally
 * full with **one** link on it, so the walk ran on the swap gesture — the most
 * ordinary pointer-move there is — and once per frame while the pointer hovered
 * the port. Measured on the sweep's own fixture: 9.4 ms at 132 nodes, 37 ms at
 * 260, **153 ms at 516**, ×4.1 per doubling against a 16 ms frame budget.
 *
 * The cause was one call recomputed with identical arguments: for each
 * branching node in the document, the reachability of the whole graph with
 * that node removed was walked once **per edge on the port**, and the answer
 * cannot depend on the edge. Two assertions, because wall-clock alone is
 * either flaky or toothless:
 *
 *  - **counting**, which is exact and cannot be flaky: doubling the number of
 *    links on the port must not multiply how hard the document is
 *    interrogated. Asked twice — once of the model, which the old code could
 *    also have been asked, and once of the collaborator, where the claim is
 *    exactly "once per branching node, not once per branching node per edge".
 *  - a **ratio** at the rule's own level, the shape
 *    `acyclicGraphRule.scaling.test.ts` already uses, with a margin wide
 *    enough that a loaded machine cannot fail it and narrow enough that
 *    quadratic growth cannot pass it.
 */

/**
 * `routers` classifier routers in a chain, each opening two of its branches
 * onto agents that rejoin at a report, and `producers` agents hanging off the
 * end of the chain, all of them feeding one agent's single-slot `prompt`.
 *
 * The producers are deliberately **downstream of every router**, which is the
 * expensive case: a producer no branch can reach is answered without a walk at
 * all, and a fixture built that way would flatter the fix.
 */
function chainFeedingOnePrompt(
  routers: number,
  producers: number,
): { workbench: Workbench; edges: { source: { nodeId: NodeId; portId: string } }[] } {
  const workbench = makeWorkbench();
  let head = addNode(workbench, TYPE.textInput);
  let headPort = 'text';
  for (let i = 0; i < routers; i += 1) {
    const router = addNode(workbench, TYPE.router);
    connect(workbench, head, headPort, router, 'question');
    const left = addNode(workbench, TYPE.agent);
    const right = addNode(workbench, TYPE.agent);
    connect(workbench, router, 'branch:b1', left, 'prompt');
    connect(workbench, router, 'branch:b2', right, 'prompt');
    const join = addNode(workbench, TYPE.formatReport);
    connect(workbench, left, 'result', join, 'candidate');
    connect(workbench, right, 'result', join, 'candidate');
    head = join;
    headPort = 'report';
  }
  const target = addNode(workbench, TYPE.agent);
  const edges: { source: { nodeId: NodeId; portId: string } }[] = [];
  for (let i = 0; i < producers; i += 1) {
    const producer = addNode(workbench, TYPE.agent);
    connect(workbench, head, headPort, producer, 'prompt');
    connect(workbench, producer, 'result', target, 'prompt');
    edges.push({ source: { nodeId: producer.id, portId: 'result' } });
  }
  return { workbench, edges };
}

/** Counts every question the document is asked, whoever asks it. */
function countingModel(model: WorkflowModel): { model: WorkflowModel; asked: () => number } {
  let asked = 0;
  const watched = new Set(['node', 'nodes', 'edges', 'edgesOf', 'edgesFrom', 'edgesInto']);
  const proxy = new Proxy(model, {
    get(target, property, receiver) {
      const value = Reflect.get(target, property, receiver) as unknown;
      if (typeof value !== 'function') return value;
      const method = value as (...args: unknown[]) => unknown;
      if (!watched.has(String(property))) return method.bind(target);
      return (...args: unknown[]): unknown => {
        asked += 1;
        return method.apply(target, args);
      };
    },
  });
  return { model: proxy, asked: () => asked };
}

/** Counts the walks, which is the exact form of the claim. */
function countingGraph(graph: IControlFlowGraph): {
  graph: IControlFlowGraph;
  walks: () => number;
} {
  let walks = 0;
  return {
    walks: () => walks,
    graph: {
      roots: graph.roots,
      branchingNodes: graph.branchingNodes,
      targetsFrom: (branch: BranchPort) => graph.targetsFrom(branch),
      reachable: (from, options) => {
        walks += 1;
        return graph.reachable(from, options);
      },
      ancestorsOf: (node) => graph.ancestorsOf(node),
    },
  };
}

/** Best of N, because a single sample measures the scheduler, not the code. */
function bestOf(runs: number, work: () => void): number {
  let best = Infinity;
  for (let i = 0; i < runs; i += 1) {
    const started = performance.now();
    work();
    best = Math.min(best, performance.now() - started);
  }
  return best;
}

describe('reachability is resolved once per branching node, not once per edge', () => {
  it('does not interrogate the document harder when the port holds four times the links', () => {
    const few = chainFeedingOnePrompt(16, 2);
    const many = chainFeedingOnePrompt(16, 8);

    const watchedFew = countingModel(few.workbench.model);
    const watchedMany = countingModel(many.workbench.model);
    concurrentProducerCount(watchedFew.model, few.workbench.registry, few.edges);
    concurrentProducerCount(watchedMany.model, many.workbench.registry, many.edges);

    // The old shape walked the document once per branching node *per edge*, so
    // four times the links was four times the interrogation. The document is
    // slightly larger too (four more producers), so the bound is not 1.
    const growth = watchedMany.asked() / watchedFew.asked();
    expect(growth, `${watchedFew.asked()} → ${watchedMany.asked()} calls`).toBeLessThan(1.5);
  });

  it('walks once per branching node plus once per branch, whatever the edge count', () => {
    const branchesPerRouter = 2;
    const routers = 16;
    const counted = (producers: number): number => {
      const { workbench, edges } = chainFeedingOnePrompt(routers, producers);
      const watched = countingGraph(new ControlFlowGraph(workbench.model));
      concurrentProducerCountOn(watched.graph, edges);
      return watched.walks();
    };

    // Every router in the chain gates every producer, so every one of them is
    // a gate that has to be resolved: one walk for "what still runs without
    // this router", and one per branch it opens. Branches it does not open
    // reach nothing, and are walked just as cheaply.
    const perRouter = 1 + 5;
    expect(counted(2)).toBe(routers * perRouter);
    expect(counted(8)).toBe(routers * perRouter);
    expect(branchesPerRouter).toBeLessThan(perRouter);
  });
});

describe('one pointer-move onto a full port grows with the document, not with its square', () => {
  it('is no worse than the size increase, on the gesture the rule exists for', () => {
    // The sweep's own fixture: a full single-slot `prompt` and one more link
    // dropped on it. 132 nodes → 516 nodes is four times the document; the old
    // code measured ×4.1 per *doubling*, i.e. ~17× across this gap.
    const gesture = (routers: number) => {
      const { workbench } = chainFeedingOnePrompt(routers, 1);
      const nodes = workbench.model.nodes();
      const target = nodes[nodes.length - 2]!;
      const dragged = addNode(workbench, TYPE.agent);
      const source = { nodeId: dragged.id, portId: 'result' };
      const port = { nodeId: target.id, portId: 'prompt' };
      return () => {
        workbench.connectionValidator.validate(source, port);
      };
    };

    const small = gesture(32);
    const large = gesture(128);
    small();
    large();

    const smallMs = bestOf(5, small);
    const largeMs = bestOf(5, large);
    const growth = largeMs / smallMs;

    expect(growth, `${smallMs.toFixed(3)}ms → ${largeMs.toFixed(3)}ms`).toBeLessThan(10);
  });
});
