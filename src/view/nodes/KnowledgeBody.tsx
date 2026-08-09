import { useCallback, useEffect, useState } from 'react';
import { BrainCircuit, NotebookPen } from 'lucide-react';
import { Button, Icon } from '@design/primitives';
import { CURRENT_SLUG_KEY } from '@app/workflowFileWatch';
import { Dialog } from '../overlays/Dialog';
import type { NodeBodyProps } from './nodeBodyRegistry';
import './KnowledgeBody.css';

/**
 * The Knowledge node's card body: "Build second brain", plus the curation
 * surface over what the builders wrote.
 *
 * One click POSTs to the backend's knowledge builder for the OPEN workflow
 * (the slug in `sessionStorage`, same as `CompositionBody`/`AskPanel` read
 * it), which introspects the workflow's own sources — SQL databases
 * mechanically, unrecognized sources through the bounded explorer — and
 * writes one procedural doc per topic to `workflows/<slug>/knowledge/`.
 *
 * Below the button, the topic index (name — hint, with generated/claimed and
 * stale badges) and click-to-edit: a dialog with one textarea and an
 * explicit Save. Saving claims the doc — the backend strips the generated
 * marker, so the builder never overwrites it again (the curation contract's
 * auto-claim). No autosave into an authority store, ever.
 *
 * Fetches directly (the `LockedPromptSections` precedent) rather than
 * widening a core client for one card.
 */

type BuildState =
  | { status: 'idle' }
  | { status: 'busy' }
  | { status: 'done'; written: number; skipped: number }
  | { status: 'failed'; message: string };

interface TopicStatus {
  name: string;
  hint: string;
  generated: boolean;
  source: string;
  stale: boolean;
}

const API_BASE = 'http://localhost:8000';

function openSlug(): string | null {
  return typeof sessionStorage === 'undefined' ? null : sessionStorage.getItem(CURRENT_SLUG_KEY);
}

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

async function fetchTopics(slug: string): Promise<TopicStatus[]> {
  try {
    const response = await fetch(
      `${API_BASE}/api/workflows/${encodeURIComponent(slug)}/knowledge`,
    );
    if (!response.ok) return [];
    const payload = (await response.json()) as unknown;
    if (!Array.isArray(payload)) return [];
    return payload.filter(
      (row): row is TopicStatus => typeof row === 'object' && row !== null && 'name' in row,
    );
  } catch {
    return [];
  }
}

function TopicEditor({
  slug,
  topic,
  onClose,
  onSaved,
}: {
  slug: string;
  topic: TopicStatus;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [body, setBody] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch(
          `${API_BASE}/api/workflows/${encodeURIComponent(slug)}/knowledge/${encodeURIComponent(topic.name)}`,
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = (await response.json()) as { body?: unknown };
        if (!cancelled) setBody(typeof payload.body === 'string' ? payload.body : '');
      } catch {
        if (!cancelled) setError('Could not load this doc from the runtime.');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [slug, topic.name]);

  const save = async () => {
    if (body === null) return;
    setSaving(true);
    setError(null);
    try {
      const response = await fetch(
        `${API_BASE}/api/workflows/${encodeURIComponent(slug)}/knowledge/${encodeURIComponent(topic.name)}`,
        {
          method: 'PUT',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ body }),
        },
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      onSaved();
      onClose();
    } catch {
      setError('Save failed — is the runtime running?');
      setSaving(false);
    }
  };

  return (
    <Dialog
      title={topic.name}
      subtitle={topic.hint || 'Knowledge topic'}
      icon={NotebookPen}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={body === null || saving} onClick={() => void save()}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </>
      }
    >
      {error ? (
        <div className="node__composition--missing" role="alert">
          {error}
        </div>
      ) : null}
      <textarea
        className="knowledge__editor"
        aria-label={`Knowledge doc for ${topic.name}`}
        value={body ?? 'Loading…'}
        disabled={body === null}
        onChange={(event) => setBody(event.target.value)}
        spellCheck={false}
      />
      <p className="knowledge__claim-note">
        Saving claims this doc as hand-authored: the generated marker is removed and the builder
        will never overwrite it again.
      </p>
    </Dialog>
  );
}

export function KnowledgeBody(_props: NodeBodyProps) {
  const [state, setState] = useState<BuildState>({ status: 'idle' });
  const [topics, setTopics] = useState<TopicStatus[]>([]);
  const [editing, setEditing] = useState<TopicStatus | null>(null);

  const refreshTopics = useCallback(async () => {
    const slug = openSlug();
    if (slug) setTopics(await fetchTopics(slug));
  }, []);

  useEffect(() => {
    void refreshTopics();
  }, [refreshTopics]);

  const build = async () => {
    const slug = openSlug();
    if (!slug) {
      setState({ status: 'failed', message: 'Save the workflow first — no open slug to build for.' });
      return;
    }
    setState({ status: 'busy' });
    setState(await requestBuild(slug));
    await refreshTopics();
  };

  const slug = openSlug();

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
      {topics.length > 0 ? (
        <ul className="knowledge__topics">
          {topics.map((topic) => (
            <li key={topic.name}>
              <button
                type="button"
                className="knowledge__topic"
                title={topic.hint || topic.name}
                onClick={() => setEditing(topic)}
              >
                <span className="knowledge__topic-name">{topic.name}</span>
                {topic.hint ? <span className="knowledge__topic-hint">{topic.hint}</span> : null}
                <span className="knowledge__badge">
                  {topic.generated ? topic.source || 'generated' : 'claimed'}
                </span>
                {topic.stale ? (
                  <span
                    className="knowledge__badge knowledge__badge--stale"
                    title="The source behind this doc has changed since it was written."
                  >
                    stale
                  </span>
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {editing && slug ? (
        <TopicEditor
          slug={slug}
          topic={editing}
          onClose={() => setEditing(null)}
          onSaved={() => void refreshTopics()}
        />
      ) : null}
    </div>
  );
}
