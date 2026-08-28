import { useCallback, useEffect, useState, useSyncExternalStore } from 'react';
import {
  Download,
  FileJson,
  FileText,
  Image as ImageIcon,
  KeyRound,
  MessageSquareText,
  Moon,
  MoveVertical,
  Network,
  PanelLeft,
  PanelRight,
  Play,
  Plug,
  Plus,
  Grid2x2,
  Redo2,
  Save,
  Square,
  Sun,
  Undo2,
  Upload,
  GitBranch,
  Crosshair,
  Globe,
  GlobeLock,
} from 'lucide-react';
import {
  Badge,
  Button,
  Icon,
  IconButton,
  Menu,
  Tooltip,
  useMenu,
  shortcutText,
  type MenuEntry,
} from '@design/primitives';
import type { Theme } from '@design/tokens';
import {
  useController,
  useFlowDirection,
  useHistoryState,
  usePaperController,
  useWorkbench,
} from '@app/WorkbenchContext';
import {
  download,
  exportJSON,
  exportPNG,
  exportSVG,
  importJSON,
  slugify,
} from '@view/export/exportWorkflow';
import { GraphPreview } from '@view/overlays/GraphPreview';
import { OnboardingHint } from '@view/overlays/OnboardingHint';
import { ExamplesHint } from '@view/overlays/ExamplesHint';
import { rememberExamplesShelf } from '@view/workflow/examplesShelf';
import { RuntimeHealthDot } from './RuntimeHealthDot';
import { useEntryQuestion } from './useEntryQuestion';
import { runIntent } from './runIntent';
import { subscribeOpenSlug } from '@app/openWorkflow';
import { subscribeOpenAddress } from '@app/openAddress';
import { subscribeWatchReach } from '@app/workflowFileWatch';
import { saveAffordance } from './saveAffordance';
import { usePublishState } from './usePublishState';
import { publishedMessage, unpublishedMessage } from '@view/workflow/consequences';
import './TopBar.css';

interface TopBarProps {
  theme: Theme;
  onThemeChange: (theme: Theme) => void;
  showGrid: boolean;
  onGridChange: (visible: boolean) => void;
  paletteOpen: boolean;
  onPaletteToggle: () => void;
  inspectorOpen: boolean;
  onInspectorToggle: () => void;
  onOpenCredentials: () => void;
  /**
   * The MCP server registry (mcp-connect ticket 03).
   *
   * Beside the key, because it is the same class of question: what does this
   * *project* have available, as opposed to what does this document say.
   */
  onOpenMcpServers: () => void;
  onNotify: (message: string) => void;
  /**
   * Start a new workflow (ticket 06).
   *
   * The toolbar owns the *button* and nothing else: what a new workflow costs
   * and what it does is `createNewWorkflow`, shared with the Workflows panel,
   * so promoting the affordance did not fork the act.
   */
  onNewWorkflow: () => void;
  /**
   * Save this document to the backend (`say-it-on-the-surface` 01).
   *
   * The toolbar owns the *button* and nothing else: what saving costs and
   * which of its three acts fires is `saveWorkflow`, shared with the Workflows
   * panel, exactly as `onNewWorkflow` shares `createNewWorkflow`.
   */
  onSave: () => void;
  /** True while a save is in flight, so the button cannot be pressed twice. */
  saving: boolean;
  /** Route to the workflow list — open, unpublish, delete, publish, save. */
  onWorkflowsToggle: () => void;
  workflowsOpen: boolean;
  /** The chat panel, which is where a run is watched. */
  onAskToggle: () => void;
  askOpen: boolean;
  /**
   * Starts a real backend run of the question the Input node holds
   * (ticket 03). The shell owns it because running means *showing* the run in
   * the Ask panel, and the panel's thread is the shell's state, not the
   * toolbar's.
   */
  onRun: (question: string) => void;
  /**
   * Stops the run in flight (ticket 10). The toolbar owns the button but not
   * the run — same division as `onRun` — so this only asks; the Ask panel
   * holds the `AbortController` and does the aborting.
   */
  onStop: () => void;
  /** True while a backend run started from here is still streaming. */
  runInFlight: boolean;
}

