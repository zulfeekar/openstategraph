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
import type { IPortDescriptor } from '@core/model/contracts/ports';
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
import { MOUNT_BADGE, isMountType } from './mountKind';
import { resolveNodeBody } from './nodeBodyRegistry';
import { planPortLayout, portPositions, type PlannedPortRow } from './portLayout';
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

  // Keyed on the **data**, not just the node. The model is mutated in place —
  // one `AbstractNodeModel` instance for the life of the node — so `[node]`
  // memoised the errors of the data as it stood when the card first mounted,
  // and no edit ever recomputed them. The card therefore showed a validation
  // message only after something else forced a remount, which is how "refused
  // at pick time" (ticket 42) could be true in the inspector, which validates
  // on every render, and silently false on the card beside it. `_data` is
  // replaced wholesale on every `setField`, so its identity is the right key.
  const fieldErrors = useMemo(
    () =>
      node ? validateFields(node.definition.fields, node.data) : ({} as Record<string, string>),
    [node, node?.data],
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

    // The card measures; `portLayout` decides. Everything below is DOM
    // reading — which row is where, how wide the bus capsule came out — and
    // the arithmetic that turns those into coordinates is a pure function, so
    // "every port has a dot, none of them share a point" is asserted over the
    // whole catalogue instead of eyeballed on one card.
    const plan = planPortLayout(node.ports, flow);

    const rowCentres = new Map<string, number>();
    for (const { port } of plan.rows) {
      const row = card.querySelector<HTMLElement>(`[data-port-row="${port.id}"]`);
      if (!row) continue;
      const rowRect = row.getBoundingClientRect();
      rowCentres.set(port.id, Math.round((rowRect.top + rowRect.height / 2 - cardRect.top) / zoom));
    }

    // The bus capsule is drawn by CSS, so its dot is measured from the element
    // rather than re-derived from a number that would have to track a
    // stylesheet. Absent before the first paint puts it in the DOM.
    const pillElement = plan.pill
      ? card.querySelector<HTMLElement>(`[data-port-row="${plan.pill.id}"]`)
      : null;
    const pillRect = pillElement?.getBoundingClientRect();

    const ports = Object.fromEntries(
      portPositions(plan, {
        width,
        height,
        rowCentres,
        pill: pillRect
          ? {
              centre: (pillRect.left + pillRect.width / 2 - cardRect.left) / zoom,
              left: (pillRect.left - cardRect.left) / zoom,
            }
          : null,
        pillOverhang: pillRect ? pillRect.height / zoom / 2 : 0,
      }),
    );

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

  const plan = planPortLayout(node.ports, flow);
  const pill = plan.pill;
  // A mount stands for a whole graph, not for one step. That has to be legible
  // before a word is read, hence both a chip and a card treatment: the chip
  // says which kind of thing this is up close, the tinted header band survives
  // the zoom level at which no caption is readable at all.
  const mount = isMountType(definition.id);

  return (
    <div
      ref={cardRef}
      className={clsx(
        'node',
        pill && 'node--has-pill',
        mount && 'node--mount',
        `node--${nodeFamily(definition.id)}`,
      )}
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
            {mount ? (
              <span className="node__chip node__chip--mount" title={MOUNT_BADGE.title}>
                {MOUNT_BADGE.label}
              </span>
            ) : null}
            {definition.scope === 'workflow' ? (
              <span
                className="node__chip"
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
        {plan.rows.map((entry) => (
          <PortRow key={entry.port.id} entry={entry} />
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

/**
 * One labelled port row. `data-port-row` is what the measurement pass finds.
 *
 * The grid row is stated rather than left to CSS auto-placement, which
 * numbers per *cursor* and not per column: with the columns declared and the
 * row implicit, the first output landed beside the last input instead of the
 * first. `planPortLayout` owns the numbering.
 */
function PortRow({ entry }: { entry: PlannedPortRow }) {
  const { port, anchor, row } = entry;
  const workbench = useWorkbench();
  const portType = workbench.registry.portType(port.type);
  const glyph = resolveIcon(portType.iconId);

  return (
    <span
      className={clsx(
        'node__port',
        `node__port--${port.direction}`,
        port.required && 'node__port--required',
        // A binding's dot is on a card edge, not on the flank beside this
        // row, so the row reads as a legend entry rather than as an anchor.
        (anchor === 'top' || anchor === 'bottom' || anchor === 'pill') && 'node__port--offside',
      )}
      style={{ gridRow: row }}
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
