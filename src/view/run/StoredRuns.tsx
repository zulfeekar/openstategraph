import { useCallback, useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, History, RotateCcw, Undo2 } from 'lucide-react';
import { Button, Icon, PanelEmpty } from '@design/primitives';
import { RecordedRunsClient, type RecordedRun } from '@core/runtime/RecordedRunsClient';
import {
  groupRecordedRuns,
  sittingLabel,
  type RecordedSession,
} from '@core/runtime/recordedRunTree';
import { recordedRunView } from './recordedRunRows';
import { runView } from './runView';
import './StoredRuns.css';

/**
 * Every run this deployment's run store kept, and a way into each one.
 *
 * `memory-and-replay` 73. The owner asked for *"a panel — similar to the
 * Workflows popover UX in the top bar — to see all the runs saved in the
 * SQLite store for replay"*, and for selecting one to **replace the existing
 * timeline source** and play it on the timeline that is already there.
 *
 * ## What this is not
 *
 * It is not `PastRuns` moved. That panel reads `GET /api/threads`, which is the
 * **checkpointer**, and it answers *what supersteps ran in the workflow on the
 * canvas* — scoped to that workflow on purpose, because a deployment's whole
 * history is a different question with different privacy weight. This reads
 * `runs.sqlite`, is not scoped to the open document, and answers *how the
 * output arrived*. Only the second carries the offsets a playhead can honestly
 * move between, which is why `RunDock` recorded the cadence as missing while
 * `PastRuns` was already shipping.
 *
 * The two are cross-referenced rather than merged, and neither is a twin of
 * the other: they read different files and can disagree, because a run whose
 * checkpoints were swept still has its row here and a run that predates `47`
 * has a row with no recording.
 *
 * ## The levels are the ones the store has
 *
 * Sitting → conversation → turn. The third rung the owner named — *subthread*
 * — is not in this store, is not anywhere in this repository, and is not
 * invented here; `recordedRunTree.ts` carries the table. A turn is a real row
 * and is what a reader picks a recording from.
 *
 * ## Selecting one holds it, and the way back is never more than one press
 *
 * `runView.hold` puts a recording on the dock and `runView.release` gives the
 * surface back to the live run — the one the panel reached *while the
 * recording was up*, not the one that was there when it opened. Two controls
 * offer it: the row at the top of this list, and a button in the dock's own
 * header, which is the one still reachable after this popover is closed.
 */
type Listing =
  | { status: 'loading' }
  | { status: 'ready'; sessions: readonly RecordedSession[] }
  | { status: 'failed'; message: string };

