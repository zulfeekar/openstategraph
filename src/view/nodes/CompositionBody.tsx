import { useCallback, useEffect, useState } from 'react';
import { WorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import { SlugCache } from '@core/runtime/SlugCache';
import { peekDiagramId, peekMermaid } from '@core/runtime/mermaidPeek';
import { useWorkbench } from '@app/WorkbenchContext';
import { CURRENT_SLUG_KEY } from '@app/workflowFileWatch';
import { getOpenAddress } from '@app/openAddress';
import { childAddress, parseMountAddress } from '@core/model/MountAddress';
import { Pencil } from 'lucide-react';
import { Icon } from '@design/primitives';
import { loadMountIntoEditor } from '@view/workflow/loadWorkflowIntoEditor';
import { compositionSurface, type MountDocumentState } from './compositionSurface';
import type { NodeBody, NodeBodyProps } from './nodeBodyRegistry';
import './CompositionBody.css';

/**
 * The composition annotation on a Team or Workflow card — collapsed to one
 * line, expandable to a peek at the graph inside.
 *
 * A mount is an opaque box *in the model*: its members live in another
 * document, they are not nodes of this canvas, and nothing here can edit them.
 * That boundary is what the original one-line census protected, and it still
 * holds — but opacity for the model is not the same as opacity for the reader.
 * A card reading `sourcing-team · 1 supervisor · 2 workers` still leaves
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
 * **Open this mount** is the honest way in, and since ticket 42 it opens *this
 * instance* rather than the shared package: the address it navigates to is
 * `<here>/<this node's id>`, so two mounts of one workflow are two documents
 * with their own overrides. Drilling in remains a navigation, not a zoom — but
 * the address now says which mount you are inside, so a reload comes back to
 * the same one and the trail is derivable from it rather than remembered.
 *
 * ## One early return, and there must never be a second
 *
 * Everything this component decides beyond "what did the fetch say" is decided
 * by `compositionSurface`, which is pure and tested. The regression that put it
 * there (ticket 43) was not a deletion: **Open this mount** was written as a
 * *child* of the census, and four of the five states a slug can be in returned
 * `null` before reaching it — so an unsaved package, an empty child or a
 * restarting runtime produced a mount card with no way into it and nothing
 * saying why. Nothing removed the affordance; a condition did, silently.
 *
 * Reading the child is how the card *describes* the box. It is not how the card
 * lets you *in*. So the verb is a sibling of the census, not a child of it, and
 * the census's absence is a sentence rather than a silence.
 */
function CompositionAnnotation({ node }: NodeBodyProps) {
  const workbench = useWorkbench();
  const slug = (node.getField<string>('workflow') ?? '').trim();
  const [state, setState] = useState<MountDocumentState>(
    () => CACHE.settled(slug) ?? { status: 'loading' },
  );
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

  const surface = compositionSurface({
    slug,
    state,
    overrides: node.getField<string>('overrides') ?? '',
    // Whether this mount promises anything is what decides if a missing loop
    // is worth mentioning — see `CompositionContext`. Read from the node
    // rather than its type, because since v3 the type no longer distinguishes.
    claimsOutcome: Boolean((node.getField<string>('outcome') ?? '').trim()),
    // The words come from the registry, not from `core/` — see
    // `ModelRegistry.censusTerms` (reviews-2026-08-14 ticket 13). An empty
    // registry is not a broken card: every type falls back to its family, so
    // the census reads "1 agent · 3 tool" rather than coming back empty.
    vocabulary: workbench.registry.censusTerms.list(),
  });

  // Nothing while unset: an unconfigured mount has no composition to describe,
  // and a placeholder there would read as a failure rather than an empty field.
  if (!surface) return null;

  return (
    <div className="node__composition">
      {surface.purpose ? <div className="node__composition-purpose">{surface.purpose}</div> : null}
      <div className="node__composition-row" data-no-drag>
        {surface.census ? (
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
            {surface.census}
            <OverriddenNote count={surface.overridden} />
          </button>
        ) : (
          <span className="node__composition-note">
            {surface.note}
            <OverriddenNote count={surface.overridden} />
          </span>
        )}
        {surface.open ? (
          <div className="node__composition-open-group">
            <OpenMount slug={slug} mountId={node.id} />
            <span className="node__composition-scope">this mount only, others unaffected</span>
          </div>
        ) : null}
      </div>
      {expanded && surface.peekable ? <GraphPeek slug={slug} /> : null}
    </div>
  );
}

/**
 * `· n overridden`, beside whichever line the row is showing.
 *
 * A fact about this instance's own data, so it outlives a failed fetch: a card
 * claiming the package default while an override runs would be a lie about what
 * executes, and it would tell that lie exactly when the runtime is down.
 */
function OverriddenNote({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span
      className="node__composition-overridden"
      title="This mount overrides fields of the shared package (see the Overrides field in the inspector). Other mounts keep the package defaults."
    >
      {' '}
      · {count} overridden
    </span>
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
  const [state, setState] = useState<PeekState>(() => PEEKS.settled(slug) ?? { status: 'loading' });

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
 * Edit this instance — the honest way in.
 *
 * The label names the *thing*, not the mechanism. "Open" said nothing about
 * what opens, or that an edit lands on this mount alone: it opens *this
 * instance*, at `<parent>/<mountId>`, and a change becomes an override on
 * this mount only.
 *
 * Until `say-it-on-the-surface/08` that fact lived only in this button's
 * `title` — invisible on a touch device and for a keyboard user tabbing to
 * the control, and on a mouse only after a deliberate hover. The sibling
 * `node__composition-scope` span beside the button (in `CompositionAnnotation`
 * above) now says it in visible text; the title stays as the fuller sentence
 * for a mouse.
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
/**
 * Why this mount cannot be opened yet, in words a first-time reader has met.
 *
 * It said *"this workflow has no address yet"* until 2026-08-18. **Address** is
 * internal vocabulary — a `MountAddress` is a chain like
 * `concierge/wf-music` — and it arrived in a sentence explaining a refusal to
 * somebody who by definition did not know what was wrong. The same defect
 * `say-it-on-the-surface` 03 removed from the mount field one commit earlier,
 * in the file next door.
 *
 * Declared once because two surfaces say it: the button's hover text, before
 * the press, and the inline error, after one.
 */
const UNSAVED_PARENT_REFUSAL =
  'Save this workflow first. Opening a mount edits it inside the workflow that holds it, so that workflow needs a folder on the backend before there is anywhere to put the change.';

function OpenMount({ slug, mountId }: { slug: string; mountId: string }) {
  const workbench = useWorkbench();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // One label. This was a ternary on the mount kind whose two branches were
  // the same string — dead before `team.workflow` was collapsed, and there is
  // now not even a kind to branch on (ticket 16).
  const label = 'Open this mount';

  // **Knowable before the click, so it is said before the click.** This used
  // to compute the address inside `open()`, so an unsaved workflow presented a
  // live-looking button, took the press, and only then produced a sentence.
  // The answer is readable at render — same store, same call — and this
  // repository already settled the principle twice: "unavailable rather than
  // merely punished" (ticket 42's mount combobox, and the greyed package rows
  // that carry their refusal in their hover text).
  //
  // Not `disabled`, for the reason `PackageItem` records: a disabled button
  // fires no mouse events, so it would swallow the hover text that explains
  // itself. `aria-disabled` plus a title that says why.
  const rooted =
    getOpenAddress() ?? parseMountAddress(sessionStorage.getItem(CURRENT_SLUG_KEY) ?? '');
  const unsaved = rooted === null;

  const open = useCallback(async () => {
    setBusy(true);
    // The address of *this* mount, not the child's slug — ticket 42. Two
    // mounts of one package are two instances with their own overrides, and
    // the slug alone could not tell the editor which one was opened.
    //
    // Read before the load, since the import replaces the open document.
    const here =
      getOpenAddress() ?? parseMountAddress(sessionStorage.getItem(CURRENT_SLUG_KEY) ?? '');
    const target = here ? childAddress(here, mountId) : null;
    if (!target) {
      setBusy(false);
      setError(UNSAVED_PARENT_REFUSAL);
      return;
    }
    const outcome = await loadMountIntoEditor(target, new WorkflowFileClient(), workbench);
    setBusy(false);
    setError(outcome.ok ? null : outcome.error);
  }, [mountId, workbench]);

  return (
    <>
      <button
        type="button"
        className="node__composition-open"
        disabled={busy}
        aria-disabled={unsaved}
        title={
          unsaved
            ? UNSAVED_PARENT_REFUSAL
            : `Opens this mount of ${slug} — its own overrides, not the shared definition. Other mounts are unaffected.`
        }
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

/**
 * The body a mount card shows.
 *
 * Ticket vocabulary: a Team claims its loop, a Workflow mount does not — the
 * claim is derived by `summarizeComposition`, never asserted by the card.
 * Which type ids are mounts is declared once, in `mountKind.ts`.
 */
export function compositionBody(): NodeBody {
  const Body = (props: NodeBodyProps) => <CompositionAnnotation {...props} />;
  Body.displayName = 'CompositionBody';
  return Body;
}

/* ================================================================== *
 * Per-slug cache
 * ================================================================== */

/**
 * One fetch per slug, shared by every card referencing it.
 *
 * Two mounts of the same team on one canvas (Page Analytics has exactly
 * that) would otherwise each hit the backend on every re-render, and a card
 * re-renders on every drag. The in-flight promise is cached, not just the
 * result, so concurrent mounts coalesce into one request.
 *
 * `SlugCache` owns when an entry dies, and now genuinely does what the
 * comment here used to claim: a failure to *reach* the runtime is not a fact
 * about the document and is dropped immediately; a saved package drops the
 * slug it names; and the whole thing is bounded. Before that, "cached only
 * until the next slug change" described an eviction that existed nowhere.
 */
const CACHE = new SlugCache<MountDocumentState>('composition.document', {
  keep: (state) => state.status !== 'unreachable',
});

function resolveSlug(slug: string): Promise<MountDocumentState> {
  return CACHE.resolve(slug, async (): Promise<MountDocumentState> => {
    const result = await new WorkflowFileClient().loadIfPresent(slug);
    if (!result.ok) return { status: 'unreachable' };
    return result.value == null
      ? { status: 'missing' }
      : { status: 'ready', document: result.value };
  });
}

/* ================================================================== *
 * Per-slug compiled-graph peek cache
 * ================================================================== */

type PeekState =
  { status: 'loading' } | { status: 'ready'; svg: string } | { status: 'failed'; message: string };

/**
 * Same contract as `CACHE`, for a much more expensive answer: the backend has
 * to *compile* the workflow, and Mermaid has to lay it out. A card re-renders
 * on every drag, so without this an expanded peek would recompile the child's
 * graph continuously while its parent card was being moved.
 *
 * The rendered SVG is the heaviest thing either card body holds, which is why
 * the bound matters here more than anywhere: a failure is dropped at once, a
 * save drops the slug, and beyond that the ceiling is `SlugCache`'s.
 */
const PEEKS = new SlugCache<PeekState>('composition.peek', {
  keep: (state) => state.status !== 'failed',
  // Lower than the default: an SVG per slug, and a peek is only rendered
  // while its card is expanded, so few are ever wanted at once.
  limit: 8,
});

/** Monotonic, so two cards on one canvas never share a Mermaid element id. */
let peekSequence = 0;

function resolvePeek(slug: string): Promise<PeekState> {
  return PEEKS.resolve(slug, async (): Promise<PeekState> => {
    const outcome = await new WorkflowFileClient().compiledGraph(slug);
    if (!outcome.ok) return { status: 'failed', message: outcome.error };
    try {
      const mermaid = (await import('mermaid')).default;
      mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'neutral' });
      const { svg } = await mermaid.render(
        peekDiagramId(slug, (peekSequence += 1)),
        peekMermaid(outcome.value),
      );
      return { status: 'ready', svg };
    } catch (error) {
      return {
        status: 'failed',
        message: `could not draw this graph: ${error instanceof Error ? error.message : String(error)}`,
      };
    }
  });
}
