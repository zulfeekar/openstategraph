import { useState, type ComponentType } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Expand, Minimize2 } from 'lucide-react';
import { Icon, IconButton } from '@design/primitives';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { INodeDefinition } from '@core/model/contracts/node';
import { FieldRenderer } from './FieldRenderer';

export interface NodeBodyProps {
  node: AbstractNodeModel;
}

export type NodeBody = ComponentType<NodeBodyProps>;

/**
 * Custom card bodies, keyed by node type.
 *
 * Most nodes need nothing here — their card is generated from the field
 * schema. This registry is the escape hatch for the ones whose body *is* the
 * point: a rendered result, a group's notes. Keeping it a registry rather
 * than a conditional in `NodeCard` means a plugin can ship a bespoke body
 * without touching the card.
 */
const BODIES = new Map<string, NodeBody>();

export function registerNodeBody(nodeTypeId: string, body: NodeBody): void {
  BODIES.set(nodeTypeId, body);
}

const EmptyBody: NodeBody = () => null;

export function resolveNodeBody(definition: INodeDefinition): NodeBody {
  return BODIES.get(definition.bodyId ?? definition.id) ?? EmptyBody;
}

/* ================================================================== *
 * Built-in bodies
 * ================================================================== */

/**
 * The output node's body: the rendered result.
 *
 * Renders Markdown with GFM so the tables agents are asked to produce
 * actually come out as tables. Expanding lifts the height cap rather than
 * opening a modal — the value of this node is seeing the result *in place*,
 * next to the graph that produced it.
 */
function FormattedOutputBody({ node }: NodeBodyProps) {
  const [expanded, setExpanded] = useState(false);
  const value = node.runtime.output;
  const text = typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value, null, 2);

  if (!text) {
    return (
      <div className="node__result-empty">
        Run the workflow to see the result here.
      </div>
    );
  }

  return (
    <div className="node__result" style={expanded ? { maxHeight: 'none' } : undefined}>
      <span className="node__expand" data-no-drag>
        <IconButton
          size="xs"
          label={expanded ? 'Collapse result' : 'Expand result'}
          icon={<Icon glyph={expanded ? Minimize2 : Expand} size="xs" />}
          onClick={() => setExpanded((value) => !value)}
        />
      </span>
      <div className="prose">
        <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
      </div>
    </div>
  );
}

/**
 * The container's body: a title and Markdown notes above its children.
 *
 * Both are edited in the inspector, not inline — a text field inside a frame
 * would swallow the drags used to move the frame and everything in it.
 */
function GroupBody({ node }: NodeBodyProps) {
  const title = node.getField<string>('title');
  const notes = node.getField<string>('notes');

  return (
    <>
      {title ? <div className="node__group-title">{title}</div> : null}
      {notes ? (
        <div className="prose">
          <Markdown remarkPlugins={[remarkGfm]}>{notes}</Markdown>
        </div>
      ) : null}
    </>
  );
}

/**
 * A note's body: Markdown, editable in place.
 *
 * Notes are the one node type where inline editing is right — a note exists
 * to be written on, and routing that through the inspector would make the
 * quickest annotation the slowest action on the canvas.
 */
function NoteBody({ node }: NodeBodyProps) {
  const [editing, setEditing] = useState(false);
  const body = node.getField<string>('body');
  const schema = node.definition.fields[0];

  if (editing && schema) {
    return (
      <div
        data-no-drag
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
            setEditing(false);
          }
        }}
      >
        <FieldRenderer nodeId={node.id} schema={schema} data={node.data} />
      </div>
    );
  }

  return (
    <div
      className="prose"
      role="button"
      tabIndex={0}
      onDoubleClick={() => setEditing(true)}
      onKeyDown={(event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          setEditing(true);
        }
      }}
      title="Double-click to edit"
    >
      {body ? (
        <Markdown remarkPlugins={[remarkGfm]}>{body}</Markdown>
      ) : (
        <span className="node__note-placeholder">Double-click to write a note…</span>
      )}
    </div>
  );
}

/** Registered here so the map is populated before the first card renders. */
registerNodeBody('output.formatted', FormattedOutputBody);
registerNodeBody('annotate.group', GroupBody);
registerNodeBody('annotate.note', NoteBody);