export function StoredRuns({
  onClose,
  onShowTimeline,
}: {
  readonly onClose: () => void;
  /**
   * Bring the timeline up, because a picker whose effect is on a surface that
   * is closed does nothing a reader can see.
   *
   * The dock is a toggle the reader owns, and this only ever **opens** it —
   * the same one-way move the first run of a tab already makes. Choosing a
   * recording is an unambiguous request to look at one.
   */
  readonly onShowTimeline: () => void;
}) {
  const [state, setState] = useState<Listing>({ status: 'loading' });
  const [open, setOpen] = useState<string | null>(null);
  const [showing, setShowing] = useState<string | null>(null);
  /** Bumped by Refresh. The fetch lives in the effect; starting it is an event. */
  const [nonce, setNonce] = useState(0);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void new RecordedRunsClient().list().then((outcome) => {
      if (!live) return;
      setState(
        outcome.ok
          ? { status: 'ready', sessions: groupRecordedRuns(outcome.value) }
          : { status: 'failed', message: outcome.error },
      );
    });
    return () => {
      live = false;
    };
  }, [nonce]);

  /**
   * Fetch one conversation's recordings and put the chosen turn on the dock.
   *
   * The turn is addressed by **its position in its thread**, because the store
   * mints no run id and none is invented here: a sqlite `rowid` is storage
   * rather than a fact about the run, and `at` is second precision. A
   * conversation and a position in it is what a turn actually is.
   */
  const play = useCallback(
    async (threadId: string, ordinal: number) => {
      setFailure(null);
      const outcome = await new RecordedRunsClient().thread(threadId);
      if (!outcome.ok) {
        setFailure(outcome.error);
        return;
      }
      const turn = outcome.value[ordinal];
      if (turn === undefined) {
        setFailure('That turn is no longer in the store.');
        return;
      }
      if (turn.bursts.length === 0) {
        // An absence, and an answer. A run recorded before `47`, a workflow with
        // no model in it, and a recording this reader is refused all arrive this
        // way — and none of them is a run that took no time. A blank chart would
        // say the third thing, so the panel says the first two instead and
        // leaves the dock showing whatever it was already showing.
        setFailure(
          'That turn has no recording — the store kept the run and not how its output arrived. Runs recorded before the cadence was stored, and workflows with no model in them, both read this way.',
        );
        return;
      }
      runView.hold(recordedRunView(turn));
      setShowing(`${threadId}#${ordinal}`);
      onShowTimeline();
    },
    [onShowTimeline],
  );

  const back = useCallback(() => {
    runView.release();
    setShowing(null);
  }, []);

  return (
    <div className="stored-runs">
      <div className="stored-runs__bar">
        <span className="stored-runs__title">
          <Icon glyph={History} size="sm" />
          Stored runs
        </span>
        <span className="stored-runs__bar-actions">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setState({ status: 'loading' });
              setNonce((value) => value + 1);
            }}
            aria-label="Refresh stored runs"
          >
            <Icon glyph={RotateCcw} size="xs" />
          </Button>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </span>
      </div>

      {/* The way back, at the top of the list and offered whenever a recording
          is on the dock — including one opened before this popover was. The
          dock's own header carries the other one, which is the copy that
          survives this panel closing. */}
      <Button
        variant="ghost"
        size="sm"
        className="stored-runs__back"
        disabled={showing === null && !runView.held()}
        onClick={back}
      >
        <Icon glyph={Undo2} size="xs" />
        Back to this tab&apos;s run
      </Button>

      <p className="stored-runs__note">
        Reading a recording back. Nothing here re-runs anything — no model is called and no token is
        spent.
      </p>

      {state.status === 'loading' ? <p className="ask__meta">Reading the run store…</p> : null}
      {state.status === 'failed' ? (
        <p className="ask__meta" role="alert">
          {state.message}
        </p>
      ) : null}
      {failure !== null ? (
        <p className="ask__meta" role="alert">
          {failure}
        </p>
      ) : null}
      {state.status === 'ready' && state.sessions.length === 0 ? (
        <PanelEmpty
          glyph={History}
          title="No runs have been recorded yet"
          body="Every run this deployment finishes is written to the local run store. Ask a workflow something and it will appear here."
        />
      ) : null}

      {state.status === 'ready'
        ? state.sessions.map((sitting) => (
            <section className="stored-runs__sitting" key={sitting.sessionId || '(none)'}>
              <h3 className="stored-runs__sitting-title">{sittingLabel(sitting.sessionId)}</h3>
              {sitting.threads.map((thread) => {
                const expanded = open === thread.threadId;
                return (
                  <div className="stored-runs__thread" key={thread.threadId}>
                    <button
                      type="button"
                      className="stored-runs__thread-head"
                      aria-expanded={expanded}
                      onClick={() => setOpen(expanded ? null : thread.threadId)}
                    >
                      <Icon glyph={expanded ? ChevronDown : ChevronRight} size="xs" />
                      <span className="stored-runs__thread-slug">{thread.workflowSlug}</span>
                      <span className="stored-runs__thread-id">{thread.threadId}</span>
                      <span className="stored-runs__count">
                        {thread.turns.length === 1 ? '1 turn' : `${thread.turns.length} turns`}
                      </span>
                    </button>
                    {expanded
                      ? thread.turns.map((turn, index) => (
                          <Turn
                            key={`${thread.threadId}#${index}`}
                            turn={turn}
                            showing={
                              showing ===
                              `${thread.threadId}#${turnOrdinal(thread.turns.length, index)}`
                            }
                            onPlay={() =>
                              void play(thread.threadId, turnOrdinal(thread.turns.length, index))
                            }
                          />
                        ))
                      : null}
                  </div>
                );
              })}
            </section>
          ))
        : null}
    </div>
  );
}

/**
 * The listing hands a thread's turns **newest first** and the detail door
 * hands them **oldest first**, each for its own good reason — a list is
 * browsed from the newest and a conversation is read from its beginning. This
 * is the one place the two orders meet, so it is the one place the conversion
 * lives.
 */
function turnOrdinal(count: number, index: number): number {
  return count - 1 - index;
}

function Turn({
  turn,
  showing,
  onPlay,
}: {
  readonly turn: RecordedRun;
  readonly showing: boolean;
  readonly onPlay: () => void;
}) {
  return (
    <button
      type="button"
      className="stored-runs__turn"
      data-showing={showing || undefined}
      onClick={onPlay}
    >
      <span className="stored-runs__turn-question">
        {turn.question || '(no question recorded)'}
      </span>
      <span className="stored-runs__turn-facts">
        <span>{turn.at}</span>
        {/* `—` and `0 s` are two different claims, and the store can say
            either: a run that reported no duration is not an instant one. */}
        <span>{turn.seconds > 0 ? `${turn.seconds.toFixed(1)} s` : '—'}</span>
        {turn.failed ? <span className="stored-runs__failed">failed</span> : null}
      </span>
    </button>
  );
}
