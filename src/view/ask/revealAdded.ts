import type { WorkflowModel } from '@core/model/WorkflowModel';

/**
 * The rectangle a newly added node occupies, for bringing it into view.
 *
 * Pressing **Add & re-run** placed a tool correctly — right type, right agent,
 * right port — and left it **unselected and roughly 300px below the fold**,
 * while the re-run's highlight animated four *other* nodes
 * (`every-workflow-green` 31). The two failure modes are indistinguishable
 * from the chair: "it worked, off-screen" and "it did nothing".
 *
 * The node is placed *below* the agent it attaches to
 * (`y + height + 120`), so the lower that agent already sits, the more
 * reliably the new node lands outside the viewport. It is not an edge case; it
 * is the normal case for any workflow taller than one screen.
 *
 * A pure function of the model so the decision is testable without a paper, a
 * DOM or a canvas — `core/` knows nothing of JointJS and this stays on the
 * right side of that line. The caller does the scrolling.
 */
export function rectOfAdded(model: WorkflowModel, nodeId: string | null): {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
} | null {
  if (!nodeId) return null;
  const node = model.node(nodeId);
  if (!node) return null;
  return {
    x: node.position.x,
    y: node.position.y,
    width: node.size.width,
    height: node.size.height,
  };
}
