import { useCallback, useEffect, useMemo, useState } from 'react';
import { FileJson, FolderOpen, Plus, Save, Trash2, X } from 'lucide-react';
import {
  Button,
  Field,
  Icon,
  IconButton,
  Panel,
  PanelBody,
  PanelHeader,
  PanelSection,
  TextInput,
} from '@design/primitives';
import { useController, useWorkbench } from '@app/WorkbenchContext';
import { slugify, WorkflowFileClient, type WorkflowSummary } from '@core/runtime/WorkflowFileClient';
import './WorkflowManager.css';

interface WorkflowManagerProps {
  open: boolean;
  onClose: () => void;
  onNotify: (message: string) => void;
}

const CURRENT_SLUG_KEY = 'dyflow-current-workflow-slug';

/**
 * Workflow manager panel — create, save, load, and delete workflows.
 *
 * Backed by `workflows/<slug>/workflow.json` on the Python backend (tickets
 * 10/14/16 — files own the definition), not `localStorage`. The browser
 * cannot write to disk itself, so every save/load/delete here is a request to
 * the backend, same shape as `RuntimeClient`.
 *
 * The slug is frozen at first save and kept for the rest of this browser
 * session (`sessionStorage`, not the model): renaming the workflow afterwards
 * changes its display name, never its directory — the identity ticket 14
 * settled on, because a slug that moves on rename breaks every reference to
 * it and its git history.
 */
export function WorkflowManager({ open, onClose, onNotify }: WorkflowManagerProps) {
  const workbench = useWorkbench();
  const controller = useController();
  const client = useMemo(() => new WorkflowFileClient(), []);
  const [workflows, setWorkflows] = useState<readonly WorkflowSummary[]>([]);
  const [newName, setNewName] = useState('');
  const [busy, setBusy] = useState(false);

  const refreshList = useCallback(async () => {
    const outcome = await client.list();
    if (outcome.ok) setWorkflows(outcome.value);
    else onNotify(`Could not list workflows: ${outcome.error}`);
  }, [client, onNotify]);

  // Fetching eagerly on every app load would mean every session error-toasts
  // if the backend happens to be down — refresh only when the panel opens.
  useEffect(() => {
    if (open) void refreshList();
  }, [open, refreshList]);

  const handleNewWorkflow = useCallback(() => {
    controller.document.clear();
    const name = newName.trim() || `Workflow ${new Date().getFullYear()}`;
    controller.document.setName(name);
    // A fresh workflow has no slug yet — the next save mints one from
    // whatever name it has at that moment.
    sessionStorage.removeItem(CURRENT_SLUG_KEY);
    onNotify(`Created new workflow: ${name}`);
    setNewName('');
    onClose();
  }, [controller, newName, onNotify, onClose]);

  const handleSave = useCallback(async () => {
    const slug = sessionStorage.getItem(CURRENT_SLUG_KEY) || slugify(workbench.model.name);
    setBusy(true);
    const document = JSON.parse(workbench.serializer.toJSONString(workbench.model)) as unknown;
    const outcome = await client.save(slug, workbench.model.name, document);
    setBusy(false);
    if (outcome.ok) {
      sessionStorage.setItem(CURRENT_SLUG_KEY, slug);
      onNotify(`Saved: ${workbench.model.name}`);
      void refreshList();
    } else {
      onNotify(`Could not save: ${outcome.error}`);
    }
  }, [client, workbench, onNotify, refreshList]);

  const handleLoad = useCallback(
    async (slug: string) => {
      setBusy(true);
      const outcome = await client.load(slug);
      setBusy(false);
      if (!outcome.ok) {
        onNotify(`Could not load: ${outcome.error}`);
        return;
      }
      try {
        controller.document.importJSON(JSON.stringify(outcome.value));
        // Continuing to edit and save now updates *this* workflow, not a new one.
        sessionStorage.setItem(CURRENT_SLUG_KEY, slug);
        onNotify(`Loaded: ${workbench.model.name}`);
        onClose();
      } catch (error) {
        onNotify(`Failed to import: ${error instanceof Error ? error.message : 'Unknown error'}`);
      }
    },
    [client, controller, workbench, onNotify, onClose],
  );

  const handleDelete = useCallback(
    async (slug: string, name: string) => {
      if (!confirm(`Delete "${name}"? This cannot be undone.`)) return;
      const outcome = await client.remove(slug);
      if (outcome.ok) {
        if (sessionStorage.getItem(CURRENT_SLUG_KEY) === slug) {
          sessionStorage.removeItem(CURRENT_SLUG_KEY);
        }
        onNotify(`Deleted: ${name}`);
        void refreshList();
      } else {
        onNotify(`Could not delete: ${outcome.error}`);
      }
    },
    [client, onNotify, refreshList],
  );

  if (!open) return null;

  return (
    <Panel side="left" className="workflow-manager" style={{ width: 320 }}>
      <PanelHeader
        title="Workflows"
        actions={
          <IconButton label="Close" icon={<Icon glyph={X} size="sm" />} onClick={onClose} />
        }
      />
      <PanelBody>
        <PanelSection heading="New Workflow">
          <Field label="Name">
            <TextInput
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="My Workflow"
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleNewWorkflow();
              }}
            />
          </Field>
          <Button variant="primary" onClick={handleNewWorkflow} icon={<Icon glyph={Plus} size="sm" />}>
            Create New
          </Button>
        </PanelSection>

        <PanelSection heading="Save Current">
          <Button
            variant="secondary"
            onClick={() => void handleSave()}
            icon={<Icon glyph={Save} size="sm" />}
            disabled={busy}
          >
            Save {workbench.model.name}
          </Button>
        </PanelSection>

        <PanelSection heading="Saved Workflows">
          {workflows.length === 0 ? (
            <p className="workflow-manager__empty">
              No saved workflows yet. Create one above!
            </p>
          ) : (
            <ul className="workflow-manager__list">
              {workflows.map((wf) => (
                <li key={wf.slug} className="workflow-manager__item">
                  <div className="workflow-manager__info">
                    <Icon glyph={FileJson} size="sm" />
                    <span className="workflow-manager__name">{wf.name}</span>
                    <span className="workflow-manager__date">
                      {wf.savedAt ? new Date(wf.savedAt).toLocaleDateString() : ''}
                    </span>
                  </div>
                  <div className="workflow-manager__actions">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => void handleLoad(wf.slug)}
                      icon={<Icon glyph={FolderOpen} size="xs" />}
                    >
                      Load
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => void handleDelete(wf.slug, wf.name)}
                      icon={<Icon glyph={Trash2} size="xs" />}
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </PanelSection>
      </PanelBody>
    </Panel>
  );
}
