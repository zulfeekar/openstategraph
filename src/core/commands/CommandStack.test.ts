import { beforeEach, describe, expect, it } from 'vitest';
import type { Workbench } from '@app/Workbench';
import { addNode, connect, makeWorkbench, TYPE } from '@core/testing/fixtures';

/**
 * The command stack.
 *
 * Undo is the one mechanism every feature in the editor depends on, and it is
 * generic — no feature implements its own. So a regression here is not "undo
 * is slightly off", it is every editing gesture becoming unreliable at once.
 *
 * The tests go through `WorkflowController` rather than constructing commands
 * directly, because the controller is what the UI calls; testing the commands
 * in isolation would verify a path nothing uses.
 */
describe('CommandStack via WorkflowController', () => {
  let workbench: Workbench;

  beforeEach(() => {
    workbench = makeWorkbench();
  });

  describe('undo and redo', () => {
    it('starts empty', () => {
      expect(workbench.controller.canUndo).toBe(false);
      expect(workbench.controller.canRedo).toBe(false);
    });

    it('undoes an add, and redo restores it', () => {
      workbench.controller.addNode(TYPE.textInput, { x: 0, y: 0 });
      expect(workbench.model.nodeCount).toBe(1);

      workbench.controller.undo();
      expect(workbench.model.nodeCount).toBe(0);

      workbench.controller.redo();
      expect(workbench.model.nodeCount).toBe(1);
    });

    it('keeps the node id stable across undo and redo', () => {
      workbench.controller.addNode(TYPE.textInput, { x: 0, y: 0 });
      const originalId = workbench.model.nodes()[0]?.id;

      workbench.controller.undo();
      workbench.controller.redo();

      // Re-minting the id on redo would orphan every edge pointing at it,
      // which is why the command caches the instance rather than recreating.
      expect(workbench.model.nodes()[0]?.id).toBe(originalId);
    });

    it('reports nothing to undo once the stack is exhausted', () => {
      workbench.controller.addNode(TYPE.textInput, { x: 0, y: 0 });
      workbench.controller.undo();
      expect(workbench.controller.canUndo).toBe(false);
      // A second undo must be a no-op, not an error or a double-apply.
      workbench.controller.undo();
      expect(workbench.model.nodeCount).toBe(0);
    });

    it('discards the redo branch when a new edit follows an undo', () => {
      workbench.controller.addNode(TYPE.textInput, { x: 0, y: 0 });
      workbench.controller.undo();
      expect(workbench.controller.canRedo).toBe(true);

      workbench.controller.addNode(TYPE.output, { x: 100, y: 0 });

      expect(workbench.controller.canRedo).toBe(false);
    });
  });

  describe('deleting restores edges', () => {
    it('brings back the edges that a deleted node owned', () => {
      const input = addNode(workbench, TYPE.textInput);
      const agent = addNode(workbench, TYPE.agent);
      connect(workbench, input, 'text', agent, 'prompt');
      expect(workbench.model.edgeCount).toBe(1);

      workbench.controller.deleteNodes([agent.id]);
      expect(workbench.model.nodeCount).toBe(1);
      expect(workbench.model.edgeCount).toBe(0);

      workbench.controller.undo();

      // The edge is the interesting part: removing a node cascades to its
      // links, so undo has to restore both, in an order where the endpoints
      // exist before the link attaches.
      expect(workbench.model.nodeCount).toBe(2);
      expect(workbench.model.edgeCount).toBe(1);
    });

    it('restores an edge between two nodes deleted together exactly once', () => {
      const input = addNode(workbench, TYPE.textInput);
      const agent = addNode(workbench, TYPE.agent);
      connect(workbench, input, 'text', agent, 'prompt');

      workbench.controller.deleteNodes([input.id, agent.id]);
      workbench.controller.undo();

      // The shared edge is reachable from both doomed nodes, so a naive
      // implementation captures and restores it twice.
      expect(workbench.model.edgeCount).toBe(1);
    });

    it('promotes a container’s children rather than deleting them, and undo re-embeds', () => {
      const group = addNode(workbench, TYPE.group);
      const agent = addNode(workbench, TYPE.agent);
      workbench.model.setNodeParent(agent.id, group.id);

      workbench.controller.deleteNodes([group.id]);
      expect(workbench.model.hasNode(agent.id)).toBe(true);
      expect(workbench.model.node(agent.id)?.parentId).toBeNull();

      workbench.controller.undo();
      expect(workbench.model.node(agent.id)?.parentId).toBe(group.id);
    });
  });

  describe('coalescing', () => {
    it('collapses a burst of edits to one field into a single undo step', () => {
      const input = addNode(workbench, TYPE.textInput);

      workbench.controller.setField(input.id, 'prompt', 'a');
      workbench.controller.setField(input.id, 'prompt', 'ab');
      workbench.controller.setField(input.id, 'prompt', 'abc');

      expect(workbench.model.node(input.id)?.data['prompt']).toBe('abc');

      workbench.controller.undo();

      // One Cmd-Z should undo "the word", not one character.
      expect(workbench.model.node(input.id)?.data['prompt']).toBe('');
      expect(workbench.controller.canUndo).toBe(false);
    });

    it('does not merge edits to different fields', () => {
      const tool = addNode(workbench, TYPE.redditSearch);

      workbench.controller.setField(tool.id, 'subreddit', 'typescript');
      workbench.controller.setField(tool.id, 'topicLimit', 5);

      workbench.controller.undo();
      expect(workbench.model.node(tool.id)?.data['topicLimit']).toBe(10);
      expect(workbench.model.node(tool.id)?.data['subreddit']).toBe('typescript');

      workbench.controller.undo();
      expect(workbench.model.node(tool.id)?.data['subreddit']).toBe('reactjs');
    });

    it('does not merge edits to the same field on different nodes', () => {
      const a = addNode(workbench, TYPE.textInput);
      const b = addNode(workbench, TYPE.textInput);

      workbench.controller.setField(a.id, 'prompt', 'first');
      workbench.controller.setField(b.id, 'prompt', 'second');

      workbench.controller.undo();
      expect(workbench.model.node(b.id)?.data['prompt']).toBe('');
      expect(workbench.model.node(a.id)?.data['prompt']).toBe('first');
    });

    it('restores the original value after a merged burst, not the intermediate one', () => {
      const input = addNode(workbench, TYPE.textInput, { data: { prompt: 'start' } });

      workbench.controller.setField(input.id, 'prompt', 'x');
      workbench.controller.setField(input.id, 'prompt', 'xy');
      workbench.controller.undo();

      // The merge must keep the *first* command's captured previous value.
      expect(workbench.model.node(input.id)?.data['prompt']).toBe('start');
    });
  });

  describe('move coalescing', () => {
    it('collapses a drag into one undo returning the node to its start', () => {
      const node = addNode(workbench, TYPE.textInput, { at: { x: 0, y: 0 } });

      workbench.controller.moveNodes([{ nodeId: node.id, position: { x: 40, y: 0 } }]);
      workbench.controller.moveNodes([{ nodeId: node.id, position: { x: 80, y: 0 } }]);
      workbench.controller.moveNodes([{ nodeId: node.id, position: { x: 120, y: 0 } }]);

      expect(workbench.model.node(node.id)?.position.x).toBe(120);

      workbench.controller.undo();
      expect(workbench.model.node(node.id)?.position.x).toBe(0);
      expect(workbench.controller.canUndo).toBe(false);
    });

    it('does not merge moves of different node sets', () => {
      const a = addNode(workbench, TYPE.textInput, { at: { x: 0, y: 0 } });
      const b = addNode(workbench, TYPE.output, { at: { x: 0, y: 0 } });

      workbench.controller.moveNodes([{ nodeId: a.id, position: { x: 40, y: 0 } }]);
      workbench.controller.moveNodes([{ nodeId: b.id, position: { x: 40, y: 0 } }]);

      workbench.controller.undo();
      expect(workbench.model.node(b.id)?.position.x).toBe(0);
      expect(workbench.model.node(a.id)?.position.x).toBe(40);
    });
  });

  describe('transactions', () => {
    it('groups a composite edit into one undo step', () => {
      const input = addNode(workbench, TYPE.textInput);
      const agent = addNode(workbench, TYPE.agent);
      connect(workbench, input, 'text', agent, 'prompt');

      workbench.controller.selectNodes([input.id, agent.id]);
      workbench.controller.deleteSelection();
      expect(workbench.model.nodeCount).toBe(0);

      // Deleting a selection touches edges and nodes through several
      // commands; one undo must reverse all of it.
      workbench.controller.undo();
      expect(workbench.model.nodeCount).toBe(2);
      expect(workbench.model.edgeCount).toBe(1);
      expect(workbench.controller.canUndo).toBe(false);
    });

    it('reverses a reconnect that displaced an existing link, in one step', () => {
      const first = addNode(workbench, TYPE.textInput);
      const second = addNode(workbench, TYPE.textInput);
      const agent = addNode(workbench, TYPE.agent);

      workbench.controller.connect(
        { nodeId: first.id, portId: 'text' },
        { nodeId: agent.id, portId: 'prompt' },
      );
      workbench.controller.connect(
        { nodeId: second.id, portId: 'text' },
        { nodeId: agent.id, portId: 'prompt' },
      );

      // Single-slot input: the second connect displaces the first.
      expect(workbench.model.edgeCount).toBe(1);
      expect(workbench.model.edges()[0]?.source.nodeId).toBe(second.id);

      workbench.controller.undo();

      expect(workbench.model.edgeCount).toBe(1);
      expect(workbench.model.edges()[0]?.source.nodeId).toBe(first.id);
    });
  });

  describe('history is not polluted by non-edits', () => {
    it('does not record selection changes', () => {
      const node = addNode(workbench, TYPE.textInput);
      workbench.controller.selectNodes([node.id]);
      workbench.controller.selection.clear();
      expect(workbench.controller.canUndo).toBe(false);
    });

    it('does not record a measured size applied by the view', () => {
      const node = addNode(workbench, TYPE.textInput);
      workbench.controller.applyMeasuredSize(node.id, { width: 252, height: 300 });
      // A consequence of rendering is not a user edit.
      expect(workbench.controller.canUndo).toBe(false);
      expect(workbench.model.node(node.id)?.size.height).toBe(300);
    });

    it('clears history when a document is imported', () => {
      workbench.controller.addNode(TYPE.textInput, { x: 0, y: 0 });
      expect(workbench.controller.canUndo).toBe(true);

      const json = workbench.controller.exportJSON();
      const outcome = workbench.controller.importJSON(json);

      expect(outcome.ok).toBe(true);
      // Undoing across a document boundary would be meaningless.
      expect(workbench.controller.canUndo).toBe(false);
    });
  });
});
