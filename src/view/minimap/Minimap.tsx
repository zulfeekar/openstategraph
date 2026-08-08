import { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronDown, Maximize2, Minus, Plus } from 'lucide-react';
import { Icon, IconButton, Tooltip } from '@design/primitives';
import { unionRects, type Rect } from '@core/kernel/geometry';
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

  useEffect(() => {
    if (!paper) return;
    const sync = () => {
      setZoom(paper.viewport.zoom);
      setViewRect(paper.viewport.visibleRect);
    };
    sync();
    return paper.viewport.onChange(sync);
  }, [paper]);

  const nodes = workbench.model.nodes();
  const rects = nodes.map((node) => ({
    id: node.id,
    kind: node.kind,
    accent: node.definition.accent,
    x: node.position.x,
    y: node.position.y,
    width: node.size.width,
    height: node.size.height,
  }));

  // The map frames the graph *and* the viewport, so panning away from the
  // nodes still shows where you are rather than an empty box.
  const world = unionRects([...rects, ...(viewRect ? [viewRect] : [])]);

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
    <div className="minimap" data-collapsed={collapsed || undefined}>
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
