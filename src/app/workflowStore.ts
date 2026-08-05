import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { WorkflowSerializer } from '@core/serialization/WorkflowSerializer';

/**
 * Browser-local workflow storage.
 *
 * A stopgap until the Python backend owns persistence (tickets 07/10/16), but a
 * stopgap that can lose a user's work, so it is built to be tested rather than
 * hoped about. Everything takes an injectable `Storage`, which is the whole
 * reason this file exists separately from the React hooks: the previous version
 * called `localStorage` directly at module scope and was therefore untestable in
 * a node environment, and consequently untested.
 */

export const STORAGE_PREFIX = 'dyflow-workflow-';

/** Just the slice of `Storage` used here, so a test can supply a Map. */
export interface KeyValueStore {
  readonly length: number;
  key(index: number): string | null;
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export interface SavedWorkflow {
  readonly id: string;
  readonly name: string;
  readonly savedAt: string;
}

export interface SaveOutcome {
  readonly ok: boolean;
  readonly reason?: string;
}

const keyFor = (id: string): string => `${STORAGE_PREFIX}${id}`;

/**
 * Writes a workflow.
 *
 * Returns an outcome instead of swallowing failures into a `console.error`.
 * The realistic failure is the ~5MB quota, and a silent quota failure is the
 * worst possible behaviour for a feature whose entire purpose is not losing
 * work — the user keeps editing, believing it is saved.
 */
export function saveWorkflow(
  store: KeyValueStore,
  id: string,
  model: WorkflowModel,
  serializer: WorkflowSerializer,
  now: () => string = () => new Date().toISOString(),
): SaveOutcome {
  try {
    const payload = JSON.stringify({
      version: 1,
      savedAt: now(),
      workflowId: id,
      name: model.name,
      workflow: JSON.parse(serializer.toJSONString(model)),
    });
    store.setItem(keyFor(id), payload);
    return { ok: true };
  } catch (error) {
    const reason = error instanceof Error ? error.message : 'Unknown storage error';
    return { ok: false, reason };
  }
}

/** Reads a workflow back as the JSON string `importJSON` expects. */
export function loadWorkflow(store: KeyValueStore, id: string): string | null {
  const raw = store.getItem(keyFor(id));
  if (raw == null) return null;
  try {
    const payload = JSON.parse(raw) as Record<string, unknown>;
    if (payload['workflow'] != null) return JSON.stringify(payload['workflow']);
    // An entry written before the envelope existed is the document itself.
    if (payload['nodes'] != null || payload['edges'] != null) return raw;
    return null;
  } catch {
    // A corrupt entry must not take the app down on startup.
    return null;
  }
}

/**
 * Every saved workflow, newest first.
 *
 * A single unreadable entry is skipped rather than failing the listing — one
 * bad key should not make the whole manager panel empty.
 */
export function listWorkflows(store: KeyValueStore): SavedWorkflow[] {
  const found: SavedWorkflow[] = [];
  for (let i = 0; i < store.length; i += 1) {
    const key = store.key(i);
    if (key == null || !key.startsWith(STORAGE_PREFIX)) continue;
    const raw = store.getItem(key);
    if (raw == null) continue;
    try {
      const payload = JSON.parse(raw) as { name?: unknown; savedAt?: unknown };
      found.push({
        id: key.slice(STORAGE_PREFIX.length),
        name: typeof payload.name === 'string' ? payload.name : 'Untitled workflow',
        savedAt: typeof payload.savedAt === 'string' ? payload.savedAt : '',
      });
    } catch {
      continue;
    }
  }
  return found.sort((a, b) => b.savedAt.localeCompare(a.savedAt));
}

export function deleteWorkflow(store: KeyValueStore, id: string): void {
  store.removeItem(keyFor(id));
}

export function mostRecentWorkflowId(store: KeyValueStore): string | null {
  return listWorkflows(store)[0]?.id ?? null;
}

/**
 * Decides which workflow this tab is editing, and whether to restore it.
 *
 * This is the fix for a compounding defect, so it is worth stating what went
 * wrong. Previously the save hook **minted a fresh `wf-<timestamp>` id whenever
 * the session had none**, and separately performed an unconditional "initial
 * save" on mount. The load hook then imported the *most recent* workflow. The
 * result, on every new tab:
 *
 *   1. a new id is minted,
 *   2. the seeded demo is saved under it,
 *   3. some older workflow is imported over the top,
 *   4. autosave writes *that* content under the new id as well.
 *
 * So each tab open left another full copy of the graph in `localStorage`, keyed
 * by a fresh id, forever. Adopting the existing id instead of minting is what
 * stops the duplication.
 *
 * `shouldRestore` is false for a freshly minted id: there is nothing to restore,
 * and importing over the default document would clear the undo stack for nothing.
 */
export function resolveSession(input: {
  sessionId: string | null;
  mostRecentId: string | null;
  mintId: () => string;
}): { id: string; shouldRestore: boolean } {
  if (input.sessionId != null && input.sessionId !== '') {
    return { id: input.sessionId, shouldRestore: true };
  }
  if (input.mostRecentId != null && input.mostRecentId !== '') {
    // Adopt rather than mint. Two tabs then share an id and the last write
    // wins, which is a smaller problem than unbounded duplicate entries.
    return { id: input.mostRecentId, shouldRestore: true };
  }
  return { id: input.mintId(), shouldRestore: false };
}
