import { useState } from 'react';
import { BrainCircuit } from 'lucide-react';
import { Icon } from '@design/primitives';
import { CURRENT_SLUG_KEY } from '@app/workflowFileWatch';
import type { NodeBodyProps } from './nodeBodyRegistry';

/**
 * The Knowledge node's card body: the "Build second brain" button.
 *
 * One click POSTs to the backend's knowledge builder for the OPEN workflow
 * (the slug in `sessionStorage`, same as `CompositionBody`/`AskPanel` read
 * it), which introspects the workflow's own sources — its SQL databases
 * today, pluggable per builder — and writes one procedural doc per topic to
 * `workflows/<slug>/knowledge/`. The lookup tool this card represents then
 * serves those docs to agents **on demand**; nothing here ever concatenates
 * knowledge into a prompt.
 *
 * Fetches directly (the `LockedPromptSections` precedent) rather than
 * widening a core client for one button. Result and failure are reported in
 * place on the card — the button is the whole surface of this feature.
 */

type BuildState =
  | { status: 'idle' }
  | { status: 'busy' }
  | { status: 'done'; written: number; skipped: number }
  | { status: 'failed'; message: string };

const API_BASE = 'http://localhost:8000';

async function requestBuild(slug: string): Promise<BuildState> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/workflows/${encodeURIComponent(slug)}/knowledge/build`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({}),
    });
  } catch {
    return { status: 'failed', message: `Could not reach the runtime at ${API_BASE}.` };
  }
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === 'string') detail = payload.detail;
    } catch {
      // keep the status-code message
    }
    return { status: 'failed', message: detail };
  }
  try {
    const payload = (await response.json()) as { written?: unknown; skipped?: unknown };
    return {
      status: 'done',
      written: Array.isArray(payload.written) ? payload.written.length : 0,
      skipped: Array.isArray(payload.skipped) ? payload.skipped.length : 0,
    };
  } catch {
    return { status: 'failed', message: 'The runtime returned invalid JSON.' };
  }
}

export function KnowledgeBody(_props: NodeBodyProps) {
  const [state, setState] = useState<BuildState>({ status: 'idle' });

  const build = async () => {
    const slug =
      typeof sessionStorage === 'undefined' ? null : sessionStorage.getItem(CURRENT_SLUG_KEY);
    if (!slug) {
      setState({ status: 'failed', message: 'Save the workflow first — no open slug to build for.' });
      return;
    }
    setState({ status: 'busy' });
    setState(await requestBuild(slug));
  };

  return (
    <div className="node__knowledge" data-no-drag>
      <button
        type="button"
        className="node__composition-open"
        disabled={state.status === 'busy'}
        title="Introspects this workflow’s data sources and writes one knowledge doc per topic to its knowledge/ folder. Hand-authored docs are never overwritten."
        onClick={() => void build()}
      >
        <Icon glyph={BrainCircuit} size="xs" />
        {state.status === 'busy' ? 'Building…' : 'Build second brain'}
      </button>
      {state.status === 'done' ? (
        <div className="node__composition">
          {state.written} doc{state.written === 1 ? '' : 's'} written
          {state.skipped > 0 ? `, ${state.skipped} hand-authored kept` : ''}
        </div>
      ) : null}
      {state.status === 'failed' ? (
        <div className="node__composition--missing" role="alert">
          {state.message}
        </div>
      ) : null}
    </div>
  );
}
