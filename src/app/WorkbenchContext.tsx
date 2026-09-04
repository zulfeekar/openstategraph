import {
  baselineSlugAfterRestore,
  ensureDiskBaseline,
  writeOpenMountHostToDisk,
  writeOpenWorkflowToDisk,
  type DiskAutosaveOutcome,
} from '@app/diskAutosave';
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
  mostRecentWorkflowId,
  newWriteGuard,
  releaseSession,
  resolveSession,
  saveWorkflow,
  type WriteGuard,
} from './workflowStore';
import { getOpenSlug, readSlugFromSearch, resolveOpenRequest } from './openWorkflow';
import { formatMountAddress } from '@core/model/MountAddress';
import { getOpenAddress, openSubject } from './openAddress';
import {
  DRAFT_SESSION_KEY,
  draftIdForSlug,
  draftSavedAt,
  followAdoptedDraftKey,
  followOpenSubjectWithDraftKey,
  hasDraftFor,
  restoreSessionDraft,
  type DraftRestoreReport,
} from './workflowDrafts';
import { followOpenPackage } from './capabilityRefresh';
import {
  hasPlacedStarter,
  placeFirstRunStarter,
  refreshStarterNote,
  shouldPlaceStarter,
  starterReadinessOf,
} from './firstRunStarter';
import { serverReadiness } from '@core/providers/serverReadiness';

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
  restore: DraftRestoreReport;
  workflowId: string | null;
  /**
   * Whether *this* load handed over ticket 24's starter — not whether the
   * marker is set, which is true forever afterwards. The arrival offer
   * (`install-experience` 28) stands aside on exactly the one visit 24 owns,
   * and only this effect can tell that visit from every later one.
   */
  placedStarter: boolean;
} {
  const controller = useController();
  const workbench = useWorkbench();
  const [state, setState] = useState<{
    restore: DraftRestoreReport;
    workflowId: string | null;
    placedStarter: boolean;
  }>({
    restore: { restored: false },
    workflowId: null,
    placedStarter: false,
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
    // Ticket 49: with no draft under the open slug's key, "restore this tab's
    // autosave" restores nothing and the canvas stays blank. Both startup hooks
    // ask the same question of the same storage so they keep agreeing in
    // advance about which of them owns the document.
    // The **address**, not the class slug — `openSubject` carries the whole
    // argument. `CURRENT_SLUG_KEY` holds `chinook-assistant` while the URL
    // holds `concierge/wf-music`, so comparing against it called every reload
    // of an open mount a fresh arrival, while the address hook next door
    // called the same load a reload. Both then stood aside and the canvas came
    // up with no document at all (`production-ready` 07).
    const openSlug = openSubject({
      openAddress: (() => {
        const open = getOpenAddress();
        return open === null ? null : formatMountAddress(open);
      })(),
      classSlug: getOpenSlug(),
    });
    const request = resolveOpenRequest({
      urlSlug: readSlugFromSearch(window.location.search),
      openSlug,
      hasDraft: hasDraftFor(openSlug, localStorage),
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

    // Read once, before anything below can write: it is both an input to
    // `resolveSession` and the evidence `shouldPlaceStarter` uses to tell a
    // browser that has never held work from one that has.
    const mostRecentId = mostRecentWorkflowId(localStorage);

    const session =
      request.action === 'fetch'
        ? { id: draftIdForSlug(request.slug), shouldRestore: false, notice: undefined }
        : resolveSession({
            sessionId: sessionStorage.getItem(DRAFT_SESSION_KEY),
            mostRecentId,
            mintId: () => `wf-${Date.now()}`,
          });
    if (session.notice != null) reportRef.current(session.notice);

    // What actually reached the canvas, not what we set out to do
    // (`production-ready` 71). The two differ exactly when the draft is gone —
    // cleared site data, an eviction, a key never migrated — and the
    // difference used to be a package overwritten by a blank document.
    const restore = restoreSessionDraft(session, workbench, writer, localStorage);
    if (restore.notice != null) reportRef.current(restore.notice);

    // **The first visit, and only the first** (`install-experience` 24). A
    // browser holding no draft and no marker has never opened this editor, and
    // an empty canvas beside twenty node types teaches nothing; it is handed
    // Input → Agent → Output with a Note saying what they are.
    //
    // Deliberately *after* every decision above, and gated on all of them: 23
    // is the ticket that removed a document from this canvas, and the way back
    // into its defect is placing anything before knowing that the URL named
    // nothing, this tab restored nothing, and nobody's draft is in this
    // browser. What goes on is nobody's — four nodes composed here — unsaved,
    // `Untitled`, one undo away and one delete away, and never offered twice.
    const placedStarter = shouldPlaceStarter({
      opening: request.action,
      restored: restore.restored,
      nodeCount: workbench.model.nodeCount,
      mostRecentId,
      alreadyPlaced: hasPlacedStarter(localStorage),
    });
    if (placedStarter) {
      // With whatever the shared readiness already holds — usually `null`, as
      // the health poll rarely beats the first paint. The listener below is
      // what makes that acceptable rather than a wrong note that stays wrong.
      placeFirstRunStarter(workbench, localStorage, starterReadinessOf(serverReadiness));
    }

    sessionStorage.setItem(DRAFT_SESSION_KEY, session.id);
    claimSession(localStorage, session.id, writer);
    setState({ restore, workflowId: session.id, placedStarter });
  }, [controller, workbench]);

  /**
   * The first visit's note catches up with the server (`stable-beta-public/06`,
   * slice 3).
   *
   * Readiness is read at placement, and on first paint it is almost always
   * `null`: `/api/health` is in flight while the canvas is drawn. So the note
   * a stranger meets says *press Run*, and if the answer that lands says
   * nothing can run, that invitation has become false. One listener on the
   * shared source — the same one the top bar's health dot publishes into —
   * rewrites it, in either direction, and only while the note is still
   * carrying its marker.
   *
   * Here rather than in a component, because every component that could hold
   * it unmounts: the note outlives any panel, and a subscription that goes
   * with a closed chat is a note that stops catching up. Unconditional, and
   * cheap: `refreshStarterNote` is a walk of the nodes that returns `false` on
   * every canvas that is not a still-awaiting starter.
   */
  useEffect(
    () =>
      serverReadiness.onChange(() =>
        refreshStarterNote(workbench, starterReadinessOf(serverReadiness)),
      ),
    [workbench],
  );

  // The autosave key follows the open workflow for the rest of the session.
  //
  // Without this, ticket 23's other half stays open: an in-app Load replaces
  // the document but leaves the key pointing at the workflow the user just
  // left, so the very next debounced save writes the *new* graph over the
  // *old* one's draft. Re-keying is what keeps one draft per workflow rather
  // than one per tab.
  //
  // **Including when there is nothing open.** `clearOpenSlug` announces `null`
  // — the gesture behind `New` — and this listener used to answer it with a
  // bare `return`, so the new document went on autosaving as the *previous*
  // package's unsaved edits and was restored over it next visit
  // (`production-ready` 77). The rule, null case and all, lives in
  // `followOpenSubjectWithDraftKey`, where it can be tested through the real
  // channel with no DOM.
  useEffect(
    () =>
      followOpenSubjectWithDraftKey(
        (writerRef.current ??= newWriteGuard()),
        (id) =>
          setState((previous) =>
            previous.workflowId === id ? previous : { ...previous, workflowId: id },
          ),
        localStorage,
      ),
    [],
  );

  // The other way this tab's autosave key moves — a draft recovered by name
  // from *Unsaved in this browser* (`install-experience` 23). Without this the
  // recovered document would go on screen while the tab kept writing under the
  // key it minted at startup, leaving a second entry holding the same graph.
  useEffect(
    () =>
      followAdoptedDraftKey(
        (writerRef.current ??= newWriteGuard()),
        (id) =>
          setState((previous) =>
            previous.workflowId === id ? previous : { ...previous, workflowId: id },
          ),
        localStorage,
      ),
    [],
  );

  // The same announcement, answered by the other thing that was keyed to the
  // workflow the user just left: the palette's "This workflow" section
  // (`production-ready` 75). `clearOpenSlug` is followed by no fetch, because
  // there is nothing to fetch, so without this the blank canvas **New** hands
  // over goes on offering the previous package's discovered tools as its own.
  useEffect(() => followOpenPackage(), []);

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
    const restoredSlug = baselineSlugAfterRestore(state.restore, getOpenSlug());
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
        const reportDisk = (disk: DiskAutosaveOutcome) => {
          if (disk.kind !== 'failed') {
            lastDiskReported = null;
            return;
          }
          if (disk.reason === lastDiskReported) return;
          lastDiskReported = disk.reason;
          reportRef.current(`Not written to the workflow folder: ${disk.reason}`);
        };

        const client = (diskClientRef.current ??= new WorkflowFileClient());
        void writeOpenWorkflowToDisk(
          client,
          workbench.model,
          workbench.serializer,
          sessionStorage,
        ).then(reportDisk);

        // The other document an edit can belong to. While a mount is open the
        // call above writes nothing — what is on screen is derived, and
        // writing it back to the package would burn one instance's overrides
        // into the shared definition. The override itself lives on the
        // **host's** mount node, and until ticket 44 nothing wrote that
        // either: the inspector badged the field `overridden` and `Back`
        // discarded it. Both are called on every tick; exactly one of them
        // ever has somewhere to write.
        void writeOpenMountHostToDisk(client, controller.document.mountContext() ?? null).then(
          reportDisk,
        );
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
  }, [controller, workbench, workflowId, state.restore]);

  return state;
}

const SAVE_DELAY_MS = 1000;
/** Comfortably inside `CLAIM_STALE_MS`, so a live tab is never mistaken for dead. */
const CLAIM_HEARTBEAT_MS = 10_000;
