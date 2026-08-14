import { useCallback, useMemo } from 'react';
import { CircleAlert, Info, MousePointer2, TriangleAlert, Trash2 } from 'lucide-react';
import {
  Badge,
  Button,
  Field,
  Icon,
  Panel,
  PanelBody,
  PanelEmpty,
  PanelHeader,
  PanelSection,
  StatusDot,
  TextInput,
  type StatusTone,
} from '@design/primitives';
import { groupFieldsForInspector, validateFields } from '@core/model/contracts/fields';
import { describeEdge } from '@core/model/edgeDescription';
import { LockedPromptSections } from './LockedPromptSections';
import { useDraftValue } from '@view/hooks/useDraftValue';
import type { Diagnostic } from '@core/validation/WorkflowValidator';
import {
  useController,
  useNode,
  usePaperController,
  useSelection,
  useWorkbench,
  useWorkflowVersion,
} from '@app/WorkbenchContext';
import { FieldRenderer } from '@view/nodes/FieldRenderer';
import './Inspector.css';

/**
 * The property panel.
 *
 * Three modes, chosen by what is selected: a node's full configuration, a
 * link, or — with nothing selected — the document's health. That last one is
 * the useful one most of the time, and a panel that only says "nothing
 * selected" wastes a third of the window.
 *
 * **Link is the third mode, and its absence was ticket 24.** Clicking a link
 * always did select it — the gesture reached `SelectionModel` and the canvas
 * put `is-selected` on the link. But the panel had only two modes, so a
 * selected link fell through to *"Nothing selected · Click a node to edit
 * it"*: the one channel that could confirm the selection denied it, while the
 * shortcuts drawer advertised "Delete selection ⌫" for a selection nobody
 * could believe they had made. The reported symptom was "an edge can be drawn
 * but never removed"; the cause was a missing panel mode, not a missing
 * gesture.
 *
 * Fields are rendered from the same schema the card uses. The card shows the
 * few marked `onCard`; this shows everything.
 */
export function Inspector() {
  const { nodes, edges } = useSelection();
  const singleNode = nodes.length === 1 && edges.length === 0 ? nodes[0] : null;
  const singleEdge = edges.length === 1 && nodes.length === 0 ? edges[0] : null;

  return (
    <Panel side="right" className="inspector" style={{ width: 'var(--layout-inspector-width)' }}>
      {singleNode ? (
        <NodeInspector nodeId={singleNode} />
      ) : singleEdge ? (
        <EdgeInspector edgeId={singleEdge} />
      ) : (
        <WorkflowInspector count={nodes.length + edges.length} />
      )}
    </Panel>
  );
}

/**
 * The link mode.
 *
 * Deliberately small: a link has no configuration to edit, so the panel's
 * whole job is to *confirm what is selected* and to offer the one action the
 * canvas could not discover — removal, routed through the controller so it is
 * undoable like every other edit.
 */
function EdgeInspector({ edgeId }: { edgeId: string }) {
  const workbench = useWorkbench();
  const controller = useController();
  // A link's description depends on its endpoints' titles and ports, so any
  // document change can move it.
  const version = useWorkflowVersion();
  const described = useMemo(
    () => describeEdge(workbench.model, edgeId),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [workbench, edgeId, version],
  );

  if (!described) {
    return (
      <>
        <PanelHeader bordered title="Link" />
        <PanelBody>
          <PanelEmpty
            glyph={MousePointer2}
            title="Link removed"
            body="That link is no longer in the workflow."
          />
        </PanelBody>
      </>
    );
  }

  return (
    <>
      <PanelHeader bordered title="Link" />
      <PanelBody>
        <PanelSection heading="Connection">
          <div className="inspector__link-end">
            <span className="inspector__link-node">{described.sourceNode}</span>
            <Badge tone="neutral">{described.sourcePort}</Badge>
          </div>
          <p className="inspector__description" aria-hidden="true">
            ↓
          </p>
          <div className="inspector__link-end">
            <span className="inspector__link-node">{described.targetNode}</span>
            <Badge tone="neutral">{described.targetPort}</Badge>
          </div>
          <p className="inspector__description">
            Carries <strong>{described.type}</strong>.
          </p>
        </PanelSection>

        <PanelSection>
          <Button
            variant="danger"
            icon={<Icon glyph={Trash2} size="sm" />}
            onClick={() => controller.edges.disconnect([edgeId])}
          >
            Remove link
          </Button>
          <p className="inspector__description">
            Or press ⌫. Removing a link is undoable, and both nodes stay where they are.
          </p>
        </PanelSection>
      </PanelBody>
    </>
  );
}

