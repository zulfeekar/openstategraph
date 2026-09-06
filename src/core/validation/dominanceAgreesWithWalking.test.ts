import { describe, expect, it } from 'vitest';
import { TYPE, addNode, connect, makeWorkbench } from '@core/testing/fixtures';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { NodeId } from '@core/model/contracts/node';
import type { WorkflowModel } from '@core/model/WorkflowModel';
import { ControlFlowGraph, type IControlFlowGraph } from './controlFlowGraph';
import { concurrentProducerCountOn } from './concurrentProducers';

/**
 * The two implementations behind one verdict, run against each other.
 *
 * `the-cost-of-one-more/21` replaced a walk of the whole document per branching
 * node with **one dominator pass** read by all of them, and kept `03`'s walks
 * as the answer for the documents the index declines: a control-flow cycle, or
 * a producer the roots cannot reach. Two implementations of one question is a
 * standing invitation to drift, and the argument for why they agree is a
 * paragraph in `concurrentProducers.ts` — an argument, which is exactly the
 * kind of thing this repository has learned to pin.
 *
 * So the fast path is compared with the slow one on random documents, the way
 * `03` compared its rewrite with the code it replaced. The difference is that
 * `03`'s harness was temporary and this is not: the walks are still in the tree
 * and still reachable, so the comparison has something to compare forever.
 *
 * The invariant under test, stated so a failure says which half broke:
 *
 *  - **gating is dominance** — "still reachable from the roots with the owner
 *    deleted" and "not on every path from a root" are one sentence read from
 *    two ends, and dominance is a property of the document rather than of the
 *    branching node asking.
 *  - **the owner cannot be re-entered** — a branch target has no path back to
 *    its owner in an acyclic graph, so "reaches the producer" and "reaches the
 *    producer with the owner deleted" are the same set. This is the half that
 *    needs the acyclicity, and the half the cyclic cases below aim at.
 */

/** The same graph, refusing to answer from the index — i.e. `03`'s code path. */
function walkingOnly(graph: IControlFlowGraph): IControlFlowGraph {
  return {
    roots: graph.roots,
    branchingNodes: graph.branchingNodes,
    targetsFrom: (branch) => graph.targetsFrom(branch),
    reachable: (from, options) => graph.reachable(from, options),
    ancestorsOf: (node) => graph.ancestorsOf(node),
    dominatorsOf: () => null,
  };
}

/** Deterministic, so a failure is reproducible from the seed in its message. */
function randomiser(seed: number): () => number {
  let state = seed >>> 0 || 1;
  return () => {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    state >>>= 0;
    return state / 0x1_0000_0000;
  };
}

/**
 * Node kinds, weighted towards the ones that decide something: a document of
 * agents proves nothing here, because exclusivity only ever comes from a
 * branch.
 */
const KINDS = [
  TYPE.agent,
  TYPE.agent,
  TYPE.router,
  TYPE.router,
  TYPE.grader,
  TYPE.formatReport,
  TYPE.output,
];

/** Read off the node itself rather than listed here, so a catalogue change
 * cannot quietly turn these documents into unconnected dust. */
const portsOf = (node: AbstractNodeModel, direction: 'in' | 'out'): readonly string[] =>
  node.ports.filter((port) => port.direction === direction).map((port) => port.id);

/**
 * A random document grown from one input, and the links arriving on one full
 * port.
 *
 * Grown rather than sprinkled: every node is attached to one already in the
 * document, so the result is a connected graph where branches genuinely gate
 * things downstream of them. A uniformly random edge set produces documents in
 * which nothing is ever proven exclusive, and then the two implementations
 * agree on a number neither of them had to think about.
 *
 * `acyclic` decides whether an extra link may point backwards in the creation
 * order. Both shapes are drawable — `acyclicGraphRule` calls an escapable loop
 * a correct graph — and only one of them is a shape the index will answer,
 * which is the point of generating both.
 */
