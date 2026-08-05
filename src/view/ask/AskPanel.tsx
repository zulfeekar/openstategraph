import { useCallback, useMemo, useRef, useState } from 'react';
import { Send, TriangleAlert } from 'lucide-react';
import { Button, Field, Icon, Panel, PanelBody, PanelHeader, TextInput } from '@design/primitives';
import { RuntimeClient, type RunResult, type RunStreamEvent } from '@core/runtime/RuntimeClient';
import { useController } from '@app/WorkbenchContext';
import { TEXT_INPUT_TYPE } from '@nodes/inputs/TextInputNode';
import './AskPanel.css';

/** One row in a turn's live "Activity" feed — a node that has started running. */
interface ActivityRow {
  readonly node: string;
  /** Distinguishes concurrently dispatched worker instances (ticket 27). */
  readonly taskId: string | null;
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

  const running = turns.some((turn) => turn.running);

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
      { id, question: trimmed, running: true, activity: [], thinking: '', result: null, error: null },
    ]);
    setQuestion('');
    scrollToEnd();

    // Serialised through the same path as “export”, so the runtime receives
    // exactly the bytes that would be saved — no second representation.
    const document = JSON.parse(controller.document.exportJSON()) as unknown;
    const seen = new Set<string>();
    let activeNode: string | null = null;

    // Queues node highlights so each one is visible for at least
    // `MIN_HIGHLIGHT_MS`, regardless of how fast the SSE frames themselves
    // arrive — see the constant's own comment for why this exists.
    let highlightChain: Promise<void> = Promise.resolve();
    const activate = (nodeId: string) => {
      highlightChain = highlightChain.then(async () => {
        // One node glows at a time, in the order the stream reports — the
        // previous node's card returns to its resting state exactly as it
        // would after a local preview run finishes with it.
        if (activeNode && activeNode !== nodeId) {
          controller.model.setNodeRuntime(activeNode, { status: 'success' });
        }
        controller.model.setNodeRuntime(nodeId, { status: 'running' });
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

    const onEvent = (event: RunStreamEvent) => {
      if (event.type === 'update') {
        seen.add(event.node);
        activate(event.node);
        // Data collection is never delayed by the animation pacing above —
        // only the visual glow is paced, not the record of what happened.
        setTurns((all) =>
          all.map((turn) =>
            turn.id === id
              ? { ...turn, activity: [...turn.activity, { node: event.node, taskId: event.taskId }] }
              : turn,
          ),
        );
        scrollToEnd();
      } else if (event.type === 'token') {
        setTurns((all) =>
          all.map((turn) => (turn.id === id ? { ...turn, thinking: turn.thinking + event.content } : turn)),
        );
        scrollToEnd();
      }
    };

    const outcome = await client.runStream({ workflow: document, question: trimmed }, onEvent);

    // Waits for the last queued highlight's minimum-visible window before
    // finalising, so the very last node to act does not flash and vanish
    // the instant the run's own answer arrives.
    await highlightChain;
    if (activeNode) {
      controller.model.setNodeRuntime(activeNode, { status: outcome.ok ? 'success' : 'error' });
    }

    if (outcome.ok) {
      // Once finished, show the whole path that ran rather than just the
      // last node the stream happened to touch.
      controller.selectionActions.selectNodes([...seen]);
      updateTurn(id, { running: false, result: outcome.value });
    } else {
      updateTurn(id, { running: false, error: outcome.error });
    }
    scrollToEnd();
  }, [client, controller, question, running, scrollToEnd, updateTurn]);

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
            <Turn key={turn.id} turn={turn} />
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

function Turn({ turn }: { turn: ChatTurn }) {
  return (
    <div className="ask__turn">
      <div className="ask__question">{turn.question}</div>

      {turn.running || turn.activity.length > 0 ? <Activity rows={turn.activity} /> : null}

      {turn.thinking ? (
        <pre className="ask__thinking">{turn.thinking}</pre>
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
 * The live feed: which node just acted, in order, as the stream reports it.
 *
 * This is what makes a fan-out visible — three dispatched worker rows with
 * distinct `taskId`s appear one at a time as `Send` schedules them, rather
 * than a single spinner that gives no sense a fan-out happened at all.
 */
function Activity({ rows }: { rows: readonly ActivityRow[] }) {
  return (
    <div className="ask__activity">
      {rows.length === 0 ? <p className="ask__meta">Waiting for the first node to run…</p> : null}
      {rows.map((row, index) => (
        <div key={`${row.node}-${row.taskId ?? index}`} className="ask__activity-row">
          <span className="ask__activity-node">{row.node.replace(/^node:/, '')}</span>
          {row.taskId ? <span className="ask__activity-task">{row.taskId}</span> : null}
        </div>
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

      <pre className="ask__answer">{result.answer || '_No answer was produced._'}</pre>

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
