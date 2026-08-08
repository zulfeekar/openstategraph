import { useEffect, useRef } from 'react';
import {
  WorkflowFileClient,
  type ToolCapability,
  type WorkflowSummary,
} from '@core/runtime/WorkflowFileClient';
import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { Registry } from '@core/kernel/Registry';
import type { INodeExecutor } from '@core/execution/INodeExecutor';
import { registerDiscoveredCapabilities } from '@nodes/workflowScoped';

/**
 * The slug of whichever saved workflow this tab currently has open —
 * `sessionStorage`, not the model, so a rename changes the display name
 * only, never the directory (ticket 14's identity decision).
 */
export const CURRENT_SLUG_KEY = 'openstategraph-current-workflow-slug';

/**
 * The `savedAt` this tab itself last wrote or read for a slug — a plain
 * module-level map, not persisted, because a full page reload re-restores
 * everything through `useWorkflowSession` and the watch below re-baselines
 * on its first poll with no false positive either way.
 */
const knownSavedAt = new Map<string, string>();

export function recordKnownSavedAt(slug: string, savedAt: string | undefined): void {
  if (savedAt) knownSavedAt.set(slug, savedAt);
}

export function forgetKnownSavedAt(slug: string): void {
  knownSavedAt.delete(slug);
}

/** Exposed for tests — the hook itself reads the map directly. */
export function getKnownSavedAt(slug: string): string | undefined {
  return knownSavedAt.get(slug);
}

/**
 * The tool capability ids this tab last knew for a slug — separate from
 * `knownSavedAt` because a new file dropped into `tools/` does not change
 * `workflow.json`'s own `savedAt` at all; the two must be tracked and
 * polled independently.
 */
const knownCapabilityIds = new Map<string, readonly string[]>();

export type CapabilityRefreshAction =
  | { readonly kind: 'baseline'; readonly ids: readonly string[] }
  | { readonly kind: 'unchanged' }
  | {
      readonly kind: 'changed';
      readonly ids: readonly string[];
      readonly added: readonly string[];
    };

/**
 * Ticket 18's hot-reload gap, closed with the polling infrastructure this
 * file already runs rather than new backend wiring: the ticket's own
 * design sketched an SSE "capabilities changed" push, but reusing the
 * existing 5s poll achieves the same user-visible outcome (the palette
 * picks up a newly-dropped `tools/*.py` file without a manual re-Load)
 * with no new endpoint. Pure decision, same reasoning as
 * `decideFileWatchAction`: order-independent (`Set`, not array-equality)
 * because the backend's own discovery order has no promised stability.
 */
export function decideCapabilityRefresh(
  fresh: readonly ToolCapability[],
  known: readonly string[] | undefined,
): CapabilityRefreshAction {
  const ids = fresh.map((c) => c.id);
  if (known === undefined) return { kind: 'baseline', ids };

  const knownSet = new Set(known);
  const freshSet = new Set(ids);
  const same = knownSet.size === freshSet.size && [...knownSet].every((id) => freshSet.has(id));
  if (same) return { kind: 'unchanged' };

  const added = ids.filter((id) => !knownSet.has(id));
  return { kind: 'changed', ids, added };
}

export type FileWatchAction =
  | { readonly kind: 'none' }
  | { readonly kind: 'baseline'; readonly savedAt: string }
  | { readonly kind: 'notify-deleted' }
  | { readonly kind: 'notify-changed' };

/**
 * The pure decision behind one poll: given what the backend currently
 * reports for `slug` and what this tab last knew, what should happen.
 * Pulled out of the hook below so it is testable without a timer, a
 * network stub, or React — the same reasoning `ExecutionEngine`'s
 * `rejectBeforeStart` split applies to its own side effect.
 */
export function decideFileWatchAction(
  entries: readonly WorkflowSummary[],
  slug: string,
  known: string | undefined,
): FileWatchAction {
  const entry = entries.find((wf) => wf.slug === slug);
  if (!entry) return { kind: 'notify-deleted' };
  if (known === undefined) return { kind: 'baseline', savedAt: entry.savedAt };
  if (entry.savedAt !== known) return { kind: 'notify-changed' };
  return { kind: 'none' };
}

