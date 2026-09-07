import { nextId } from '@core/kernel/id';
import type { Point } from '@core/kernel/geometry';
import type { PortRef } from './contracts/ports';
import type { EdgeId, IEdgeModel, SerializedEdge } from './contracts/workflow';

/**
 * A directed connection between one node's output port and another's
 * input port.
 *
 * Endpoints are immutable: re-pointing a link is modelled as remove +
 * add so undo restores the exact prior topology rather than replaying a
 * partial mutation.
 *
 * Its geometry is not stored — where the run goes is derived from the two
 * ports by the router — with one exception: `vertices`, the points the run is
 * required to pass through. Those exist because a user placed one, or because
 * the layout reserved a lane for a back-edge, and both are decisions the
 * document has to remember.
 */
export class EdgeModel implements IEdgeModel {
  readonly id: EdgeId;
  readonly source: PortRef;
  readonly target: PortRef;

  private _label: string | null;
  private _vertices: readonly Point[];

  constructor(init: {
    id?: EdgeId;
    source: PortRef;
    target: PortRef;
    label?: string | null;
    vertices?: readonly Point[];
  }) {
    this.id = init.id ?? nextId('edge');
    this.source = { ...init.source };
    this.target = { ...init.target };
    this._label = init.label ?? null;
    this._vertices = EdgeModel.clean(init.vertices);
  }

  get label(): string | null {
    return this._label;
  }

  get vertices(): readonly Point[] {
    return this._vertices;
  }

  /** Called by `WorkflowModel` only. */
  applyLabel(label: string | null): void {
    const trimmed = label?.trim();
    this._label = trimmed ? trimmed : null;
  }

  /** Called by `WorkflowModel` only. */
  applyVertices(vertices: readonly Point[]): void {
    this._vertices = EdgeModel.clean(vertices);
  }

  /** True when either endpoint sits on the given node. */
  touches(nodeId: string): boolean {
    return this.source.nodeId === nodeId || this.target.nodeId === nodeId;
  }

  toJSON(): SerializedEdge {
    return {
      source: { ...this.source },
      target: { ...this.target },
      ...(this._label != null ? { label: this._label } : {}),
      // Omitted when empty, so every document written before waypoints
      // existed round-trips to the same bytes.
      ...(this._vertices.length > 0 ? { vertices: this._vertices.map((p) => ({ ...p })) } : {}),
    };
  }

  /**
   * Copies the list and drops anything that is not a finite pair of numbers.
   *
   * Copied because a caller keeping a reference could otherwise mutate the
   * document behind the model's back; filtered because `Infinity` and `NaN`
   * are not representable in JSON, and a single one of them would make the
   * whole document unwritable — the standing rule against a non-finite number
   * in a serialisable field, enforced at the one door they can come through.
   */
  private static clean(vertices: readonly Point[] | undefined): readonly Point[] {
    if (!vertices || vertices.length === 0) return [];
    return vertices
      .filter((p) => p != null && Number.isFinite(p.x) && Number.isFinite(p.y))
      .map((p) => ({ x: p.x, y: p.y }));
  }
}