/**
 * The application toolbar.
 *
 * Grouped by what the controls act on — document, history, layout, then the
 * run action and the view/session controls on the right — rather than by
 * icon similarity. Run is the only filled button on screen, because it is
 * the only action that does something irreversible-feeling and the one a user
 * comes here to press.
 */
export function TopBar({
  theme,
  onThemeChange,
  showGrid,
  onGridChange,
  paletteOpen,
  onPaletteToggle,
  inspectorOpen,
  onInspectorToggle,
  onOpenCredentials,
  onOpenMcpServers,
  onNotify,
  onNewWorkflow,
  onSave,
  saving,
  onWorkflowsToggle,
  workflowsOpen,
  onAskToggle,
  askOpen,
  onRun,
  onStop,
  runInFlight,
}: TopBarProps) {
  const [graphOpen, setGraphOpen] = useState(false);
  // Re-derived whenever the open workflow's identity moves. The label is a
  // claim about whether this document has a folder, and that claim changes the
  // instant one is minted — so it subscribes to the two stores that own the
  // answer rather than taking a nonce from a parent that would have to
  // remember to bump it.
  const [save, setSave] = useState(saveAffordance);
  useEffect(() => {
    const refresh = () => setSave(saveAffordance());
    const offSlug = subscribeOpenSlug(refresh);
    const offAddress = subscribeOpenAddress(refresh);
    // The third store it depends on (`say-it-on-the-surface/07`): whether the
    // file watch can still reach the backend. Same reason as the other two —
    // the sentence is a claim about a folder, and it stops being true the
    // moment nothing can look at that folder.
    const offReach = subscribeWatchReach(refresh);
    return () => {
      offSlug();
      offAddress();
      offReach();
    };
  }, []);
  // **Is what I am editing live to customers?** (`ship-it` 39.) The other
  // half of the pair the toolbar owes an open package — Save answers "is my
  // work on disk", and until this there was nowhere on the canvas that
  // answered the more consequential one. The state, the words and the
  // save/publish relationship are all `publishAffordance`'s; this renders it.
  const publish = usePublishState();
  const [publishing, setPublishing] = useState(false);

  const workbench = useWorkbench();
  const flowDirection = useFlowDirection();
  const controller = useController();
  const paper = usePaperController();
  const { canUndo, canRedo } = useHistoryState();
  const exportMenu = useMenu<HTMLButtonElement>();

  const [running, setRunning] = useState(false);
  const [tokens, setTokens] = useState(0);

  /* ---------------- follow the run (ticket 08) ----------------
   *
   * Mirrored into React state rather than read on each render: the follower
   * latches itself off on a pan or a zoom, so the button has to hear about a
   * change it did not make. `reason` arrives exactly once per run, which is
   * why it is toasted here rather than rendered — a persistent badge saying
   * "not following" would be a second thing to dismiss. */
  const following = useSyncExternalStore(
    useCallback(
      (onStoreChange: () => void) => paper?.follower.onChange(onStoreChange) ?? (() => {}),
      [paper],
    ),
    () => paper?.follower.enabled ?? false,
  );

  useEffect(() => {
    if (!paper) return;
    return paper.follower.onChange(({ reason }) => {
      if (reason) onNotify(reason);
    });
  }, [paper, onNotify]);

  useEffect(() => {
    const { engine } = workbench;
    const offStart = engine.on('run:start', () => {
      setRunning(true);
      setTokens(0);
    });
    const offUsage = engine.on('run:usage', ({ usage }) => setTokens(usage.totalTokens));
    const offFinish = engine.on('run:finish', ({ ok, error, reason }) => {
      setRunning(false);
      // A handover to the backend runtime is not a failure and gets no error
      // toast — the shell opens the chat panel and explains it there, where
      // the user's next action already is. Toasting as well would read as
      // "something went wrong" for a run that is about to work.
      if (reason === 'requires-backend-runtime') return;
      if (!ok && error) onNotify(error);
    });
    return () => {
      offStart();
      offUsage();
      offFinish();
    };
  }, [workbench, onNotify]);

  /**
   * What Run would actually ask. Live — it re-reads on every field edit, so
   * the button's tooltip follows the developer's typing.
   */
  const question = useEntryQuestion();

  // Ticket 03: **Run means run.** It no longer starts the in-browser preview
  // engine; it streams a real backend run of the Input node's text, through
  // the same `RuntimeClient` the Ask panel uses, and shows it in that panel.
  // The preview engine is untouched and still drives the internal tests — it
  // is simply no longer what this button means.
  //
  // Ticket 21: and a press of it always *means* something. It used to be
  // `disabled` whenever the entry question was empty, which on the shipped
  // `concierge` — whose Input node is blank on purpose — made the primary
  // action of the editor do nothing at all, with no panel, no toast and no
  // console line. The tooltip that explained it could not appear either: a
  // disabled button dispatches no mouse events, so the click and the hover
  // died together. The decision itself lives in `runIntent`, where it can be
  // tested; this handler is only the gesture.
  const run = () => {
    const intent = runIntent(question, runInFlight);
    if (intent.kind === 'stop') return onStop();
    if (intent.kind === 'explain') return onNotify(intent.reason);
    onRun(intent.question);
  };

  /**
   * The gesture. The act is the hook's, the words are `consequences`' — the
   * Workflows panel presses the same endpoint and says the same two sentences,
   * so a reword there cannot leave this surface contradicting it.
   *
   * The confirm fires only when this browser holds work the file does not, and
   * it is the whole of the ticket's second half: publishing ships the **saved**
   * package, and a control that would quietly put something other than what is
   * on screen in front of customers owes the user that sentence.
   */
  const onPublishToggle = useCallback(async () => {
    // `affordanceNow`, deliberately, not the rendered one — see the hook.
    const { action, confirmation } = publish.affordanceNow();
    if (action === null) return;
    if (confirmation !== null && !confirm(confirmation)) return;
    setPublishing(true);
    const failure = await publish.setPublished(action === 'publish');
    setPublishing(false);
    const name = workbench.model.name;
    if (failure !== null) {
      onNotify(`Could not ${action}: ${failure}`);
      return;
    }
    onNotify(action === 'publish' ? publishedMessage(name) : unpublishedMessage(name));
  }, [publish, workbench, onNotify]);

  const exportEntries: MenuEntry[] = [
    {
      id: 'json',
      label: 'Workflow JSON',
      icon: FileJson,
      onSelect: () => exportJSON(controller),
    },
    {
      id: 'svg',
      label: 'Canvas as SVG',
      icon: ImageIcon,
      onSelect: () => {
        if (!paper) return;
        const svg = exportSVG(paper);
        if (!svg.ok) {
          onNotify(svg.error);
          return;
        }
        download(
          new Blob([svg.value], { type: 'image/svg+xml' }),
          `${slugify(workbench.model.name)}.svg`,
        );
      },
    },
    {
      id: 'png',
      label: 'Canvas as PNG',
      icon: ImageIcon,
      onSelect: () => {
        if (!paper) return;
        void exportPNG(paper).then((result) => {
          if (!result.ok) {
            onNotify(result.error);
            return;
          }
          download(result.value, `${slugify(workbench.model.name)}.png`);
        });
      },
    },
    { kind: 'separator', id: 'sep' },
    {
      id: 'import',
      label: 'Import JSON…',
      icon: Upload,
      onSelect: () =>
        // No fit here: replacing the document is framed by the canvas's own
        // `FrameOnLoadFeature`, which is why drilling into a mount — a path
        // that had no such hand-written call — used to lose the view.
        importJSON(controller, (outcome) => {
          if (outcome.message) onNotify(outcome.message);
        }),
    },
  ];

  return (
    <>
      <header className="topbar">
        <div className="topbar__brand">
          <span className="topbar__mark" aria-hidden="true">
            <Icon glyph={Network} size="md" />
          </span>
          <span className="topbar__product">OpenStateGraph</span>
          <span className="topbar__divider" role="presentation" />
          <RuntimeHealthDot />
          <span className="topbar__doc" title={workbench.model.name}>
            {workbench.model.name}
          </span>
        </div>

        {/* The document group — ticket 06's owner pass. Create New and the
            workflow list were both reachable only from inside the Workflows
            panel, which is a panel nobody knows is there; these are the two
            controls a user who has just drawn something needs, so they sit in
            the first place anybody looks. Neither one *does* anything here:
            New calls the same `createNewWorkflow` the panel calls, and
            Workflows opens the panel itself. */}
        <div className="topbar__group">
          <Tooltip content="Start a new workflow" multiline>
            <Button variant="ghost" icon={<Icon glyph={Plus} size="sm" />} onClick={onNewWorkflow}>
              New
            </Button>
          </Tooltip>
          {/* **Save, where a person who has just drawn something looks for
              it** (`say-it-on-the-surface` 01). It was reachable only from
              inside the Workflows panel, behind a toggle, with no `Mod+S` —
              and what filled the gap was autosave, which is browser-local and
              reaches no backend. So the cost of not finding the panel was
              lost work, which is why this is the one control here that
              changes its own copy: `saveAffordance` says which of the three
              acts is about to fire and whether this document is on disk at
              all. `secondary`, not `primary` — Run is the primary and a
              second filled button means neither is. */}
          <Tooltip content={save.hint} shortcut="Mod+S" multiline>
            <Button
              variant="secondary"
              icon={<Icon glyph={Save} size="sm" />}
              onClick={onSave}
              disabled={saving}
            >
              {save.label}
              {/* **The persistent half of telling three states apart**
                  (`say-it-on-the-surface/07`). Deleted, unreachable and
                  healthy all rendered identically once the toast faded — and
                  a toast fades in five seconds. One element with a state, not
                  two dots: `unsaved` is already legible from the hint and from
                  an empty address bar, while "nothing has answered for three
                  checks" is carried nowhere else. */}
              {save.marker !== null ? (
                <span
                  className="topbar__unsaved"
                  data-state={save.marker}
                  role={save.marker === 'unreachable' ? 'status' : undefined}
                  aria-hidden={save.marker === 'unreachable' ? undefined : true}
                  aria-label={
                    save.marker === 'unreachable'
                      ? 'Cannot reach the backend — this workflow is no longer being watched'
                      : undefined
                  }
                />
              ) : null}
            </Button>
          </Tooltip>
          {/* **Who can see this** — `ship-it` 39. The badge and the verb are
              one cluster because they are one fact: the word is the state, and
              the button is the only thing that changes it. The badge is
              `Badge`'s explained form, so the claim carries its sentence to a
              keyboard as well as to a pointer, and both come from
              `publishAffordance` rather than being written here. Nothing is
              printed at all while the runtime has not answered, or while a
              mount instance is open — a lifecycle word this surface cannot act
              on is the click that goes nowhere `workflowCatalogue` warns of. */}
          {publish.affordance.label !== null ? (
            <span className="topbar__lifecycle">
              <Badge
                tone={publish.affordance.status === 'published' ? 'success' : 'neutral'}
                explanation={publish.affordance.hint}
              >
                {publish.affordance.label}
              </Badge>
              {publish.affordance.action !== null ? (
                <Tooltip content={publish.affordance.actionHint} multiline>
                  <Button
                    variant="ghost"
                    icon={
                      <Icon
                        glyph={publish.affordance.action === 'publish' ? Globe : GlobeLock}
                        size="sm"
                      />
                    }
                    onClick={() => void onPublishToggle()}
                    disabled={publishing}
                  >
                    {publish.affordance.actionLabel}
                  </Button>
                </Tooltip>
              ) : null}
            </span>
          ) : null}
          {/* Anchor for the examples pointer (ticket 23), on the control that
              actually leads to the shelf — the shelf lives inside this panel,
              collapsed, and until now nothing on any surface said so. */}
          <div className="topbar__hint-anchor">
            <Tooltip content="Open, publish or delete a saved workflow" shortcut="Mod+Shift+F">
              <Button
                variant="ghost"
                active={workflowsOpen}
                icon={<Icon glyph={FileText} size="sm" />}
                onClick={onWorkflowsToggle}
              >
                Workflows
              </Button>
            </Tooltip>
            <ExamplesHint
              onBrowseExamples={() => {
                // Expand the shelf *before* the panel mounts: `WorkflowManager`
                // reads `examplesShelfStartsOpen` in a `useState` initialiser,
                // so writing the answer here is what makes one press land on an
                // open shelf rather than on a closed one to press again. This
                // is a gesture asking for the examples, which is exactly the
                // opt-in the wave-3 collapse was written to require.
                rememberExamplesShelf(true);
                if (!workflowsOpen) onWorkflowsToggle();
              }}
            />
          </div>
        </div>

        <span className="topbar__divider" role="presentation" />

        <div className="topbar__group">
          <Tooltip content="Toggle palette" shortcut={shortcutText('Mod+B')}>
            <IconButton
              label="Toggle palette"
              active={paletteOpen}
              icon={<Icon glyph={PanelLeft} size="md" />}
              onClick={onPaletteToggle}
            />
          </Tooltip>
          <Tooltip content="Toggle grid">
            <IconButton
              label="Toggle grid"
              active={showGrid}
              icon={<Icon glyph={Grid2x2} size="md" />}
              onClick={() => onGridChange(!showGrid)}
            />
          </Tooltip>

          <span className="topbar__divider" role="presentation" />

          <Tooltip content="Undo" shortcut={shortcutText('Mod+Z')}>
            <IconButton
              label="Undo"
              disabled={!canUndo}
              icon={<Icon glyph={Undo2} size="md" />}
              onClick={() => controller.history.undo()}
            />
          </Tooltip>
          <Tooltip content="Redo" shortcut={shortcutText('Mod+Shift+Z')}>
            <IconButton
              label="Redo"
              disabled={!canRedo}
              icon={<Icon glyph={Redo2} size="md" />}
              onClick={() => controller.history.redo()}
            />
          </Tooltip>

          <span className="topbar__divider" role="presentation" />

          <Tooltip content="View compiled graph" multiline>
            <IconButton
              label="View compiled graph"
              icon={<Icon glyph={GitBranch} size="md" />}
              onClick={() => setGraphOpen(true)}
            />
          </Tooltip>

          <Tooltip content="Arrange automatically" multiline>
            <IconButton
              label="Arrange automatically"
              icon={<Icon glyph={Network} size="md" />}
              onClick={() => {
                paper?.autoLayout.run({
                  rankDir: flowDirection === 'vertical' ? 'TB' : 'LR',
                });
                requestAnimationFrame(() => paper?.fitToContent());
              }}
            />
          </Tooltip>
          <Tooltip
            content={
              flowDirection === 'vertical'
                ? 'Flow direction: vertical — switch to horizontal'
                : 'Flow direction: horizontal — switch to vertical'
            }
            multiline
          >
            <IconButton
              label="Toggle flow direction"
              active={flowDirection === 'vertical'}
              icon={<Icon glyph={MoveVertical} size="md" />}
              onClick={() => {
                const next = flowDirection === 'vertical' ? 'horizontal' : 'vertical';
                workbench.preferences.setFlowDirection(next);
                // Re-arrange in the new direction so the toggle is visibly a
                // layout decision, not a hidden mode; one undoable transaction.
                requestAnimationFrame(() => {
                  paper?.autoLayout.run({ rankDir: next === 'vertical' ? 'TB' : 'LR' });
                  requestAnimationFrame(() => paper?.fitToContent());
                });
              }}
            />
          </Tooltip>
          <Tooltip
            content={
              following
                ? 'Follow run: on — the canvas moves to whatever is running. Panning or zooming turns this off'
                : 'Follow run: off — bring the running node into view, and fit them all on a fan-out'
            }
            multiline
          >
            <IconButton
              label="Follow run"
              active={following}
              icon={<Icon glyph={Crosshair} size="md" />}
              onClick={() => {
                const next = !following;
                paper?.follower.setEnabled(next);
                // Only a *click* writes the preference. The follower also
                // turns itself off when a gesture takes the camera, and that
                // is a pause for this run — not a decision about every run
                // after it, which is what persisting it would make it.
                workbench.preferences.setFollowRun(next);
              }}
            />
          </Tooltip>
        </div>

        <div className="topbar__spacer" />

        <div className="topbar__group">
          {tokens > 0 ? (
            <Badge numeric tone={running ? 'accent' : 'neutral'}>
              {tokens.toLocaleString()} tokens
            </Badge>
          ) : null}

          {/* Anchor for the first-run hint, which points at this exact
              button — so the pointer and the thing it points at cannot drift
              apart when the toolbar is rearranged. */}
          <div className="topbar__hint-anchor">
            <Tooltip content="API keys and endpoints" multiline>
              <IconButton
                label="API keys and endpoints"
                icon={<Icon glyph={KeyRound} size="md" />}
                onClick={onOpenCredentials}
              />
            </Tooltip>
            <OnboardingHint onOpenCredentials={onOpenCredentials} />
          </div>

          {/* A peer of the key, and reached the same way: both dialogs
              describe what this project can reach, and neither is a property
              of the document on the canvas. */}
          <Tooltip content="MCP servers this project can bind" multiline>
            <IconButton
              label="MCP servers"
              icon={<Icon glyph={Plug} size="md" />}
              onClick={onOpenMcpServers}
            />
          </Tooltip>

          {/* Wrapped, because a `disabled` button fires no pointer events and
              the tooltip is the entire explanation of why it is disabled. */}
          <Tooltip
            content={
              runInFlight
                ? // Said here rather than only after the fact, because it is
                  // the one thing a user needs to decide whether to press it:
                  // the run stops between steps, and the step already in
                  // flight finishes and is thrown away.
                  'Stop this run — nothing further is scheduled; steps already dispatched finish and are discarded'
                : question === ''
                  ? // Still the first explanation offered, for anyone whose
                    // pointer arrives before their click. It is no longer the
                    // ONLY one — see `runIntent`: this tooltip was
                    // unreachable for as long as the button was disabled,
                    // which is the whole of ticket 21.
                    'This workflow takes its question at run time — type one in the Input node to run it from here'
                  : `Run: ${truncate(question)}`
            }
            multiline
          >
            <span className="topbar__run">
              {/* While a run streams this is a Stop, not a disabled
                  "Running…" — the button in the place a user already looks
                  for run control is the one that should offer to stop it.
                  Danger-solid: the destructive action IS the primary
                  affordance for as long as the run lasts. */}
              <Button
                variant={runInFlight ? 'danger-solid' : 'primary'}
                size="lg"
                icon={
                  runInFlight ? (
                    <Icon glyph={Square} size="sm" strokeWidth={2.25} />
                  ) : (
                    <Icon glyph={Play} size="sm" strokeWidth={2.25} />
                  )
                }
                // One handler for both states (ticket 21): `runIntent`
                // already answers "stop or run or explain", and having the
                // JSX decide it a second way is two places to disagree.
                onClick={run}
                // Never disabled. A refusal has to be audible, and a
                // disabled button cannot make a sound — not even the
                // tooltip above it.
                disabled={false}
              >
                {runInFlight ? 'Stop' : 'Run'}
              </Button>
            </span>
          </Tooltip>

          {/* Asking the workflow a question, in the toolbar rather than
              floating beside it — it was one of the two buttons that used to
              live outside the header and made it stop short of the window. */}
          <Tooltip content="Ask the workflow" shortcut="Mod+Shift+K">
            <IconButton
              label="Ask the workflow"
              icon={<Icon glyph={MessageSquareText} size="md" />}
              active={askOpen}
              onClick={onAskToggle}
            />
          </Tooltip>

          <Tooltip content="Export or import">
            <IconButton
              ref={exportMenu.anchorRef}
              label="Export or import"
              icon={<Icon glyph={Download} size="md" />}
              {...exportMenu.triggerProps}
            />
          </Tooltip>
          <Menu
            anchorRef={exportMenu.anchorRef}
            entries={exportEntries}
            open={exportMenu.open}
            onClose={exportMenu.close}
          />

          <Tooltip content={theme === 'dark' ? 'Light theme' : 'Dark theme'}>
            <IconButton
              label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              icon={<Icon glyph={theme === 'dark' ? Sun : Moon} size="md" />}
              onClick={() => onThemeChange(theme === 'dark' ? 'light' : 'dark')}
            />
          </Tooltip>

          <Tooltip content="Toggle inspector">
            <IconButton
              label="Toggle inspector"
              active={inspectorOpen}
              icon={<Icon glyph={PanelRight} size="md" />}
              onClick={onInspectorToggle}
            />
          </Tooltip>
        </div>
      </header>
      <GraphPreview open={graphOpen} onClose={() => setGraphOpen(false)} />
    </>
  );
}

/** One line of the question, for the Run tooltip — the Input node can hold
 * paragraphs and a tooltip is not the place to re-read them. */
function truncate(text: string): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  return flat.length <= 80 ? flat : `${flat.slice(0, 79)}…`;
}

/** Re-exported so the shell can show the same glyph in its run affordances. */
export { Square as StopGlyph };
