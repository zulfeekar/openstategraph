import { useState, type ComponentType } from 'react';
import Markdown from 'react-markdown';
import { Expand, Minimize2 } from 'lucide-react';
import { Icon, IconButton } from '@design/primitives';
import { Registry } from '@core/kernel/Registry';
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

/** One card body, under the node type (or `bodyId`) it renders. */
export interface NodeBodyEntry {
  readonly id: string;
  readonly body: NodeBody;
}

const EmptyBody: NodeBody = () => null;

/**
 * Custom card bodies, keyed by node type — the seventh of CLAUDE.md's seven
 * extension points, and now a `Registry<T>` like the other six.
 *
 * Most nodes need nothing here: their card is generated from the field
 * schema. This is the escape hatch for the ones whose body *is* the point —
 * a rendered result, a group's notes — so a plugin ships a bespoke body
 * without touching `NodeCard`.
 *
 * **Why it was a `Map`, and what that cost** (framework-packaging ticket 12).
 * The hatch had never been used — every body was registered inside this file
 * — so its shape had never been felt. `Map.set` overwrites silently, which
 * means a plugin could replace a built-in card body with no error and no way
 * for anyone to notice; `Registry.register` throws on a duplicate id and
 * `upsert` is the way to say you meant it. It also brings `list()`, so the
 * set can be enumerated and asserted, and change notification.
 *
 * **Why it is owned here rather than by the `Workbench`**, which is where the
 * ticket's first option put it and where four of the other six live. A card
 * body is a React component. `Workbench` is the app's composition root and is
 * deliberately framework-free — "nothing in this class is React-aware" — and
 * buying symmetry with a `ComponentType` on its public surface would be
 * paying in the boundary to make a list read evenly. The precedent is already
 * there: canvas features are a `Registry<IPaperFeature>` on `PaperController`,
 * not on the `Workbench`, for exactly the same reason one layer down. What a
 * registry is worth is its behaviour, not its address.
 */
export function createNodeBodyRegistry(): Registry<NodeBodyEntry> {
  const registry = new Registry<NodeBodyEntry>('card bodies');
  for (const [id, body] of BUILT_IN_BODIES) registry.register({ id, body });
  return registry;
}

/**
 * Registers a card body on the shipped registry. Throws on a duplicate id —
 * use `nodeBodies.upsert` to replace a built-in on purpose.
 */
export function registerNodeBody(nodeTypeId: string, body: NodeBody): void {
  nodeBodies.register({ id: nodeTypeId, body });
}

export function resolveNodeBody(
  definition: INodeDefinition,
  registry: Registry<NodeBodyEntry> = nodeBodies,
): NodeBody {
  return registry.get(definition.bodyId ?? definition.id)?.body ?? EmptyBody;
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
      {/* `rich-text--narrow` (`stable-beta-public/15`): a node card is ~216px, and
          `.prose`'s table rules are written for a grid that fits — an index column
          at `width: 1%; white-space: nowrap` took 170px of that and left the text
          beside it 212px tall. Every `.prose` here is a card body, so all three
          carry it; the wide surfaces keep `RichText.css`'s own rule. */}
      <div className="prose rich-text--narrow">
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
        <div className="prose rich-text--narrow">
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
      className="prose rich-text--narrow"
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

/**
 * What ships. A table rather than a run of `register` calls at module load,
 * so that `createNodeBodyRegistry` can hand a *fresh* populated registry to
 * anyone who asks — a test, or a second editor instance — instead of there
 * being exactly one, mutated in place, for the lifetime of the module.
 */
const BUILT_IN_BODIES: readonly (readonly [string, NodeBody])[] = [
  ['output.formatted', FormattedOutputBody],
  ['input.text', LiveInputBody],
  // The mounts, driven from the one declaration of which types are mounts —
  // the same map `NodeCard` badges from, so a card can never be badged as
  // holding a graph while showing no composition (or the reverse).
  ...MOUNT_TYPES.map((typeId) => [typeId, compositionBody()] as const),
  ['annotate.group', GroupBody],
  ['annotate.note', NoteBody],
  ['tool.knowledge-lookup', KnowledgeBody],
  // The schema tool's card shows what it can reach instead of a table control
  // that never reached the runtime — see `SqlSchemaBody`.
  ['tool.chinook-get-schema', SqlSchemaBody],
  // The two node types whose instruction was invisible. A Router shows its
  // `rules` and a Grader its `criteria` on the card already; an Agent's
  // `systemPrompt` and a Worker's `role` are `onCard: false` — right for a
  // paragraph of rules, wrong for "what is this node" — so they get a derived
  // one-line intent instead. See `IntentBody`.
  ['agent.llm', intentBody('systemPrompt')],
  ['orchestrate.worker', intentBody('role')],
];

/**
 * The one the editor renders from.
 *
 * A module-level instance is what a React component tree can reach without
 * threading a collaborator through every card; `createNodeBodyRegistry`
 * exists so a test never has to assert against whatever a previous test
 * registered here. Declared last because the table above is a `const` and
 * this line runs at module load.
 */
export const nodeBodies = createNodeBodyRegistry();
