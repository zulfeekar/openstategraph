import { beforeEach, describe, expect, it } from 'vitest';
import type { Workbench } from '@app/Workbench';
import { compareNatural } from '@core/kernel/ordering';
import { addNode, connect, makeWorkbench, TYPE } from '@core/testing/fixtures';

/**
 * Serialization.
 *
 * `workflow.json` is about to become the git-tracked source of truth, read by
 * humans in diffs and by coding agents. That promotes two properties from
 * "nice" to load-bearing:
 *
 *  - **Round-trip fidelity** — loading what we saved must reproduce the graph.
 *  - **Determinism** — the same logical graph must produce byte-identical
 *    output, or every save is a whole-file diff and review is impossible.
 *
 * The determinism tests below start RED. They document a confirmed defect:
 * `toJSON()` serialises `nodes()`, which returns Map *insertion* order.
 */
describe('WorkflowSerializer', () => {
  let workbench: Workbench;

  const seed = () => {
    const input = addNode(workbench, TYPE.textInput, {
      at: { x: 40, y: 200 },
      data: { prompt: 'trending topics' },
    });
    const agent = addNode(workbench, TYPE.agent, { at: { x: 400, y: 200 } });
    const output = addNode(workbench, TYPE.output, { at: { x: 800, y: 200 } });
    connect(workbench, input, 'text', agent, 'prompt');
    connect(workbench, agent, 'result', output, 'result');
    return { input, agent, output };
  };

  beforeEach(() => {
    workbench = makeWorkbench();
  });

  describe('round trip', () => {
    it('reproduces nodes, edges and name', () => {
      seed();
      workbench.model.setName('Trend report');
      const json = workbench.controller.document.exportJSON();

      const reloaded = makeWorkbench();
      const outcome = reloaded.controller.document.importJSON(json);

      expect(outcome.ok).toBe(true);
      expect(reloaded.model.name).toBe('Trend report');
      expect(reloaded.model.nodeCount).toBe(3);
      expect(reloaded.model.edgeCount).toBe(2);
    });

    it('preserves node ids, so links still resolve', () => {
      const { agent } = seed();
      const json = workbench.controller.document.exportJSON();

      const reloaded = makeWorkbench();
      reloaded.controller.document.importJSON(json);

      expect(reloaded.model.hasNode(agent.id)).toBe(true);
      expect(reloaded.model.edgesOf(agent.id)).toHaveLength(2);
    });

    it('preserves field data and geometry', () => {
      const { input } = seed();
      const json = workbench.controller.document.exportJSON();

      const reloaded = makeWorkbench();
      reloaded.controller.document.importJSON(json);

      const restored = reloaded.model.node(input.id);
      expect(restored?.data['prompt']).toBe('trending topics');
      expect(restored?.position).toEqual({ x: 40, y: 200 });
    });

    it('preserves containment', () => {
      const group = addNode(workbench, TYPE.group);
      const agent = addNode(workbench, TYPE.agent);
      workbench.model.setNodeParent(agent.id, group.id);

      const reloaded = makeWorkbench();
      reloaded.controller.document.importJSON(workbench.controller.document.exportJSON());

      expect(reloaded.model.node(agent.id)?.parentId).toBe(group.id);
    });

    it('is idempotent — exporting a reloaded document reproduces the bytes', () => {
      seed();
      const first = workbench.controller.document.exportJSON();

      const reloaded = makeWorkbench();
      reloaded.controller.document.importJSON(first);
      const second = reloaded.controller.document.exportJSON();

      expect(second).toBe(first);
    });
  });

  describe('determinism', () => {
    it('produces identical bytes for two independently built identical graphs', () => {
      seed();
      const first = workbench.controller.document.exportJSON();

      workbench = makeWorkbench();
      seed();
      const second = workbench.controller.document.exportJSON();

      // Two users making the same edits must produce the same file, or
      // merges conflict for no reason.
      expect(second).toBe(first);
    });

    it('is unchanged by delete-then-undo', () => {
      const { agent } = seed();
      const before = workbench.controller.document.exportJSON();

      workbench.controller.nodes.delete([agent.id]);
      workbench.controller.history.undo();

      // The graph is logically identical. Insertion order is not: the undone
      // node is re-added at the end of the Map.
      expect(workbench.controller.document.exportJSON()).toBe(before);
    });

    it('is unchanged by the order nodes were created in', () => {
      // Build the same graph back-to-front.
      const output = addNode(workbench, TYPE.output, { at: { x: 800, y: 200 } });
      const agent = addNode(workbench, TYPE.agent, { at: { x: 400, y: 200 } });
      const input = addNode(workbench, TYPE.textInput, {
        at: { x: 40, y: 200 },
        data: { prompt: 'trending topics' },
      });
      connect(workbench, agent, 'result', output, 'result');
      connect(workbench, input, 'text', agent, 'prompt');
      const reversed = workbench.controller.document.exportJSON();

      workbench = makeWorkbench();
      seed();
      const forward = workbench.controller.document.exportJSON();

      expect(reversed).toBe(forward);
    });
  });

  describe('canonical order', () => {
    it('orders node rows by number, so -2 precedes -10', () => {
      for (let i = 0; i < 11; i += 1) addNode(workbench, TYPE.textInput);

      const document = JSON.parse(workbench.controller.document.exportJSON()) as {
        nodes: { id: string }[];
      };
      const ids = document.nodes.map((node) => node.id);

      // A lexical sort would put -10 and -11 immediately after -1, which is
      // deterministic but unreadable in a diff.
      expect(ids.indexOf('node:input.text-2')).toBeLessThan(ids.indexOf('node:input.text-10'));
      expect(ids).toEqual([...ids].sort(compareNatural));
    });

    it('ends with a newline, as a text file on disk should', () => {
      seed();
      // Without it git reports "\ No newline at end of file" on every diff,
      // and appending anything rewrites the last line.
      expect(workbench.controller.document.exportJSON().endsWith('}\n')).toBe(true);
    });

    it('does not write edge ids, which are creation-order handles', () => {
      seed();
      const document = JSON.parse(workbench.controller.document.exportJSON()) as {
        edges: Record<string, unknown>[];
      };

      // An edge is identified by its endpoints; nothing references it by id.
      for (const edge of document.edges) expect(edge).not.toHaveProperty('id');
    });

    it('keeps field keys in a stable order however they were edited', () => {
      const a = addNode(workbench, TYPE.redditSearch);
      workbench.controller.nodes.setField(a.id, 'topicLimit', 7);
      workbench.controller.nodes.setField(a.id, 'subreddit', 'typescript');
      const first = workbench.controller.document.exportJSON();

      workbench = makeWorkbench();
      const b = addNode(workbench, TYPE.redditSearch);
      workbench.controller.nodes.setField(b.id, 'subreddit', 'typescript');
      workbench.controller.nodes.setField(b.id, 'topicLimit', 7);

      expect(workbench.controller.document.exportJSON()).toBe(first);
    });
  });

  describe('lenient loading', () => {
    it('rejects invalid JSON with a readable message', () => {
      const outcome = workbench.controller.document.importJSON('{ not json');
      expect(outcome.ok).toBe(false);
      expect(outcome.message).toMatch(/json/i);
    });

    it('rejects a document missing nodes or edges', () => {
      const outcome = workbench.controller.document.importJSON(JSON.stringify({ version: 1, name: 'x' }));
      expect(outcome.ok).toBe(false);
    });

    it('refuses a document from a newer schema version', () => {
      const outcome = workbench.controller.document.importJSON(
        JSON.stringify({ version: 99, name: 'x', nodes: [], edges: [] }),
      );
      expect(outcome.ok).toBe(false);
      expect(outcome.message).toMatch(/newer version/i);
    });

    it('skips an unknown node type with a warning rather than failing the load', () => {
      seed();
      const document = JSON.parse(workbench.controller.document.exportJSON()) as {
        nodes: { type: string }[];
      };
      document.nodes.push({ type: 'does.not.exist' } as never);

      const reloaded = makeWorkbench();
      const outcome = reloaded.controller.document.importJSON(JSON.stringify(document));

      // Throwing away a user's whole file over one unknown node would be
      // far worse than dropping the node and saying so.
      expect(outcome.ok).toBe(true);
      expect(outcome.message).toMatch(/unknown node type/i);
      expect(reloaded.model.nodeCount).toBe(3);
    });

    it('drops a link whose endpoint is missing', () => {
      seed();
      const document = JSON.parse(workbench.controller.document.exportJSON()) as {
        edges: { id: string; source: { nodeId: string; portId: string }; target: unknown }[];
      };
      document.edges.push({
        id: 'edge:ghost',
        source: { nodeId: 'node:gone', portId: 'text' },
        target: document.edges[0]?.target,
      });

      const reloaded = makeWorkbench();
      const outcome = reloaded.controller.document.importJSON(JSON.stringify(document));

      expect(outcome.ok).toBe(true);
      expect(outcome.message).toMatch(/missing endpoint/i);
      expect(reloaded.model.edgeCount).toBe(2);
    });

    it('drops a link to a port that no longer exists', () => {
      seed();
      const document = JSON.parse(workbench.controller.document.exportJSON()) as {
        edges: { source: { portId: string } }[];
      };
      const firstEdge = document.edges[0];
      if (firstEdge) firstEdge.source.portId = 'removed-port';

      const reloaded = makeWorkbench();
      const outcome = reloaded.controller.document.importJSON(JSON.stringify(document));

      // Ports change between versions; a link to a vanished port would
      // render as a stub attached to nothing.
      expect(outcome.ok).toBe(true);
      expect(outcome.message).toMatch(/no longer exists/i);
      expect(reloaded.model.edgeCount).toBe(1);
    });
  });

  describe('id minting after import', () => {
    it('does not collide a newly added node with an imported one', () => {
      seed();
      const json = workbench.controller.document.exportJSON();

      const reloaded = makeWorkbench();
      reloaded.controller.document.importJSON(json);
      const before = reloaded.model.nodeCount;

      reloaded.controller.nodes.add(TYPE.textInput, { x: 0, y: 0 });

      // Counters are re-seeded from the imported ids; without that, the new
      // node would reuse an existing id and the add would throw.
      expect(reloaded.model.nodeCount).toBe(before + 1);
    });
  });
});
