import { describe, expect, it } from 'vitest';
import {
  addNode,
  connect,
  LOOPABLE_TYPE,
  makeWorkbench,
  registerLoopableType,
} from '@core/testing/fixtures';

/** Named from the fixture, so this file adds no import of its own. */
type Workbench = ReturnType<typeof makeWorkbench>;
import { cyclicMembers } from '@core/model/topology';
import type { NodeId } from '@core/model/contracts/node';
import { acyclicGraphRule } from './WorkflowValidator';

/**
 * The shape of the cost, not the size of it.
 *
 * `acyclicGraphRule` used to run a full DFS *once per member* of Kahn's
 * leftover set — and that set includes everything merely downstream of a
 * cycle, deliberately (see the rule's own comment). So the filter was
 * O(V·(V+E)) exactly when a loop exists, and a loop is the feature. Measured
 * by the audit of 2026-08-15 on this file's graph shape: 0.55 ms at 50 nodes,
 * **48 ms at 800**, ×3.6 → ×4.4 per doubling, against a ×1.7 → ×1.8 control
 * with no cycle. It is on the hot path — the rules run continuously to drive
 * the per-node status dots, and `Inspector.tsx` re-memoises diagnostics on any
 * model change — so a 400-node document with a revision loop near its entry
 * paid ~12 ms inside every React render caused by a node drag.
 *
 * Two assertions, and **neither is a clock** — `the-cost-of-one-more/19`:
 *
 *  - a **counting** one, which is exact and cannot be flaky: one SCC pass
 *    visits each candidate's out-edges once, so `successors` is called once
 *    per candidate. V calls, not V².
 *  - a **ratio** one at the rule's own level, over two real documents — which
 *    is the right shape and used to be the wrong instrument. It read
 *    `expect(largeMs / smallMs).toBeLessThan(24)` on `performance.now()`,
 *    best-of-5, and it is the sibling of the assertion that failed twice in
 *    one night under load in `concurrentProducers.scaling.test.ts`. The ratio
 *    survives; it is now a ratio of counted document reads. Unlike that
 *    sibling, the count agrees with the claim the block always made: this rule
 *    really is linear.
 */

/**
 * The audit's worst case: a 3-node cycle at the head of a chain, so Kahn's
 * leftover set is the entire graph.
 */
function graphWithCycleAtTheHead(size: number): Workbench {
  const workbench = makeWorkbench();
  registerLoopableType(workbench);
  const nodes = Array.from({ length: size }, (_, i) =>
    addNode(workbench, LOOPABLE_TYPE, { at: { x: i * 10, y: 0 } }),
  );
  // a → b → c → a, then c → d → e → … to the end.
  for (let i = 0; i + 1 < size; i += 1) {
    const from = nodes[i];
    const to = nodes[i + 1];
    if (from && to) connect(workbench, from, 'out', to, 'in');
  }
  const head = nodes[0];
  const third = nodes[2];
  if (head && third) connect(workbench, third, 'out', head, 'in');
  return workbench;
}

/**
 * Every question the rule asks the document, whoever asks it.
 *
 * The exact form of "one SCC pass, not one DFS per leftover member": the pass
 * reads each candidate's out-edges once, so `edgesOf` is called once per node.
 * The old filter walked the whole blocked subgraph from every one of its
 * members and would read V² of them.
 */
function countingModel(model: Workbench['model']): {
  model: Workbench['model'];
  tally: () => Record<string, number>;
} {
  const tally: Record<string, number> = {};
  const proxy = new Proxy(model, {
    get(target, property, receiver) {
      const value = Reflect.get(target, property, receiver) as unknown;
      if (typeof value !== 'function') return value;
      const method = value as (...args: unknown[]) => unknown;
      const name = String(property);
      return (...args: unknown[]): unknown => {
        tally[name] = (tally[name] ?? 0) + 1;
        return method.apply(target, args);
      };
    },
  });
  return { model: proxy, tally: () => tally };
}

