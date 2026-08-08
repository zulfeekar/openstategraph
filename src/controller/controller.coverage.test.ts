import { describe, expect, it } from 'vitest';
import { addNode, connect, makeWorkbench, TYPE } from '@core/testing/fixtures';

/**
 * Clipboard, grouping and selection through the controller facade — the
 * gestures the keyboard/menu paths fire, exercised headless (coverage push:
 * ClipboardService sat at 4% before this file).
 */

function seeded() {
  const workbench = makeWorkbench();
  const controller = workbench.controller;
  const input = addNode(workbench, TYPE.textInput, { at: { x: 40, y: 100 } });
  const agent = addNode(workbench, TYPE.agent, { at: { x: 400, y: 100 } });
  connect(workbench, input, 'text', agent, 'prompt');
  return { workbench, controller, input, agent };
}

describe('clipboard', () => {
  it('copy + paste clones the selection with its internal edges', () => {
    const { workbench, controller, input, agent } = seeded();
    controller.selectionActions.selectNodes([input.id, agent.id]);
    expect(controller.clipboard.copy().ok).toBe(true);
    const before = workbench.model.nodes().length;
    const outcome = controller.clipboard.paste({ x: 600, y: 400 });
    expect(outcome.ok).toBe(true);
    expect(workbench.model.nodes().length).toBe(before + 2);
    // The internal edge came along: model edge count went 1 -> 2.
    expect(workbench.model.edges().length).toBe(2);
  });

  it('cut removes the originals and paste restores them, all undoable', () => {
    const { workbench, controller, input } = seeded();
    controller.selectionActions.selectNodes([input.id]);
    expect(controller.clipboard.cut().ok).toBe(true);
    expect(workbench.model.node(input.id)).toBeUndefined();
    expect(controller.clipboard.paste({ x: 100, y: 300 }).ok).toBe(true);
    controller.history.undo();
    controller.history.undo();
    expect(workbench.model.node(input.id)).toBeDefined();
  });

  it('duplicate is one call, offset from the source', () => {
    const { workbench, controller, agent } = seeded();
    const before = workbench.model.nodes().length;
    expect(controller.clipboard.duplicate([agent.id]).ok).toBe(true);
    expect(workbench.model.nodes().length).toBe(before + 1);
  });

  it('copy with nothing selected is a readable no', () => {
    const { controller } = seeded();
    controller.selectionActions.selectNodes([]);
    expect(controller.clipboard.copy().ok).toBe(false);
  });
});

describe('grouping', () => {
  it('group wraps the selection in a container and ungroup releases it', () => {
    const { workbench, controller, input, agent } = seeded();
    controller.selectionActions.selectNodes([input.id, agent.id]);
    const grouped = controller.grouping.group('annotate.group');
    expect(grouped.ok).toBe(true);
    const container = workbench.model
      .nodes()
      .find((node) => node.kind === 'container');
    expect(container).toBeDefined();
    expect(workbench.model.childrenOf(container!.id).length).toBe(2);
    expect(controller.grouping.ungroup(container!.id).ok).toBe(true);
    expect(workbench.model.childrenOf(container!.id).length).toBe(0);
  });
});

describe('selection actions', () => {
  it('selectAll and bounds behave; nudge moves the selection', () => {
    const { workbench, controller, input } = seeded();
    controller.selectionActions.selectAll();
    const bounds = controller.selectionActions.bounds();
    expect(bounds && bounds.width).toBeGreaterThan(0);
    const before = workbench.model.node(input.id)!.position.x;
    controller.selectionActions.nudge(8, 0);
    expect(workbench.model.node(input.id)!.position.x).toBe(before + 8);
  });

  it('deleteSelection removes nodes and their edges in one undoable step', () => {
    const { workbench, controller, input } = seeded();
    controller.selectionActions.selectNodes([input.id]);
    controller.selectionActions.deleteSelection();
    expect(workbench.model.node(input.id)).toBeUndefined();
    expect(workbench.model.edges().length).toBe(0);
    controller.history.undo();
    expect(workbench.model.node(input.id)).toBeDefined();
    expect(workbench.model.edges().length).toBe(1);
  });
});
