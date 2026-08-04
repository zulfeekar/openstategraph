import { useMemo } from 'react';
import {
  CircleAlert,
  Info,
  MousePointer2,
  TriangleAlert,
  Trash2,
} from 'lucide-react';
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
import { isInInspector, validateFields } from '@core/model/contracts/fields';
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
 * Two modes, chosen by what is selected: a node's full configuration, or —
 * with nothing selected — the document's health. That second mode is the
 * useful one most of the time, and a panel that only says "nothing selected"
 * wastes a third of the window.
 *
 * Fields are rendered from the same schema the card uses. The card shows the
 * few marked `onCard`; this shows everything.
 */
export function Inspector() {
  const { nodes, edges } = useSelection();
  const single = nodes.length === 1 && edges.length === 0 ? nodes[0] : null;

  return (
    <Panel side="right" className="inspector" style={{ width: 'var(--layout-inspector-width)' }}>
      {single ? <NodeInspector nodeId={single} /> : <WorkflowInspector count={nodes.length + edges.length} />}
    </Panel>
  );
}

function NodeInspector({ nodeId }: { nodeId: string }) {
  const node = useNode(nodeId);
  const controller = useController();
  const workbench = useWorkbench();

  if (!node) return <PanelEmpty title="Node not found" />;

  const definition = node.definition;
  const fields = definition.fields.filter(isInInspector);
  const errors = validateFields(definition.fields, node.data);
  const status = node.runtime.status;
  const tone: StatusTone = status === 'idle' ? 'ready' : status;

  return (
    <>
      <PanelHeader bordered title={definition.label} />
      <PanelBody>
        <PanelSection heading="Identity">
          <Field label="Name">
            <TextInput
              value={node.title}
              placeholder={definition.label}
              onChange={(event) => controller.nodes.setTitle(node.id, event.target.value)}
            />
          </Field>
          <p className="inspector__description">{definition.description}</p>
        </PanelSection>

        {fields.length > 0 ? (
          <PanelSection heading="Configuration">
            {fields.map((schema) => (
              <FieldRenderer
                key={schema.key}
                nodeId={node.id}
                schema={schema}
                data={node.data}
                {...(errors[schema.key] ? { error: errors[schema.key] } : {})}
              />
            ))}
          </PanelSection>
        ) : null}

        {node.ports.length > 0 ? (
          <PanelSection heading="Ports">
            {node.ports.map((port) => {
              const connections = workbench.model.edgesOf(node.id).filter((edge) =>
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
          {node.runtime.error ? (
            <p className="inspector__error">{node.runtime.error}</p>
          ) : null}
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

  const errors = diagnostics.filter((d) => d.severity === 'error');
  const warnings = diagnostics.filter((d) => d.severity === 'warning');
  const infos = diagnostics.filter((d) => d.severity === 'info');

  return (
    <>
      <PanelHeader bordered title="Workflow" />
      <PanelBody>
        <PanelSection heading="Document">
          <Field label="Name">
            <TextInput
              value={workbench.model.name}
              onChange={(event) => controller.document.setName(event.target.value)}
            />
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
            ) : diagnostics.length === 0 ? (
              <Badge tone="success">ready</Badge>
            ) : undefined
          }
        >
          {diagnostics.length === 0 ? (
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
              {count} items selected. Select a single node to edit its settings.
            </p>
          </PanelSection>
        ) : (
          <PanelSection>
            <PanelEmpty
              glyph={MousePointer2}
              title="Nothing selected"
              body="Click a node to edit it, or drag on empty canvas to select several."
            />
          </PanelSection>
        )}
      </PanelBody>
    </>
  );
}

function DiagnosticRow({
  diagnostic,
  onSelect,
}: {
  diagnostic: Diagnostic;
  onSelect: () => void;
}) {
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