describe('cycle membership is computed once, not once per candidate', () => {
  it('asks each candidate for its successors exactly once', () => {
    // The exact, unflakeable form of the assertion below. The old filter
    // walked the whole blocked subgraph from every one of its members; a
    // single SCC pass touches each candidate's out-edges once.
    const size = 200;
    const candidates = new Set<NodeId>(Array.from({ length: size }, (_, i) => `n${i}`));
    const asked = new Map<NodeId, number>();
    const successors = (id: NodeId): NodeId[] => {
      asked.set(id, (asked.get(id) ?? 0) + 1);
      const index = Number(id.slice(1));
      // Same shape as the graph above: a 3-cycle feeding a chain.
      if (index === 2) return [`n${0}`, `n${3}`];
      return index + 1 < size ? [`n${index + 1}`] : [];
    };

    const cyclic = cyclicMembers(candidates, successors);

    expect([...cyclic].sort()).toEqual(['n0', 'n1', 'n2']);
    expect(asked.size).toBe(size);
    expect(Math.max(...asked.values())).toBe(1);
  });

  it('finds a self-loop, which is a cycle of one', () => {
    const cyclic = cyclicMembers(new Set(['a', 'b']), (id) => (id === 'a' ? ['a', 'b'] : []));
    expect([...cyclic]).toEqual(['a']);
  });

  it('excludes a node that only *leads into* a cycle, and one that only leaves it', () => {
    // The over-inclusion the rule's comment records: Kahn's leftover set
    // holds these, and they are not cycle members.
    const cyclic = cyclicMembers(
      new Set(['up', 'a', 'b', 'down']),
      (id) =>
        ({ up: ['a'], a: ['b'], b: ['a', 'down'], down: [] })[id as 'up' | 'a' | 'b' | 'down'],
    );
    expect([...cyclic].sort()).toEqual(['a', 'b']);
  });
});

describe('the findings are unchanged by the faster membership test', () => {
  it('names the cycle members only, in the order the leftover set holds them', () => {
    // The behaviour the old per-member DFS existed to get right, and which
    // the SCC pass has to reproduce exactly: `d` and everything after it is
    // in Kahn's leftover set (blocked by a dependency that never finished)
    // and is *not* in the loop. The notice names three nodes, anchors to the
    // first, and is `info` because `c → d` is a way out.
    const workbench = graphWithCycleAtTheHead(6);
    const [notice, ...rest] = acyclicGraphRule.check({
      model: workbench.model,
      registry: workbench.registry,
    });
    expect(rest).toEqual([]);
    expect(notice?.severity).toBe('info');
    expect(notice?.code).toBe('escapable-loop');
    expect(notice?.message).toContain('3 nodes');
    expect(notice?.nodeId).toBe(workbench.model.nodes()[0]?.id);
  });
});

describe('acyclicGraphRule scales linearly with a cycle present', () => {
  it('reads the document once per node at both sizes, counted rather than timed', () => {
    const counted = (size: number): Record<string, number> => {
      const workbench = graphWithCycleAtTheHead(size);
      const watched = countingModel(workbench.model);
      acyclicGraphRule.check({ model: watched.model, registry: workbench.registry });
      return watched.tally();
    };

    // Exact. `topologicalOrder` is Kahn's one pass; `edgesOf` is the SCC
    // pass reading each candidate's out-edges, once each, plus the three the
    // notice needs to name and anchor itself.
    expect(counted(200)).toEqual({ topologicalOrder: 1, edgesOf: 203, node: 3 });
    expect(counted(1600)).toEqual({ topologicalOrder: 1, edgesOf: 1603, node: 3 });

    // 8× the document. Linear predicts ~8 and measures 7.9; the old
    // V·(V+E) filter predicts ~64 reads per node rather than one, i.e. tens of
    // thousands of `edgesOf` calls at 200 alone.
    const growth = counted(1600).edgesOf! / counted(200).edgesOf!;
    expect(growth).toBeLessThan(8.1);
  });
});
