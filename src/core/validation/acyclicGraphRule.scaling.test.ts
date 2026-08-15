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
 * Two assertions, because wall-clock alone is either flaky or toothless:
 *
 *  - a **counting** one, which is exact and cannot be flaky: one SCC pass
 *    visits each candidate's out-edges once, so `successors` is called once
 *    per candidate. V calls, not V².
 *  - a **ratio** one at the rule's own level, with a margin wide enough that
 *    a loaded machine cannot fail it and narrow enough that quadratic
 *    growth cannot pass it.
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
  it('grows no worse than the doubling itself, four times over', () => {
    const small = graphWithCycleAtTheHead(200);
    const large = graphWithCycleAtTheHead(1600);
    const run = (workbench: Workbench) => () => {
      acyclicGraphRule.check({ model: workbench.model, registry: workbench.registry });
    };

    // Warm both paths so neither measurement pays for a cold JIT.
    run(small)();
    run(large)();

    const smallMs = bestOf(5, run(small));
    const largeMs = bestOf(5, run(large));
    const growth = largeMs / smallMs;

    // 8× the work. Linear predicts ~8; the old V·(V+E) filter predicts ~64,
    // and measured ×3.6–4.4 per *doubling* — i.e. ~50× across this gap. The
    // bound is deliberately loose: it exists to catch a return to quadratic,
    // not to police a constant factor on someone's laptop.
    expect(growth, `${smallMs.toFixed(3)}ms → ${largeMs.toFixed(3)}ms`).toBeLessThan(24);
  });
});
