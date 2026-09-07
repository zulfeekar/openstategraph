import { describe, expect, it } from 'vitest';

import { addNode, makeWorkbench, TYPE } from '@core/testing/fixtures';
import { rectOfAdded } from './revealAdded';

/**
 * `every-workflow-green` 31 — the node it added was below the fold.
 */
describe('rectOfAdded', () => {
  it('returns the node rectangle, so the caller can scroll to it', () => {
    const wb = makeWorkbench();
    const node = addNode(wb, TYPE.agent, { at: { x: 40, y: 900 } });
    const rect = rectOfAdded(wb.model, node.id);
    expect(rect).not.toBeNull();
    expect(rect?.x).toBe(40);
    expect(rect?.y).toBe(900);
    expect(rect?.width).toBeGreaterThan(0);
    expect(rect?.height).toBeGreaterThan(0);
  });

  it('is null when nothing was added', () => {
    // A declined suggestion (ticket 29) adds nothing and must move nothing.
    const wb = makeWorkbench();
    expect(rectOfAdded(wb.model, null)).toBeNull();
  });

  it('is null for a node that is not on the canvas', () => {
    const wb = makeWorkbench();
    expect(rectOfAdded(wb.model, 'node:never-added')).toBeNull();
  });
});
