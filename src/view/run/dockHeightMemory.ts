import { clampDockHeight, DOCK_DEFAULT_HEIGHT } from '../layout/dockFit';

const KEY = 'openstategraph.run-dock-height';

/**
 * How tall this person likes the run dock, remembered between loads.
 *
 * **Per viewer, not per workflow, and not per run.** A dock height is a fact
 * about the screen somebody is sitting in front of — the same class of thing
 * as the theme, which `AppShell` already stores exactly this way. Keying it by
 * workflow would mean a developer who set the dock the way they like it got it
 * back on one document and not on the next, which is a preference that has
 * stopped being one.
 *
 * `localStorage` is per-viewer and it *throws* — a private window, a browser
 * set to block site data, a thumbnail capture — so both directions are wrapped
 * and a failure degrades to the default for this load. Never to a crash on a
 * drag.
 *
 * Storage and the window's height are injected with browser defaults, the
 * shape `PreferencesStore` and `workflowStore` already use here, so the whole
 * of this is decidable in the `node` environment the suite runs in rather than
 * needing a DOM shim to say anything about it.
 */
export function readDockHeight(
  storage: Storage | null = defaultStorage(),
  shellHeight: number = defaultHeight(),
): number {
  try {
    const stored = storage?.getItem(KEY) ?? null;
    if (stored === null || stored.trim() === '') return DOCK_DEFAULT_HEIGHT;
    const parsed = Number(stored);
    // Read through the same clamp a drag goes through: a stored value can
    // outlive the window it was set in — a laptop undocked from a large
    // monitor — and a height nobody can see is worse than one nobody chose.
    // The shell clamps again against its own measured height once it has one;
    // this is the most that is known before layout.
    return Number.isFinite(parsed) ? clampDockHeight(parsed, shellHeight) : DOCK_DEFAULT_HEIGHT;
  } catch {
    return DOCK_DEFAULT_HEIGHT;
  }
}

export function rememberDockHeight(
  height: number,
  storage: Storage | null = defaultStorage(),
): void {
  try {
    storage?.setItem(KEY, String(Math.round(height)));
  } catch {
    // Storage unavailable — the height still holds for this session.
  }
}

function defaultStorage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

function defaultHeight(): number {
  return typeof window === 'undefined' ? DOCK_DEFAULT_HEIGHT * 4 : window.innerHeight;
}
