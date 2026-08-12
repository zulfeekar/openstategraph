import { useCallback, useEffect, useMemo, useState } from 'react';
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
import { AccessibilityCheck } from './overlays/AccessibilityCheck';
import { Toaster, useToaster } from './overlays/Toaster';
import { WorkflowManager } from './workflow/WorkflowManager';
import { useDeepLinkedWorkflow } from './workflow/useDeepLinkedWorkflow';
import { DrillBanner } from './workflow/DrillBanner';
import { useWorkflowFileWatch } from '@app/workflowFileWatch';
import { FileText, MessageSquareText } from 'lucide-react';
import { IconButton, Icon, Tooltip } from '@design/primitives';
import './AppShell.css';

const THEME_STORAGE_KEY = 'openstategraph.theme';

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

  const [theme, setTheme] = useState<Theme>(readInitialTheme);
  const [showGrid, setShowGrid] = useState(true);
  const [paletteOpen, setPaletteOpen] = useState(true);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  // A second right-hand panel rather than a mode on the inspector: a developer
  // wants to see a node's config *and* the answer at the same time.
  const [askOpen, setAskOpen] = useState(false);
  // Set when Run hands a graph over to the backend runtime (see the
  // `run:finish` effect below); cleared as soon as the panel is closed.
  const [askNotice, setAskNotice] = useState<string | null>(null);
  const [askFocusNonce, setAskFocusNonce] = useState(0);
  /** A Run press, handed to the Ask panel to execute as a turn (ticket 03). */
  const [askRunRequest, setAskRunRequest] = useState<{
    question: string;
    nonce: number;
  } | null>(null);
  /** A Stop press, handed to the same panel to act on (ticket 10). */
  const [askStopRequest, setAskStopRequest] = useState<{ nonce: number } | null>(null);
  const [backendRunning, setBackendRunning] = useState(false);
  const [credentialsOpen, setCredentialsOpen] = useState(false);
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
    [workbench, runWorkflow],
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

  return (
    <div className="app-shell">
      <div className="app-shell__topbar-row">
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
          onNotify={onNotify}
          onRun={runWorkflow}
          // The run lives in the Ask panel, so Stop is a request forwarded to
          // it — never a second place that knows how to abort.
          onStop={() => setAskStopRequest({ nonce: Date.now() })}
          runInFlight={backendRunning}
        />
        <div className="app-shell__workflow-btn">
          {/* A button as well as a shortcut: asking the workflow a question is
              the primary action, and a chord nobody can guess is not
              discoverable. */}
          <Tooltip content="Ask the workflow" shortcut="Mod+Shift+K">
            <IconButton
              label="Ask the workflow"
              icon={<Icon glyph={MessageSquareText} size="md" />}
              onClick={() =>
                setAskOpen((value) => {
                  if (value) setAskNotice(null);
                  return !value;
                })
              }
              active={askOpen}
            />
          </Tooltip>
          <Tooltip content="Manage workflows" shortcut="Mod+Shift+F">
            <IconButton
              label="Manage workflows"
              icon={<Icon glyph={FileText} size="md" />}
              onClick={() => setWorkflowManagerOpen((value) => !value)}
              active={workflowManagerOpen}
            />
          </Tooltip>
        </div>
      </div>

      <div className="app-shell__body">
        {paletteOpen ? <Palette onNotify={onNotify} /> : null}

        <main className="app-shell__canvas">
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
