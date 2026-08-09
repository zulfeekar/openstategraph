import { useCallback, useEffect, useState } from 'react';
import { WorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import {
  formatComposition,
  summarizeComposition,
  type CompositionKind,
} from '@core/runtime/compositionSummary';
import { peekDiagramId, peekMermaid } from '@core/runtime/mermaidPeek';
import { useWorkbench } from '@app/WorkbenchContext';
import { CURRENT_SLUG_KEY } from '@app/workflowFileWatch';
import { Pencil } from 'lucide-react';
import { Icon } from '@design/primitives';
import { loadWorkflowIntoEditor } from '@view/workflow/loadWorkflowIntoEditor';
import type { NodeBodyProps } from './nodeBodyRegistry';
import './CompositionBody.css';

/**
 * The composition annotation on a Team or Workflow card — collapsed to one
 * line, expandable to a peek at the graph inside.
 *
 * A mount is an opaque box *in the model*: its members live in another
 * document, they are not nodes of this canvas, and nothing here can edit them.
 * That boundary is what the original one-line census protected, and it still
 * holds — but opacity for the model is not the same as opacity for the reader.
 * A card reading `page-metrics-team · 1 supervisor · 2 workers` still leaves
 * "what actually happens in there" a question answerable only by loading
 * another document and losing your place.
 *
 * So the line becomes a disclosure. Expanded, it shows the child's **compiled**
 * topology — the same `draw_mermaid()` text `GraphPreview` renders, from the
 * same endpoint, rendered by the same lazily-imported Mermaid — scaled to the
 * card and made inert (`pointer-events: none`). Read-only is the whole point:
 * it is a peek, not a viewport, so no gesture inside it can reach the child's
 * document and the compile seam stays one-directional (we render text the
 * compiler emitted; we never read a runtime object back into the model).
 *
 * **Edit team** / **Edit workflow** is the honest way in: it runs the ordinary
 * load path, the very same `loadWorkflowIntoEditor` the Workflows panel uses.
 * Drilling in remains a navigation, not a zoom — ticket 56's recorded
 * follow-up, now with an affordance that says what it does and leaves a trail
 * (`drillStack`) so `DrillBanner` can say where you landed and get you back.
 */
/**
 * How many child nodes this mount overrides (docs/decisions/mount-overrides.md).
 * The annotation must say so — a group visual claiming the package default
 * while an override runs would be a lie about what executes.
 */
function overriddenCount(node: NodeBodyProps['node']): number {
  const raw = (node.getField<string>('overrides') ?? '').trim();
  if (!raw) return 0;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return Object.keys(parsed).length;
    }
  } catch {
    // Malformed JSON is the inspector validator's problem; the annotation
    // stays silent rather than guessing.
  }
  return 0;
}

function CompositionAnnotation({ node, kind }: NodeBodyProps & { kind: CompositionKind }) {
  const slug = (node.getField<string>('workflow') ?? '').trim();
  const [state, setState] = useState<SlugState>(() => CACHE.get(slug)?.settled ?? { status: 'loading' });
  const [expanded, setExpanded] = useState(false);

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

  return (
    <div className="node__composition">
      <div className="node__composition-row" data-no-drag>
        <button
          type="button"
          className="node__composition-toggle"
          aria-expanded={expanded}
          title={expanded ? 'Hide what is inside' : 'Peek inside this workflow'}
          onClick={() => setExpanded((value) => !value)}
        >
          <span className="node__composition-caret" aria-hidden="true">
            {expanded ? '▾' : '▸'}
          </span>
          {formatComposition(summary)}
          {overriddenCount(node) > 0 ? (
            <span
              className="node__composition-overridden"
              title="This mount overrides fields of the shared package (see the Overrides field in the inspector). Other mounts keep the package defaults."
            >
              {' '}
              · {overriddenCount(node)} overridden
            </span>
          ) : null}
        </button>
        <OpenMount slug={slug} kind={kind} />
      </div>
      {expanded ? <GraphPeek slug={slug} /> : null}
    </div>
  );
}

/**
 * The child's compiled topology, inside the card.
 *
 * Rendered only while expanded, so a canvas of collapsed mounts costs no
 * compile requests, and the Mermaid chunk is never fetched by a user who never
 * opens one.
 */
