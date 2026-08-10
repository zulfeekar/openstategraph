import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import clsx from 'clsx';
import { Copy, EllipsisVertical, Focus, Trash2, Ungroup } from 'lucide-react';
import {
  Icon,
  IconButton,
  IconTile,
  Menu,
  StatusDot,
  useMenu,
  type MenuEntry,
  type StatusTone,
} from '@design/primitives';
import { isOnCard, validateFields } from '@core/model/contracts/fields';
import { resolvePortSide, type IPortDescriptor } from '@core/model/contracts/ports';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { NodeGeometry } from '@canvas/shapes/HtmlNode';
import type { NodeId } from '@core/model/contracts/node';
import {
  useController,
  useFlowDirection,
  useNode,
  usePaperController,
  useWorkbench,
} from '@app/WorkbenchContext';
import { resolveIcon } from '@view/icons/iconRegistry';
import { FieldRenderer } from './FieldRenderer';
import { resolveNodeBody } from './nodeBodyRegistry';
import './NodeCard.css';

interface NodeCardProps {
  /**
   * The node's id, not the node itself.
   *
   * The card resolves its own model through `useNode`, which is what makes it
   * re-render when that node changes. Taking the model as a prop looked
   * equivalent and was not: `NodeLayer` only re-renders when the *mount
   * registry* changes — that is, on add and remove — so a card given a `node`
   * prop never re-rendered for a title, data, port or run-status change.
   *
   * That bug hid because a card's own fields still looked right: typing into a
   * card's textarea leaves the text in the DOM, and since React never
   * re-rendered it never reverted it. Editing the same field from the inspector
   * exposed it immediately — the model changed and the card did not move.
   */
  nodeId: NodeId;
}

/**
 * The chrome shared by every node: header, schema-driven body, port footer.
 *
 * Also the source of the card's geometry. After layout it measures its own
 * height and the centre of every port row, then reports both to the canvas
 * adapter — that measurement loop is what makes the cards content-driven and
 * keeps port dots welded to the rows they label, whatever the content does.
 */
export function NodeCard({ nodeId }: NodeCardProps) {
  const node = useNode(nodeId);
  // A mount can briefly outlive its node, so resolving can legitimately miss.
  if (!node) return null;
  return <NodeCardBody node={node} />;
}

