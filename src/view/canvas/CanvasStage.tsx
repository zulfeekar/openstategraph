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
      flowDirection: workbench.preferences.flowDirection,
      followRun: workbench.preferences.followRun,
    });

    instance.observeConnectionRejections((reason) => {
      if (reason) onNotify(reason);
    });

    setLocalPaper(instance);
    setPaper(instance);
    // Frame whatever the document already contains — usually the seeded demo.
    // The handle is kept and cancelled below: under StrictMode's double mount
    // the effect unmounts within the same frame, and an uncancelled callback
    // would then call `fitToContent()` on an already-disposed paper.
    const framing = requestAnimationFrame(() => instance.fitToContent());

    return () => {
      cancelAnimationFrame(framing);
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

  // Port sides rotate with the reading direction, and so must everything the
  // canvas derives from them — the seeded port placement and the rhythm of the
  // branch labels. Subscribing to the store rather than taking `useFlowDirection`
  // keeps this out of the stage's render path: a re-render here would re-render
  // every card, and every card measures itself on render.
  useEffect(() => {
    if (!paper) return;
    const { preferences } = workbench;
    paper.adapter.setFlowDirection(preferences.flowDirection);
    return preferences.onChange(() => paper.adapter.setFlowDirection(preferences.flowDirection));
  }, [paper, workbench]);

  /* ---------------- run feedback on links ---------------- */

  useEffect(() => {
    if (!paper) return;

    // Light up the links leaving whichever node is running, so the eye can
    // follow execution rather than hunting for the active card.
    //
    // Only the *current* node is marked, and everything clears when the run
    // ends. A persistent "path taken" tint was tried here and removed: this
    // channel carries per-node status and no run boundary, so the editor
    // cannot tell a new run from a slow step without guessing at an idle
    // timeout — and a guess that is wrong leaves stale glow on the canvas.
    // The customer `/chat` surface keeps its visited trail instead, because
    // there the client owns the request and therefore knows where a run
    // starts and stops.
    const markActive = (nodeId: string | null) => {
      for (const link of paper.graph.getLinks()) {
        const view = link.findView(paper.paper);
        const source = link.source();
        const target = link.target();
        // Outgoing links carry the flowing dash — data leaving the node.
        view?.el.classList.toggle('is-active', nodeId != null && source?.id === nodeId);
        // Incoming links are marked too, so the eye can see *how* the run
        // arrived at the active node, not only where it goes next.
        view?.el.classList.toggle('is-incoming', nodeId != null && target?.id === nodeId);
      }
      // The active card itself: a pulse on the JointJS element root rather
      // than anything written into the model — this stays a projection.
      for (const element of paper.graph.getElements()) {
        const view = element.findView(paper.paper);
        if (!view) continue;
        view.el.classList.toggle('is-active', nodeId != null && String(element.id) === nodeId);
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
    /**
     * The paused card (UX-01): a run stopped at a `human.approval` node.
     *
     * A separate mark rather than a variant of `is-active`, because it is the
     * *opposite* claim — nothing is executing, and the person reading the
     * approval card is what the run is waiting for. So no sweep, no flowing
     * edges: a static ring and a label, both from `canvas.css`.
     */
    const markPaused = (nodeId: string | null) => {
      for (const element of paper.graph.getElements()) {
        const view = element.findView(paper.paper);
        if (!view) continue;
        view.el.classList.toggle('is-paused', nodeId != null && String(element.id) === nodeId);
      }
    };

    // Ticket 08. The follower needs the *set* of running nodes, not the last
    // one to change: a `Send` fan-out lights three workers in the same
    // superstep, and framing the third alone would leave the other two off
    // screen. The model is the register of who is running, so it is read
    // rather than a second tally being kept here.
    const runningNodes = () =>
      controller.model
        .nodes()
        .filter((node) => node.runtime.status === 'running')
        .map((node) => node.id);

    const off = controller.model.on('node:runtime', ({ nodeId, runtime }) => {
      // Exactly one of the two marks at a time, and every status that is
      // neither clears both — a node cannot be running *and* waiting, and a
      // paused node that resumes must not keep its ring.
      markActive(runtime.status === 'running' ? nodeId : null);
      markPaused(runtime.status === 'paused' ? nodeId : null);
      // A paused node is where the run *is*, so it is worth looking at too.
      const active = runtime.status === 'paused' ? [nodeId] : runningNodes();
      paper.follower.setActive(active);
    });

    // A local preview run announces itself, so the follower can clear the
    // latch: panning during one run must not disable following for every run
    // after it. A backend-streamed run has no engine, so `AppShell` calls the
    // same method when its Ask panel reports a stream starting.
    const offStart = workbench.engine.on('run:start', () => paper.follower.runStarted());

    return () => {
      off();
      offStart();
      markActive(null);
      markPaused(null);
    };
  }, [paper, controller, workbench]);

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
      <span className="canvas-empty__hint">Drag one in from the palette, or press ⌘V to paste</span>
    </div>
  );
}
