import type { WorkflowModel } from './WorkflowModel';
import type { EdgeId } from './contracts/workflow';

/**
 * A link, in the words a person would use for it.
 *
 * Pure, and in `core/` on purpose: this is the entire content of the
 * inspector's link mode, and a panel that computes its own sentences is a
 * panel nobody can test. The view renders these strings and adds a button.
 */
export interface EdgeDescription {
  readonly edgeId: EdgeId;
  /** Card title of the node the link leaves. */
  readonly sourceNode: string;
  /** Port label — what the value *is*, e.g. "result". */
  readonly sourcePort: string;
  readonly targetNode: string;
  readonly targetPort: string;
  /** Port type of the source end, which is what the edge's colour encodes. */
  readonly type: string;
}

/**
 * Describes `edgeId`, or `null` when it no longer exists.
 *
 * Endpoints are looked up rather than stored, because a node can be renamed
 * after the link was drawn and the panel must say the current name.
 *
 * A port that has since disappeared falls back to its raw id instead of
 * rendering blank: an unknown-node placeholder (ticket 20) labels its
 * synthesised ports by id, and a link to one still has to be describable —
 * and removable.
 */
export function describeEdge(model: WorkflowModel, edgeId: EdgeId): EdgeDescription | null {
  const edge = model.edge(edgeId);
  if (!edge) return null;

  const source = model.node(edge.source.nodeId);
  const target = model.node(edge.target.nodeId);
  const sourcePort = source?.port(edge.source.portId);
  const targetPort = target?.port(edge.target.portId);

  return {
    edgeId,
    sourceNode: source?.title ?? edge.source.nodeId,
    sourcePort: sourcePort?.label ?? edge.source.portId,
    targetNode: target?.title ?? edge.target.nodeId,
    targetPort: targetPort?.label ?? edge.target.portId,
    type: sourcePort?.type ?? targetPort?.type ?? 'unknown',
  };
}