function NodeCardBody({ node }: { node: AbstractNodeModel }) {
  const controller = useController();
  const workbench = useWorkbench();
  const paper = usePaperController();
  const cardRef = useRef<HTMLDivElement | null>(null);
  const menu = useMenu<HTMLButtonElement>();

  const fieldErrors = useMemo(
    () =>
      node ? validateFields(node.definition.fields, node.data) : ({} as Record<string, string>),
    [node],
  );

  /* ---------------- geometry reporting ----------------
   *
   * The card measures itself and pushes the result down to the canvas. That
   * makes it a feedback loop — a measurement writes to the model, the model
   * re-renders the card, the card measures again — so it has to be made
   * *convergent* rather than merely correct:
   *
   *   1. Heights are rounded to whole model units, so sub-pixel jitter from
   *      the zoom division can't produce an endlessly "new" value.
   *   2. The last reported geometry is remembered and identical results are
   *      dropped before they reach the model.
   *
   * Without both, the second pass writes a value a hair different from the
   * first and React exceeds its update depth. */

  const flow = useFlowDirection();
  const lastReported = useRef<string>('');

  const report = useCallback(() => {
    const card = cardRef.current;
    if (!card || !paper || !node) return;

    const cardRect = card.getBoundingClientRect();
    const zoom = paper.viewport.zoom || 1;
    // Divide out the zoom: measurements arrive in device pixels, but the
    // model — and therefore the port coordinates — are in model units.
    const height = Math.round(cardRect.height / zoom);
    const width = Math.round(cardRect.width / zoom);
    if (height <= 0) return;

    const ports: Record<string, { x: number; y: number }> = {};

    // Direction-aware: each port's side comes from the one rotation rule in
    // `resolvePortSide` (ticket 45). Several ports can now share the top or
    // bottom edge (all flow inputs, in vertical mode), so those spread
    // evenly along the width instead of stacking on one point.
    const resolved = node.ports.map((port) => ({ port, side: resolvePortSide(port, flow) }));
    const topPorts = resolved.filter((entry) => entry.side === 'top');
    const bottomPorts = resolved.filter((entry) => entry.side === 'bottom');
    const spread = (index: number, count: number) =>
      Math.round((width * (index + 1)) / (count + 1));

    for (const { port, side } of resolved) {
      if (side === 'top') {
        const index = topPorts.findIndex((entry) => entry.port.id === port.id);
        ports[port.id] = { x: spread(index, topPorts.length), y: 0 };
        continue;
      }
      if (side === 'bottom') {
        // The tool-bus pill straddles the card's bottom edge, so the port
        // goes on the pill's *lower* rim — dead centre would put the dot on
        // top of the pill's own label.
        const pill =
          port.appearance === 'pill'
            ? card.querySelector<HTMLElement>(`[data-port-row="${port.id}"]`)
            : null;
        const overhang = pill ? pill.getBoundingClientRect().height / zoom / 2 : 0;
        const index = bottomPorts.findIndex((entry) => entry.port.id === port.id);
        ports[port.id] = {
          x: spread(index, bottomPorts.length),
          y: height + Math.round(overhang),
        };
        continue;
      }
      const row = card.querySelector<HTMLElement>(`[data-port-row="${port.id}"]`);
      if (row) {
        const rowRect = row.getBoundingClientRect();
        const y = Math.round((rowRect.top + rowRect.height / 2 - cardRect.top) / zoom);
        ports[port.id] = { x: side === 'left' ? 0 : width, y };
        continue;
      }
      // A bus port rotated onto a flank has no matching footer row; centre
      // it vertically on the edge instead.
      ports[port.id] = { x: side === 'left' ? 0 : width, y: Math.round(height / 2) };
    }

    const geometry: NodeGeometry = { height, ports };
    const fingerprint = JSON.stringify(geometry);
    if (fingerprint === lastReported.current) return;
    lastReported.current = fingerprint;

    paper.adapter.applyGeometry(node.id, geometry);
    // Keep the document's idea of the node's height in step with what was
    // rendered, so an export or a reload reproduces the same layout.
    if (Math.abs(node.size.height - height) >= 1) {
      controller.nodes.applyMeasuredSize(node.id, { width: node.size.width, height });
    }
  }, [controller, flow, node, paper]);

  // Measure before the browser paints, so ports never lag a frame behind the
  // content that positions them.
  useLayoutEffect(report, [report]);

  // Catches everything a render doesn't: a textarea auto-growing, a font
  // finishing loading, the viewport zooming.
  useEffect(() => {
    const card = cardRef.current;
    if (!card || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => report());
    observer.observe(card);
    return () => observer.disconnect();
  }, [report]);

  // A zoom change invalidates the cached fingerprint, since the measured
  // pixel values are divided by it.
  useEffect(() => {
    if (!paper) return;
    return paper.viewport.onChange(() => {
      lastReported.current = '';
      report();
    });
  }, [paper, report]);

  // A mount can briefly outlive its node — the view is removed on the next
  // JointJS frame, so guard here, after the hooks, rather than dereference a
  // node that is already gone. `NodeLayer` filters with `hasNode`, but the
  // subscription in `useNode` can still read `undefined` for one render.
  if (!node) return null;

  const definition = node.definition;
  const Body = resolveNodeBody(definition);
  const cardFields = definition.fields.filter(isOnCard);

  /* ---------------- menu ---------------- */

  const entries: MenuEntry[] = [
    {
      id: 'duplicate',
      label: 'Duplicate',
      icon: Copy,
      shortcut: '⌘D',
      onSelect: () => controller.clipboard.duplicate([node.id]),
    },
    {
      id: 'focus',
      label: 'Zoom to node',
      icon: Focus,
      onSelect: () => {
        controller.selectionActions.selectNodes([node.id]);
        paper?.viewport.fit(controller.selectionActions.bounds());
      },
    },
    ...(node.kind === 'container'
      ? [
          {
            id: 'ungroup',
            label: 'Release contents',
            icon: Ungroup,
            onSelect: () => controller.grouping.ungroup(node.id),
          } satisfies MenuEntry,
        ]
      : []),
    { kind: 'separator' as const, id: 'sep' },
    {
      id: 'delete',
      label:
        node.kind === 'container' && workbench.model.childrenOf(node.id).length > 0
          ? 'Delete group and contents'
          : 'Delete',
      icon: Trash2,
      danger: true,
      shortcut: '⌫',
      onSelect: () =>
        node.kind === 'container'
          ? controller.nodes.deleteTree(node.id)
          : controller.nodes.delete([node.id]),
    },
  ];

  const status = node.runtime.status;
  const tone: StatusTone = status === 'idle' ? 'ready' : status;

  /* ---------------- container & annotation shapes ---------------- */

  if (node.kind !== 'standard') {
    return (
      <div
        ref={cardRef}
        className={clsx('node', `node--${node.kind}`)}
        data-accent={definition.accent}
        data-node-id={node.id}
      >
        <Body node={node} />
        {node.kind === 'container' ? <ResizeGrip node={node} /> : null}
      </div>
    );
  }

  const inputs = node.ports.filter((port) => port.direction === 'in');
  const outputs = node.ports.filter((port) => port.direction === 'out');
  const rowPorts = [...inputs, ...outputs].filter((port) => (port.appearance ?? 'row') === 'row');
  const pill = node.ports.find((port) => port.appearance === 'pill');

  return (
    <div
      ref={cardRef}
      className={clsx('node', pill && 'node--has-pill', `node--${nodeFamily(definition.id)}`)}
      data-accent={definition.accent}
      data-status={status}
      data-node-id={node.id}
      role="group"
      aria-label={`${definition.label}: ${node.title}`}
    >
      <header className="node__header">
        <IconTile glyph={resolveIcon(definition.iconId)} size="md" iconSize="sm" />
        <div className="node__heading">
          <div className="node__title-row">
            <StatusDot tone={tone} label={`Status: ${status}`} />
            <span className="node__title">{node.title}</span>
          </div>
          <span className="node__subtitle">
            {definition.scope === 'workflow' ? (
              <span
                className="node__scope"
                title="Workflow-scoped: this node type travels with this workflow and is unavailable elsewhere"
              >
                workflow
              </span>
            ) : null}
            {node.subtitle}
          </span>
        </div>
        <span className="node__menu" data-no-drag>
          <IconButton
            ref={menu.anchorRef}
            size="sm"
            label={`${node.title} actions`}
            icon={<Icon glyph={EllipsisVertical} size="sm" />}
            {...menu.triggerProps}
          />
          <Menu
            anchorRef={menu.anchorRef}
            entries={entries}
            open={menu.open}
            onClose={menu.close}
          />
        </span>
      </header>

      <div className="node__body">
        <Body node={node} />
        {cardFields.map((schema) => (
          <FieldRenderer
            key={schema.key}
            nodeId={node.id}
            schema={schema}
            data={node.data}
            {...(fieldErrors[schema.key] ? { error: fieldErrors[schema.key] } : {})}
          />
        ))}
      </div>

      {node.runtime.error ? (
        <div className="node__error" role="alert">
          <span>{node.runtime.error}</span>
        </div>
      ) : null}

      {node.runtime.tokens > 0 || node.runtime.durationMs != null ? (
        <div className="node__meta">
          {node.runtime.tokens > 0 ? (
            <span>{node.runtime.tokens.toLocaleString()} tokens</span>
          ) : null}
          {node.runtime.durationMs != null ? <span>{node.runtime.durationMs} ms</span> : null}
        </div>
      ) : null}

      <footer className="node__ports">
        {rowPorts.map((port) => (
          <PortRow key={port.id} port={port} />
        ))}
      </footer>

      {pill ? (
        <span className="node__pill" data-port-row={pill.id}>
          <span className="node__port-icon">
            <Icon glyph={resolveIcon(portIconId(pill))} size="xs" />
          </span>
          {pill.label}
        </span>
      ) : null}
    </div>
  );
}

