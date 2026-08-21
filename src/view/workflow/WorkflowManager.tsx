import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  Copy,
  FileJson,
  FolderOpen,
  Globe,
  GlobeLock,
  Plus,
  Save,
  Trash2,
  X,
} from 'lucide-react';
import {
  Button,
  Field,
  Icon,
  IconButton,
  Panel,
  PanelBody,
  PanelHeader,
  PanelSection,
  Select,
  TextInput,
} from '@design/primitives';
import { useController, useModelEvents, useWorkbench } from '@app/WorkbenchContext';
import { forgetKnownSavedAt } from '@app/workflowFileWatch';
import { clearOpenSlug, getOpenSlug } from '@app/openWorkflow';
import {
  WorkflowFileClient,
  type WorkflowExample,
  type WorkflowSummary,
  type WorkflowTemplate,
} from '@core/runtime/WorkflowFileClient';
import { clearDrillStack } from '@app/drillStack';
import { loadWorkflowIntoEditor } from './loadWorkflowIntoEditor';
import { saveMessage, saveSucceeded, saveWorkflow } from './saveWorkflow';
import {
  BLANK_TEMPLATE,
  createNewWorkflow,
  discardDeclined,
  discardWarning,
} from './createNewWorkflow';
import {
  deleteConfirmation,
  deletedMessage,
  publishedMessage,
  unpublishedMessage,
} from './consequences';
import { examplesShelfStartsOpen, rememberExamplesShelf } from './examplesShelf';
import { examplesShelfToggleLabel } from './examplesJourney';
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
 * The slug is **minted by the backend** at first save and frozen from then on
 * (`@app/openWorkflow`, which keeps it in `sessionStorage` and in the address
 * bar): renaming the workflow afterwards changes its display name, never its
 * directory — the identity ticket 14 settled on, because a slug that moves on
 * rename breaks every reference to it and its git history.
 *
 * Minting used to happen here, with a client-side `slugify(name)`, and that
 * was silent data loss (ticket 20): a second workflow named "My Workflow" was
 * PUT straight onto the first one's `my-workflow` directory. A name is not an
 * identity, and only the process that can see `workflows/` knows which
 * identities are free.
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
  // The scaffold's own templates (scale-and-adopt ticket 04), fetched — never
  // a second copy of the list. Empty is a legitimate state: a runtime that is
  // down or too old costs the picker, never the blank canvas.
  const [templates, setTemplates] = useState<readonly WorkflowTemplate[]>([]);
  const [template, setTemplate] = useState(BLANK_TEMPLATE);
  // The shipped gallery (workflow-gallery ticket 07). A separate shelf from
  // "Saved Workflows" on purpose: these are not in this project, they live in
  // the installed package, and they appear in the list above only once the
  // user has taken a copy. Empty is legitimate, exactly as for templates.
  const [examples, setExamples] = useState<readonly WorkflowExample[]>([]);
  // …and it starts **closed** (install-experience T9). The reasoning, and why
  // this is a gesture rather than a packaging change, is in `examplesShelf.ts`.
  const [examplesOpen, setExamplesOpen] = useState(examplesShelfStartsOpen);
  const toggleExamples = useCallback(() => {
    setExamplesOpen((wasOpen) => {
      rememberExamplesShelf(!wasOpen);
      return !wasOpen;
    });
  }, []);

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

  // The template names and their one-liners, for the picker. The *document* is
  // fetched again at apply time with the name the user actually typed, because
  // a template may put that name inside the document (the team template titles
  // its supervisor "<name> Lead") and the editor's result must be the CLI's,
  // not an approximation of it. Failure is silent by design: no picker is a
  // smaller loss than an error toast every time this panel opens.
  useEffect(() => {
    if (!open) return;
    void client.templates('New Workflow').then((outcome) => {
      if (outcome.ok) setTemplates(outcome.value);
    });
  }, [open, client]);

  // The gallery, same policy: fetched when the panel opens, silent on failure.
  // No `name` argument, because nothing is rendered into an example — it is
  // copied byte for byte, which is what makes its own AGENTS.md true of it.
  useEffect(() => {
    if (!open) return;
    void client.examples().then((outcome) => {
      if (outcome.ok) setExamples(outcome.value);
    });
  }, [open, client]);

  // …and stay current while it is open. A second tab (or `/chat`, or a script)
  // publishing, saving or deleting a workflow makes this list wrong the moment
  // it happens; the backend's `/api/events` stream says so and this refetches.
  //
  // Deliberately scoped to the open panel: a subscription held for the whole
  // session would keep a connection open for a list nobody is looking at. No
  // new state library and no cache — the refetch this already had is the
  // update. Two known limits, both the backend's: the fan-out is in-process
  // (one worker), and a `workflow.json` hand-edited on disk emits nothing.
  useEffect(() => {
    if (!open) return;
    return client.watchCatalogue(() => void refreshList());
  }, [open, client, refreshList]);

  const handleNewWorkflow = useCallback(async () => {
    // The same guard the toolbar's New uses, and for the same reason: this
    // replaces the open document, and a never-saved one exists nowhere else.
    const subject = {
      name: workbench.model.name,
      nodeCount: workbench.model.nodeCount,
      saved: getOpenSlug() !== null,
    };
    const warning = discardWarning(subject);
    if (warning !== null && !confirm(warning)) {
      // Same sentence as the toolbar's New, from the same function — one
      // refusal with one voice, on whichever surface asked (`say-it-on-the-surface` 02).
      onNotify(discardDeclined(subject));
      return;
    }

    setBusy(true);
    // The act itself is `createNewWorkflow`, shared with the toolbar — the
    // panel keeps only what is its own: the busy state, the toast, the form.
    const outcome = await createNewWorkflow({ name: newName, template }, controller, client);
    setBusy(false);
    if (!outcome.ok) {
      onNotify(outcome.error);
      return;
    }
    onNotify(
      outcome.value.template === null
        ? `Created new workflow: ${outcome.value.name}`
        : `Created new workflow: ${outcome.value.name} (from ${outcome.value.template})`,
    );
    setNewName('');
    onClose();
  }, [client, controller, workbench, newName, template, onNotify, onClose]);

  // The act itself is `saveWorkflow` — shared with the toolbar's Save
  // (`say-it-on-the-surface` 01), for the same reason `createNewWorkflow` is
  // shared with the toolbar's New: a second entry point is a promotion of this
  // panel, never a second implementation of it. What stays here is the
  // presentation — the busy flag, the toast, and refreshing the list this
  // panel is showing.
  const handleSave = useCallback(async () => {
    setBusy(true);
    const outcome = await saveWorkflow({ client, workbench, confirm: (m) => confirm(m) });
    setBusy(false);
    const message = saveMessage(outcome);
    if (message !== null) onNotify(message);
    if (saveSucceeded(outcome)) await refreshList();
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
      onNotify(
        outcome.value.restoredDraft
          ? `Loaded: ${outcome.value.name} — with your unsaved edits from this browser, not the saved file.`
          : `Loaded: ${outcome.value.name}`,
      );
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
        // The wording is `consequences.ts`, shared and tested: what changed,
        // not merely which state it landed in.
        onNotify(published ? publishedMessage(name) : unpublishedMessage(name));
        void refreshList();
      } else {
        onNotify(`Could not ${published ? 'publish' : 'unpublish'}: ${outcome.error}`);
      }
    },
    [client, onNotify, refreshList],
  );

  const handleDuplicate = useCallback(
    async (slug: string) => {
      setBusy(true);
      // No name argument: the backend defaults to `<original> (copy)`, and it
      // is the side that already knows the original's name.
      const outcome = await client.duplicate(slug);
      setBusy(false);
      if (!outcome.ok) {
        onNotify(`Could not duplicate: ${outcome.error}`);
        return;
      }
      // The minted slug is said out loud for the same reason a create says
      // it: it is the one thing the user could not have predicted, and two
      // rows now share a very similar name.
      onNotify(`Copied to: ${outcome.value.name} (${outcome.value.slug})`);
      // **Deliberately does not open the copy.** Duplicate is most often the
      // first half of "keep this one, try something on a copy", and swapping
      // the canvas out from under someone who was mid-thought is the kind of
      // help nobody asks for. The toast names it; Load opens it.
      void refreshList();
    },
    [client, onNotify, refreshList],
  );

  // Taking an example is a **copy**, and the copy is severed: from here it is
  // an ordinary package of this project's, and a later `pip install -U` does
  // not reach back into it. The backend does the copying because an example is
  // a package — tests, knowledge, eval fixture, database — and importing its
  // document alone would leave every tool binding pointing at nothing.
  const handleCopyExample = useCallback(
    async (example: WorkflowExample) => {
      setBusy(true);
      const outcome = await client.copyExample(example.slug);
      setBusy(false);
      if (!outcome.ok) {
        onNotify(`Could not copy ${example.name}: ${outcome.error}`);
        return;
      }
      const extra = outcome.value.length - 1;
      onNotify(
        extra > 0
          ? `Copied: ${example.name} — with ${extra} package(s) it mounts. It is a draft in your workflows.`
          : `Copied: ${example.name} — a draft in your workflows.`,
      );
      // Same reasoning as Duplicate: it does not swap the canvas out from
      // under someone mid-thought. The row is in the list above, with Load.
      void refreshList();
    },
    [client, onNotify, refreshList],
  );

  const handleDelete = useCallback(
    async (slug: string, name: string, published: boolean) => {
      // What is lost, before it is lost — a workflow is a folder of real
      // files, and "published" adds a consequence a draft does not have.
      if (!confirm(deleteConfirmation(name, published))) return;
      const outcome = await client.remove(slug);
      if (outcome.ok) {
        // Deleting the workflow this tab has open also takes it out of the
        // URL: leaving `?w=` pointing at a package that no longer exists would
        // turn the next reload into a 404 toast about work the user deleted
        // deliberately.
        if (getOpenSlug() === slug) clearOpenSlug();
        forgetKnownSavedAt(slug);
        onNotify(deletedMessage(name));
        void refreshList();
      } else {
        onNotify(`Could not delete: ${outcome.error}`);
      }
    },
    [client, onNotify, refreshList],
  );

  if (!open) return null;

  return (
    <Panel side="left" className="workflow-manager" style={{ width: 'var(--layout-drawer-width)' }}>
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
                if (e.key === 'Enter') void handleNewWorkflow();
              }}
            />
          </Field>
          {templates.length > 0 && (
            <Field
              label="Start from"
              hint={templates.find((t) => t.name === template)?.summary ?? 'An empty canvas.'}
            >
              <Select
                value={template}
                onValueChange={setTemplate}
                options={[
                  { value: BLANK_TEMPLATE, label: 'Blank canvas' },
                  // The catalogue's own one-liner, not the bare slug. Every
                  // template already ships a `summary` in `index.json` and
                  // nothing rendered it, so the picker read
                  // "minimal / loop / routed-qa / team" — and "loop" alone is
                  // exactly the word the lexicon forbids user-facing, since it
                  // means two different things (reviews-2026-08-14 ticket 06).
                  ...templates.map((template) => ({
                    value: template.name,
                    label: template.summary
                      ? `${template.name} — ${template.summary}`
                      : template.name,
                  })),
                ]}
              />
            </Field>
          )}
          <Button
            variant="primary"
            onClick={() => void handleNewWorkflow()}
            icon={<Icon glyph={Plus} size="sm" />}
            disabled={busy}
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
          {/* UX-04, rewritten when autosave-to-disk landed (the-editor-makes-
              a-real-package ticket 02). This paragraph used to say edits
              autosave to "this browser only", which was true and is now
              false — a saved workflow's edits reach its folder on their own.
              The one case that still needs the button is the one the text
              leads with, because it is the only one where nothing on disk
              exists to write to yet. */}
          <p className="workflow-manager__hint">
            A workflow that has never been saved lives in <strong>this browser only</strong> — save
            it once to give it a folder. After that, edits autosave to{' '}
            <code>workflows/&lt;slug&gt;/workflow.json</code> as you make them, so what is on the
            canvas is what the CLI and the tests run. The browser keeps a draft too, as crash
            recovery. Saving puts the slug in the address bar, so the URL is a link you can send;
            the slug is chosen once, from the name, and a second workflow of the same name gets its
            own.
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
                    <span className="workflow-manager__ident">
                      <span className="workflow-manager__name">{wf.name}</span>
                      {/* The slug, on every row, because the name is a label
                          and this is the identity. Two documents saved without
                          renaming both read "AI Workflow" with the same badge
                          and the same date, and nothing in the row — or in the
                          DOM — told them apart, including the delete
                          confirmation (the-editor-makes-a-real-package 07).
                          Shown always rather than only on a collision: the
                          Packages palette already prints it unconditionally
                          for the same reason, and a slug that appears only
                          sometimes is a row that changes shape under you. */}
                      <code className="workflow-manager__slug" title={`workflows/${wf.slug}/`}>
                        {wf.slug}
                      </code>
                    </span>
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
                    {/* **Open**, not "Load" (ticket 06). This is a list of
                        workflows and the verb for picking one is the verb the
                        owner's QA pass used; "load" describes what the editor
                        does, from the editor's point of view. */}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => void handleLoad(wf.slug)}
                      icon={<Icon glyph={FolderOpen} size="xs" />}
                    >
                      Open
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={busy}
                      // The rule taught where the verb is, rather than after
                      // the fact: a draft never appears in /chat.
                      title={
                        wf.published
                          ? 'Back to draft — out of the /chat picker. Nothing is deleted.'
                          : 'Put it in the /chat picker for customers. It is a draft until you do.'
                      }
                      onClick={() => void handleSetPublished(wf.slug, wf.name, !wf.published)}
                      icon={<Icon glyph={wf.published ? GlobeLock : Globe} size="xs" />}
                    >
                      {wf.published ? 'Unpublish' : 'Publish'}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={busy}
                      title={`Copy "${wf.name}" and everything in its folder to a new workflow`}
                      onClick={() => void handleDuplicate(wf.slug)}
                      icon={<Icon glyph={Copy} size="xs" />}
                    >
                      Duplicate
                    </Button>
                    {/* Labelled, like the other three. The one destructive
                        verb in the row was the only one wearing no word —
                        a bare bin icon beside three captioned buttons reads
                        as decoration until it is pressed once. */}
                    <Button
                      variant="danger"
                      size="sm"
                      title={`Delete "${wf.name}" and everything in its folder`}
                      onClick={() => void handleDelete(wf.slug, wf.name, wf.published)}
                      icon={<Icon glyph={Trash2} size="xs" />}
                    >
                      Delete
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </PanelSection>

        {examples.length > 0 && (
          <PanelSection heading="Examples">
            {/* Ticket 23. This used to be the digit `23` on a ghost button in
                the section's `aside` — which says how much is behind the
                control and nothing whatever about why anyone would press it,
                and which had about 40px to say it in. The count stays, because
                a shelf that will not admit how much it is hiding is a control
                nobody has a reason to open; what is new is that it is now a
                sentence with the three verbs in it, across the full width of
                the panel, where a first-time reader is actually looking. */}
            <Button
              variant="ghost"
              size="sm"
              className="workflow-manager__invitation"
              title={
                examplesOpen
                  ? 'Hide the shipped examples'
                  : `Show the ${examples.length} shipped examples`
              }
              aria-expanded={examplesOpen}
              onClick={toggleExamples}
              icon={<Icon glyph={examplesOpen ? ChevronDown : ChevronRight} size="xs" />}
            >
              {examplesShelfToggleLabel(examples.length, examplesOpen)}
            </Button>
            <p className="workflow-manager__hint">
              Worked examples that ship inside OpenStateGraph — one per pattern the canvas can
              express. They are <strong>not in this project</strong> until you copy one; a copy is
              yours from then on, a draft in <code>workflows/</code> that a later upgrade never
              touches. Same thing on the command line:{' '}
              <code>openstategraph examples copy &lt;slug&gt;</code>.
            </p>
            {examplesOpen && (
              <ul className="workflow-manager__list">
                {examples.map((example) => (
                  <li key={example.slug} className="workflow-manager__item">
                    <div className="workflow-manager__info">
                      <Icon glyph={FileJson} size="sm" />
                      <span className="workflow-manager__name" title={example.summary}>
                        {example.name}
                      </span>
                      <span className="workflow-manager__badge">{example.pattern}</span>
                    </div>
                    <div className="workflow-manager__actions">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        // What it will write, said before it writes it: three of
                        // these mount other examples and a copy brings them.
                        title={`Copies ${example.requires.join(', ')} into workflows/`}
                        onClick={() => void handleCopyExample(example)}
                        icon={<Icon glyph={Copy} size="xs" />}
                      >
                        Copy
                        {example.requires.length > 1 ? ` +${example.requires.length - 1}` : ''}
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </PanelSection>
        )}
      </PanelBody>
    </Panel>
  );
}
