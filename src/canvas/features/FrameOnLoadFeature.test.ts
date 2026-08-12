import { describe, expect, it, vi } from 'vitest';
import { addNode, makeWorkbench, TYPE } from '@core/testing/fixtures';
import type { Rect } from '@core/kernel/geometry';
import { FrameOnLoadFeature } from './FrameOnLoadFeature';
import type { PaperFeatureContext } from './IPaperFeature';

/**
 * The feature touches exactly two collaborators — the model's event stream
 * and the viewport's `fit`. Handing it a paper it never reads would only
 * force this test into a DOM environment for nothing.
 */
function harness() {
  const workbench = makeWorkbench();
  const fit = vi.fn<(rect: Rect | null) => void>();
  const pending: (() => void)[] = [];
  const feature = new FrameOnLoadFeature((run) => {
    pending.push(run);
    return () => {
      const at = pending.indexOf(run);
      if (at >= 0) pending.splice(at, 1);
    };
  });
  feature.install({
    controller: workbench.controller,
    viewport: { fit },
  } as unknown as PaperFeatureContext);
  return {
    workbench,
    model: workbench.model,
    fit,
    feature,
    flush: () => pending.splice(0).forEach((run) => run()),
  };
}

describe('FrameOnLoadFeature', () => {
  it('frames the new document when one is loaded wholesale', () => {
    // The bug: drilling into a mounted team replaced the document but left
    // the camera parked over the parent's coordinates, so the child's nodes
    // rendered off screen at a scale chosen for a different graph.
    const h = harness();
    addNode(h.workbench, TYPE.agent, { at: { x: 900, y: 1200 } });
    h.model.notifyReset();
    h.flush();
    expect(h.fit).toHaveBeenCalledTimes(1);
    expect(h.fit).toHaveBeenCalledWith(h.model.bounds());
    expect(h.fit.mock.calls[0]?.[0]).toMatchObject({ x: 900, y: 1200 });
  });

  it('does not move the camera for ordinary edits', () => {
    // Adding, moving or deleting a node must never yank the view — only a
    // wholesale replacement is a new coordinate space.
    const h = harness();
    const node = addNode(h.workbench, TYPE.agent, { at: { x: 40, y: 40 } });
    h.model.moveNode(node.id, { x: 4000, y: 4000 });
    h.model.removeNode(node.id);
    h.flush();
    expect(h.fit).not.toHaveBeenCalled();
  });

  it('frames an emptied document too, rather than leaving a stale transform', () => {
    const h = harness();
    addNode(h.workbench, TYPE.agent, { at: { x: 40, y: 40 } });
    h.model.clear();
    h.flush();
    expect(h.fit).toHaveBeenCalledWith(null);
  });

  it('defers the frame, so the rebuild and the cards it triggers land first', () => {
    const h = harness();
    addNode(h.workbench, TYPE.agent);
    h.model.notifyReset();
    expect(h.fit).not.toHaveBeenCalled();
    h.flush();
    expect(h.fit).toHaveBeenCalledTimes(1);
  });

  it('coalesces two resets in one frame into a single fit', () => {
    const h = harness();
    h.model.notifyReset();
    addNode(h.workbench, TYPE.agent);
    h.model.notifyReset();
    h.flush();
    expect(h.fit).toHaveBeenCalledTimes(1);
  });

  it('cancels a pending frame on dispose, so a torn-down paper is never touched', () => {
    const h = harness();
    addNode(h.workbench, TYPE.agent);
    h.model.notifyReset();
    h.feature.dispose();
    h.flush();
    expect(h.fit).not.toHaveBeenCalled();
  });

  it('stops listening once disposed', () => {
    const h = harness();
    h.feature.dispose();
    h.model.notifyReset();
    h.flush();
    expect(h.fit).not.toHaveBeenCalled();
  });
});