/** One labelled port row. `data-port-row` is what the measurement pass finds. */
function PortRow({ port }: { port: IPortDescriptor }) {
  const workbench = useWorkbench();
  const portType = workbench.registry.portType(port.type);
  const glyph = resolveIcon(portType.iconId);

  return (
    <span
      className={clsx(
        'node__port',
        `node__port--${port.direction}`,
        port.required && 'node__port--required',
      )}
      data-port-row={port.id}
      data-accent={portType.accent}
      title={
        port.description ?? `${portType.label} ${port.direction === 'in' ? 'input' : 'output'}`
      }
    >
      {port.direction === 'in' ? (
        <>
          <span className="node__port-icon">
            <Icon glyph={glyph} size="xs" />
          </span>
          <span className="node__port-label">{port.label}</span>
        </>
      ) : (
        <>
          <span className="node__port-label">{port.label}</span>
          <span className="node__port-icon">
            <Icon glyph={glyph} size="xs" />
          </span>
        </>
      )}
    </span>
  );
}

/**
 * Drag-to-resize grip for containers.
 *
 * Commits through the controller so a resize is undoable, and coalesces
 * across the drag via `ResizeNodeCommand`'s merge key.
 */
function ResizeGrip({ node }: { node: AbstractNodeModel }) {
  const controller = useController();
  const paper = usePaperController();

  return (
    <span
      className="node__resize"
      data-no-drag
      role="presentation"
      onPointerDown={(event) => {
        event.stopPropagation();
        event.preventDefault();
        const zoom = paper?.viewport.zoom ?? 1;
        const start = { x: event.clientX, y: event.clientY };
        const origin = { ...node.size };
        const target = event.currentTarget;
        target.setPointerCapture(event.pointerId);

        const onMove = (move: PointerEvent) => {
          controller.nodes.resize(node.id, {
            width: Math.max(200, origin.width + (move.clientX - start.x) / zoom),
            height: Math.max(140, origin.height + (move.clientY - start.y) / zoom),
          });
        };
        const onUp = () => {
          target.removeEventListener('pointermove', onMove);
          target.removeEventListener('pointerup', onUp);
        };
        target.addEventListener('pointermove', onMove);
        target.addEventListener('pointerup', onUp);
      }}
    />
  );
}

function portIconId(port: IPortDescriptor): string {
  return `port-${port.type}`;
}

/** `tool.reddit-search` → `tool`, used for family-level CSS hooks. */
function nodeFamily(typeId: string): string {
  return typeId.split('.')[0] ?? 'node';
}
