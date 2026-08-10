import { useCallback, useEffect, useMemo, useState } from 'react';
import { FileJson, FolderOpen, Globe, GlobeLock, Plus, Save, Trash2, X } from 'lucide-react';
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
import { useController, useModelEvents, useWorkbench } from '@app/WorkbenchContext';
import { CURRENT_SLUG_KEY, forgetKnownSavedAt, recordKnownSavedAt } from '@app/workflowFileWatch';
import {
  slugify,
  WorkflowFileClient,
  type WorkflowSummary,
} from '@core/runtime/WorkflowFileClient';
import { clearDrillStack } from '@app/drillStack';
import { loadWorkflowIntoEditor } from './loadWorkflowIntoEditor';
import './WorkflowManager.css';

interface WorkflowManagerProps {
  open: boolean;
  onClose: () => void;
  onNotify: (message: string) => void;
}

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
  // `workbench.model.name` is read directly below (not React state), so the
  // "Save current" button's own label went stale the instant a rename
  // happened while this panel stayed open — found live, renaming via the
  // Inspector's Name field with Workflows already open. The rename and the
  // eventual save were both always correct (`handleSave` reads the name
  // fresh at click time); only this button's displayed text lagged. This
  // subscription is the fix — same pattern `useNode` already uses for the
  // model's other mutable fields.
  useModelEvents(['workflow:name']);
  const client = useMemo(() => new WorkflowFileClient(), []);
  const [workflows, setWorkflows] = useState<readonly WorkflowSummary[]>([]);
  const [listError, setListError] = useState<string | null>(null);
  const [newName, setNewName] = useState('');
  const [busy, setBusy] = useState(false);

  const refreshList = useCallback(async (): Promise<readonly WorkflowSummary[]> => {
    const outcome = await client.list();
    if (outcome.ok) {
      setListError(null);
      setWorkflows(outcome.value);
      return outcome.value;
    }
    // State, not just a toast: a toast evaporates, and the stale panel then
    // reads "no workflows" — indistinguishable from a dead runtime (ticket 58).
    setListError(outcome.error);
    return [];
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
    // Same reasoning as a manual load: a brand-new document is not "inside"
    // anything, so there is nothing to go back to.
    clearDrillStack();
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
      const list = await refreshList();
      // This tab's own write — record it as known-good so the file watch
      // never mistakes this save for an external change.
      recordKnownSavedAt(slug, list.find((wf) => wf.slug === slug)?.savedAt);
    } else {
      onNotify(`Could not save: ${outcome.error}`);
    }
  }, [client, workbench, onNotify, refreshList]);

  const handleLoad = useCallback(
    async (slug: string) => {
      setBusy(true);
      // The load itself lives in `loadWorkflowIntoEditor`, shared with the
      // Open affordance on a mount card. Only the panel's own reactions —
      // busy state, toast, closing — stay here.
      const outcome = await loadWorkflowIntoEditor(slug, client, workbench);
      setBusy(false);
      if (!outcome.ok) {
        onNotify(`Could not load: ${outcome.error}`);
        return;
      }
      // Picking a workflow here is a navigation of its own, not a return, so
      // the drill trail goes with it — offering "Back to …" afterwards would
      // point at a parent the user deliberately left.
      clearDrillStack();
      onNotify(`Loaded: ${outcome.value}`);
      onClose();
    },
    [client, workbench, onNotify, onClose],
  );

  // Draft → publish lifecycle (launch-readiness ticket 04): flipping the
  // flag is the deliberate act that puts a workflow on the customer /chat
  // surface (picker + concierge Auto routing). Publishing never rebuilds
  // routing knowledge as a side effect — the toast passes that reminder on.
  const handleSetPublished = useCallback(
    async (slug: string, name: string, published: boolean) => {
      setBusy(true);
      const outcome = await client.setPublished(slug, published);
      setBusy(false);
      if (outcome.ok) {
        onNotify(
          published
            ? `Published: ${name} — now visible in /chat. Rebuild knowledge to update Auto routing.`
            : `Unpublished: ${name} — back to draft, hidden from /chat.`,
        );
        void refreshList();
      } else {
        onNotify(`Could not ${published ? 'publish' : 'unpublish'}: ${outcome.error}`);
      }
    },
    [client, onNotify, refreshList],
  );

  const handleDelete = useCallback(
    async (slug: string, name: string) => {
      if (!confirm(`Delete "${name}"? This cannot be undone.`)) return;
      const outcome = await client.remove(slug);
      if (outcome.ok) {
        if (sessionStorage.getItem(CURRENT_SLUG_KEY) === slug) {
          sessionStorage.removeItem(CURRENT_SLUG_KEY);
        }
        forgetKnownSavedAt(slug);
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
        actions={<IconButton label="Close" icon={<Icon glyph={X} size="sm" />} onClick={onClose} />}
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
          <Button
            variant="primary"
            onClick={handleNewWorkflow}
            icon={<Icon glyph={Plus} size="sm" />}
          >
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
          {/* UX-04. The editor autosaves to browser storage, and nothing on
              screen said where "saved" meant — so a user who cleared site
              data, or opened the app in a different browser, discovered the
              limit by losing work. Stated here, next to the button that makes
              it durable, rather than in a doc nobody reads mid-edit. */}
          <p className="workflow-manager__hint">
            Edits autosave to <strong>this browser only</strong> — they are not on the backend and
            will not follow you to another browser, another machine, or survive clearing site data.
            Saving here writes <code>workflows/&lt;name&gt;/workflow.json</code>, which is the copy
            that lasts.
          </p>
        </PanelSection>

        <PanelSection heading="Saved Workflows">
          {listError ? (
            <div className="workflow-manager__empty" role="alert">
              <p>Runtime unreachable: {listError}</p>
              <Button size="sm" onClick={() => void refreshList()}>
                Retry
              </Button>
            </div>
          ) : workflows.length === 0 ? (
            <p className="workflow-manager__empty">No saved workflows yet. Create one above!</p>
          ) : (
            <ul className="workflow-manager__list">
              {workflows.map((wf) => (
                <li key={wf.slug} className="workflow-manager__item">
                  <div className="workflow-manager__info">
                    <Icon glyph={FileJson} size="sm" />
                    <span className="workflow-manager__name">{wf.name}</span>
                    <span
                      className={
                        wf.published
                          ? 'workflow-manager__badge workflow-manager__badge--published'
                          : 'workflow-manager__badge'
                      }
                      title={
                        wf.published
                          ? 'Visible in the customer /chat picker and Auto routing'
                          : 'Draft — not visible in /chat until published'
                      }
                    >
                      {wf.published ? 'Published' : 'Draft'}
                    </span>
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
                      variant="ghost"
                      size="sm"
                      disabled={busy}
                      onClick={() => void handleSetPublished(wf.slug, wf.name, !wf.published)}
                      icon={<Icon glyph={wf.published ? GlobeLock : Globe} size="xs" />}
                    >
                      {wf.published ? 'Unpublish' : 'Publish'}
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
