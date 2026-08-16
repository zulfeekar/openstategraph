import { SUBGRAPH_TYPE } from '@nodes/compose/SubgraphNode';
import type { NodeData } from '@core/model/contracts/fields';

/**
 * A palette drag carrying a **package** — a node type *and* the data that binds
 * it to one saved workflow (organisms-first-class ticket 11).
 *
 * A third MIME beside `PALETTE_DRAG_TYPE` and `PALETTE_ASSEMBLY_DRAG_TYPE`, for
 * the reason those two are separate from each other: the canvas has to know
 * during `dragover` — before it can read any payload — what it is about to
 * receive. `dataTransfer.getData` returns `''` for every type until the drop.
 *
 * The payload carries its own `typeId` rather than the canvas hardcoding
 * `workflow.subgraph`. That is what keeps the drop handler generic: it adds a
 * node of the type it was handed with the data it was handed, and never learns
 * the name of the mount family. If a second kind of pre-bound drag ever exists,
 * this route already carries it.
 */
export const PALETTE_PACKAGE_DRAG_TYPE = 'application/x-openstategraph-package';

/** A node type and the fields a drop must create it with. */
export interface PackageDragPayload {
  readonly typeId: string;
  readonly data: Partial<NodeData>;
}

/** The payload for a Packages row bound to `slug`. */
export function encodePackageDrag(slug: string): string {
  return JSON.stringify({ typeId: SUBGRAPH_TYPE, data: { workflow: slug.trim() } });
}

/**
 * The payload back, or `null` for anything this did not write.
 *
 * Total on purpose. A drop handler runs on whatever the operating system hands
 * it — another application's drag can set any MIME string it likes — so this
 * validates rather than casts, and a malformed payload costs the drop instead
 * of throwing out of an event handler where nothing would report it.
 *
 * An empty slug is malformed too, not merely unset: a mount bound to nothing is
 * exactly the two-step this drag exists to replace.
 */
export function decodePackageDrag(raw: string): PackageDragPayload | null {
  if (!raw) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;

  const { typeId, data } = parsed as { typeId?: unknown; data?: unknown };
  if (typeof typeId !== 'string' || !typeId) return null;
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null;

  const workflow = (data as { workflow?: unknown }).workflow;
  if (typeof workflow !== 'string' || !workflow.trim()) return null;

  // Rebuilt rather than passed through, so a drop takes only the keys this
  // route is allowed to set — and so every decode yields its own object.
  return { typeId, data: { workflow: workflow.trim() } };
}
