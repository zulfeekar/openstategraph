import { useCallback, useMemo, useRef, useState } from 'react';
import { Send, TriangleAlert } from 'lucide-react';
import { Button, Field, Icon, Panel, PanelBody, PanelHeader, TextInput } from '@design/primitives';
import {
  RuntimeClient,
  type RunOutcome,
  type RunResult,
  type RunStreamEvent,
} from '@core/runtime/RuntimeClient';
import { useController } from '@app/WorkbenchContext';
import { CURRENT_SLUG_KEY } from '@app/workflowFileWatch';
import { TEXT_INPUT_TYPE } from '@nodes/inputs/TextInputNode';
import { RichText } from '@view/common/RichText';
import './AskPanel.css';

/**
 * The slug of the workflow currently open, if the file-watch layer knows it.
 * Read fresh per call: the open workflow can change between sends, and the
 * backend uses it to bind the tools living beside that workflow.
 */
function currentWorkflowSlug(): string | undefined {
  try {
    return sessionStorage.getItem(CURRENT_SLUG_KEY) ?? undefined;
  } catch {
    return undefined; // sessionStorage can throw in restricted contexts
  }
}

/** One row in a turn's live "Activity" feed — a node that has started running. */
interface ActivityRow {
  readonly node: string;
  /** Distinguishes concurrently dispatched worker instances (ticket 27). */
  readonly taskId: string | null;
  /** A step inside a node's own loop (model call, tool, middleware) —
   * rendered as a tree child, never a top-level row (ticket 63). */
  readonly internal: boolean;
  /** Wall-clock gap since the previous frame — the same honest
   * approximation the Inspector's duration badge uses. */
  readonly durationMs: number;
  readonly output: string | null;
}

/** One node's subtree: the node plus the internal steps it ran. */
interface TraceNode {
  readonly node: string;
  readonly taskId: string | null;
  readonly durationMs: number;
  readonly output: string | null;
  readonly children: readonly Omit<ActivityRow, 'internal'>[];
}

/** Nests internal steps under the most recent canvas node — the stream is
 * ordered, so ownership is positional (LangGraph reports a namespace only
 * for true nested subgraphs, not for loop internals). */
function buildTrace(rows: readonly ActivityRow[]): TraceNode[] {
  const tree: TraceNode[] = [];
  for (const row of rows) {
    const last = tree[tree.length - 1];
    if (row.internal && last) {
      (last.children as ActivityRow[]).push(row);
    } else if (!row.internal) {
      tree.push({ ...row, children: [] });
    }
  }
  return tree;
}

