import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import type { Workbench } from './Workbench';
import type { WorkflowController } from '@controller/WorkflowController';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { NodeId } from '@core/model/contracts/node';
import type { WorkflowEvents } from '@core/model/contracts/workflow';
import type { PaperController } from '@canvas/PaperController';

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
  const value = useMemo<WorkbenchValue>(
    () => ({ workbench, paper, setPaper }),
    [workbench, paper],
  );
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
  useEffect(
    () => workbench.model.onAny(() => setVersion((value) => value + 1)),
    [workbench],
  );
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

function selectionSnapshot(selection: {
  nodes: readonly NodeId[];
  edges: readonly string[];
}): { nodes: readonly NodeId[]; edges: readonly string[] } {
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
export function useHistoryState(): { canUndo: boolean; canRedo: boolean } {
  const { workbench } = useWorkbenchValue();
  const { commands } = workbench.controller;
  const [state, setState] = useState({ canUndo: false, canRedo: false });

  useEffect(
    () =>
      commands.on('changed', ({ canUndo, canRedo }) => setState({ canUndo, canRedo })),
    [commands],
  );

  return state;
}
