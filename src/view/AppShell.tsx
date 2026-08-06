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
import { Inspector } from './inspector/Inspector';
import { CanvasStage } from './canvas/CanvasStage';
import { Minimap } from './minimap/Minimap';
import { ShortcutsDrawer } from './overlays/ShortcutsDrawer';
import { CredentialsDialog } from './overlays/CredentialsDialog';
import { AccessibilityCheck } from './overlays/AccessibilityCheck';
import { Toaster, useToaster } from './overlays/Toaster';
import { WorkflowManager } from './workflow/WorkflowManager';
import { useWorkflowFileWatch } from '@app/workflowFileWatch';
import { FileText, MessageSquareText } from 'lucide-react';
import { IconButton, Icon, Tooltip } from '@design/primitives';
import './AppShell.css';

const THEME_STORAGE_KEY = 'dyflow.theme';

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
  useWorkflowSession();

  // Ticket 16's other half: notices when the saved file changes on disk
  // underneath this open editor (another tab, a teammate's pull, a
  // hand-edit) — independent of whether "Manage Workflows" happens to be
  // open, since an external change can land at any time.
  useWorkflowFileWatch(notify, workbench.registry, workbench.engine.executors);

  const [theme, setTheme] = useState<Theme>(readInitialTheme);
  const [showGrid, setShowGrid] = useState(true);
  const [paletteOpen, setPaletteOpen] = useState(true);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  // A second right-hand panel rather than a mode on the inspector: a developer
  // wants to see a node's config *and* the answer at the same time.
  const [askOpen, setAskOpen] = useState(false);
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
        run: () => void workbench.engine.run(),
      },
      {
        keys: 'Mod+K',
        label: 'Models and credentials',
        group: 'Run',
        run: () => setCredentialsOpen(true),
      },
    ],
    [workbench],
  );

  /* ---------------- run feedback ---------------- */

  useEffect(() => {
    const off = workbench.engine.on('run:finish', ({ ok, usage }) => {
      if (ok) notify(`Run finished · ${usage.totalTokens.toLocaleString()} tokens`);
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
        />
        <div className="app-shell__workflow-btn">
          {/* A button as well as a shortcut: asking the workflow a question is
              the primary action, and a chord nobody can guess is not
              discoverable. */}
          <Tooltip content="Ask the workflow" shortcut="Mod+Shift+K">
            <IconButton
              label="Ask the workflow"
              icon={<Icon glyph={MessageSquareText} size="md" />}
              onClick={() => setAskOpen((value) => !value)}
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
          {paper ? <Minimap /> : null}
          <ShortcutsDrawer shortcuts={paper?.shortcuts ?? []} />
          <AccessibilityCheck />
        </main>

        {askOpen || inspectorOpen ? (
          // Grouped so the narrow-window overlay rule (AppShell.css) can lay
          // both out side by side instead of stacking them at an identical
          // `right: 0`, which made whichever mounted second (Inspector)
          // silently intercept every click meant for the other.
          <div className="app-shell__right-panels">
            {askOpen ? <AskPanel /> : null}
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
