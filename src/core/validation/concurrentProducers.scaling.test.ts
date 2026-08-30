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
 * cannot depend on the edge. Three assertions, and **not one of them is a
 * clock** — `the-cost-of-one-more/19`:
 *
 *  - **counting**, which is exact and cannot be flaky: doubling the number of
 *    links on the port must not multiply how hard the document is
 *    interrogated. Asked twice — once of the model, which the old code could
 *    also have been asked, and once of the collaborator, where the claim is
 *    exactly "once per branching node, not once per branching node per edge".
 *  - a **ratio** across two document sizes, which is the right shape and was
 *    the wrong instrument. It used to read
 *    `expect(largeMs / smallMs).toBeLessThan(10)`, best-of-5 on
 *    `performance.now()`, and it failed for two different sessions under load
 *    — `0.890ms → 9.987ms`, and `10.5` — while passing alone every time. The
 *    ratio survives; the clock does not. It is now a ratio of **counted walks
 *    and counted node visits**, which a busy machine cannot move.
 *
 * Replacing the clock changed what the file claims, which is the part worth
 * reading twice. The old block was titled *"grows with the document, not with
 * its square"* and the counter says that is **false**: the walks are linear in
 * the document and the node visits inside them are not — ×3.98 per doubling,
 * ×15.5 across the 132 → 516 gap the block measures. So the ceiling of 10 was
 * not merely loose, it was asserting the opposite of what the code does, and
 * the flakiness was the measurement brushing against a curve it was written to
 * forbid. Filed as `the-cost-of-one-more/21`; recorded exactly here so the day
 * it is fixed this file goes red and somebody re-records it.
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

/**
 * Counts the walks, which is the exact form of the claim, and the **nodes
 * those walks visit**, which is the size of the bill.
 *
 * Two numbers rather than one because they answer different questions and here
 * they disagree: a walk is cheap to count and says how many times the search
 * was started, while a visit says how much document each start read. `03` moved
 * the first and left the second alone.
 *
 * A visit is counted as the size of the set the walk returns, which is exactly
 * the number of nodes it added to `seen` — `walk` in `controlFlowGraph.ts`
 * enqueues a node the same moment it marks it seen, so the returned set is the
 * queue and its size is the step count. That equality is why this can be
 * measured from outside without instrumenting the private walk.
 */
function countingGraph(graph: IControlFlowGraph): {
  graph: IControlFlowGraph;
  walks: () => number;
  visits: () => number;
} {
  let walks = 0;
  let visits = 0;
  return {
    walks: () => walks,
    visits: () => visits,
    graph: {
      roots: graph.roots,
      branchingNodes: graph.branchingNodes,
      targetsFrom: (branch: BranchPort) => graph.targetsFrom(branch),
      reachable: (from, options) => {
        walks += 1;
        const reached = graph.reachable(from, options);
        visits += reached.size;
        return reached;
      },
      // Deliberately not counted. `ancestorsOf` runs once per *distinct
      // producer* — the filter `03` added — so it is bounded by the links on
      // the port and not by the branching nodes, which is the other claim
      // entirely. Counting it here would put the edge count into a number the
      // test below asserts is independent of it.
      ancestorsOf: (node) => graph.ancestorsOf(node),
    },
  };
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

describe('one pointer-move onto a full port is counted, never timed', () => {
  it('starts a walk per branching node whatever the document size, and reads the whole document in each', () => {
    // The sweep's own fixture: a full single-slot `prompt` and one more link
    // dropped on it. 132 nodes → 516 nodes is four times the document.
    const gesture = (routers: number): { walks: number; visits: number; nodes: number } => {
      const { workbench, edges } = chainFeedingOnePrompt(routers, 1);
      const nodes = workbench.model.nodes();
      const dragged = addNode(workbench, TYPE.agent);
      // Exactly the argument `capacityRule` builds when the pointer crosses a
      // full `prompt`: the links already on it, plus the one being dragged.
      const arriving = [...edges, { source: { nodeId: dragged.id, portId: 'result' } }];
      const watched = countingGraph(new ControlFlowGraph(workbench.model));
      concurrentProducerCountOn(watched.graph, arriving);
      // The dragged node is part of the document the gesture happens in.
      return { walks: watched.walks(), visits: watched.visits(), nodes: nodes.length + 1 };
    };

    const small = gesture(32);
    const large = gesture(128);

    // Exact, because the fixture is deterministic and nothing here is timed.
    expect(small).toEqual({ nodes: 132, walks: 192, visits: 6272 });
    expect(large).toEqual({ nodes: 516, walks: 768, visits: 98816 });

    // What `03` fixed, and what it did not, stated as the ratio the deleted
    // clock was reaching for. Walks track the document — ×4.00 against a ×3.91
    // document. Visits track its square — ×15.76, which is ×3.98 per doubling,
    // and is `the-cost-of-one-more/21`.
    const documentGrowth = large.nodes / small.nodes;
    expect(large.walks / small.walks).toBeLessThan(documentGrowth * 1.1);
    expect(large.visits / small.visits).toBeGreaterThan(documentGrowth * 3);
  });
});
