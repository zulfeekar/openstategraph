import { useEffect, useRef, useState } from 'react';
import { WorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import { CURRENT_SLUG_KEY } from '@app/workflowFileWatch';
import './GraphPreview.css';

/**
 * The compiled graph, as the backend compiler actually produced it — ticket
 * 54, and the cheap half of the dual-view ask (ticket 68). The backend asks
 * for `xray=True`, which expands nothing: a concierge's routed children and a
 * Team's members are closures over the child graph's invoke(), not LangGraph
 * subgraphs, so each renders as one flat box.
 *
 * Mermaid renders locally (lazy-imported so its chunk costs nothing until
 * someone opens this); the Mermaid *text* is also exposed for copy, because
 * the text is the portable artifact — it pastes into a PR description or
 * mermaid.live without this app.
 */
export function GraphPreview({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [state, setState] = useState<
    | { kind: 'loading' }
    | { kind: 'error'; message: string }
    | { kind: 'ready'; mermaid: string; svg: string }
  >({ kind: 'loading' });
  const hostRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setState({ kind: 'loading' });
    (async () => {
      const slug = sessionStorage.getItem(CURRENT_SLUG_KEY);
      if (!slug) {
        setState({
          kind: 'error',
          message: 'Save or load this workflow first — the compiled view comes from the backend.',
        });
        return;
      }
      const outcome = await new WorkflowFileClient().compiledGraph(slug);
      if (cancelled) return;
      if (!outcome.ok) {
        setState({ kind: 'error', message: outcome.error });
        return;
      }
      try {
        const mermaid = (await import('mermaid')).default;
        mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'neutral' });
        const { svg } = await mermaid.render(`compiled-${Date.now()}`, outcome.value);
        if (!cancelled) setState({ kind: 'ready', mermaid: outcome.value, svg });
      } catch (error) {
        if (!cancelled)
          setState({
            kind: 'error',
            message: `Diagram render failed: ${error instanceof Error ? error.message : String(error)}`,
          });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="graph-preview" role="dialog" aria-label="Compiled graph" onClick={onClose}>
      <div className="graph-preview__panel" onClick={(event) => event.stopPropagation()}>
        <header className="graph-preview__header">
          <strong>Compiled graph</strong>
          {/* Twice wrong, and the second half is the interesting one. "Subgraph"
              is a LangGraph name in a sentence a user reads, which the lexicon
              forbids — and nothing was ever expanded: this compiler emits no
              LangGraph subgraph, so a mount is one box (production-ready 37,
              consistency-sweep 10). */}
          <span className="graph-preview__hint">
            what the LangGraph compiler produced — a mount is one box
          </span>
          {state.kind === 'ready' ? (
            <button
              type="button"
              className="graph-preview__copy"
              onClick={() => void navigator.clipboard.writeText(state.mermaid)}
            >
              Copy Mermaid
            </button>
          ) : null}
          <button
            type="button"
            className="graph-preview__close"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </header>
        <div className="graph-preview__body" ref={hostRef}>
          {state.kind === 'loading' ? <p>Compiling…</p> : null}
          {state.kind === 'error' ? <p role="alert">{state.message}</p> : null}
          {state.kind === 'ready' ? (
            // Mermaid's output is SVG it generated itself under securityLevel
            // 'strict'; this is the documented way to mount it.
            <div dangerouslySetInnerHTML={{ __html: state.svg }} />
          ) : null}
        </div>
      </div>
    </div>
  );
}