function NodeInspector({ nodeId }: { nodeId: string }) {
  const node = useNode(nodeId);
  const controller = useController();
  const workbench = useWorkbench();

  if (!node) return <PanelEmpty title="Node not found" />;

  const definition = node.definition;
  // Sections derive from the schema itself (group/advanced, ticket 38) so a
  // node's declaration decides its own presentation — nothing per-panel.
  const fieldGroups = groupFieldsForInspector(definition.fields);
  const errors = validateFields(definition.fields, node.data);
  const status = node.runtime.status;
  const tone: StatusTone = status === 'idle' ? 'ready' : status;

  return (
    <>
      <PanelHeader bordered title={definition.label} />
      <PanelBody>
        <PanelSection heading="Identity">
          <Field label="Name">
            <NodeTitleInput nodeId={node.id} title={node.title} placeholder={definition.label} />
          </Field>
          <p className="inspector__description">{definition.description}</p>
        </PanelSection>

        <LockedPromptSections nodeType={definition.id} />

        {fieldGroups.map((group) => (
          <PanelSection key={group.heading} heading={group.heading}>
            {group.fields.map((schema) => (
              <FieldRenderer
                key={schema.key}
                nodeId={node.id}
                schema={schema}
                data={node.data}
                {...(errors[schema.key] ? { error: errors[schema.key] } : {})}
              />
            ))}
            {group.advanced.length > 0 ? (
              // Native disclosure: collapsed by default, keyboard-accessible
              // for free, and open state is fine to lose on re-render.
              <details className="inspector__advanced">
                <summary className="inspector__advanced-summary">Advanced</summary>
                {group.advanced.map((schema) => (
                  <FieldRenderer
                    key={schema.key}
                    nodeId={node.id}
                    schema={schema}
                    data={node.data}
                    {...(errors[schema.key] ? { error: errors[schema.key] } : {})}
                  />
                ))}
              </details>
            ) : null}
          </PanelSection>
        ))}

        {node.ports.length > 0 ? (
          <PanelSection heading="Ports">
            {node.ports.map((port) => {
              const connections = workbench.model
                .edgesOf(node.id)
                .filter((edge) =>
                  port.direction === 'in'
                    ? edge.target.portId === port.id
                    : edge.source.portId === port.id,
                ).length;
              return (
                <div key={port.id} className="inspector__port">
                  <span className="inspector__port-name">{port.label}</span>
                  <Badge tone={connections > 0 ? 'success' : 'neutral'} numeric>
                    {connections === 0 ? 'not wired' : `${connections}`}
                  </Badge>
                </div>
              );
            })}
          </PanelSection>
        ) : null}

        <PanelSection heading="Last run">
          <div className="inspector__status">
            <StatusDot tone={tone} />
            <span>{describeStatus(status)}</span>
            {node.runtime.tokens > 0 ? (
              <Badge numeric>{node.runtime.tokens.toLocaleString()} tok</Badge>
            ) : null}
            {node.runtime.durationMs != null ? (
              <Badge numeric>{node.runtime.durationMs} ms</Badge>
            ) : null}
          </div>
          {node.runtime.error ? <p className="inspector__error">{node.runtime.error}</p> : null}
          {node.runtime.log.length > 0 ? (
            <ol className="inspector__log">
              {node.runtime.log.map((line, index) => (
                <li key={`${index}-${line}`}>{line}</li>
              ))}
            </ol>
          ) : null}
        </PanelSection>

        <PanelSection>
          <Button
            variant="danger"
            icon={<Icon glyph={Trash2} size="sm" />}
            onClick={() =>
              node.kind === 'container'
                ? controller.nodes.deleteTree(node.id)
                : controller.nodes.delete([node.id])
            }
          >
            Delete node
          </Button>
        </PanelSection>
      </PanelBody>
    </>
  );
}

