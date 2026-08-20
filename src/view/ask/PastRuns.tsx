import { useCallback, useEffect, useState } from 'react';
import { History, RotateCcw } from 'lucide-react';
import { Button, Icon, PanelEmpty } from '@design/primitives';
import { RuntimeClient, type PastRun, type PastRunHistory } from '@core/runtime/RuntimeClient';
import {
  describeRun,
  laneTitle,
  lanes,
  stepLines,
  stepTitle,
  toolCallLine,
} from '@core/runtime/pastRunView';
import './PastRuns.css';

/**
 * Past runs of the open workflow — what the backend actually checkpointed.
 *
 * "Past runs", never "replay". Everything on this surface was written while
 * the run happened and is read back out of the checkpointer: opening one calls
 * no model, spends no token, and re-executes nothing. That is why it can be a
 * plain list rather than a mode — there is nothing here to be careful with.
 *
 * The one thing that *does* re-execute lives elsewhere on purpose: a run whose
 * status is `waiting for you` is resumable through the ordinary approval path
 * in the chat thread, and this list says so rather than growing a second
 * button that resumes runs from a history view. One way to continue a run.
 *
 * Scoped to the workflow on the canvas. A deployment's whole history is a
 * different question with different privacy weight; the editor asks the
 * narrow one, and the backend's filters (`workflow_slug`, `user_email`,
 * `session_id`) are what a wider surface would use.
 */
type Listing =
  | { status: 'loading' }
  | { status: 'ready'; runs: readonly PastRun[]; at: number }
  | { status: 'failed'; message: string };

export function PastRuns({ slug, onClose }: { slug: string | undefined; onClose: () => void }) {
  const [state, setState] = useState<Listing>({ status: 'loading' });
  const [open, setOpen] = useState<string | null>(null);
  /**
   * Bumped by Refresh. The effect below owns the fetch and writes state only
   * from its callback — a `setState` in an effect's own body is the pattern
   * that makes a render depend on a render, so the "start loading" half lives
   * in the click handler, where it is an event, not a render.
   */
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let live = true;
    void new RuntimeClient().pastRuns({ workflowSlug: slug }).then((outcome) => {
      if (!live) return;
      setState(
        outcome.ok
          ? // One instant for the whole list, captured with the answer: every
            // row's "20 min ago" is then measured from the same clock reading
            // rather than from whenever that row happened to re-render.
            { status: 'ready', runs: outcome.value, at: Date.now() }
          : { status: 'failed', message: outcome.error },
      );
    });
    return () => {
      live = false;
    };
  }, [slug, nonce]);

  const refresh = useCallback(() => {
    setState({ status: 'loading' });
    setNonce((value) => value + 1);
  }, []);

  return (
    <div className="past-runs">
      <div className="past-runs__bar">
        {/* Says which question it answered. Without a known slug the backend
            has no filter to apply and returns everything this deployment
            stored — true, and worth saying, because a list mixing workflows
            would otherwise read as history of the one on screen. */}
        <span className="past-runs__title">
          <Icon glyph={History} size="sm" />
          {slug ? `Past runs · ${slug}` : 'Past runs · all workflows'}
        </span>
        <span className="past-runs__bar-actions">
          <Button variant="ghost" size="sm" onClick={refresh} aria-label="Refresh past runs">
            <Icon glyph={RotateCcw} size="xs" />
          </Button>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </span>
      </div>

      {state.status === 'loading' ? <p className="ask__meta">Reading the checkpoints…</p> : null}
      {state.status === 'failed' ? (
        <p className="ask__meta" role="alert">
          {state.message}
        </p>
      ) : null}
      {state.status === 'ready' && state.runs.length === 0 ? (
        <PanelEmpty
          glyph={History}
          title="No stored runs yet"
          body="Runs appear here once this workflow has been asked something and the backend has a checkpointer."
        />
      ) : null}
      {state.status === 'ready'
        ? state.runs.map((run) => (
            <RunRow
              key={run.threadId}
              run={run}
              at={state.at}
              showWorkflow={!slug}
              expanded={open === run.threadId}
              onToggle={() =>
                setOpen((current) => (current === run.threadId ? null : run.threadId))
              }
            />
          ))
        : null}
    </div>
  );
}