function GraphPeek({ slug }: { slug: string }) {
  const [state, setState] = useState<PeekState>(() => PEEKS.get(slug)?.settled ?? { status: 'loading' });

  useEffect(() => {
    let live = true;
    void resolvePeek(slug).then((next) => {
      if (live) setState(next);
    });
    return () => {
      live = false;
    };
  }, [slug]);

  if (state.status === 'loading') {
    return <div className="node__peek node__peek--note">compiling…</div>;
  }
  if (state.status === 'failed') {
    return (
      <div className="node__peek node__peek--note" role="note">
        {state.message}
      </div>
    );
  }
  return (
    <div
      className="node__peek"
      role="img"
      aria-label={`Compiled graph of ${slug}`}
      // Mermaid's own SVG output under `securityLevel: 'strict'` — the
      // documented way to mount it, same as `GraphPreview`.
      dangerouslySetInnerHTML={{ __html: state.svg }}
    />
  );
}

/**
 * Edit the referenced package — the honest way in.
 *
 * The label names the *thing*, not the mechanism. "Open" said nothing about
 * what opens, or that what opens is shared: a mount is a reference to one
 * definition, so editing it through this button changes every other mount of
 * it. "Edit team" / "Edit workflow" plus a tooltip that says *shared
 * definition* is the smallest wording that makes both facts visible before the
 * click rather than after it.
 *

 * Reaches the app through `useWorkbench()` — the context every card already
 * sits in — rather than a new prop on the body registry: the registry's
 * contract is deliberately just `{ node }`, and widening it for one body would
 * make every future body pay for this one's needs.
 *
 * There is no toast context, so a failure is reported in place rather than
 * invented plumbing to the shell's `Toaster`. Success needs no message: the
 * canvas becomes the other workflow, which is the loudest feedback available.
 */
function OpenMount({ slug, kind }: { slug: string; kind: CompositionKind }) {
  const workbench = useWorkbench();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const label = kind === 'team' ? 'Edit team' : 'Edit workflow';

  const open = useCallback(async () => {
    setBusy(true);
    // Provenance is read *before* the load, since the import replaces both
    // the current slug and the model's name with the child's.
    const fromSlug = sessionStorage.getItem(CURRENT_SLUG_KEY) ?? '';
    const fromName = workbench.model.name;
    const outcome = await loadWorkflowIntoEditor(slug, new WorkflowFileClient(), workbench, {
      fromSlug,
      fromName,
    });
    setBusy(false);
    setError(outcome.ok ? null : outcome.error);
  }, [slug, workbench]);

  return (
    <>
      <button
        type="button"
        className="node__composition-open"
        disabled={busy}
        title={`Opens ${slug} for editing — this is the shared definition, every mount of it is affected.`}
        onClick={() => void open()}
      >
        <Icon glyph={Pencil} size="xs" />
        {label}
      </button>
      {error ? (
        <span className="node__composition--missing" role="alert">
          {error}
        </span>
      ) : null}
    </>
  );
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

/* ================================================================== *
 * Per-slug compiled-graph peek cache
 * ================================================================== */

type PeekState =
  | { status: 'loading' }
  | { status: 'ready'; svg: string }
  | { status: 'failed'; message: string };

interface PeekEntry {
  readonly inFlight: Promise<PeekState>;
  settled?: PeekState;
}

/**
 * Same coalescing contract as `CACHE`, for a much more expensive answer: the
 * backend has to *compile* the workflow, and Mermaid has to lay it out. A card
 * re-renders on every drag, so without this an expanded peek would recompile
 * the child's graph continuously while its parent card was being moved.
 *
 * A failure is not cached — a compile that failed because the backend was
 * down must retry on the next expand rather than stick as a fact.
 */
const PEEKS = new Map<string, PeekEntry>();

/** Monotonic, so two cards on one canvas never share a Mermaid element id. */
let peekSequence = 0;

function resolvePeek(slug: string): Promise<PeekState> {
  const existing = PEEKS.get(slug);
  if (existing) return existing.inFlight;

  const inFlight = (async (): Promise<PeekState> => {
    const outcome = await new WorkflowFileClient().compiledGraph(slug);
    if (!outcome.ok) {
      PEEKS.delete(slug);
      return { status: 'failed', message: outcome.error };
    }
    try {
      const mermaid = (await import('mermaid')).default;
      mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'neutral' });
      const { svg } = await mermaid.render(
        peekDiagramId(slug, (peekSequence += 1)),
        peekMermaid(outcome.value),
      );
      return { status: 'ready', svg };
    } catch (error) {
      PEEKS.delete(slug);
      return {
        status: 'failed',
        message: `could not draw this graph: ${error instanceof Error ? error.message : String(error)}`,
      };
    }
  })();

  const entry: PeekEntry = { inFlight };
  PEEKS.set(slug, entry);
  void inFlight.then((settled) => {
    entry.settled = settled;
  });
  return inFlight;
}