function WorkflowInspector({ count }: { count: number }) {
  const workbench = useWorkbench();
  const controller = useController();
  const paper = usePaperController();
  // Diagnostics are derived from the whole document, so they must be
  // recomputed on any change rather than memoised on a narrow dependency.
  const version = useWorkflowVersion();
  const diagnostics = useMemo(
    () => controller.document.diagnostics(),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [controller, version],
  );

  // A canvas with nothing on it has no problems and is not ready — those are
  // different statements, and the badge used to conflate them.
  const isEmpty = workbench.model.nodes().length === 0;

  const errors = diagnostics.filter((d) => d.severity === 'error');
  const warnings = diagnostics.filter((d) => d.severity === 'warning');
  const infos = diagnostics.filter((d) => d.severity === 'info');

  return (
    <>
      <PanelHeader bordered title="Workflow" />
      <PanelBody>
        <PanelSection heading="Document">
          <Field label="Name">
            <WorkflowNameInput name={workbench.model.name} />
          </Field>
          <div className="inspector__stats">
            <span>
              {workbench.model.nodeCount} node{workbench.model.nodeCount === 1 ? '' : 's'}
            </span>
            <span>
              {workbench.model.edgeCount} link{workbench.model.edgeCount === 1 ? '' : 's'}
            </span>
          </div>
        </PanelSection>

        <PanelSection
          heading="Diagnostics"
          aside={
            errors.length > 0 ? (
              <Badge tone="danger" numeric>
                {errors.length}
              </Badge>
            ) : diagnostics.length === 0 && !isEmpty ? (
              <Badge tone="success">ready</Badge>
            ) : undefined
          }
        >
          {isEmpty ? (
            // "Ready to run" on a canvas with nothing on it is the same class
            // of false green as the accessibility check's was: technically
            // "no problems found", and untrue (reviews-2026-08-14 ticket 06).
            <p className="inspector__description">
              Nothing to run yet — drag a node in from the palette to start.
            </p>
          ) : diagnostics.length === 0 ? (
            <p className="inspector__description">
              Everything checks out — this workflow is ready to run.
            </p>
          ) : (
            [...errors, ...warnings, ...infos].map((diagnostic, index) => (
              <DiagnosticRow
                key={`${diagnostic.code}-${index}`}
                diagnostic={diagnostic}
                onSelect={() => {
                  if (!diagnostic.nodeId) return;
                  controller.selectionActions.selectNodes([diagnostic.nodeId]);
                  paper?.viewport.fit(controller.selectionActions.bounds());
                }}
              />
            ))
          )}
        </PanelSection>

        {count > 1 ? (
          <PanelSection heading="Selection">
            <p className="inspector__description">
              {count} items selected. Select a single node to edit its settings, or a single link to
              inspect and remove it.
            </p>
          </PanelSection>
        ) : (
          <PanelSection>
            <PanelEmpty
              glyph={MousePointer2}
              title="Nothing selected"
              body="Click a node to edit it, click a link to inspect or remove it, or drag on empty canvas to select several."
            />
          </PanelSection>
        )}
      </PanelBody>
    </>
  );
}

function DiagnosticRow({ diagnostic, onSelect }: { diagnostic: Diagnostic; onSelect: () => void }) {
  const glyph =
    diagnostic.severity === 'error'
      ? CircleAlert
      : diagnostic.severity === 'warning'
        ? TriangleAlert
        : Info;

  return (
    <button
      type="button"
      className={`inspector__diagnostic inspector__diagnostic--${diagnostic.severity}`}
      onClick={onSelect}
      disabled={!diagnostic.nodeId}
    >
      <Icon glyph={glyph} size="sm" />
      <span>{diagnostic.message}</span>
    </button>
  );
}

function describeStatus(status: string): string {
  switch (status) {
    case 'running':
      return 'Running…';
    case 'success':
      return 'Completed';
    case 'error':
      return 'Failed';
    case 'warning':
      return 'Completed with warnings';
    default:
      return 'Not run yet';
  }
}

/**
 * The node's display name.
 *
 * Its own component so `useDraftValue` has somewhere to live — and because the
 * draft must reset when the selection moves to a different node, which a `key`
 * on `nodeId` gives for free.
 */
function NodeTitleInput({
  nodeId,
  title,
  placeholder,
}: {
  nodeId: string;
  title: string;
  placeholder: string;
}) {
  const controller = useController();
  const commit = useCallback(
    (value: string) => controller.nodes.setTitle(nodeId, value),
    [controller, nodeId],
  );
  const draft = useDraftValue(title, commit);

  return (
    <TextInput
      key={nodeId}
      value={draft.value}
      placeholder={placeholder}
      onChange={(event) => draft.onChange(event.target.value)}
      onBlur={draft.onBlur}
    />
  );
}

/** The document's name. Same buffering problem — `setName` also normalises. */
function WorkflowNameInput({ name }: { name: string }) {
  const controller = useController();
  const commit = useCallback((value: string) => controller.document.setName(value), [controller]);
  const draft = useDraftValue(name, commit);

  return (
    <TextInput
      value={draft.value}
      onChange={(event) => draft.onChange(event.target.value)}
      onBlur={draft.onBlur}
    />
  );
}