const POLL_INTERVAL_MS = 5000;

/**
 * Ticket 16's other half, plus ticket 18's hot-reload gap, sharing one poll
 * loop since both are "did something change on disk under this open
 * workflow":
 *
 * **Document changes** (ticket 16) — `WorkflowManager` already writes
 * files; nothing noticed when a file changed *underneath* an open editor —
 * another tab saving the same slug, a teammate's pull, a hand-edit. Compares
 * the workflow list's `savedAt` against the value this tab itself last
 * recorded (`recordKnownSavedAt`, called by `WorkflowManager` after every
 * successful save or load) — so this tab's own writes never self-trigger
 * the notice, only a change this tab did not make. Deliberately
 * notify-only, never auto-reload or merge — silently discarding unsaved
 * local edits to pull in an external change is a worse failure than asking
 * the user to reload by hand via the existing "Manage Workflows" panel.
 *
 * **Capability changes** (ticket 18) — a new or edited file in the
 * workflow's `tools/` folder doesn't touch `workflow.json` at all, so it
 * needs its own comparison, but the same poll cadence answers it: has the
 * backend's discovered-tool list changed since the last check. This one
 * *is* safe to apply automatically and silently — registering a node type
 * is additive, non-destructive, and does not touch the open document the
 * way reloading it would.
 *
 * Mounted once, independent of whether "Manage Workflows" happens to be
 * open, since either kind of change can land at any time.
 */
export function useWorkflowFileWatch(
  onNotify: (message: string) => void,
  registry: ModelRegistry,
  executors: Registry<INodeExecutor>,
): void {
  const clientRef = useRef<WorkflowFileClient | null>(null);
  if (!clientRef.current) clientRef.current = new WorkflowFileClient();

  useEffect(() => {
    const client = clientRef.current;
    if (!client) return;
    let cancelled = false;

    const poll = async () => {
      const slug = sessionStorage.getItem(CURRENT_SLUG_KEY);
      if (!slug) return;

      const outcome = await client.list();
      if (!cancelled && outcome.ok) {
        const action = decideFileWatchAction(outcome.value, slug, knownSavedAt.get(slug));
        switch (action.kind) {
          case 'baseline':
            knownSavedAt.set(slug, action.savedAt);
            break;
          case 'notify-deleted':
            onNotify(
              'This workflow was deleted on disk — your open copy is no longer backed by a saved file.',
            );
            break;
          case 'notify-changed':
            onNotify(
              'This workflow changed on disk — open Manage Workflows and Load it to see the latest version.',
            );
            break;
          case 'none':
            break;
        }
      }

      // A workflow with no `tools/` folder 404s or returns an empty list —
      // either way, an unsuccessful fetch means "nothing to refresh", not
      // an error worth surfacing; ticket 18's discovery endpoint already
      // treats an absent folder as empty, not a failure, for exactly this.
      const capOutcome = await client.capabilities(slug);
      if (cancelled) return;
      const tools = capOutcome.ok ? capOutcome.value.tools : [];
      const capAction = decideCapabilityRefresh(tools, knownCapabilityIds.get(slug));
      switch (capAction.kind) {
        case 'baseline':
          knownCapabilityIds.set(slug, capAction.ids);
          registerDiscoveredCapabilities(tools, registry, executors);
          break;
        case 'changed':
          knownCapabilityIds.set(slug, capAction.ids);
          registerDiscoveredCapabilities(tools, registry, executors);
          if (capAction.added.length > 0) {
            onNotify(
              capAction.added.length === 1
                ? `Discovered a new tool: ${capAction.added[0]}`
                : `Discovered ${capAction.added.length} new tools`,
            );
          }
          break;
        case 'unchanged':
          break;
      }
    };

    const timer = window.setInterval(() => void poll(), POLL_INTERVAL_MS);
    void poll();
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [onNotify, registry, executors]);
}
