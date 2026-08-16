import { describe, expect, it } from 'vitest';
import { makeWorkbench } from '@core/testing/fixtures';
import { SUBGRAPH_TYPE, type SubgraphNodeModel } from '@nodes/compose/SubgraphNode';
import { decodePackageDrag, encodePackageDrag } from '@view/palette/packageDrag';

/**
 * Dropping a named package from the palette — organisms-first-class ticket 11.
 *
 * The drop is `controller.nodes.add(typeId, at, { data })` with the payload the
 * palette row carried, so the assertions below are the canvas's drop handler
 * with the DOM taken out: the same call, on a real `Workbench`.
 */
function drop(
  workbench: ReturnType<typeof makeWorkbench>,
  slug: string,
  at: { x: number; y: number },
): SubgraphNodeModel {
  const payload = decodePackageDrag(encodePackageDrag(slug));
  if (!payload) throw new Error('the palette wrote a payload its own decoder refused');
  const before = new Set(workbench.model.nodes().map((node) => node.id));
  const outcome = workbench.controller.nodes.add(payload.typeId, at, { data: payload.data });
  expect(outcome.ok).toBe(true);
  const created = workbench.model.nodes().find((node) => !before.has(node.id));
  if (!created) throw new Error('nothing was added');
  return created as SubgraphNodeModel;
}

describe('dragging a named package onto the canvas', () => {
  it('lands a mount already pointing at that package', () => {
    const workbench = makeWorkbench();
    const mount = drop(workbench, 'chinook-assistant', { x: 200, y: 120 });

    expect(mount.type).toBe(SUBGRAPH_TYPE);
    // The whole ticket: no second step. The slug is on the node the drop
    // created, not something the user then has to go and tell it.
    expect(mount.workflowSlug).toBe('chinook-assistant');
  });

  it('keeps the schema defaults the payload said nothing about', () => {
    const workbench = makeWorkbench();
    const mount = drop(workbench, 'chinook-assistant', { x: 200, y: 120 });

    // A partial `data` is merged over the defaults, not substituted for them —
    // a mount whose `overrides` key was simply absent would serialise a
    // document the loader has to guess at.
    expect(mount.data.outcome).toBe('');
    expect(mount.data.overrides).toBe('');
  });

  it('is undoable as one step, like every other add', () => {
    const workbench = makeWorkbench();
    drop(workbench, 'chinook-assistant', { x: 200, y: 120 });
    expect(workbench.model.nodeCount).toBe(1);

    workbench.controller.history.undo();
    expect(workbench.model.nodeCount).toBe(0);
  });

  /**
   * The property the whole model turns on: **a package is the definition, a
   * mount is the instance**. Two drops of one package are two instances, and
   * overriding one must not touch the other — `new Root()` twice, not one
   * object handed out twice.
   */
  describe('two drops of one package', () => {
    it('are two nodes, both bound to it', () => {
      const workbench = makeWorkbench();
      const first = drop(workbench, 'chinook-assistant', { x: 200, y: 120 });
      const second = drop(workbench, 'chinook-assistant', { x: 520, y: 120 });

      expect(first.id).not.toBe(second.id);
      expect(first.workflowSlug).toBe('chinook-assistant');
      expect(second.workflowSlug).toBe('chinook-assistant');
    });

    it('have independent overrides', () => {
      const workbench = makeWorkbench();
      const first = drop(workbench, 'chinook-assistant', { x: 200, y: 120 });
      const second = drop(workbench, 'chinook-assistant', { x: 520, y: 120 });

      workbench.controller.nodes.setField(
        first.id,
        'overrides',
        '{"grader1": {"criteria": "- stricter"}}',
      );

      expect(first.data.overrides).toBe('{"grader1": {"criteria": "- stricter"}}');
      // The package's own value still applies here. If these two shared a data
      // bag — one `data` object reached by both, the failure a partial `data`
      // passed by reference invites — this is the line that would go red.
      expect(second.data.overrides).toBe('');
    });

    it('do not share the data object the drop payload was made of', () => {
      const workbench = makeWorkbench();
      const first = drop(workbench, 'chinook-assistant', { x: 200, y: 120 });
      const second = drop(workbench, 'chinook-assistant', { x: 520, y: 120 });

      expect(first.data).not.toBe(second.data);
    });
  });
});
