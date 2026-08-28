import { useCallback, useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import type { Theme } from '@design/tokens';
import type { Shortcut } from '@canvas/features/KeyboardFeature';
import {
  usePaperController,
  useWorkbench,
  useWorkflowSession,
  useController,
} from '@app/WorkbenchContext';
import { TopBar } from './topbar/TopBar';
import { Palette } from './palette/Palette';
import { AskPanel } from './ask/AskPanel';
import { entryQuestion } from '@nodes/inputs/entryQuestion';
import { Inspector } from './inspector/Inspector';
import { CanvasStage } from './canvas/CanvasStage';
import { Minimap } from './minimap/Minimap';
import { ShortcutsDrawer } from './overlays/ShortcutsDrawer';
import { CredentialsDialog } from './overlays/CredentialsDialog';
import { McpServersDialog } from './overlays/McpServersDialog';
import { AccessibilityCheck } from './overlays/AccessibilityCheck';
import { Toaster, useToaster } from './overlays/Toaster';
import { WorkflowManager } from './workflow/WorkflowManager';
import { leftOverlayWidth, panelsMustOverlay, rightOverlayWidth } from './layout/panelFit';
import { useViewportWidth } from './layout/useViewportWidth';
import { interruptedRunNotice, takeInterruptedRun } from './ask/interruptedRun';
import { useDeepLinkedWorkflow } from './workflow/useDeepLinkedWorkflow';
import { DrillBanner } from './workflow/DrillBanner';
import { useWorkflowFileWatch } from '@app/useWorkflowFileWatch';
import { WorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import { RuntimeClient } from '@core/runtime/RuntimeClient';
import { OpenStreams } from '@core/runtime/OpenStreams';
import { getOpenSlug } from '@app/openWorkflow';
import {
  BLANK_TEMPLATE,
  createNewWorkflow,
  discardDeclined,
  discardWarning,
} from './workflow/createNewWorkflow';
import { saveMessage, saveSucceeded, saveWorkflow } from './workflow/saveWorkflow';
import './AppShell.css';

const THEME_STORAGE_KEY = 'openstategraph.theme';

/**
 * The run this tab was watching when it was last reloaded, if there was one
 * (ticket 55.6) — read at module scope because it belongs to the *page load*,
 * not to a component.
 *
 * `takeInterruptedRun` clears the mark as it reads it, so there is exactly one
 * honest reader: an effect would be run twice by StrictMode and the second
 * pass would find nothing, and a `useState` initialiser is invoked twice for
 * the same reason. Here it is consumed once, before React starts.
 */
const INTERRUPTED_RUN = takeInterruptedRun();

/**
 * The application layout.
 *
 * Owns only chrome-level state — theme, which panels are open, transient
 * toasts. Everything about the document lives in the model, and everything
 * about the canvas lives in the paper controller, so this component stays a
 * layout and never becomes the place logic accumulates.
 */
export function AppShell() {
  const workbench = useWorkbench();
  const paper = usePaperController();
  useController();
  const { toasts, notify, dismiss } = useToaster();
  // Only the toolbar's New needs it here; the Workflows panel keeps its own,
  // because it is mounted and unmounted with the panel.
  const workflowFiles = useMemo(() => new WorkflowFileClient(), []);

  // Enable auto-save and auto-load for the current workflow
  // Restores this tab's workflow, then keeps it saved. One hook, because
  // identity has to be resolved before either behaviour runs.
  //
  // `notify` is passed, not omitted (UX-04): browser storage fails in ways the
  // user must hear about — a full quota, an unreadable autosave, a second tab
  // that already owns this workflow. Autosave previously discarded every one
  // of those outcomes, which made "your work is safe" a claim nothing checked.
  useWorkflowSession(notify);

  // Ticket 16's other half: notices when the saved file changes on disk
  // underneath this open editor (another tab, a teammate's pull, a
  // hand-edit) — independent of whether "Manage Workflows" happens to be
  // open, since an external change can land at any time.
  useWorkflowFileWatch(notify);

  // Ticket 20: `?w=<slug>` in the address bar opens that workflow. After
  // `useWorkflowSession`, and never fighting it — the two agree in advance
  // through `resolveOpenRequest`, so exactly one of "restore this tab's
  // autosave" and "fetch the linked workflow" happens.
  useDeepLinkedWorkflow(notify);

  // mcp-connect ticket 07: the `tool.mcp` card's Server picker reads the
  // registry, and the registry arrives over HTTP. One read here so a card
  // dropped before the MCP panel has ever been opened still offers the truth;
  // after that the panel's own client keeps the catalogue current, because
  // every registry answer publishes on its way through `McpRegistryClient`.
  useEffect(() => {
    void new RuntimeClient().mcp.servers();
  }, []);

  // Ticket 42: a gesture refused because it cannot differ per mount. Said out
  // loud, because the alternative is the silent no-op this codebase has a
  // standing rule against — the card would simply not move and nothing would
  // explain why.
  useEffect(
    () => workbench.controller.history.onRefused(({ reason }) => notify(reason)),
    [workbench, notify],
  );

  const viewportWidth = useViewportWidth();
  const [theme, setTheme] = useState<Theme>(readInitialTheme);
  const [showGrid, setShowGrid] = useState(true);
  const [paletteOpen, setPaletteOpen] = useState(true);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  // A second right-hand panel rather than a mode on the inspector: a developer
  // wants to see a node's config *and* the answer at the same time.
  // Open on arrival when a run was interrupted by the reload: the notice
  // below explains it, and History — which the panel opens on — is where the
  // server's record of that run is.
  const [askOpen, setAskOpen] = useState(INTERRUPTED_RUN !== null);
  // Set when Run hands a graph over to the backend runtime (see the
  // `run:finish` effect below); cleared as soon as the panel is closed.
  const [askNotice, setAskNotice] = useState<string | null>(
    INTERRUPTED_RUN === null ? null : interruptedRunNotice(INTERRUPTED_RUN),
  );
  const [askFocusNonce, setAskFocusNonce] = useState(0);
  /** A Run press, handed to the Ask panel to execute as a turn (ticket 03). */
  const [askRunRequest, setAskRunRequest] = useState<{
    question: string;
    nonce: number;
  } | null>(null);
  /** A Stop press, handed to the same panel to act on (ticket 10). */
  const [askStopRequest, setAskStopRequest] = useState<{ nonce: number } | null>(null);
  const [backendRunning, setBackendRunning] = useState(false);
  /**
   * The abort handle for every stream the Ask panel opens — held **here**,
   * because the panel is conditionally rendered and closing it is a real
   * unmount (install-experience ticket 07).
   *
   * A run whose handle died with the panel was a run nobody could stop: the
   * `fetch` stayed open, the reader kept writing into a dead component, and
   * the unmount reported "not running" so the toolbar retired Stop. The panel
   * cannot fix that from an unmount effect — React's StrictMode double-mount
   * makes a cleanup indistinguishable from a close, and Run opens this panel
   * *and* starts a run, so an abort-on-cleanup killed the run it had just
   * started (the panel's own comment records that regression). A gesture is
   * distinguishable, so the abort hangs off the Ask toggle below.
   */
  const askStreams = useMemo(() => new OpenStreams(), []);
  const [credentialsOpen, setCredentialsOpen] = useState(false);
  const [mcpServersOpen, setMcpServersOpen] = useState(false);
  const [workflowManagerOpen, setWorkflowManagerOpen] = useState(false);

  /* ---------------- theme ---------------- */

  useEffect(() => {
    document.documentElement.dataset['theme'] = theme;
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // Storage unavailable — the theme still applies for this session.
    }
  }, [theme]);

  /* ---------------- shell shortcuts ----------------
   * Contributed into the canvas keyboard feature rather than handled here,
   * so every binding in the app lives in one table and shows up in the
   * shortcuts drawer automatically. */

  /**
   * Run, from the toolbar or the shortcut (ticket 03).
   *
   * Opens the Ask panel *showing* the run rather than running invisibly, and
   * hands the question to that panel's own thread — so the run has the same
   * history, the same client and the same stream as a typed question, and a
   * developer who then wants to follow up is already in the conversation.
   *
   * The nonce, not the text, is the trigger: pressing Run twice without
   * editing the Input node must run twice.
   */
  const runWorkflow = useCallback((question: string) => {
    if (question.trim() === '') return;
    setAskNotice(null);
    setAskOpen(true);
    setAskRunRequest((previous) => ({
      question,
      nonce: (previous?.nonce ?? 0) + 1,
    }));
  }, []);

  /**
   * The toolbar's **Save** (`say-it-on-the-surface` 01).
   *
   * The act is `saveWorkflow`, the one the Workflows panel calls — this is a
   * gesture, not a second implementation, the same division `startNewWorkflow`
   * keeps below. What the shell adds is the one thing a panel already had and
   * a toolbar did not: a busy flag, so the button cannot be double-pressed
   * into two creates. The button's own copy re-derives itself — it subscribes
   * to the slug and address stores rather than being told.
   *
   * `window.confirm` is passed in rather than reached for inside the act, so
   * the act stays testable without a DOM — and so the day this project has a
   * better dialog than the browser's, one call site changes.
   */
  const [saving, setSaving] = useState(false);
  const saveOpenWorkflow = useCallback(async () => {
    setSaving(true);
    const outcome = await saveWorkflow({
      client: workflowFiles,
      workbench,
      confirm: (message) => window.confirm(message),
    });
    setSaving(false);
    const message = saveMessage(outcome);
    if (message !== null) notify(message);
    return saveSucceeded(outcome);
  }, [workflowFiles, workbench, notify]);

  const shellShortcuts = useMemo<readonly Shortcut[]>(
    () => [
      {
        keys: 'Mod+B',
        label: 'Toggle palette',
        group: 'View',
        run: () => setPaletteOpen((value) => !value),
      },
      {
        // Not Mod+K: Chrome claims it for the address bar, so the shortcut
        // registered correctly and simply never reached the page. Verified in a
        // real browser rather than assumed.
        keys: 'Mod+Shift+K',
        label: 'Toggle ask panel',
        group: 'View',
        run: () => setAskOpen((value) => !value),
      },
      {
        keys: 'Mod+I',
        label: 'Toggle inspector',
        group: 'View',
        run: () => setInspectorOpen((value) => !value),
      },
      {
        keys: 'Mod+Shift+G',
        label: 'Toggle grid',
        group: 'View',
        run: () => setShowGrid((value) => !value),
      },
      {
        keys: 'Mod+Shift+D',
        label: 'Toggle theme',
        group: 'View',
        run: () => setTheme((current) => (current === 'dark' ? 'light' : 'dark')),
      },
      {
        keys: 'Mod+Shift+F',
        label: 'Workflow manager',
        group: 'View',
        run: () => setWorkflowManagerOpen((value) => !value),
      },
      {
        // The convention every editor on this machine already trained the
        // user in. `allowInTextEntry` because a save you have to click out of
        // a textarea to reach is a save you lose work to — and because the
        // browser's own Save-Page dialog is what fires otherwise.
        keys: 'Mod+S',
        label: 'Save workflow',
        group: 'Run',
        allowInTextEntry: true,
        run: () => void saveOpenWorkflow(),
      },
      {
        keys: 'Mod+Enter',
        label: 'Run workflow',
        group: 'Run',
        allowInTextEntry: true,
        // Same meaning as the Run button, so the shortcut cannot drift into
        // being a different feature: a real backend run of the Input node's
        // text, shown in the Ask panel. Read at press time rather than
        // subscribed — a keystroke needs the answer once, now.
        run: () => runWorkflow(entryQuestion(workbench.model)),
      },
      {
        keys: 'Mod+K',
        label: 'Models and credentials',
        group: 'Run',
        run: () => setCredentialsOpen(true),
      },
    ],
    [workbench, runWorkflow, saveOpenWorkflow],
  );

  /* ---------------- run feedback ---------------- */

  useEffect(() => {
    const off = workbench.engine.on('run:finish', ({ ok, usage, error, reason }) => {
      if (ok) {
        notify(`Run finished · ${usage.totalTokens.toLocaleString()} tokens`);
        return;
      }
      // Run must not dead-end where Chat would have worked. The canvas
      // preview cannot walk a cycle, but the backend runtime — the same one
      // this panel already uses — runs it fine, so Run hands over instead of
      // refusing: open the chat, say why, focus the box. Deliberately *not* an
      // automatic run: the backend needs a question, and inventing an empty
      // one would spend tokens on something nobody asked.
      if (reason === 'requires-backend-runtime') {
        setAskNotice(error ?? 'This graph runs on the backend runtime.');
        setAskOpen(true);
        setAskFocusNonce((value) => value + 1);
      }
    });
    return off;
  }, [workbench, notify]);

  const onNotify = useCallback((message: string) => notify(message), [notify]);

  /**
   * The toolbar's **New** (ticket 06).
   *
   * A blank canvas, deliberately: the panel's picker exists for starting from
   * a template, and a toolbar button that opened a form would be the buried
   * affordance again with an extra step. The *act* is `createNewWorkflow`,
   * the one the panel calls — this is a gesture, not a second implementation.
   */
  const startNewWorkflow = useCallback(async () => {
    const subject = {
      name: workbench.model.name,
      nodeCount: workbench.model.nodeCount,
      saved: getOpenSlug() !== null,
    };
    const warning = discardWarning(subject);
    if (warning !== null && !window.confirm(warning)) {
      // `say-it-on-the-surface` 02: a refusal is audible on the gesture that
      // was refused. A bare `return` here is what made New look broken.
      notify(discardDeclined(subject));
      return;
    }
    const outcome = await createNewWorkflow(
      { name: '', template: BLANK_TEMPLATE },
      workbench.controller,
      workflowFiles,
    );
    notify(
      outcome.ok
        ? `New workflow: ${outcome.value.name} — an empty canvas. Rename it in the inspector, then Save to give it a folder.`
        : outcome.error,
    );
  }, [workbench, workflowFiles, notify]);

  // Whether the panels share the row with the canvas or float over it,
  // decided by what is open rather than by a breakpoint (55.4). Computed once
  // here so both `data-overlay` and the canvas's right-edge inset (76) read
  // the same answer.
  const mustOverlay = panelsMustOverlay(viewportWidth, {
    palette: paletteOpen,
    ask: askOpen,
    inspector: inspectorOpen,
    workflows: workflowManagerOpen,
  });

  return (
    <div className="app-shell">
      <TopBar
        theme={theme}
        onThemeChange={setTheme}
        showGrid={showGrid}
        onGridChange={setShowGrid}
        paletteOpen={paletteOpen}
        onPaletteToggle={() => setPaletteOpen((value) => !value)}
        inspectorOpen={inspectorOpen}
        onInspectorToggle={() => setInspectorOpen((value) => !value)}
        onOpenCredentials={() => setCredentialsOpen(true)}
        onOpenMcpServers={() => setMcpServersOpen(true)}
        onNotify={onNotify}
        onNewWorkflow={() => void startNewWorkflow()}
        onSave={() => void saveOpenWorkflow()}
        saving={saving}
        onWorkflowsToggle={() => setWorkflowManagerOpen((value) => !value)}
        workflowsOpen={workflowManagerOpen}
        askOpen={askOpen}
        onAskToggle={() =>
          setAskOpen((value) => {
            if (value) {
              setAskNotice(null);
              // Closing the panel ends the runs it was showing. The panel is
              // where a run is watched, answered and continued, and its
              // transcript goes with it — so a stream left open would write
              // to nothing a user can ever read while still billing tokens.
              // Said here rather than in the panel's cleanup for the reason
              // `askStreams` records.
              askStreams.abortAll();
            }
            return !value;
          })
        }
        onRun={runWorkflow}
        // The run lives in the Ask panel, so Stop is a request forwarded to
        // it — never a second place that knows how to abort. Except when the
        // panel is not there to receive it: the shell holds the handle, so a
        // Stop offered while the panel is closed is one that can be delivered
        // rather than a button that silently does nothing (ticket 07).
        onStop={() => (askOpen ? setAskStopRequest({ nonce: Date.now() }) : askStreams.abortAll())}
        runInFlight={backendRunning}
      />

      <div
        className="app-shell__body"
        // Whether the panels share the row with the canvas or float over it,
        // decided by what is open rather than by a breakpoint (55.4). Four
        // panels at 1280 used to leave ~140px of canvas, silently.
        data-overlay={mustOverlay || undefined}
        // The drawer is a second left-hand panel: floating, it must stand
        // beside the palette rather than on top of it.
        data-palette-open={paletteOpen || undefined}
      >
        {paletteOpen ? <Palette onNotify={onNotify} /> : null}

        <main
          className="app-shell__canvas"
          // Ask/Inspector float over the canvas rather than sharing its row
          // when overlaying (55.4), so the canvas element stays full width —
          // anything centred on it, like the empty-state copy, was centring
          // on space the panels sit on top of (76). This tells the canvas how
          // much of its right edge is actually covered.
          style={
            {
              '--canvas-empty-inset-right': `${rightOverlayWidth(mustOverlay, {
                ask: askOpen,
                inspector: inspectorOpen,
              })}px`,
              // launch-readiness 39: the palette (and the Workflows drawer
              // beside it) float over the canvas at `left: 0` in overlay
              // mode too — the empty-state hint needs the same inset on the
              // left that Ask/Inspector already get on the right (76), or a
              // narrow window centres it behind the palette.
              '--canvas-empty-inset-left': `${leftOverlayWidth(mustOverlay, {
                palette: paletteOpen,
                workflows: workflowManagerOpen,
              })}px`,
            } as CSSProperties
          }
        >
          <CanvasStage shortcuts={shellShortcuts} showGrid={showGrid} onNotify={onNotify} />
          {/* Over the canvas, not in the topbar: it is a fact about *this
              document*, and it appears and disappears with a navigation —
              the topbar's contents are fixed chrome. */}
          <DrillBanner />
          {paper ? <Minimap /> : null}
          <ShortcutsDrawer
            shortcuts={paper?.shortcuts ?? []}
            portTypes={workbench.registry.portTypes.list()}
          />
          <AccessibilityCheck />
        </main>

        {askOpen || inspectorOpen ? (
          // Grouped so the narrow-window overlay rule (AppShell.css) can lay
          // both out side by side instead of stacking them at an identical
          // `right: 0`, which made whichever mounted second (Inspector)
          // silently intercept every click meant for the other.
          <div className="app-shell__right-panels">
            {askOpen ? (
              <AskPanel
                notice={askNotice}
                focusNonce={askFocusNonce}
                runRequest={askRunRequest}
                stopRequest={askStopRequest}
                streams={askStreams}
                openHistory={INTERRUPTED_RUN !== null}
                onRunningChange={(running) => {
                  setBackendRunning(running);
                  // Ticket 08: a backend-streamed run has no local engine to
                  // fire `run:start`, so this is where the canvas learns a new
                  // run has begun and the follow latch may be released.
                  if (running) paper?.follower.runStarted();
                }}
              />
            ) : null}
            {inspectorOpen ? <Inspector /> : null}
          </div>
        ) : null}
        {workflowManagerOpen ? (
          <WorkflowManager
            open={workflowManagerOpen}
            onClose={() => setWorkflowManagerOpen(false)}
            onNotify={onNotify}
          />
        ) : null}
      </div>

      {credentialsOpen ? <CredentialsDialog onClose={() => setCredentialsOpen(false)} /> : null}
      {mcpServersOpen ? <McpServersDialog onClose={() => setMcpServersOpen(false)} /> : null}
      <Toaster toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}

/** Stored preference, else the OS setting. */
function readInitialTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
  } catch {
    // Fall through to the media query.
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
