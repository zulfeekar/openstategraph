import { useEffect, useRef, useState } from 'react';
import { Workflow } from 'lucide-react';
import { Icon } from '@design/primitives';
import { PaperController } from '@canvas/PaperController';
import type { Shortcut } from '@canvas/features/KeyboardFeature';
import { closestEdgeToPoint } from '@core/model/topology';
import {
  useController,
  useSetPaperController,
  useWorkbench,
  useWorkflowVersion,
} from '@app/WorkbenchContext';
import { NodeLayer } from '@view/nodes/NodeLayer';
import { PALETTE_DRAG_TYPE } from '@view/palette/Palette';
import '@canvas/canvas.css';

/**
 * How close a drop must land to an edge's node-centre line before it counts
 * as a splice-insert (ticket 25) rather than an ordinary drop-on-canvas.
 * Deliberately generous relative to a card's own footprint — a drop
 * anywhere clearly *between* two connected cards should splice, not just a
 * drop on the thin rendered line, which the model has no way to hit-test
 * exactly anyway (see `closestEdgeToPoint`'s own note on why it uses node
 * centres rather than the live curve).
 */
const SPLICE_DROP_DISTANCE = 40;

interface CanvasStageProps {
  /** Shell-owned shortcuts, merged with the canvas defaults. */
  shortcuts: readonly Shortcut[];
  showGrid: boolean;
  onNotify: (message: string) => void;
}

/**
 * Mounts the JointJS paper and hosts the React node layer over it.
 *
 * The paper is created once, imperatively, and torn down on unmount. React
 * never re-renders it — it renders the *cards*, through portals into the
 * mounts the paper publishes. Keeping that boundary sharp is what stops the
 * two rendering models from fighting over the same DOM.
 */
export function CanvasStage({ shortcuts, showGrid, onNotify }: CanvasStageProps) {
  const workbench = useWorkbench();
  const controller = useController();
  const setPaper = useSetPaperController();
  const stageRef = useRef<HTMLDivElement | null>(null);
  const [paper, setLocalPaper] = useState<PaperController | null>(null);
  const [dropActive, setDropActive] = useState(false);

  /* ---------------- paper lifecycle ---------------- */

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;

    const instance = new PaperController(stage, controller, workbench.registry, {
      shortcuts,
      showGrid,
    });

    instance.observeConnectionRejections((reason) => {
      if (reason) onNotify(reason);
    });

    setLocalPaper(instance);
    setPaper(instance);
    // Frame whatever the document already contains — usually the seeded demo.
    requestAnimationFrame(() => instance.fitToContent());

    return () => {
      setPaper(null);
      setLocalPaper(null);
      instance.dispose();
    };
    // Deliberately mount-only: the paper is imperative and must not be
    // rebuilt when a prop like `showGrid` changes (handled below instead).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controller, workbench]);

  useEffect(() => {
    paper?.setGridVisible(showGrid);
  }, [paper, showGrid]);

  /* ---------------- run feedback on links ---------------- */

  useEffect(() => {
    if (!paper) return;

    // Light up the links leaving whichever node is running, so the eye can
    // follow execution rather than hunting for the active card.
    const markActive = (nodeId: string | null) => {
      for (const link of paper.graph.getLinks()) {
        const view = link.findView(paper.paper);
        const source = link.source();
        view?.el.classList.toggle('is-active', nodeId != null && source?.id === nodeId);
      }
    };

    // Driven by `node.runtime`, not the local mock engine directly — the
    // engine already writes every status change through
    // `WorkflowModel.setNodeRuntime()` (one-for-one with its own `run:node`
    // bus event), so this is the same signal, not a second one. The reason
    // to key off the model instead: a **backend-streamed** run (the chat
    // panel, ticket 27) has no local `ExecutionEngine` run at all — it calls
    // `setNodeRuntime()` directly as each SSE `update` frame arrives — and
    // this is the one channel both a local preview run and a live backend
    // run pass through, so the flowing-edge animation works for either
    // without the canvas needing to know which kind of run is happening.
    const off = controller.model.on('node:runtime', ({ nodeId, runtime }) => {
      markActive(runtime.status === 'running' ? nodeId : null);
    });

    return () => {
      off();
      markActive(null);
    };
  }, [paper, controller]);

  /* ---------------- palette drop ---------------- */

  const isPaletteDrag = (event: React.DragEvent) =>
    event.dataTransfer.types.includes(PALETTE_DRAG_TYPE);

  return (
    <div
      ref={stageRef}
      className="canvas-stage"
      data-drop-active={dropActive || undefined}
      onDragOver={(event) => {
        if (!isPaletteDrag(event)) return;
        // Both calls are required for a drop to be accepted at all.
        event.preventDefault();
        event.dataTransfer.dropEffect = 'copy';
        setDropActive(true);
      }}
      onDragLeave={(event) => {
        // Ignore bubbling leaves from children, or the highlight flickers.
        if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
        setDropActive(false);
      }}
      onDrop={(event) => {
        if (!isPaletteDrag(event)) return;
        event.preventDefault();
        setDropActive(false);
        const typeId = event.dataTransfer.getData(PALETTE_DRAG_TYPE);
        if (!typeId || !paper) return;
        const at = paper.clientToLocal(event.clientX, event.clientY);

        // Ticket 25's splice-insert: a drop that lands near an existing
        // edge inserts inline instead of dropping onto empty canvas.
        const nearbyEdge = closestEdgeToPoint(
          (id) => controller.model.node(id),
          controller.model.edges(),
          at,
          SPLICE_DROP_DISTANCE,
        );
        const outcome = nearbyEdge
          ? controller.edges.insertOnEdge(nearbyEdge, typeId, at)
          : controller.nodes.add(typeId, at);
        if (!outcome.ok && outcome.message) onNotify(outcome.message);
      }}
    >
      <NodeLayer />
      <EmptyState />
    </div>
  );
}

/**
 * Own component so its model subscription doesn't re-render the stage.
 *
 * `CanvasStage` renders `NodeLayer`; if the stage re-rendered on every model
 * event, every node card would re-render with it — and every card measures
 * itself on render.
 */
function EmptyState() {
  const workbench = useWorkbench();
  useWorkflowVersion();

  if (workbench.model.nodeCount > 0) return null;

  return (
    <div className="canvas-empty">
      <span className="canvas-empty__art">
        <Icon glyph={Workflow} size="xl" />
      </span>
      <span className="canvas-empty__title">Start with a node</span>
      <span className="canvas-empty__hint">
        Drag one in from the palette, or press ⌘V to paste
      </span>
    </div>
  );
}