function RunRow({
  run,
  at,
  showWorkflow,
  expanded,
  onToggle,
}: {
  run: PastRun;
  /** When the list was fetched — the reference instant for "20 min ago". */
  at: number;
  /** Only when the list is unfiltered, where the row would otherwise not say
   * which workflow it belongs to. */
  showWorkflow: boolean;
  expanded: boolean;
  onToggle: () => void;
}) {
  const described = describeRun(run, at);
  return (
    <div className="past-runs__run" data-status={run.status}>
      <button
        type="button"
        className="past-runs__run-head"
        aria-expanded={expanded}
        onClick={onToggle}
      >
        <span className="past-runs__run-title">{described.title}</span>
        <span className="ask__meta">
          {showWorkflow && run.workflowSlug ? `${run.workflowSlug} · ` : ''}
          {described.meta}
          {described.identity ? ` · ${described.identity}` : ''}
          {run.status === 'paused' ? ` · ${described.statusLabel}` : ''}
        </span>
      </button>
      {expanded ? <RunHistory run={run} /> : null}
    </div>
  );
}

/**
 * One run, checkpoint by checkpoint — fetched only when a row is opened, so a
 * list of fifty runs costs one request rather than fifty-one.
 */
function RunHistory({ run }: { run: PastRun }) {
  const [state, setState] = useState<
    | { status: 'loading' }
    | { status: 'ready'; history: PastRunHistory }
    | { status: 'failed'; message: string }
  >({ status: 'loading' });

  useEffect(() => {
    let live = true;
    void new RuntimeClient()
      .pastRun(run.threadId, run.workflowSlug || undefined)
      .then((outcome) => {
        if (!live) return;
        setState(
          outcome.ok
            ? { status: 'ready', history: outcome.value }
            : { status: 'failed', message: outcome.error },
        );
      });
    return () => {
      live = false;
    };
  }, [run.threadId, run.workflowSlug]);

  if (state.status === 'loading') return <p className="ask__meta">Reading this thread…</p>;
  if (state.status === 'failed')
    return (
      <p className="ask__meta" role="alert">
        {state.message}
      </p>
    );

  return (
    <div className="past-runs__steps">
      {run.status === 'paused' ? (
        <p className="past-runs__note">
          This run is parked at an approval. Ask again in the chat above to continue it — history
          only reads.
        </p>
      ) : null}
      {/*
        One lane per graph, never one flat list. A run of this workflow
        checkpoints the workflow itself and every agent subgraph under the same
        thread, each numbering its own supersteps from -1 — so flat, a
        `morning-brief` run printed `Step 0 · loop` five times with nothing to
        say they were five different graphs (`memory-and-replay` 37).
      */}
      {lanes(state.history.steps).map((lane) => (
        <div className="past-runs__lane" key={`${lane.namespace.join('|')}#${lane.occurrence}`}>
          <div className="past-runs__lane-head">
            <span className="past-runs__lane-title">{laneTitle(lane)}</span>
            <span className="ask__meta">
              {lane.steps.length} {lane.steps.length === 1 ? 'step' : 'steps'}
            </span>
          </div>
          {lane.steps.map((step) => (
            <div className="past-runs__step" key={step.checkpointId}>
              <div className="past-runs__step-head">
                {stepTitle(step)}
                {step.wrote.length > 0 ? (
                  <span className="past-runs__wrote">wrote {step.wrote.join(', ')}</span>
                ) : null}
              </div>
              {/*
                Above the state, because it is the cause and the state is the
                effect — and because a run that answered wrongly usually asked
                for the wrong thing, or was refused.
              */}
              {step.toolCalls.map((call, index) => (
                <div className="past-runs__tool" key={`${call.name}-${index}`}>
                  {toolCallLine(call)}
                </div>
              ))}
              {stepLines(step).map((line) => (
                <div className="past-runs__line" key={line.key}>
                  <span className="past-runs__line-key">{line.key}</span>
                  <span className="past-runs__line-value">{line.value}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      ))}
      {state.history.steps.length === 0 ? (
        <p className="ask__meta">This thread has no readable checkpoints.</p>
      ) : null}
    </div>
  );
}
