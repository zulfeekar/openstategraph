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
import { loadWorkflow, mostRecentWorkflowId, resolveSession, saveWorkflow } from './workflowStore';
import { registerNodeTypesForRawDocument } from '@nodes/workflowScoped';

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
 */
export function useWorkflowSession(): { restored: boolean; workflowId: string | null } {
  const controller = useController();
  const workbench = useWorkbench();
  const [state, setState] = useState<{ restored: boolean; workflowId: string | null }>({
    restored: false,
    workflowId: null,
  });
  // StrictMode mounts effects twice; restoring twice would be visible.
  const done = useRef(false);

  useEffect(() => {
    if (done.current) return;
    done.current = true;

    const session = resolveSession({
      sessionId: sessionStorage.getItem(SESSION_KEY),
      mostRecentId: mostRecentWorkflowId(localStorage),
      mintId: () => `wf-${Date.now()}`,
    });

    if (session.shouldRestore) {
      const json = loadWorkflow(localStorage, session.id);
      // A missing or corrupt entry leaves the current document alone rather
      // than blanking the canvas.
      if (json != null) {
        try {
          // Same ordering requirement as the named-file Load path: a
          // workflow-scoped node type must be registered *before* import, or
          // `fromJSON` silently skips every node of that type.
          registerNodeTypesForRawDocument(
            JSON.parse(json),
            workbench.registry,
            workbench.engine.executors,
          );
          controller.document.importJSON(json);
        } catch (error) {
          // A corrupt autosave entry must not take the whole app down —
          // the seeded demo (already on screen) stays, same as the
          // missing-entry case just above.
          console.error('Could not restore the autosaved workflow:', error);
        }
      }
    }

    sessionStorage.setItem(SESSION_KEY, session.id);
    setState({ restored: session.shouldRestore, workflowId: session.id });
  }, [controller, workbench]);

  // Saving starts only once identity is settled, so nothing is ever written
  // under a placeholder id.
  const workflowId = state.workflowId;
  useEffect(() => {
    if (workflowId == null) return;

    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = () => {
      if (timer != null) clearTimeout(timer);
      timer = setTimeout(() => {
        saveWorkflow(localStorage, workflowId, workbench.model, workbench.serializer);
      }, SAVE_DELAY_MS);
    };

    // No initial save: a mount is not an edit, and saving on mount is what
    // wrote the demo into storage under a fresh id.
    const off = controller.onChange(schedule);
    return () => {
      off();
      if (timer != null) clearTimeout(timer);
    };
  }, [controller, workbench, workflowId]);

  return state;
}

const SESSION_KEY = 'dyflow-current-workflow-id';
const SAVE_DELAY_MS = 1000;
