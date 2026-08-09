import { useEffect, useState } from 'react';
import { WorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import {
  formatComposition,
  summarizeComposition,
  type CompositionKind,
} from '@core/runtime/compositionSummary';
import type { NodeBodyProps } from './nodeBodyRegistry';
import './CompositionBody.css';

/**
 * The composition annotation on a Team or Workflow card.
 *
 * A mount is an opaque box by design — its members live in another document
 * and drilling in is a load, not a zoom. The cost of that opacity is that a
 * card reading only `page-metrics-team` says nothing about what is inside, so
 * this restores exactly one line of it: a census of the referenced document,
 * derived by the pure `summarizeComposition` and merely *displayed* here.
 *
 * Deliberately not a preview: no thumbnail, no member list, nothing
 * clickable. The moment a card tries to show the graph inside it, the box
 * stops being a box and the composition boundary starts leaking into the
 * parent canvas.
 */
function CompositionAnnotation({ node, kind }: NodeBodyProps & { kind: CompositionKind }) {
  const slug = (node.getField<string>('workflow') ?? '').trim();
  const [state, setState] = useState<SlugState>(() => CACHE.get(slug)?.settled ?? { status: 'loading' });

  useEffect(() => {
    if (!slug) return;
    let live = true;
    void resolveSlug(slug).then((next) => {
      if (live) setState(next);
    });
    return () => {
      live = false;
    };
  }, [slug]);

  // Nothing while unset: an unconfigured mount has no composition to describe,
  // and a placeholder there would read as a failure rather than an empty field.
  if (!slug) return null;
  if (state.status === 'missing') {
    return <div className="node__composition node__composition--missing">unknown workflow: {slug}</div>;
  }
  if (state.status !== 'ready') return null;

  const summary = summarizeComposition(state.document, kind);
  if (!summary) return null;
  return <div className="node__composition">{formatComposition(summary)}</div>;
}

/** Ticket vocabulary: a Team claims its loop, a Workflow mount does not. */
export const TeamCompositionBody = (props: NodeBodyProps) => (
  <CompositionAnnotation {...props} kind="team" />
);

export const SubgraphCompositionBody = (props: NodeBodyProps) => (
  <CompositionAnnotation {...props} kind="subgraph" />
);

/* ================================================================== *
 * Per-slug cache
 * ================================================================== */

type SlugState =
  | { status: 'loading' }
  | { status: 'ready'; document: unknown }
  | { status: 'missing' }
  | { status: 'unreachable' };

interface CacheEntry {
  readonly inFlight: Promise<SlugState>;
  settled?: SlugState;
}

/**
 * One fetch per slug, shared by every card referencing it.
 *
 * Two mounts of the same team on one canvas (Page Analytics has exactly
 * that) would otherwise each hit the backend on every re-render, and a card
 * re-renders on every drag. The in-flight promise is cached, not just the
 * result, so concurrent mounts coalesce into one request.
 *
 * A failure to *reach* the runtime is cached only until the next slug change:
 * it is not a fact about the document, so it must not stick.
 */
const CACHE = new Map<string, CacheEntry>();

function resolveSlug(slug: string): Promise<SlugState> {
  const existing = CACHE.get(slug);
  if (existing) return existing.inFlight;

  const inFlight = new WorkflowFileClient().loadIfPresent(slug).then((result): SlugState => {
    if (!result.ok) {
      CACHE.delete(slug);
      return { status: 'unreachable' };
    }
    return result.value == null ? { status: 'missing' } : { status: 'ready', document: result.value };
  });

  const entry: CacheEntry = { inFlight };
  CACHE.set(slug, entry);
  void inFlight.then((settled) => {
    entry.settled = settled;
  });
  return inFlight;
}

/** Test/dev seam: forget everything, e.g. after a workflow is saved. */
export function clearCompositionCache(): void {
  CACHE.clear();
}
