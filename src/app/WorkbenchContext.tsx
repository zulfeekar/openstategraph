import { ensureDiskBaseline, writeOpenWorkflowToDisk } from '@app/diskAutosave';
import { WorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react';
import type { Workbench } from './Workbench';
import type { WorkflowController } from '@controller/WorkflowController';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { NodeId } from '@core/model/contracts/node';
import type { WorkflowEvents } from '@core/model/contracts/workflow';
import type { FlowDirection } from '@core/model/contracts/ports';
import type { PaperController } from '@canvas/PaperController';
import {
  claimSession,
  isClaimedByAnother,
  mostRecentWorkflowId,
  newWriteGuard,
  readWorkflow,
  releaseSession,
  resolveSession,
  saveWorkflow,
  type WriteGuard,
} from './workflowStore';
import { registerNodeTypesForRawDocument } from '@nodes/workflowScoped';
import {
  getOpenSlug,
  readSlugFromSearch,
  resolveOpenRequest,
  subscribeOpenSlug,
} from './openWorkflow';
import { draftIdForSlug, draftSavedAt } from './workflowDrafts';

interface WorkbenchValue {
  readonly workbench: Workbench;
  /** Set once the canvas has mounted; null during the first render. */
  readonly paper: PaperController | null;
  readonly setPaper: (paper: PaperController | null) => void;
}

const WorkbenchContext = createContext<WorkbenchValue | null>(null);

export function WorkbenchProvider({
  workbench,
  children,
}: {
  workbench: Workbench;
  children: ReactNode;
}) {
  const [paper, setPaper] = useState<PaperController | null>(null);
  const value = useMemo<WorkbenchValue>(() => ({ workbench, paper, setPaper }), [workbench, paper]);
  return <WorkbenchContext.Provider value={value}>{children}</WorkbenchContext.Provider>;
}

function useWorkbenchValue(): WorkbenchValue {
  const value = useContext(WorkbenchContext);
  if (!value) throw new Error('Component used outside <WorkbenchProvider>');
  return value;
}

export function useWorkbench(): Workbench {
  return useWorkbenchValue().workbench;
}

export function useController(): WorkflowController {
  return useWorkbenchValue().workbench.controller;
}

export function usePaperController(): PaperController | null {
  return useWorkbenchValue().paper;
}

export function useSetPaperController(): (paper: PaperController | null) => void {
  return useWorkbenchValue().setPaper;
}

/* ================================================================== *
 * Model subscriptions
 *
 * The model is a plain observable object, not React state. These hooks
 * bridge it with `useSyncExternalStore`, which is the supported way to read
 * external mutable state without tearing during concurrent rendering — a
 * `useEffect` + `useState` pairing would drop synchronous updates that
 * happen between render and effect, and a drag produces plenty of those.
 * ================================================================== */

/**
 * Re-renders when any of the named model events fire.
 *
 * Narrow event lists matter: a component that only shows a node's title
 * should not re-render on every pointer-move during a drag.
 */
export function useModelEvents(events: readonly (keyof WorkflowEvents & string)[]): number {
  const { workbench } = useWorkbenchValue();
  const { model } = workbench;

  const subscribe = useCallback(
    (onChange: () => void) => {
      const unsubscribes = events.map((event) => model.on(event, onChange));
      return () => unsubscribes.forEach((off) => off());
    },
    // `events` is a literal array at every call site; joining it gives a
    // stable identity without forcing callers to memoise.
    [model, events.join(',')],
  );

  const [version, setVersion] = useState(0);
  useEffect(() => subscribe(() => setVersion((value) => value + 1)), [subscribe]);
  return version;
}

/** Re-renders on *any* document change. For coarse consumers only. */
export function useWorkflowVersion(): number {
  const { workbench } = useWorkbenchValue();
  const [version, setVersion] = useState(0);
  useEffect(() => workbench.model.onAny(() => setVersion((value) => value + 1)), [workbench]);
  return version;
}

/** The current selection, as a stable snapshot. */
export function useSelection(): { nodes: readonly NodeId[]; edges: readonly string[] } {
  const { workbench } = useWorkbenchValue();
  const { selection } = workbench.controller;

  return useSyncExternalStore(
    useCallback((onChange) => selection.on(onChange), [selection]),
    // Cached so repeated reads within one render return the same object and
    // don't trip the store's tearing check.
    useCallback(() => selectionSnapshot(selection), [selection]),
  );
}

let cachedSelection: { nodes: readonly NodeId[]; edges: readonly string[] } = {
  nodes: [],
  edges: [],
};

function selectionSnapshot(selection: { nodes: readonly NodeId[]; edges: readonly string[] }): {
  nodes: readonly NodeId[];
  edges: readonly string[];
} {
  const nodes = selection.nodes;
  const edges = selection.edges;
  if (
    cachedSelection.nodes.length === nodes.length &&
    cachedSelection.edges.length === edges.length &&
    cachedSelection.nodes.every((id, index) => nodes[index] === id) &&
    cachedSelection.edges.every((id, index) => edges[index] === id)
  ) {
    return cachedSelection;
  }
  cachedSelection = { nodes, edges };
  return cachedSelection;
}

/**
 * A single node, re-reading whenever *that* node changes.
 *
 * Filtered by node id rather than subscribing to everything. With dozens of
 * cards on screen, an unfiltered subscription means every card re-renders on
 * every keystroke in any other card — and since cards measure themselves on
 * render, that turns into a measurement storm.
 */
export function useNode(nodeId: NodeId): AbstractNodeModel | undefined {
  const { workbench } = useWorkbenchValue();
  const [, force] = useState(0);

  useEffect(() => {
    const { model } = workbench;
    const bump = () => force((value) => value + 1);
    const forThisNode = (payload: { nodeId: NodeId }) => {
      if (payload.nodeId === nodeId) bump();
    };

    const offs = [
      model.on('node:data', forThisNode),
      model.on('node:title', forThisNode),
      model.on('node:runtime', forThisNode),
      model.on('node:resized', forThisNode),
      model.on('node:parent', forThisNode),
      // Link changes have no node id but affect a card's port indicators.
      // They are rare enough that a broad re-render costs nothing.
      model.on('edge:added', bump),
      model.on('edge:removed', bump),
    ];

    return () => offs.forEach((off) => off());
  }, [workbench, nodeId]);

  return workbench.model.node(nodeId);
}

/** Undo/redo availability, for toolbar enablement. */
/** The canvas flow direction, live — re-renders on toggle. Ticket 45. */
export function useFlowDirection(): FlowDirection {
  const { workbench } = useWorkbenchValue();
  const { preferences } = workbench;
  const [direction, setDirection] = useState<FlowDirection>(preferences.flowDirection);

  useEffect(
    () => preferences.onChange(() => setDirection(preferences.flowDirection)),
    [preferences],
  );

  return direction;
}

export function useHistoryState(): { canUndo: boolean; canRedo: boolean } {
  const { workbench } = useWorkbenchValue();
  const { history } = workbench.controller;
  const [state, setState] = useState({ canUndo: false, canRedo: false });

  useEffect(() => history.onChange(setState), [history]);

  return state;
}

/**
 * Ties this tab to one stored workflow: restore it, then keep it saved.
 *
 * Deliberately a *single* hook. It replaced two — an auto-save hook and an
 * auto-load hook — whose interaction was the bug:
 *
 *   1. the save hook minted a fresh `wf-<timestamp>` id whenever the session had
 *      none, and saved unconditionally on mount, so the seeded demo was written
 *      under a brand-new key;
 *   2. the load hook then imported the *most recent* workflow over the top;
 *   3. auto-save wrote that content under the new id as well.
 *
 * Every tab open therefore left another complete copy of the graph in storage.
 * Ordering them correctly is not enough — identity has to be resolved **once**,
 * before either behaviour runs, which is what `resolveSession` does.
 *
 * Restoring also clears the undo stack (`importJSON` must), so it happens at most
 * once per mount and never for a freshly minted id.
 *
 * **`report` is not optional decoration (UX-04).** Autosave used to call
 * `saveWorkflow` and *discard its outcome*, so a full quota — the one failure
 * that actually happens — left the user editing a document nothing was
 * recording, with no signal of any kind. A store that reports failures to a
 * caller that ignores them is a store that fails silently. Every path that can
 * lose work now ends in a sentence the user sees.
 */
export function useWorkflowSession(report: (message: string) => void = () => {}): {
  restored: boolean;
  workflowId: string | null;
} {
  const controller = useController();
  const workbench = useWorkbench();
  const [state, setState] = useState<{ restored: boolean; workflowId: string | null }>({
    restored: false,
    workflowId: null,
  });
  // StrictMode mounts effects twice; restoring twice would be visible.
  const done = useRef(false);
  // This tab's write identity, minted once and never regenerated: it is what
  // distinguishes "I wrote that" from "another tab did". A ref, filled inside
  // the effects rather than during render — it is mutable by design
  // (`lastSeenAt` advances with every write) and never read while rendering,
  // which is exactly what a ref is for and what React state is not.
  const writerRef = useRef<WriteGuard | null>(null);
  // One client for the life of the hook: a new one per autosave would build a
  // fresh base-url resolution on every keystroke.
  const diskClientRef = useRef<WorkflowFileClient | null>(null);
  // `report` is recreated by the toaster on every toast, and the restore
  // effect below must not re-run because of that.
  const reportRef = useRef(report);
  useEffect(() => {
    reportRef.current = report;
  }, [report]);

  useEffect(() => {
    if (done.current) return;
    done.current = true;
    const writer = (writerRef.current ??= newWriteGuard());

    // A deep link (`?w=<slug>`, ticket 20) names the document, so browser
    // storage supplies neither its content nor its id: restoring an autosave
    // over a workflow fetched from the backend would show a link's recipient
    // their own last canvas, and *adopting* the most recent autosave id would
    // then overwrite that stored graph with the fetched one. Minting is the
    // whole answer to both. `resolveOpenRequest` is what decides this is a
    // genuine arrival rather than a reload of the workflow already open here.
    const request = resolveOpenRequest({
      urlSlug: readSlugFromSearch(window.location.search),
      openSlug: getOpenSlug(),
    });

    // A deep link (`?w=<slug>`, ticket 20) names the document, so browser
    // storage supplies neither its content nor its id here: the load path owns
    // the content, and it decides between the file and this browser's draft of
    // that same slug (`workflowDrafts.restoreDraftFor`).
    //
    // The id, though, is now the *slug's* (ticket 23), not a fresh mint. A
    // minted id tied the draft to the tab rather than to the document, so
    // opening a second workflow pointed the one key at a different graph and
    // the first draft became unreachable — silent, unrecoverable, and with no
    // prompt. Keying on the slug is what makes coming back to a workflow come
    // back to your edits to *it*.
    if (request.action === 'fetch') {
      // Baseline the write guard against the draft this tab is about to be
      // handed by the load path. Without it the first autosave compares
      // itself against the previous page load's write, finds it newer, and
      // reports a conflict with a tab that does not exist — then stops saving.
      writer.lastSeenAt = draftSavedAt(request.slug, localStorage);
    }

    const session =
      request.action === 'fetch'
        ? { id: draftIdForSlug(request.slug), shouldRestore: false, notice: undefined }
        : resolveSession({
            sessionId: sessionStorage.getItem(SESSION_KEY),
            mostRecentId: mostRecentWorkflowId(localStorage),
            mintId: () => `wf-${Date.now()}`,
            // The clobber gate: a workflow another live tab is editing is not
            // adopted at all, so two tabs never share one autosave key.
            isClaimed: (id) => isClaimedByAnother(localStorage, id, writer),
          });
    if (session.notice != null) reportRef.current(session.notice);

    if (session.shouldRestore) {
      const outcome = readWorkflow(localStorage, session.id);
      if (outcome.status === 'corrupt') {
        // Recovered, not crashed: the seeded demo already on screen stays, the
        // bad bytes are quarantined by the reader, and the user is told —
        // which is the part that was missing when this returned a bare null.
        reportRef.current(outcome.reason);
      } else if (outcome.status === 'ok') {
        // Remember which version we restored. Without this the first autosave
        // cannot tell its own lineage from another tab's newer write.
        writer.lastSeenAt = outcome.savedAt;
        try {
          // Same ordering requirement as the named-file Load path: a
          // workflow-scoped node type must be registered *before* import, or
          // `fromJSON` silently skips every node of that type.
          registerNodeTypesForRawDocument(
            JSON.parse(outcome.json),
            workbench.registry,
            workbench.engine.executors,
          );
          controller.document.importJSON(outcome.json);
        } catch (error) {
          // A structurally valid envelope holding a document this build cannot
          // import. Same recovery, same duty to say so.
          const detail = error instanceof Error ? error.message : String(error);
          reportRef.current(
            `The autosaved workflow could not be restored (${detail}). ` +
              'The editor has started from a blank workflow; nothing was deleted.',
          );
        }
      }
    }

    sessionStorage.setItem(SESSION_KEY, session.id);
    claimSession(localStorage, session.id, writer);
    setState({ restored: session.shouldRestore, workflowId: session.id });
  }, [controller, workbench]);

  // The autosave key follows the open workflow for the rest of the session.
  //
  // Without this, ticket 23's other half stays open: an in-app Load replaces
  // the document but leaves the key pointing at the workflow the user just
  // left, so the very next debounced save writes the *new* graph over the
  // *old* one's draft. Re-keying is what keeps one draft per workflow rather
  // than one per tab.
  useEffect(
    () =>
      subscribeOpenSlug((slug) => {
        if (slug == null) return;
        const id = draftIdForSlug(slug);
        // Re-baseline for the same reason as the mount path above: the tab is
        // adopting a key whose stored version it has just been shown.
        const writer = (writerRef.current ??= newWriteGuard());
        writer.lastSeenAt = draftSavedAt(slug, localStorage);
        try {
          sessionStorage.setItem(SESSION_KEY, id);
        } catch {
          // Storage unavailable; the in-memory id below is still correct for
          // this session, which is what autosave actually writes under.
        }
        setState((previous) =>
          previous.workflowId === id ? previous : { ...previous, workflowId: id },
        );
      }),
    [],
  );

  // Saving starts only once identity is settled, so nothing is ever written
  // under a placeholder id.
  const workflowId = state.workflowId;
  useEffect(() => {
    if (workflowId == null) return;
    const writer = (writerRef.current ??= newWriteGuard());

    // The heartbeat behind `isClaimedByAnother`. A claim is refreshed while
    // this tab lives and goes stale when it does not, so a crashed tab cannot
    // lock a user out of their own workflow.
    claimSession(localStorage, workflowId, writer);
    const heartbeat = setInterval(
      () => claimSession(localStorage, workflowId, writer),
      CLAIM_HEARTBEAT_MS,
    );

    // Tell disk autosave what the file holds, for the one path that never
    // fetched it: a reload of the workflow already open in this tab restores
    // the browser draft instead of re-loading from the backend, so nothing
    // else would ever say what is on disk and the tab would (correctly, but
    // uselessly) refuse to save for the rest of its life.
    //
    // Gated on a document having actually been **restored** for this slug, and
    // that condition is doing real work rather than being cautious. A page
    // that seeds the demo instead — no draft to restore — can still find a
    // slug in `sessionStorage` from a previous visit. Baselining there would
    // hand autosave a package it is allowed to write while the model holds a
    // demo, and the next tick would write the demo into that package.
    const restoredSlug = state.restored ? getOpenSlug() : null;
    if (restoredSlug) {
      void ensureDiskBaseline(
        restoredSlug,
        (diskClientRef.current ??= new WorkflowFileClient()),
        workbench.serializer,
      );
    }

    let timer: ReturnType<typeof setTimeout> | null = null;
    // One complaint per distinct failure, not one per keystroke: autosave runs
    // on every edit, and a full quota would otherwise produce a toast per
    // second forever. Cleared by the next success, so a recovery is visible.
    let lastReported: string | null = null;
    let lastDiskReported: string | null = null;
    const schedule = () => {
      if (timer != null) clearTimeout(timer);
      timer = setTimeout(() => {
        const outcome = saveWorkflow(
          localStorage,
          workflowId,
          workbench.model,
          workbench.serializer,
          writer,
        );
        if (outcome.ok) {
          lastReported = null;
        } else if (outcome.kind !== lastReported) {
          lastReported = outcome.kind ?? 'error';
          reportRef.current(outcome.reason ?? 'This change was not autosaved.');
        }

        // …and to the package on disk, which is the copy a developer reads
        // with `git diff` and the one the CLI, the tests and the wheel run
        // (ticket 02). The browser draft stays: it is the crash-recovery
        // layer, and the only home a workflow has before its first save
        // mints a slug.
        //
        // `conflict` is the one failure that also stops the disk write:
        // another tab owns this document, and two tabs writing one package
        // file makes the last keystroke anywhere win, silently. `quota` and
        // `too-large` do not stop it — those are limits of *browser* storage,
        // and disk is precisely where such a workflow belongs.
        if (outcome.kind === 'conflict') return;
        //
        // Failures are reported once per distinct reason for the same reason
        // the storage ones are — this fires on every edit, and a backend that
        // is down would otherwise raise a toast per second.
        void writeOpenWorkflowToDisk(
          (diskClientRef.current ??= new WorkflowFileClient()),
          workbench.model,
          workbench.serializer,
          sessionStorage,
        ).then((disk) => {
          if (disk.kind !== 'failed') {
            lastDiskReported = null;
            return;
          }
          if (disk.reason === lastDiskReported) return;
          lastDiskReported = disk.reason;
          reportRef.current(`Not written to the workflow folder: ${disk.reason}`);
        });
      }, SAVE_DELAY_MS);
    };

    // No initial save: a mount is not an edit, and saving on mount is what
    // wrote the demo into storage under a fresh id.
    const off = controller.onChange(schedule);
    return () => {
      off();
      clearInterval(heartbeat);
      if (timer != null) clearTimeout(timer);
      releaseSession(localStorage, workflowId, writer);
    };
  }, [controller, workbench, workflowId, state.restored]);

  return state;
}

const SESSION_KEY = 'openstategraph-current-workflow-id';
const SAVE_DELAY_MS = 1000;
/** Comfortably inside `CLAIM_STALE_MS`, so a live tab is never mistaken for dead. */
const CLAIM_HEARTBEAT_MS = 10_000;
