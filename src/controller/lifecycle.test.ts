import { describe, expect, it } from 'vitest';
import { addNode, makeWorkbench, TYPE } from '@core/testing/fixtures';

/**
 * Disposal is proven by *effect*, not by counting handlers.
 *
 * A test asserting "the set is empty" would pass against a controller that
 * unregistered its handlers and left a live reference to the model — the leak
 * that actually matters in a long editor session, where a drill-in/drill-out
 * builds a controller per workflow. Emitting after `dispose()` and asserting
 * nothing runs is the observable version of the same claim, and it cannot be
 * satisfied by bookkeeping alone.
 */
describe('controller disposal', () => {
  it('stops reacting to model events', () => {
    const workbench = makeWorkbench();
    const controller = workbench.controller;
    const node = addNode(workbench, TYPE.agent, { at: { x: 0, y: 0 } });
    controller.selectionActions.selectNodes([node.id]);
    expect(controller.selection.nodes).toEqual([node.id]);

    controller.dispose();
    // Removing the node fires `node:removed`. A live controller would prune
    // the now-dangling id out of the selection; a disposed one must not.
    workbench.model.removeNode(node.id);

    expect(controller.selection.nodes).toEqual([node.id]);
  });

  it('is idempotent — a second dispose is not an error', () => {
    const controller = makeWorkbench().controller;
    controller.dispose();
    expect(() => controller.dispose()).not.toThrow();
  });

  it('releases every onChange subscriber the caller unsubscribed', () => {
    const workbench = makeWorkbench();
    const controller = workbench.controller;
    let calls = 0;
    const off = controller.onChange(() => (calls += 1));

    addNode(workbench, TYPE.agent, { at: { x: 0, y: 0 } });
    expect(calls).toBeGreaterThan(0);

    const seen = calls;
    off();
    addNode(workbench, TYPE.agent, { at: { x: 100, y: 0 } });

    expect(calls).toBe(seen);
  });
});
