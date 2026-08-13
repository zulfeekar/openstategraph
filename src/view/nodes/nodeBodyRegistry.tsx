import { useState, type ComponentType } from 'react';
import Markdown from 'react-markdown';
import { Expand, Minimize2 } from 'lucide-react';
import { Icon, IconButton } from '@design/primitives';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { INodeDefinition } from '@core/model/contracts/node';
import { MARKDOWN_COMPONENTS, MARKDOWN_PLUGINS } from '@view/common/RichText';
import { FieldRenderer } from './FieldRenderer';
import { compositionBody } from './CompositionBody';
import { MOUNT_TYPES } from './mountKind';
import { KnowledgeBody } from './KnowledgeBody';
import { SqlSchemaBody } from './SqlSchemaBody';
import { intentBody } from './IntentBody';
import { liveInputValue } from './liveInputValue';

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
  const text =
    typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value, null, 2);

  if (!text) {
    return <div className="node__result-empty">Run the workflow to see the result here.</div>;
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
        <Markdown remarkPlugins={MARKDOWN_PLUGINS} components={MARKDOWN_COMPONENTS}>
          {text}
        </Markdown>
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
          <Markdown remarkPlugins={MARKDOWN_PLUGINS} components={MARKDOWN_COMPONENTS}>
            {notes}
          </Markdown>
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
        <Markdown remarkPlugins={MARKDOWN_PLUGINS} components={MARKDOWN_COMPONENTS}>
          {body}
        </Markdown>
      ) : (
        <span className="node__note-placeholder">Double-click to write a note…</span>
      )}
    </div>
  );
}

/**
 * The entry Input's body: the question the **run** is carrying, when that is
 * not the question the file holds (ticket 34).
 *
 * Above the editable field rather than replacing it, deliberately. The two are
 * different facts — what this document says, and what is happening right now —
 * and a card that showed only one of them is how the bug read as correct for
 * so long. Read-only, because a run is a record; the field below stays the
 * only editable thing on the card.
 */
function LiveInputBody({ node }: NodeBodyProps) {
  const live = liveInputValue(node.runtime.output, String(node.data['prompt'] ?? ''));
  if (live === null) return null;

  return (
    <div className="node__live-input">
      <span className="node__live-input-label">This run is asking</span>
      <span className="node__live-input-value">{live}</span>
    </div>
  );
}

/** Registered here so the map is populated before the first card renders. */
registerNodeBody('output.formatted', FormattedOutputBody);
registerNodeBody('input.text', LiveInputBody);
// The mounts, driven from the one declaration of which types are mounts —
// the same map `NodeCard` badges from, so a card can never be badged as
// holding a graph while showing no composition (or the reverse).
for (const typeId of MOUNT_TYPES) {
  registerNodeBody(typeId, compositionBody());
}
registerNodeBody('annotate.group', GroupBody);
registerNodeBody('annotate.note', NoteBody);
registerNodeBody('tool.knowledge-lookup', KnowledgeBody);
// The schema tool's card shows what it can reach instead of a table control
// that never reached the runtime — see `SqlSchemaBody`.
registerNodeBody('tool.chinook-get-schema', SqlSchemaBody);
// The two node types whose instruction was invisible. A Router shows its
// `rules` and a Grader its `criteria` on the card already; an Agent's
// `systemPrompt` and a Worker's `role` are `onCard: false` — right for a
// paragraph of rules, wrong for "what is this node" — so they get a derived
// one-line intent instead. See `IntentBody`.
registerNodeBody('agent.llm', intentBody('systemPrompt'));
registerNodeBody('orchestrate.worker', intentBody('role'));
