import { useEffect, useRef, useState } from 'react';
import { Workflow } from 'lucide-react';
import { Icon } from '@design/primitives';
import { PaperController } from '@canvas/PaperController';
import type { Shortcut } from '@canvas/features/KeyboardFeature';
import {
  useController,
  useSetPaperController,
  useWorkbench,
  useWorkflowVersion,
} from '@app/WorkbenchContext';
import { NodeLayer } from '@view/nodes/NodeLayer';
import { PALETTE_DRAG_TYPE } from '@view/palette/Palette';
import '@canvas/canvas.css';

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
    const { engine } = workbench;

    // Light up the links leaving whichever node is running, so the eye can
    // follow execution rather than hunting for the active card.
    const markActive = (nodeId: string | null) => {
      for (const link of paper.graph.getLinks()) {
        const view = link.findView(paper.paper);
        const source = link.source();
        view?.el.classList.toggle('is-active', nodeId != null && source?.id === nodeId);
      }
    };

    const offNode = engine.on('run:node', ({ nodeId, status }) => {
      markActive(status === 'running' ? nodeId : null);
    });
    const offFinish = engine.on('run:finish', () => markActive(null));

    return () => {
      offNode();
      offFinish();
      markActive(null);
    };
  }, [paper, workbench]);

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
        const outcome = controller.nodes.add(typeId, at);
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