function randomDocument(
  seed: number,
  acyclic: boolean,
): { model: WorkflowModel; edges: { source: { nodeId: NodeId; portId: string } }[] } {
  const next = randomiser(seed);
  const pick = <T>(from: readonly T[]): T => from[Math.floor(next() * from.length)] as T;

  const workbench = makeWorkbench();
  const input = addNode(workbench, TYPE.textInput);
  const nodes: AbstractNodeModel[] = [input];

  // A hub whose branches open onto separate chains, because that is the only
  // shape in which anything is ever proven exclusive. A document grown by
  // attaching each node to a uniformly random parent produces documents where
  // the answer is the link count whatever either implementation decides, and
  // then the comparison below is between two numbers neither had to think
  // about — measured at 23 documents in a thousand before this was added.
  const hub = addNode(workbench, next() < 0.5 ? TYPE.router : TYPE.grader);
  connect(workbench, input, 'text', hub, portsOf(hub, 'in')[0] ?? 'question');
  nodes.push(hub);
  const chains: AbstractNodeModel[][] = [];
  for (const branch of hub.ports.filter((port) => port.direction === 'out' && port.branch)) {
    const chain: AbstractNodeModel[] = [];
    chains.push(chain);
    let head: AbstractNodeModel = hub;
    let headPort = branch.id;
    const length = 1 + Math.floor(next() * 3);
    for (let step = 0; step < length; step += 1) {
      const child = addNode(workbench, pick(KINDS));
      const into = portsOf(child, 'in');
      if (into.length === 0) break;
      connect(workbench, head, headPort, child, pick(into));
      nodes.push(child);
      chain.push(child);
      const out = portsOf(child, 'out');
      if (out.length === 0) break;
      head = child;
      headPort = pick(out);
    }
  }

  const count = 4 + Math.floor(next() * 10);
  for (let index = 0; index < count; index += 1) {
    const child = addNode(workbench, pick(KINDS));
    const into = portsOf(child, 'in');
    if (into.length === 0) {
      nodes.push(child);
      continue;
    }
    const parent = nodes[Math.floor(next() * nodes.length)] as AbstractNodeModel;
    const out = portsOf(parent, 'out');
    if (out.length > 0) connect(workbench, parent, pick(out), child, pick(into));
    nodes.push(child);
  }

  // Extra links, which is where joins — and, when `acyclic` is false, cycles —
  // come from.
  const extra = 2 + Math.floor(next() * 8);
  for (let index = 0; index < extra; index += 1) {
    const fromIndex = Math.floor(next() * nodes.length);
    const toIndex = acyclic
      ? fromIndex + 1 + Math.floor(next() * Math.max(1, nodes.length - fromIndex - 1))
      : Math.floor(next() * nodes.length);
    const from = nodes[fromIndex];
    const to = nodes[toIndex];
    if (!from || !to || from === to) continue;
    const out = portsOf(from, 'out');
    const into = portsOf(to, 'in');
    if (out.length === 0 || into.length === 0) continue;
    connect(workbench, from, pick(out), to, pick(into));
  }

  // Producers taken one per branch chain where possible, because two
  // producers under the *same* branch are never exclusive and a random pick
  // lands there most of the time.
  const producers = 2 + Math.floor(next() * 4);
  const edges: { source: { nodeId: NodeId; portId: string } }[] = [];
  const populated = chains.filter((chain) => chain.length > 0);
  for (let index = 0; index < producers; index += 1) {
    const chain = populated[index % Math.max(1, populated.length)];
    const from =
      chain && chain.length > 0 && next() < 0.8
        ? chain[Math.floor(next() * chain.length)]
        : nodes[Math.floor(next() * nodes.length)];
    const out = from ? portsOf(from, 'out') : [];
    if (!from || out.length === 0) continue;
    edges.push({ source: { nodeId: from.id, portId: pick(out) } });
  }
  return { model: workbench.model, edges };
}

describe('the dominator index and the walks answer the same question', () => {
  it('agrees on a thousand acyclic documents', () => {
    let answered = 0;
    let proven = 0;
    for (let seed = 1; seed <= 1000; seed += 1) {
      const { model, edges } = randomDocument(seed, true);
      if (edges.length < 2) continue;
      const graph = new ControlFlowGraph(model);
      const fast = concurrentProducerCountOn(graph, edges);
      const slow = concurrentProducerCountOn(walkingOnly(new ControlFlowGraph(model)), edges);
      expect(fast, `seed ${seed}`).toBe(slow);
      if (fast < edges.length) proven += 1;
      if (edges.some((edge) => graph.dominatorsOf(edge.source.nodeId) !== null)) answered += 1;
    }
    // Otherwise the loop above proves only that two `null`s are equal — and,
    // worse, that they agree on documents where nothing is exclusive and the
    // answer is the link count whatever either of them decides.
    expect(answered).toBeGreaterThan(800);
    expect(proven, 'documents where some pair was proven exclusive').toBeGreaterThan(40);
  });

  it('agrees on documents with a control-flow cycle, where the index declines', () => {
    let declined = 0;
    for (let seed = 1; seed <= 1000; seed += 1) {
      const { model, edges } = randomDocument(seed, false);
      if (edges.length < 2) continue;
      const graph = new ControlFlowGraph(model);
      const fast = concurrentProducerCountOn(graph, edges);
      const slow = concurrentProducerCountOn(walkingOnly(new ControlFlowGraph(model)), edges);
      expect(fast, `seed ${seed}`).toBe(slow);
      if (edges.some((edge) => graph.dominatorsOf(edge.source.nodeId) === null)) declined += 1;
    }
    // The fallback is not dead code: these documents are the reason it stays.
    expect(declined).toBeGreaterThan(25);
  });
});