/** The downloadable run record — ticket 63's "export as tree JSON". */
function exportTrace(turn: ChatTurn): void {
  const payload = {
    question: turn.question,
    trace: buildTrace(turn.activity),
    answer: turn.result?.answer ?? null,
    attempts: turn.result?.attempts ?? null,
    decisions: turn.result?.decisions ?? {},
    exportedAt: new Date().toISOString(),
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'dyflow-trace.json';
  a.click();
  URL.revokeObjectURL(url);
}

/** A run paused at a `human.approval` node, waiting on this turn. */
interface PendingApproval {
  readonly threadId: string;
  readonly message: string;
  readonly candidate: string;
}

/** One question-and-answer exchange in the chat thread. */
interface ChatTurn {
  readonly id: string;
  readonly question: string;
  readonly running: boolean;
  readonly activity: readonly ActivityRow[];
  /** Streamed message content, concatenated live — "how the agent thinks". */
  readonly thinking: string;
  readonly result: RunResult | null;
  readonly error: string | null;
  /** Set while this turn's run is paused waiting for a human decision. */
  readonly pendingApproval: PendingApproval | null;
}

let nextTurnId = 0;

/**
 * Floor on how long a node's "running" glow stays visible.
 *
 * Without this, a node that needs no model (a router, a grader's
 * deterministic checks) or an agent with no model configured at all
 * resolves in single-digit milliseconds — the exact case that prompted this:
 * a run with no provider configured streamed and finished so fast that the
 * canvas animation was imperceptible, even though it fired correctly. This
 * paces the *visual* transition only; the activity list, streamed thinking
 * text and final result are never delayed by it.
 */
const MIN_HIGHLIGHT_MS = 350;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * Chat with the workflow, and watch it run.
 *
 * A **thread**, not a single-shot form: every question becomes a new turn
 * appended below the last, each with its own streamed activity and answer —
 * so a developer can see a conversation build up rather than one answer slot
 * that overwrites itself.
 *
 * Sending a message writes it onto the canvas's own entry `Text Input` node
 * before running, rather than only passing it to the backend as a side
 * channel — the chat's "first contact" with the workflow is visibly the same
 * node a developer would type into by hand, not a hidden parallel path.
 *
 * The whole point of this panel is that it sends **the document on the
 * canvas** to the runtime — not a server-side graph and not the browser's own
 * engine. So what a developer sees is what ran, and the per-node outputs
 * coming back are the evidence for that rather than a claim about it.
 *
 * Streamed rather than a single blocking response, because ticket 27's sidebar
 * needs to show **which node is currently in charge** as the run happens — a
 * router's branch, a fan-out's dispatched workers, a revise loop's extra lap —
 * not only the outcome once everything has finished. Every `update` event
 * writes `node.runtime` (`controller.model.setNodeRuntime`) so the canvas
 * lights up exactly as a local preview run already does — same status dot
 * glow, same flowing-edge animation (`CanvasStage`) — because a live backend
 * run and a local one now drive the identical channel.
 *
 * Deliberately thin. It holds no credentials, builds no graph, and does not
 * know what LangGraph is; it serialises the document, posts it, and renders
 * what streams back (ticket 07).
 */
export function AskPanel() {
  const controller = useController();
  const [question, setQuestion] = useState('');
  const [turns, setTurns] = useState<readonly ChatTurn[]>([]);
  const threadRef = useRef<HTMLDivElement | null>(null);

  // One client for the panel's lifetime; the base URL is a dev default until
  // configuration exists.
  const client = useMemo(() => new RuntimeClient(), []);

  // A paused-on-approval turn is not `running`, but the composer should stay
  // disabled until it is resolved — sending a new message mid-approval would
  // overwrite the entry node's `prompt` out from under the paused thread.
  const running = turns.some((turn) => turn.running || turn.pendingApproval);

  const updateTurn = useCallback((id: string, patch: Partial<ChatTurn>) => {
    setTurns((all) => all.map((turn) => (turn.id === id ? { ...turn, ...patch } : turn)));
  }, []);

  const scrollToEnd = useCallback(() => {
    // Newest turn at the bottom, so a growing thread reads like a chat rather
    // than requiring a manual scroll to see what just arrived.
    requestAnimationFrame(() => {
      const el = threadRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }, []);

  /**
   * Runs the shared tail of both a fresh send and a resumed approval: wires
   * `onEvent` to the canvas highlight/activity feed, then settles the turn
   * into a result, an error, or — new for `human.approval` — a paused
   * `pendingApproval` state instead of either. Same shape for both callers
   * because a resumed run can itself pause again at a later approval node.
   */
  const streamAndSettle = useCallback(
    async (
      id: string,
      call: (onEvent: (event: RunStreamEvent) => void) => Promise<{
        readonly ok: boolean;
        readonly value?: RunOutcome;
        readonly error?: string;
      }>,
    ) => {
      const seen = new Set<string>();
      let activeNode: string | null = null;

      // For the per-node duration readout the Inspector already shows (built
      // for the local preview path, which measures a real start/end) — a
      // backend-streamed run has no such pair, since LangGraph's `updates`
      // stream mode reports a node only *after* it finishes, never when it
      // starts. The honest substitute: the wall-clock gap since the previous
      // `update` frame arrived. For a sequential chain this is a close
      // approximation of that node's own run time; for nodes dispatched
      // concurrently by a fan-out (ticket 27's `Send`) it overstates any one
      // of them, since several are genuinely running at once behind one gap.
      // Shown anyway rather than left blank — a labelled approximation beats
      // no signal at all, and the Inspector's "ms" badge is not claimed
      // anywhere to be profiler-grade precision.
      let lastEventAt = performance.now();

      // Queues node highlights so each one is visible for at least
      // `MIN_HIGHLIGHT_MS`, regardless of how fast the SSE frames themselves
      // arrive — see the constant's own comment for why this exists.
      let highlightChain: Promise<void> = Promise.resolve();
      const activate = (nodeId: string, output: string | null) => {
        const now = performance.now();
        const durationMs = Math.round(now - lastEventAt);
        lastEventAt = now;

        highlightChain = highlightChain.then(async () => {
          // One node glows at a time, in the order the stream reports — the
          // previous node's card returns to its resting state exactly as it
          // would after a local preview run finishes with it.
          if (activeNode && activeNode !== nodeId) {
            controller.model.setNodeRuntime(activeNode, { status: 'success' });
          }
          // The SSE `update` frame reports a node that has *already* produced
          // its output — LangGraph's `updates` stream mode fires after a node
          // completes, not before — so the value is written here, at the same
          // moment the card starts to glow, rather than waiting for a later
          // event that never carries it. Without this, the local preview run
          // populates `node.runtime.output` (`ExecutionEngine` does the same
          // thing) but a backend-streamed run never did, so cards like
          // Formatted Output stayed on their empty "Run the workflow to see
          // the result here" placeholder even after a real answer streamed in.
          // `durationMs` closes the identical gap for the Inspector's "LAST
          // RUN" timing badge — previously always blank for a Chat-driven run.
          controller.model.setNodeRuntime(nodeId, {
            status: 'running',
            durationMs,
            ...(output != null ? { output } : {}),
          });
          // Highlight whichever node just acted — the "currently in charge"
          // the ticket asks for. A dispatched worker's `taskId` still selects
          // the one static Worker node on the canvas; there is nowhere else
          // for a runtime task instance to be shown (ticket 27's own finding:
          // `Send` creates tasks, never new canvas nodes).
          controller.selectionActions.selectNodes([nodeId]);
          activeNode = nodeId;
          await sleep(MIN_HIGHLIGHT_MS);
        });
      };

      let lastFrameAt = performance.now();
      const onEvent = (event: RunStreamEvent) => {
        if (event.type === 'update') {
          const now = performance.now();
          const durationMs = Math.round(now - lastFrameAt);
          lastFrameAt = now;
          if (!event.internal) {
            seen.add(event.node);
            activate(event.node, event.output);
          }
          // Data collection is never delayed by the animation pacing above —
          // only the visual glow is paced, not the record of what happened.
          setTurns((all) =>
            all.map((turn) =>
              turn.id === id
                ? {
                    ...turn,
                    activity: [
                      ...turn.activity,
                      {
                        node: event.node,
                        taskId: event.taskId,
                        internal: event.internal,
                        durationMs,
                        output: event.output,
                      },
                    ],
                  }
                : turn,
            ),
          );
          scrollToEnd();
        } else if (event.type === 'token') {
          setTurns((all) =>
            all.map((turn) =>
              turn.id === id ? { ...turn, thinking: turn.thinking + event.content } : turn,
            ),
          );
          scrollToEnd();
        }
      };

      const outcome = await call(onEvent);

      // Waits for the last queued highlight's minimum-visible window before
      // finalising, so the very last node to act does not flash and vanish
      // the instant the run's own answer arrives.
      await highlightChain;

      if (outcome.ok && outcome.value && 'interrupted' in outcome.value) {
        // Paused, not finished: the last active node stays highlighted rather
        // than flipping to "success", since it has not actually completed.
        updateTurn(id, {
          running: false,
          pendingApproval: {
            threadId: outcome.value.threadId,
            message: outcome.value.message,
            candidate: outcome.value.candidate,
          },
        });
        scrollToEnd();
        return;
      }

      if (activeNode) {
        controller.model.setNodeRuntime(activeNode, { status: outcome.ok ? 'success' : 'error' });
      }

      if (outcome.ok && outcome.value) {
        // Once finished, show the whole path that ran rather than just the
        // last node the stream happened to touch.
        controller.selectionActions.selectNodes([...seen]);
        updateTurn(id, {
          running: false,
          result: outcome.value as RunResult,
          pendingApproval: null,
        });
      } else {
        updateTurn(id, {
          running: false,
          error: outcome.error ?? 'The run failed.',
          pendingApproval: null,
        });
      }
      scrollToEnd();
    },
    [controller, scrollToEnd, updateTurn],
  );

  const respondToApproval = useCallback(
    async (turnId: string, decision: 'approve' | 'reject') => {
      const turn = turns.find((t) => t.id === turnId);
      if (!turn || !turn.pendingApproval) return;
      const { threadId } = turn.pendingApproval;

      updateTurn(turnId, { running: true, pendingApproval: null });
      const document = JSON.parse(controller.document.exportJSON()) as unknown;

      await streamAndSettle(turnId, (onEvent) =>
        client.resume(
          { threadId, workflow: document, decision, workflowSlug: currentWorkflowSlug() },
          onEvent,
        ),
      );
    },
    [client, controller, streamAndSettle, turns, updateTurn],
  );

  const send = useCallback(async () => {
    const trimmed = question.trim();
    if (trimmed === '' || running) return;

    // The entry Text Input is the workflow's own "first contact" — writing
    // the message there means the chat and the canvas agree about what was
    // asked, rather than the question living only inside this panel.
    const entry = controller.model.nodes().find((node) => node.type === TEXT_INPUT_TYPE);
    if (entry) controller.nodes.setField(entry.id, 'prompt', trimmed);

    const id = `turn-${nextTurnId++}`;
    setTurns((all) => [
      ...all,
      {
        id,
        question: trimmed,
        running: true,
        activity: [],
        thinking: '',
        result: null,
        error: null,
        pendingApproval: null,
      },
    ]);
    setQuestion('');
    scrollToEnd();

    // Serialised through the same path as “export”, so the runtime receives
    // exactly the bytes that would be saved — no second representation.
    const document = JSON.parse(controller.document.exportJSON()) as unknown;

    await streamAndSettle(id, (onEvent) =>
      client.runStream(
        { workflow: document, question: trimmed, workflowSlug: currentWorkflowSlug() },
        onEvent,
      ),
    );
  }, [client, controller, question, running, scrollToEnd, streamAndSettle]);

  return (
    <Panel side="right" className="ask" style={{ width: 'var(--layout-inspector-width)' }}>
      <PanelHeader bordered title="Chat" />
      <PanelBody>
        <div className="ask__thread" ref={threadRef}>
          {turns.length === 0 ? (
            <p className="ask__meta ask__empty">
              Ask a question — it runs against the workflow on the canvas, live.
            </p>
          ) : null}
          {turns.map((turn) => (
            <Turn key={turn.id} turn={turn} onRespond={respondToApproval} />
          ))}
        </div>

        <Field label="Message" className="ask__composer">
          <TextInput
            value={question}
            placeholder="Which genre earned the most revenue?"
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              // Enter sends it. A message is one line, so a newline would be
              // less useful than the shortcut.
              if (event.key === 'Enter' && !event.shiftKey) void send();
            }}
          />
        </Field>
        <Button
          variant="primary"
          icon={<Icon glyph={Send} size="sm" />}
          disabled={running || question.trim() === ''}
          onClick={() => void send()}
        >
          {running ? 'Running…' : 'Send'}
        </Button>
      </PanelBody>
    </Panel>
  );
}

function Turn({
  turn,
  onRespond,
}: {
  turn: ChatTurn;
  onRespond: (turnId: string, decision: 'approve' | 'reject') => void;
}) {
  return (
    <div className="ask__turn">
      <div className="ask__question">{turn.question}</div>

      {turn.running || turn.activity.length > 0 ? <Activity rows={turn.activity} /> : null}

      {!turn.running && turn.activity.length > 0 ? (
        <button
          type="button"
          className="ask__export"
          onClick={() => exportTrace(turn)}
          title="Download this run as structured trace JSON"
        >
          Export trace JSON
        </button>
      ) : null}

      {turn.thinking ? (
        // Raw tokens while streaming (legible mid-arrival), markdown once
        // settled — the "improperly formatted chat" fix (ticket 62).
        turn.running ? (
          <pre className="ask__thinking">{turn.thinking}</pre>
        ) : (
          <RichText className="ask__thinking ask__thinking--settled" text={turn.thinking} />
        )
      ) : null}

      {turn.pendingApproval ? (
        <ApprovalPrompt
          approval={turn.pendingApproval}
          onApprove={() => onRespond(turn.id, 'approve')}
          onReject={() => onRespond(turn.id, 'reject')}
        />
      ) : null}

      {turn.error ? (
        <p className="ask__error">
          <Icon glyph={TriangleAlert} size="sm" />
          {turn.error}
        </p>
      ) : null}

      {turn.result ? <Answer result={turn.result} /> : null}
    </div>
  );
}

/**
 * The canvas affordance for a paused `human.approval` node: the chat panel,
 * since a run only pauses mid-conversation and the chat is where a developer
 * is already looking when it happens (the design question the handover left
 * open — "how does `interrupt()` surface as a canvas affordance" — settled
 * here rather than a dedicated modal or a node-card control, since the node
 * card has nowhere to show streamed context and a modal would block the rest
 * of the canvas for no reason).
 */
function ApprovalPrompt({
  approval,
  onApprove,
  onReject,
}: {
  approval: PendingApproval;
  onApprove: () => void;
  onReject: () => void;
}) {
  return (
    <div className="ask__approval">
      <p className="ask__approval-message">{approval.message}</p>
      {approval.candidate ? <RichText className="ask__answer" text={approval.candidate} /> : null}
      <div className="ask__approval-actions">
        <Button variant="primary" onClick={onApprove}>
          Approve
        </Button>
        <Button variant="secondary" onClick={onReject}>
          Reject
        </Button>
      </div>
    </div>
  );
}

/**
 * The live feed: which node just acted, in order, as the stream reports it.
 *
 * This is what makes a fan-out visible — three dispatched worker rows with
 * distinct `taskId`s appear one at a time as `Send` schedules them, rather
 * than a single spinner that gives no sense a fan-out happened at all.
 */
function Activity({ rows }: { rows: readonly ActivityRow[] }) {
  const trace = buildTrace(rows);
  return (
    <div className="ask__activity">
      {rows.length === 0 ? <p className="ask__meta">Waiting for the first node to run…</p> : null}
      {trace.map((step, index) => (
        <details
          key={`${step.node}-${step.taskId ?? index}`}
          className="ask__trace-step"
          open={false}
        >
          <summary className="ask__activity-row">
            <span className="ask__activity-node">{step.node.replace(/^node:/, '')}</span>
            {step.taskId ? <span className="ask__activity-task">{step.taskId}</span> : null}
            <span className="ask__activity-ms">{step.durationMs} ms</span>
            {step.children.length > 0 ? (
              <span className="ask__activity-count">{step.children.length} steps</span>
            ) : null}
          </summary>
          {step.children.map((child, childIndex) => (
            <div key={childIndex} className="ask__activity-row ask__activity-row--child">
              <span className="ask__activity-node">{child.node}</span>
              <span className="ask__activity-ms">{child.durationMs} ms</span>
            </div>
          ))}
          {step.output ? <RichText className="ask__trace-output" text={step.output} /> : null}
        </details>
      ))}
    </div>
  );
}

function Answer({ result }: { result: RunResult }) {
  const decisions = Object.entries(result.decisions);

  return (
    <div className="ask__answer-block">
      {/* Rendered first and styled like an error, not a footnote: an empty
          or ungrounded answer with the *reason* buried below it reads as a
          bug. Found live — "No answer was produced" with no explanation is
          indistinguishable from a real failure. */}
      {result.warnings.map((warning) => (
        <p key={warning} className="ask__warning">
          <Icon glyph={TriangleAlert} size="sm" />
          {warning}
        </p>
      ))}

      <RichText className="ask__answer" text={result.answer || '_No answer was produced._'} />

      {result.attempts > 1 ? (
        // Surfaced because a silent retry hides real cost and real quality
        // signal — two attempts means the grader rejected the first.
        <p className="ask__meta">{result.attempts} attempts before the grader passed it.</p>
      ) : null}

      {decisions.length > 0 ? (
        <div className="ask__decisions">
          {decisions.map(([nodeId, branch]) => (
            <div key={nodeId} className="ask__decision">
              <span className="ask__decision-node">{nodeId.replace(/^node:/, '')}</span>
              <span className="ask__decision-branch">{branch}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
