import type { FlowDirection } from '@core/model/contracts/ports';

const FLOW_DIRECTION_KEY = 'openstategraph.flow-direction';

/**
 * User preferences — chrome-level choices that belong to the person, not the
 * document (ticket 45). The canvas flow direction lives here; a
 * workflow-level override, when one exists, comes from `workflow.settings`
 * and wins.
 *
 * Framework-free and storage-injectable, following `workflowStore.ts`'s
 * shape, so it unit-tests without a browser. A throwing storage (private
 * browsing) degrades to session-only memory — a preference that does not
 * survive a reload is better than a crash on toggle.
 */
export class PreferencesStore {
  private readonly listeners = new Set<() => void>();
  private _flowDirection: FlowDirection;

  constructor(private readonly storage: Storage | null = defaultStorage()) {
    this._flowDirection = readFlowDirection(this.storage);
  }

  get flowDirection(): FlowDirection {
    return this._flowDirection;
  }

  setFlowDirection(direction: FlowDirection): void {
    if (direction === this._flowDirection) return;
    this._flowDirection = direction;
    try {
      this.storage?.setItem(FLOW_DIRECTION_KEY, direction);
    } catch {
      // Session-only fallback; the in-memory value above still holds.
    }
    for (const listener of [...this.listeners]) listener();
  }

  onChange(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}

function defaultStorage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

function readFlowDirection(storage: Storage | null): FlowDirection {
  try {
    const stored = storage?.getItem(FLOW_DIRECTION_KEY);
    // An unrecognised value is a default, never an error — the store must
    // not crash the app over a hand-edited localStorage entry.
    return stored === 'vertical' ? 'vertical' : 'horizontal';
  } catch {
    return 'horizontal';
  }
}
