import type { FlowDirection } from '@core/model/contracts/ports';

const FLOW_DIRECTION_KEY = 'openstategraph.flow-direction';
const FOLLOW_RUN_KEY = 'openstategraph.follow-run';

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
  private _followRun: boolean;

  constructor(private readonly storage: Storage | null = defaultStorage()) {
    this._flowDirection = readFlowDirection(this.storage);
    this._followRun = readFollowRun(this.storage);
  }

  get flowDirection(): FlowDirection {
    return this._flowDirection;
  }

  /**
   * Whether the camera follows whatever is running. **On by default.**
   *
   * It was off, and the consequence was that the whole follow-and-focus
   * mechanism — built, tuned and unit-tested — never fired for anyone who had
   * not found the toolbar toggle. A canvas that watches a graph run is the
   * reason to watch a graph on a canvas at all; making that opt-in was
   * shipping the feature switched off.
   *
   * Safe as a default only because the follower already surrenders to the
   * first real gesture (`RunFollower`): a default that fought the user for
   * the camera would be worse than one nobody found.
   */
  get followRun(): boolean {
    return this._followRun;
  }

  setFollowRun(followRun: boolean): void {
    if (followRun === this._followRun) return;
    this._followRun = followRun;
    try {
      this.storage?.setItem(FOLLOW_RUN_KEY, followRun ? 'on' : 'off');
    } catch {
      // Session-only fallback, exactly as above.
    }
    for (const listener of [...this.listeners]) listener();
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

/**
 * Only an explicit `off` turns following off.
 *
 * Deliberately asymmetric with `readFlowDirection`, which has two equal
 * options: here one value is the default and the stored entry exists purely
 * to record a person having opted out. So an absent key, a corrupt key and a
 * throwing storage all mean the same thing — follow — and no upgrade path is
 * needed for the people who never had the key.
 */
function readFollowRun(storage: Storage | null): boolean {
  try {
    return storage?.getItem(FOLLOW_RUN_KEY) !== 'off';
  } catch {
    return true;
  }
}
