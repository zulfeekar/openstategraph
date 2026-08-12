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
/**
 * A node of a type no build registers — modelled on the real one, the
 * `tool.validate-workflow` node `workflow-architect` was losing.
 */
const unknownNodeEntry = (): Record<string, unknown> => ({
  id: 't-validate',
  type: 'tool.validate-workflow',
  position: { x: 400, y: 600 },
  size: { width: 240, height: 96 },
  parentId: null,
  data: { note: 'kept' },
});

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

    it('round-trips a router edge to an underscore-named branch', () => {
      // Found live: a real saved document (the intent-routed demo)
      // classifies into "off_topic"/"general_knowledge" and had edges from
      // those exact branch ports. `RouterNode`'s port-id slug used to
      // collapse "_" into "-", so importing that same document back always
      // produced a *different* port id than the one the edge pointed at —
      // `fromJSON` then dropped the edge as pointing to "a port that no
      // longer exists". This is the regression at the serializer's own
      // load-then-check-warnings level, not just the port-id unit.
      const router = addNode(workbench, TYPE.router, { data: { branches: 'off_topic\ngreeting' } });
      const agent = addNode(workbench, TYPE.agent, { at: { x: 200, y: 0 } });
      connect(workbench, router, 'branch:off_topic', agent, 'prompt');

      const json = workbench.controller.document.exportJSON();
      const reloaded = makeWorkbench();
      const outcome = reloaded.controller.document.importJSON(json);

      expect(outcome.ok).toBe(true);
      // A message only appears when `fromJSON` dropped something — absent
      // here means the edge survived, not just that loading didn't throw.
      expect(outcome).not.toHaveProperty('message');
      expect(reloaded.model.edgesOf(router.id)).toHaveLength(1);
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

  describe('waypoints', () => {
    it('round-trips the points a user placed on a link', () => {
      const { input, agent } = seed();
      const edge = workbench.model.edgesFrom({ nodeId: input.id, portId: 'text' })[0]!;
      workbench.controller.edges.setVertices(edge.id, [
        { x: 220, y: 40 },
        { x: 220, y: 300 },
      ]);

      const reloaded = makeWorkbench();
      reloaded.controller.document.importJSON(workbench.controller.document.exportJSON());

      const restored = reloaded.model
        .edgesOf(agent.id)
        .find((candidate) => candidate.source.nodeId === input.id);
      expect(restored?.vertices).toEqual([
        { x: 220, y: 40 },
        { x: 220, y: 300 },
      ]);
    });

    it('writes nothing for a link with no points, so old documents keep their bytes', () => {
      seed();
      const document = JSON.parse(workbench.controller.document.exportJSON()) as {
        edges: Record<string, unknown>[];
      };
      for (const edge of document.edges) expect('vertices' in edge).toBe(false);
    });

    it('loads a document written before waypoints existed', () => {
      // `vertices` is additive, which is exactly why the schema version does
      // not move: an older file simply has none, and the router draws the whole
      // run as it always did.
      seed();
      const document = JSON.parse(workbench.controller.document.exportJSON()) as {
        edges: Record<string, unknown>[];
      };
      const reloaded = makeWorkbench();
      const outcome = reloaded.controller.document.importJSON(JSON.stringify(document));
      expect(outcome.ok).toBe(true);
      expect(reloaded.model.edges().every((edge) => edge.vertices.length === 0)).toBe(true);
    });

    it('drops a hand-edited point that is not a finite pair of numbers', () => {
      // `Infinity` and `NaN` cannot be written to JSON, so one of them in a
      // link would make the whole document unwritable. The rule is enforced at
      // the one door they can come through.
      const { input, agent } = seed();
      const document = JSON.parse(workbench.controller.document.exportJSON()) as {
        edges: { source: { nodeId: string }; vertices?: unknown[] }[];
      };
      const edge = document.edges.find((candidate) => candidate.source.nodeId === input.id)!;
      edge.vertices = [
        { x: 10, y: 20 },
        { x: 'nope', y: 5 },
        { x: 30, y: 40 },
      ];

      const reloaded = makeWorkbench();
      reloaded.controller.document.importJSON(JSON.stringify(document));

      const restored = reloaded.model
        .edgesOf(agent.id)
        .find((candidate) => candidate.source.nodeId === input.id);
      expect(restored?.vertices).toEqual([
        { x: 10, y: 20 },
        { x: 30, y: 40 },
      ]);
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
      const outcome = workbench.controller.document.importJSON(
        JSON.stringify({ version: 1, name: 'x' }),
      );
      expect(outcome.ok).toBe(false);
    });

    it('refuses a document from a newer schema version', () => {
      const outcome = workbench.controller.document.importJSON(
        JSON.stringify({ version: 99, name: 'x', nodes: [], edges: [] }),
      );
      expect(outcome.ok).toBe(false);
      expect(outcome.message).toMatch(/newer version/i);
    });

    it('keeps a node of an unknown type, with a warning, rather than dropping it', () => {
      seed();
      const document = JSON.parse(workbench.controller.document.exportJSON()) as {
        nodes: Record<string, unknown>[];
      };
      document.nodes.push(unknownNodeEntry());

      const reloaded = makeWorkbench();
      const outcome = reloaded.controller.document.importJSON(JSON.stringify(document));

      // Skipping it was silent data loss with a one-click trigger: open, edit
      // anything, save, and the node is written out of the file.
      expect(outcome.ok).toBe(true);
      expect(outcome.message).toMatch(/unknown node type/i);
      expect(reloaded.model.nodeCount).toBe(4);
      expect(reloaded.model.node('t-validate')?.type).toBe('tool.validate-workflow');
    });

    it('keeps the links that touch an unknown node', () => {
      // Preserving the node and losing its edges is half a fix, and the
      // harder half to notice — the serializer drops any link whose endpoint
      // port does not exist, so the placeholder has to declare the ports the
      // document's own edges name.
      const { agent } = seed();
      const document = JSON.parse(workbench.controller.document.exportJSON()) as {
        nodes: Record<string, unknown>[];
        edges: Record<string, unknown>[];
      };
      document.nodes.push(unknownNodeEntry());
      document.edges.push({
        source: { nodeId: 't-validate', portId: 'tool' },
        target: { nodeId: agent.id, portId: 'tools' },
      });

      const reloaded = makeWorkbench();
      reloaded.controller.document.importJSON(JSON.stringify(document));

      expect(reloaded.model.edgeCount).toBe(3);
      expect(reloaded.model.edgesOf('t-validate')).toHaveLength(1);
    });

    it('round-trips a document with an unknown node byte-identically', () => {
      // The invariant, stated as a test: load then save loses nothing. This is
      // the property `workflow-architect` failed — it serves 7 nodes and 7
      // edges, and the editor wrote back 6 and 6.
      const { agent } = seed();
      const document = JSON.parse(workbench.controller.document.exportJSON()) as {
        nodes: Record<string, unknown>[];
        edges: Record<string, unknown>[];
      };
      document.nodes.push(unknownNodeEntry());
      document.edges.push({
        source: { nodeId: 't-validate', portId: 'tool' },
        target: { nodeId: agent.id, portId: 'tools' },
      });

      // Canonicalise once through a build that *does* nothing special, so the
      // comparison is about preservation and not about key order.
      const canonical = (() => {
        const first = makeWorkbench();
        first.controller.document.importJSON(JSON.stringify(document));
        return first.controller.document.exportJSON();
      })();

      const reloaded = makeWorkbench();
      reloaded.controller.document.importJSON(canonical);

      expect(reloaded.controller.document.exportJSON()).toBe(canonical);
    });

    it('does not inject execution-override defaults into an unknown node', () => {
      // `defineNode` appends `maxRetries`/`timeoutSeconds` to every standard
      // node type, and `AbstractNodeModel` seeds schema defaults into `data`.
      // Building the placeholder definition through it would add two keys the
      // document never had, and the first save would be a diff nobody asked
      // for — a quieter version of the same loss.
      seed();
      const document = JSON.parse(workbench.controller.document.exportJSON()) as {
        nodes: Record<string, unknown>[];
      };
      document.nodes.push(unknownNodeEntry());

      const reloaded = makeWorkbench();
      reloaded.controller.document.importJSON(JSON.stringify(document));

      expect(reloaded.model.node('t-validate')?.data).toEqual({ note: 'kept' });
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
