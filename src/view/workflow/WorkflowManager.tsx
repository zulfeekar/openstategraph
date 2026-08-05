import { useCallback, useState } from 'react';
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
import {
  deleteWorkflow,
  listWorkflows,
  loadWorkflow,
  saveWorkflow,
} from '@app/workflowStore';
import { nextId } from '@core/kernel/id';
import './WorkflowManager.css';

interface WorkflowManagerProps {
  open: boolean;
  onClose: () => void;
  onNotify: (message: string) => void;
}

/**
 * Workflow manager panel — create, save, load, and delete workflows.
 *
 * Until the Python backend is implemented, workflows are stored in localStorage.
 * This provides basic CRUD operations for managing multiple workflows.
 */
export function WorkflowManager({ open, onClose, onNotify }: WorkflowManagerProps) {
  const workbench = useWorkbench();
  const controller = useController();
  const [workflows, setWorkflows] = useState(() => listWorkflows(localStorage));
  const [newName, setNewName] = useState('');

  // Refresh the list when the panel opens
  const refreshList = useCallback(() => {
    setWorkflows(listWorkflows(localStorage));
  }, []);

  /**
   * Creates a new blank workflow.
   */
  const handleNewWorkflow = useCallback(() => {
    controller.document.clear();
    const name = newName.trim() || `Workflow ${new Date().getFullYear()}`;
    controller.document.setName(name);
    onNotify(`Created new workflow: ${name}`);
    setNewName('');
    refreshList();
    onClose();
  }, [controller, newName, onNotify, refreshList, onClose]);

  /**
   * Saves the current workflow.
   */
  const handleSave = useCallback(() => {
    const workflowId = getWorkflowId();
    const outcome = saveWorkflow(localStorage, workflowId, workbench.model, workbench.serializer);
    refreshList();
    // Report the real result. Claiming success on a full quota is how a user
    // loses work while being told it is safe.
    onNotify(
      outcome.ok
        ? `Saved: ${workbench.model.name}`
        : `Could not save: ${outcome.reason ?? 'storage unavailable'}`,
    );
  }, [workbench, onNotify, refreshList]);

  /**
   * Loads a workflow from storage.
   */
  const handleLoad = useCallback(
    (id: string) => {
      const json = loadWorkflow(localStorage, id);
      if (!json) {
        onNotify('Failed to load workflow');
        return;
      }
      try {
        controller.document.importJSON(json);
        onNotify(`Loaded: ${workbench.model.name}`);
        onClose();
      } catch (error) {
        onNotify(`Failed to import: ${error instanceof Error ? error.message : 'Unknown error'}`);
      }
    },
    [controller, workbench, onNotify, onClose],
  );

  /**
   * Deletes a workflow from storage.
   */
  const handleDelete = useCallback(
    (id: string, name: string) => {
      if (!confirm(`Delete "${name}"? This cannot be undone.`)) return;
      deleteWorkflow(localStorage, id);
      refreshList();
      onNotify(`Deleted: ${name}`);
    },
    [refreshList, onNotify],
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
            onClick={handleSave}
            icon={<Icon glyph={Save} size="sm" />}
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
                <li key={wf.id} className="workflow-manager__item">
                  <div className="workflow-manager__info">
                    <Icon glyph={FileJson} size="sm" />
                    <span className="workflow-manager__name">{wf.name}</span>
                    <span className="workflow-manager__date">
                      {new Date(wf.savedAt).toLocaleDateString()}
                    </span>
                  </div>
                  <div className="workflow-manager__actions">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleLoad(wf.id)}
                      icon={<Icon glyph={FolderOpen} size="xs" />}
                    >
                      Load
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => handleDelete(wf.id, wf.name)}
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

/**
 * Gets or creates a workflow ID for the current session.
 * Stored in sessionStorage so it persists across reloads but not across tabs.
 */
function getWorkflowId(): string {
  let id = sessionStorage.getItem('dyflow-current-workflow-id');
  if (!id) {
    id = nextId('workflow', 'current');
    sessionStorage.setItem('dyflow-current-workflow-id', id);
  }
  return id;
}
