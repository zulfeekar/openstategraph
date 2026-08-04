import { nextId } from '@core/kernel/id';
import type { PortRef } from './contracts/ports';
import type { EdgeId, IEdgeModel, SerializedEdge } from './contracts/workflow';

/**
 * A directed connection between one node's output port and another's
 * input port.
 *
 * Endpoints are immutable: re-pointing a link is modelled as remove +
 * add so undo restores the exact prior topology rather than replaying a
 * partial mutation.
 */
export class EdgeModel implements IEdgeModel {
  readonly id: EdgeId;
  readonly source: PortRef;
  readonly target: PortRef;

  private _label: string | null;

  constructor(init: {
    id?: EdgeId;
    source: PortRef;
    target: PortRef;
    label?: string | null;
  }) {
    this.id = init.id ?? nextId('edge');
    this.source = { ...init.source };
    this.target = { ...init.target };
    this._label = init.label ?? null;
  }

  get label(): string | null {
    return this._label;
  }

  /** Called by `WorkflowModel` only. */
  applyLabel(label: string | null): void {
    const trimmed = label?.trim();
    this._label = trimmed ? trimmed : null;
  }

  /** True when either endpoint sits on the given node. */
  touches(nodeId: string): boolean {
    return this.source.nodeId === nodeId || this.target.nodeId === nodeId;
  }

  toJSON(): SerializedEdge {
    return {
      id: this.id,
      source: { ...this.source },
      target: { ...this.target },
      ...(this._label != null ? { label: this._label } : {}),
    };
  }
}
