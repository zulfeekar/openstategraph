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
 * its square"* and the counter said that was **false**: the walks were linear
 * in the document and the node visits inside them were not — ×3.98 per
 * doubling, ×15.76 across the 132 → 516 gap the block measures. So the ceiling
 * of 10 was not merely loose, it was asserting the opposite of what the code
 * did, and the flakiness was the measurement brushing against a curve it was
 * written to forbid.
 *
 * `19` therefore left two assertions pointing in **opposite directions on
 * purpose** — walks within 1.1× of the document growth, visits *above* three
 * times it — so that the day somebody fixed the quadratic this file would go
 * red and have to be re-recorded with an argument. That day is
 * `the-cost-of-one-more/21`, and this is the re-recording:
 *
 * ```
 *   nodes    walks    visits        walks    visits     (21)
 *     132      192     6,272            4       196
 *     516      768    98,816            4       772
 *              x4.0    x15.76         x1.0     x3.94
 * ```
 *
 * The visits ratio is now **below** the document's own ×3.91 growth plus a
 * tenth, which is the same bound the walks have always been held to, and the
 * block title is true of the code under it for the first time. Nothing was
 * deleted to get there: the ratio assertion that used to read
 * `toBeGreaterThan(documentGrowth * 3)` reads `toBeLessThan(documentGrowth *
 * 1.1)`, in the same place, about the same number.
 *
 * What bought it is one dominator pass over the successor index, shared by
 * every branching node — `dominators.ts`, and the invariant it rests on is
 * written at `constraintsByDominance`. The walks did not go away; they are the
 * exact answer for a document with a control-flow cycle, and
 * `dominanceAgreesWithWalking.test.ts` runs the two against each other.
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
  const counted = <T extends ReadonlySet<NodeId> | null>(answer: T): T => {
    walks += 1;
    visits += answer?.size ?? 0;
    return answer;
  };
  return {
    walks: () => walks,
    visits: () => visits,
    graph: {
      roots: graph.roots,
      branchingNodes: graph.branchingNodes,
      targetsFrom: (branch: BranchPort) => graph.targetsFrom(branch),
      reachable: (from, options) => counted(graph.reachable(from, options)),
      ancestorsOf: (node) => counted(graph.ancestorsOf(node)),
      dominatorsOf: (node) => counted(graph.dominatorsOf(node)),
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

  it('walks once per link on the port, and never once per branching node', () => {
    const counted = (routers: number, producers: number): number => {
      const { workbench, edges } = chainFeedingOnePrompt(routers, producers);
      const watched = countingGraph(new ControlFlowGraph(workbench.model));
      concurrentProducerCountOn(watched.graph, edges);
      return watched.walks();
    };

    // Two questions per **distinct producer** and nothing else: where it can
    // be reached from, and what lies on every path to it. Both are properties
    // of the producer; the branching nodes read the answers.
    //
    // `03` bought the second half of this — a walk per branching node rather
    // than per branching node per edge — and `21` bought the first: the
    // routers are no longer in the number at all, which is why the same count
    // survives quadrupling them.
    expect(counted(16, 2)).toBe(2 * 2);
    expect(counted(64, 2)).toBe(2 * 2);
    expect(counted(16, 8)).toBe(8 * 2);
    expect(counted(64, 8)).toBe(8 * 2);
  });
});

describe('one pointer-move onto a full port is counted, never timed', () => {
  it('reads the document once per link on the port, whatever the document size', () => {
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
    expect(small).toEqual({ nodes: 132, walks: 4, visits: 196 });
    expect(large).toEqual({ nodes: 516, walks: 4, visits: 772 });

    // The block's own title, finally true of the code under it. Walks no
    // longer track the document at all — four, at both sizes, two per link on
    // the port — and the visits inside them track the document rather than its
    // square.
    //
    // **This is the assertion `19` pointed the other way on purpose**, and it
    // is turned around rather than deleted: it used to read
    // `toBeGreaterThan(documentGrowth * 3)`, recording ×15.76 as the measured
    // truth so that the day somebody fixed it this file would go red. That day
    // is `the-cost-of-one-more/21`, and the number it re-records is below.
    const documentGrowth = large.nodes / small.nodes;
    expect(large.walks / small.walks).toBeLessThanOrEqual(documentGrowth);
    expect(large.visits / small.visits).toBeLessThan(documentGrowth * 1.1);
  });
});
