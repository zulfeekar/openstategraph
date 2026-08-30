import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, Maximize2, Minus, Plus } from 'lucide-react';
import { Icon, IconButton, Tooltip } from '@design/primitives';
import { unionRects, type Point, type Rect } from '@core/kernel/geometry';
import { coversAnyNode, type ScreenProjection } from './coverage';
import { observeResize } from '../layout/observeResize';
import { usePaperController, useWorkbench, useWorkflowVersion } from '@app/WorkbenchContext';
import './Minimap.css';

const MAP_WIDTH = 168;
const MAP_HEIGHT = 104;

/**
 * The navigator: an overview map plus the zoom controls.
 *
 * Drawn from the model's node rectangles rather than by rendering a second
 * JointJS paper. A second paper would mean a second set of foreignObjects,
 * a second React portal tree and a second layout pass per frame — for a
 * thumbnail in which none of that detail is legible anyway. Rectangles are
 * the honest level of detail here, and cost nothing.
 */
export function Minimap() {
  const workbench = useWorkbench();
  const paper = usePaperController();
  const version = useWorkflowVersion();
  const [collapsed, setCollapsed] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [viewRect, setViewRect] = useState<Rect | null>(null);
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!paper) return;
    const sync = () => {
      setZoom(paper.viewport.zoom);
      setViewRect(paper.viewport.visibleRect);
    };
    sync();
    return paper.viewport.onChange(sync);
  }, [paper]);

  // Rebuilt when the model says so, not on every render of the shell — which
  // is what gives the coverage effect below something honest to depend on. The
  // node geometry is derived from the whole document, so `version` is the
  // signal that invalidates it; the same idiom, and the same suppression, as
  // `Inspector.tsx`'s diagnostics memo.
  const rects = useMemo(
    () =>
      workbench.model.nodes().map((node) => ({
        id: node.id,
        kind: node.kind,
        accent: node.definition.accent,
        x: node.position.x,
        y: node.position.y,
        width: node.size.width,
        height: node.size.height,
      })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [workbench, version],
  );

  // The map frames the graph *and* the viewport, so panning away from the
  // nodes still shows where you are rather than an empty box.
  const world = unionRects([...rects, ...(viewRect ? [viewRect] : [])]);

  /**
   * The map's own laid-out rectangle, re-measured only when it can have moved.
   *
   * `the-cost-of-one-more/22`. This read used to sit inside the coverage
   * effect below, which had **no dependency array** — so a `getBoundingClientRect`
   * forced a synchronous layout of the whole document after every render of
   * the shell, for every reason the shell renders. `20`'s CPU profile put it
   * at 19.7% of a 700-frame burst, second only to Markdown parsing, growing
   * ×3.65 per doubling of the frame count: not because the minimap does more
   * work, but because a forced layout costs what the document costs and the
   * run trace was adding rows to that document on every frame.
   *
   * An empty dependency array would have been the wrong fix and a second bug
   * in the same place — the map moves, and a box measured once at mount is
   * wrong for the rest of the session. Two observers, because two different
   * things move it and neither raises an event the other would catch:
   *
   *  - **its own box**, which changes when the map is collapsed or expanded;
   *  - **the stage it floats in**, which changes on a window resize and when
   *    the run dock takes three hundred pixels of height out of it. The map is
   *    anchored to the stage's bottom-right, so that moves the map without
   *    changing its size — a `ResizeObserver` on the map alone would never
   *    hear it. `observeResize`'s own docstring is about exactly this dock.
   *
   * A pan or a zoom is neither: it moves the *nodes* under a stationary map,
   * and the projection below carries that.
   */
  const [mapBox, setMapBox] = useState<Rect | null>(null);
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const measure = () => {
      const box = root.getBoundingClientRect();
      setMapBox({ x: box.x, y: box.y, width: box.width, height: box.height });
    };
    measure();
    const stopWatchingSelf = observeResize(root, measure);
    const stopWatchingStage = observeResize(root.parentElement, measure);
    return () => {
      stopWatchingSelf();
      stopWatchingStage();
    };
  }, []);

  /**
   * Model coordinates → screen ones, for the camera we were last told about.
   *
   * The viewport is read live because that is the only place `localToClient`
   * lives, but the *identity* of this object is keyed on the camera state the
   * subscription above publishes — which is what gives the coverage effect
   * something honest to depend on. A pan changes `viewRect`, a zoom changes
   * `zoom`, and either rebuilds the projection.
   */
  const view = useMemo<ScreenProjection | null>(
    () =>
      paper === null || viewRect === null
        ? null
        : { zoom, localToClient: (at: Point) => paper.viewport.localToClient(at) },
    [paper, zoom, viewRect],
  );

  // Whether the map is currently sitting on a card (ticket 55.8).
  //
  // Written straight onto the element rather than held as state. It is a fact
  // about where the DOM ended up that drives nothing but an opacity — routing
  // it back through React would buy a second render per pan for a value no
  // other code reads.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    root.toggleAttribute('data-covering', view !== null && coversAnyNode(mapBox, rects, view));
  }, [mapBox, rects, view]);

  const project = useCallback(
    (rect: Rect) => {
      if (!world || world.width === 0 || world.height === 0) return null;
      const scale = Math.min(MAP_WIDTH / world.width, MAP_HEIGHT / world.height);
      const offsetX = (MAP_WIDTH - world.width * scale) / 2;
      const offsetY = (MAP_HEIGHT - world.height * scale) / 2;
      return {
        left: (rect.x - world.x) * scale + offsetX,
        top: (rect.y - world.y) * scale + offsetY,
        width: Math.max(2, rect.width * scale),
        height: Math.max(2, rect.height * scale),
      };
    },
    [world],
  );

  /** Clicking or dragging the map recentres the viewport there. */
  const jumpTo = (clientX: number, clientY: number) => {
    const surface = surfaceRef.current;
    if (!surface || !world || !paper) return;
    const rect = surface.getBoundingClientRect();
    const scale = Math.min(MAP_WIDTH / world.width, MAP_HEIGHT / world.height);
    const offsetX = (MAP_WIDTH - world.width * scale) / 2;
    const offsetY = (MAP_HEIGHT - world.height * scale) / 2;
    const local = {
      x: (clientX - rect.left - offsetX) / scale + world.x,
      y: (clientY - rect.top - offsetY) / scale + world.y,
    };
    paper.viewport.centerOn({ x: local.x, y: local.y, width: 0, height: 0 });
  };

  const viewBox = viewRect ? project(viewRect) : null;

  return (
    <div ref={rootRef} className="minimap" data-collapsed={collapsed || undefined}>
      {!collapsed ? (
        <div
          ref={surfaceRef}
          className="minimap__surface"
          style={{ width: MAP_WIDTH, height: MAP_HEIGHT }}
          role="presentation"
          onPointerDown={(event) => {
            event.currentTarget.setPointerCapture(event.pointerId);
            jumpTo(event.clientX, event.clientY);
          }}
          onPointerMove={(event) => {
            if (event.buttons !== 1) return;
            jumpTo(event.clientX, event.clientY);
          }}
        >
          {version >= 0 &&
            rects.map((rect) => {
              const box = project(rect);
              if (!box) return null;
              return (
                <span
                  key={rect.id}
                  className={`minimap__node minimap__node--${rect.kind}`}
                  data-accent={rect.accent}
                  style={box}
                />
              );
            })}
          {viewBox ? <span className="minimap__viewport" style={viewBox} /> : null}
        </div>
      ) : null}

      <div className="minimap__controls">
        <IconButton
          size="sm"
          label={collapsed ? 'Show minimap' : 'Hide minimap'}
          icon={
            <Icon glyph={ChevronDown} size="sm" className={collapsed ? 'is-flipped' : undefined} />
          }
          onClick={() => setCollapsed((value) => !value)}
        />
        <span className="minimap__divider" role="presentation" />
        <Tooltip content="Zoom out" placement="top">
          <IconButton
            size="sm"
            label="Zoom out"
            icon={<Icon glyph={Minus} size="sm" />}
            onClick={() => paper?.viewport.zoomOut()}
          />
        </Tooltip>
        <button
          type="button"
          className="minimap__zoom"
          title="Reset zoom to 100%"
          onClick={() => paper?.viewport.resetZoom()}
        >
          {Math.round(zoom * 100)}%
        </button>
        <Tooltip content="Zoom in" placement="top">
          <IconButton
            size="sm"
            label="Zoom in"
            icon={<Icon glyph={Plus} size="sm" />}
            onClick={() => paper?.viewport.zoomIn()}
          />
        </Tooltip>
        <span className="minimap__divider" role="presentation" />
        <Tooltip content="Fit to screen" placement="top">
          <IconButton
            size="sm"
            label="Fit to screen"
            icon={<Icon glyph={Maximize2} size="sm" />}
            onClick={() => paper?.fitToContent()}
          />
        </Tooltip>
      </div>
    </div>
  );
}
