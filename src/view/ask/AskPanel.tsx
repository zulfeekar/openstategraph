import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Info, Lightbulb, Send, Square, TriangleAlert } from 'lucide-react';
import { Button, Icon, Panel, PanelBody, PanelHeader, TextInput } from '@design/primitives';
import {
  RuntimeClient,
  isCancelled,
  type RunOutcome,
  type RunResult,
  type RunStreamEvent,
} from '@core/runtime/RuntimeClient';
import { useController, useWorkbench } from '@app/WorkbenchContext';
import { collectRuntimeCredentials } from '@core/runtime/providerCredentials';
import { CURRENT_SLUG_KEY } from '@app/workflowFileWatch';
import { TEXT_INPUT_TYPE } from '@nodes/inputs/TextInputNode';
import { RichText } from '@view/common/RichText';
import { Activity, exportTrace, type ActivityRow } from './traceTree';
import { RunTimeline } from './RunTimeline';
import { parseSuggestion, type CapabilitySuggestion } from './suggestion';
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

/**
 * The browser-held provider keys, read fresh per send.
 *
 * Fresh rather than captured: a developer who hits "no model configured",
 * opens "Models and credentials" and pastes a key expects the very next send
 * to work, without reloading the editor. Omitted entirely when nothing is
 * stored, so a deployment with server-side keys sends no field at all.
 */
function credentialsPatch(
  providers: Parameters<typeof collectRuntimeCredentials>[0],
): { credentials?: Readonly<Record<string, string>> } {
  const credentials = collectRuntimeCredentials(providers);
  return credentials ? { credentials } : {};
}

/** One row in a turn's live "Activity" feed — a node that has started running. */

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
  /**
   * How this turn ended when the developer pressed Stop — and the two cases
   * are genuinely different, so they are not collapsed into a boolean.
   *
   * `'streaming'`: a live run was aborted. The client closed the connection,
   * the server's stream generator exited, and nothing further is scheduled.
   * Measured, not assumed: work already dispatched into the current step —
   * for a fan-out crew, every worker in it — runs to completion in the
   * background and its result is thrown away.
   *
   * `'paused'`: the turn was sitting at a `human.approval` interrupt, where
   * nothing is running to stop. Pressing Stop only walks away from the
   * prompt — LangGraph has the thread checkpointed and it stays resumable,
   * which is exactly what the line rendered for this case says. Calling that
   * "stopped" without the qualification would be a lie about the server.
   */
  readonly stopped: 'streaming' | 'paused' | null;
  /**
   * A capability gap the agent named, already validated against this editor
   * (`parseSuggestion`) — so its presence means the offer can actually be
   * honoured, never that a model merely asked for something.
   */
  readonly suggestion: CapabilitySuggestion | null;
  /** How the developer answered the offer. `null` while it still stands. */
  readonly suggestionDecision: 'accepted' | 'declined' | null;
  /**
   * What the editor did to the canvas on their behalf, in plain words.
   *
   * The product rule is explicit that the editor must *tell the user what it
   * did* — a graph that changes silently underneath a conversation is the
   * failure mode this whole feature is trying to avoid.
   */
  readonly notice: string | null;
  /** The answer with the suggestion fence stripped, when one was honoured. */
  readonly answerText: string | null;
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
export interface AskPanelProps {
  /**
   * A one-line explanation of *why* the panel just opened, when something
   * else opened it — today, Run handing a looping graph over to the backend
   * runtime. Shown above the thread and never as a modal: it explains a
   * transition the user did not ask for, so it must not also interrupt them.
   */
  readonly notice?: string | null;
  /**
   * Bumped by the opener each time it wants the composer focused. A counter
   * rather than a boolean because the *same* notice can be triggered twice in
   * a row, and focus must follow both times.
   */
  readonly focusNonce?: number;
  /**
   * A question the *toolbar* asked to run (ticket 03: Run is a real backend
   * run of the Input node's text). It arrives as a turn in this thread,
   * exactly as if the developer had typed it here — same client, same
   * stream, same history — so pressing Run and asking a question are one
   * conversation rather than two parallel ones.
   */
  readonly runRequest?: { readonly question: string; readonly nonce: number } | null;
  /**
   * Bumped by the toolbar's Stop button (ticket 10). A nonce for the same
   * reason `runRequest` is one: the *second* Stop press after a new run
   * started must land, and a boolean could not express it.
   *
   * The panel owns the `AbortController`, not the toolbar — the toolbar owns
   * the button but not the run, exactly as it already does for Run.
   */
  readonly stopRequest?: { readonly nonce: number } | null;
  /** Reports whether a run is streaming, so the toolbar's Run button can say so. */
  readonly onRunningChange?: (running: boolean) => void;
}

export function AskPanel({
  notice = null,
  focusNonce = 0,
  runRequest = null,
  stopRequest = null,
  onRunningChange,
}: AskPanelProps = {}) {
  const controller = useController();
  const workbench = useWorkbench();
  const [question, setQuestion] = useState('');
  const [turns, setTurns] = useState<readonly ChatTurn[]>([]);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLInputElement | null>(null);

  // Focus, never auto-send: the graph runs on the backend now, but *what* to
  // ask is still the developer's to say. Silently executing an empty question
  // would spend tokens on a question nobody asked.
  useEffect(() => {
    if (focusNonce > 0) composerRef.current?.focus();
  }, [focusNonce]);

  // One client for the panel's lifetime; the base URL is a dev default until
  // configuration exists.
  const client = useMemo(() => new RuntimeClient(), []);

  // A paused-on-approval turn is not `running`, but the composer should stay
  // disabled until it is resolved — sending a new message mid-approval would
  // overwrite the entry node's `prompt` out from under the paused thread.
  const running = turns.some((turn) => turn.running || turn.pendingApproval);

  /**
   * The abort handle for each turn that has a stream open, by turn id.
   *
   * A ref rather than state: nothing renders from it, and a re-render for a
   * controller nobody looks at would be pure churn. Entries are deleted the
   * moment their stream settles, so this map is empty between runs.
   *
   * Deliberately NOT aborted on unmount, for two reasons found in that
   * order. The decisive one is correctness: React's development StrictMode
   * mounts effects twice, so an abort-on-cleanup killed the very run the
   * mount had just started — pressing Run produced a turn that said
   * "Stopped by you" before a single node had reported. The second reason is
   * that it was the wrong policy anyway: the Chat panel is a toggle, and
   * hiding a panel is not a request to cancel the work you are watching.
   * Stop is the only thing that stops a run, which is exactly what a button
   * called Stop should mean.
   */
  const aborters = useRef(new Map<string, AbortController>());

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
      call: (
        onEvent: (event: RunStreamEvent) => void,
        signal: AbortSignal,
      ) => Promise<{
        readonly ok: boolean;
        readonly value?: RunOutcome;
        readonly error?: string;
      }>,
    ) => {
      // Created here rather than by each caller, so every stream this panel
      // opens is stoppable by construction and none can be forgotten.
      const aborter = new AbortController();
      aborters.current.set(id, aborter);
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
      /** The node most recently *queued* to glow — `activeNode` above is the
       * one currently glowing, which lags by the paced highlight chain. */
      let queuedActive: string | null = null;
      const onEvent = (event: RunStreamEvent) => {
        if (event.type === 'update') {
          const now = performance.now();
          const durationMs = Math.round(now - lastFrameAt);
          lastFrameAt = now;
          // What glows is the stream's own answer to "where is the run right
          // now" (ticket 01), not this frame's reporting node. During a
          // mounted team or a long agent step every frame is `internal`, so
          // the old `if (!event.internal)` gate left the highlight on the
          // previous top-level node — the router — for the entire time
          // something else was working.
          //
          // Internal frames are still not *rows* in the flat feed; they only
          // move the glow, and only when the owner actually changes, so a
          // chatty agent loop cannot flood the paced highlight queue.
          const target = event.activeNode || event.node;
          if (target && (!event.internal || target !== queuedActive)) {
            seen.add(target);
            // The output belongs to the frame's own node; a frame reporting
            // from inside a mount has nothing to write onto the mount's card.
            activate(target, event.node === target ? event.output : null);
            queuedActive = target;
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
                        namespace: event.namespace,
                        durationMs,
                        output: event.output,
                      },
                    ],
                  }
                : turn,
            ),
          );
          scrollToEnd();
        } else if (event.type === 'spawn') {
          // A spawn takes no time of its own — it is an announcement, not a
          // step — so it does not move `lastFrameAt` and carries a zero
          // duration. The next real frame still measures its gap from the
          // last frame that actually ran.
          setTurns((all) =>
            all.map((turn) =>
              turn.id === id
                ? {
                    ...turn,
                    activity: [
                      ...turn.activity,
                      {
                        node: event.parent,
                        taskId: event.taskId,
                        internal: false,
                        namespace: event.namespace,
                        durationMs: 0,
                        output: null,
                        spawn: {
                          kind: event.kind,
                          label: event.label,
                          instruction: event.instruction,
                        },
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

      const outcome = await call(onEvent, aborter.signal);
      // The stream is settled either way; nothing is left to abort. Dropped
      // before any of the branches below so no path can leak the entry.
      aborters.current.delete(id);

      // Waits for the last queued highlight's minimum-visible window before
      // finalising, so the very last node to act does not flash and vanish
      // the instant the run's own answer arrives.
      await highlightChain;

      if (outcome.ok && outcome.value && isCancelled(outcome.value)) {
        // Stopped. Not `success` (nothing completed) and not `error` (nothing
        // failed) — the node returns to rest, which is the same state a
        // canvas that never ran is in.
        if (activeNode) controller.model.setNodeRuntime(activeNode, { status: 'idle' });
        updateTurn(id, { running: false, pendingApproval: null, stopped: 'streaming' });
        scrollToEnd();
        return;
      }

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
        const result = outcome.value as RunResult;
        // Validated against the *live* editor here, not in the renderer: a
        // suggestion naming an unregistered type or a node that is not on
        // this canvas comes back as `null`, and its fence stays in the prose.
        const parsed = parseSuggestion(result.answer, {
          nodeTypes: new Set(workbench.registry.nodeTypes.list().map((type) => type.id)),
          nodeIds: new Set(controller.model.nodes().map((node) => node.id)),
        });
        updateTurn(id, {
          running: false,
          result,
          pendingApproval: null,
          suggestion: parsed.suggestion,
          answerText: parsed.suggestion ? parsed.text : null,
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
    [controller, scrollToEnd, updateTurn, workbench],
  );

  const respondToApproval = useCallback(
    async (turnId: string, decision: 'approve' | 'reject') => {
      const turn = turns.find((t) => t.id === turnId);
      if (!turn || !turn.pendingApproval) return;
      const { threadId } = turn.pendingApproval;

      updateTurn(turnId, { running: true, pendingApproval: null, stopped: null });
      const document = JSON.parse(controller.document.exportJSON()) as unknown;

      await streamAndSettle(turnId, (onEvent, signal) =>
        client.resume(
          {
            threadId,
            workflow: document,
            decision,
            workflowSlug: currentWorkflowSlug(),
            ...credentialsPatch(workbench.providers),
          },
          onEvent,
          { signal },
        ),
      );
    },
    [client, controller, streamAndSettle, turns, updateTurn, workbench],
  );

  /**
   * Runs one question as a new turn in the thread.
   *
   * Split out of `send` because the advisor loop needs to ask the *same*
   * question again after wiring a tool in — and a re-run has to be a genuine
   * turn (its own activity feed, its own answer, its own chance to suggest
   * again), not a quietly patched-up copy of the first one.
   */
  const ask = useCallback(
    async (trimmed: string) => {
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
          stopped: null,
          suggestion: null,
          suggestionDecision: null,
          notice: null,
          answerText: null,
        },
      ]);
      scrollToEnd();

      // Serialised through the same path as “export”, so the runtime receives
      // exactly the bytes that would be saved — no second representation.
      // Read *here*, per run: a re-run after a suggestion was applied must
      // post the canvas as it now is, with the new tool wired in.
      const document = JSON.parse(controller.document.exportJSON()) as unknown;

      await streamAndSettle(id, (onEvent, signal) =>
        client.runStream(
          {
            workflow: document,
            question: trimmed,
            workflowSlug: currentWorkflowSlug(),
            // Editor only — this is what lets an agent name a capability gap
            // and offer the fix. The customer `/chat` page never sets it.
            advisor: true,
            ...credentialsPatch(workbench.providers),
          },
          onEvent,
          { signal },
        ),
      );
    },
    [client, controller, scrollToEnd, streamAndSettle, workbench],
  );

  /**
   * Stop, from either the composer or the toolbar.
   *
   * Two shapes, because "running" covers two genuinely different situations
   * and only one of them has work to interrupt:
   *
   * - **A live stream.** Abort it. The fetch is torn down, the body reader is
   *   cancelled, the connection closes, and the backend's stream generator
   *   exits between supersteps (it logs that it did). A model call already in
   *   flight finishes in the provider and is discarded — nothing client-side
   *   can reach into it, and the UI never claims otherwise.
   * - **A turn paused at an approval.** Nothing is running. Stop just walks
   *   away from the prompt; the thread stays checkpointed on the server and
   *   is still resumable, which the rendered line says out loud.
   */
  const stop = useCallback(() => {
    const streaming = turns.find((turn) => turn.running);
    if (streaming) {
      aborters.current.get(streaming.id)?.abort();
      return;
    }
    const paused = turns.find((turn) => turn.pendingApproval);
    if (paused) updateTurn(paused.id, { pendingApproval: null, stopped: 'paused' });
  }, [turns, updateTurn]);

  // Stop, pressed in the toolbar. Same nonce discipline as Run above, and the
  // same reason: the press is the event, not the value.
  const stopNonce = stopRequest?.nonce ?? 0;
  const stopRef = useRef(stop);
  useEffect(() => {
    stopRef.current = stop;
  }, [stop]);
  const stoppedNonce = useRef(0);
  useEffect(() => {
    if (stopNonce <= 0 || stoppedNonce.current === stopNonce) return;
    stoppedNonce.current = stopNonce;
    stopRef.current();
  }, [stopNonce]);

  const send = useCallback(async () => {
    const trimmed = question.trim();
    if (trimmed === '' || running) return;
    setQuestion('');
    await ask(trimmed);
  }, [ask, question, running]);

  // Run, pressed in the toolbar. Keyed on the nonce alone: pressing Run twice
  // with the *same* Input text must run twice, which a value-keyed effect
  // could not express. `ask` is deliberately not a dependency — it changes
  // identity whenever the canvas does, and re-running the last question
  // because a node moved would be a run nobody asked for.
  const runNonce = runRequest?.nonce ?? 0;
  const askRef = useRef(ask);
  const runningRef = useRef(running);
  // Kept current in effects, never assigned during render: these refs exist
  // only so the run effect below can read the *latest* `ask` without taking
  // it as a dependency.
  useEffect(() => {
    askRef.current = ask;
  }, [ask]);
  useEffect(() => {
    runningRef.current = running;
  }, [running]);
  // Which nonce has already been honoured. Necessary, not defensive: React's
  // development StrictMode mounts effects twice, and without this a single
  // Run press started two real backend runs (seen live, two identical turns
  // in the thread).
  const ranNonce = useRef(0);
  useEffect(() => {
    if (runNonce <= 0 || ranNonce.current === runNonce) return;
    const trimmed = (runRequest?.question ?? '').trim();
    if (trimmed === '' || runningRef.current) return;
    ranNonce.current = runNonce;
    void askRef.current(trimmed);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the nonce is the trigger; see above
  }, [runNonce]);

  // The toolbar owns the Run button but not the run, so the one place that
  // knows a stream is open tells it.
  useEffect(() => {
    onRunningChange?.(running);
  }, [running, onRunningChange]);

  // A closed panel reports nothing, so the toolbar must not be left showing a
  // Stop it can no longer deliver — the panel that owns the abort handle is
  // gone. Reopening the panel re-reports the truth on its next render.
  const runningChangeRef = useRef(onRunningChange);
  useEffect(() => {
    runningChangeRef.current = onRunningChange;
  }, [onRunningChange]);
  useEffect(() => () => runningChangeRef.current?.(false), []);

  /**
   * Honours a suggestion: add the node, wire it, say so, ask again.
   *
   * Every mutation goes through the controller's command layer, so the canvas
   * projects the change the same way it would for a hand-drawn one and the
   * whole thing is a single undo away — which matters more here than
   * anywhere else in the editor, since this is the one edit the *developer*
   * did not draw.
   */
  const applySuggestion = useCallback(
    async (turnId: string, suggestion: CapabilitySuggestion) => {
      const target = controller.model.node(suggestion.attachTo);
      const definition = workbench.registry.nodeTypes.get(suggestion.nodeType);
      if (!target || !definition) {
        // Re-checked at click time, not only at parse time: the developer may
        // have deleted the agent while the offer sat in the thread.
        updateTurn(turnId, {
          suggestionDecision: 'declined',
          notice: 'That suggestion no longer fits this canvas — nothing was changed.',
        });
        return;
      }

      // Below the agent, not above it: a tool node's own port sits on its top
      // edge and links *upward* into the agent's bottom tool bus (see
      // `TOOL_PORT`), so anywhere else would draw a link back across the card.
      // Shifted right by whatever is already on that bus, so the second
      // suggested tool does not land on top of the first.
      const busy = controller.model.edgesInto({
        nodeId: suggestion.attachTo,
        portId: suggestion.port,
      }).length;
      const at = {
        x: target.position.x + busy * (definition.defaultSize.width + 32),
        y: target.position.y + target.size.height + 120,
      };

      const before = new Set(controller.model.nodes().map((node) => node.id));
      let created: string | null = null;
      // One transaction, so undo takes the node *and* its link back together.
      controller.history.transact(`Add ${definition.label}`, () => {
        if (!controller.nodes.add(suggestion.nodeType, at, { centre: false, select: false }).ok) {
          return;
        }
        created =
          controller.model.nodes().find((node) => !before.has(node.id))?.id ?? null;
        if (created) {
          controller.edges.connect(
            { nodeId: created, portId: 'tool' },
            { nodeId: suggestion.attachTo, portId: suggestion.port },
          );
        }
      });

      if (!created) {
        updateTurn(turnId, {
          suggestionDecision: 'declined',
          notice: `${definition.label} could not be added to this workflow.`,
        });
        return;
      }

      updateTurn(turnId, {
        suggestionDecision: 'accepted',
        notice: `Added ${definition.label} and wired it to ${target.title || suggestion.attachTo}. Re-running…`,
      });
      scrollToEnd();
      await ask(turns.find((turn) => turn.id === turnId)?.question ?? '');
    },
    [ask, controller, scrollToEnd, turns, updateTurn, workbench],
  );

  const declineSuggestion = useCallback(
    (turnId: string) => updateTurn(turnId, { suggestionDecision: 'declined' }),
    [updateTurn],
  );

  return (
    <Panel side="right" className="ask" style={{ width: 'var(--layout-inspector-width)' }}>
      <PanelHeader bordered title="Chat" />
      <PanelBody>
        {notice ? (
          <p className="ask__notice">
            <Icon glyph={Info} size="sm" />
            <span>{notice}</span>
          </p>
        ) : null}
        <div className="ask__thread" ref={threadRef}>
          {turns.length === 0 ? (
            <div className="ask__empty">
              <p className="ask__empty-title">Ask anything</p>
              <p className="ask__meta">
                Your question runs against the workflow on the canvas, live — the cards light up
                as each step takes its turn.
              </p>
            </div>
          ) : null}
          {turns.map((turn) => (
            <Turn
              key={turn.id}
              turn={turn}
              onRespond={respondToApproval}
              onApplySuggestion={applySuggestion}
              onDeclineSuggestion={declineSuggestion}
            />
          ))}
        </div>

        {/* One control, not a labelled field plus a detached button: the
            composer is the panel's primary affordance and should read as a
            single place to type and send, the way every chat does. The label
            is carried by the placeholder and `aria-label`, so nothing is lost
            to a screen reader. */}
        <div className="ask__composer" data-running={running || undefined}>
          <TextInput
            ref={composerRef}
            className="ask__composer-input"
            value={question}
            aria-label="Message"
            placeholder="Which genre earned the most revenue?"
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              // Enter sends it. A message is one line, so a newline would be
              // less useful than the shortcut.
              if (event.key === 'Enter' && !event.shiftKey) void send();
            }}
          />
          {/* One control, two meanings — Send becomes Stop while the turn
              streams, rather than a disabled "Running…" that leaves the
              developer with nothing to press. Same slot, so the thing to
              click never moves. */}
          <Button
            variant={running ? 'danger-solid' : 'primary'}
            className="ask__composer-send"
            icon={<Icon glyph={running ? Square : Send} size="sm" />}
            disabled={running ? false : question.trim() === ''}
            aria-label={running ? 'Stop' : 'Send'}
            onClick={() => (running ? stop() : void send())}
          >
            {running ? 'Stop' : 'Send'}
          </Button>
        </div>
      </PanelBody>
    </Panel>
  );
}

function Turn({
  turn,
  onRespond,
  onApplySuggestion,
  onDeclineSuggestion,
}: {
  turn: ChatTurn;
  onRespond: (turnId: string, decision: 'approve' | 'reject') => void;
  onApplySuggestion: (turnId: string, suggestion: CapabilitySuggestion) => void;
  onDeclineSuggestion: (turnId: string) => void;
}) {
  // Per turn, and ephemeral: a run's timeline is a fact about that run, and
  // nothing about it deserves to be persisted.
  const [view, setView] = useState<'trace' | 'timeline'>('trace');

  return (
    <div className="ask__turn">
      <div className="ask__question">{turn.question}</div>

      {turn.running || turn.activity.length > 0 ? (
        <div className="ask__steps">
          {/* Two readings of one record, never two records: the trace answers
              *what* ran and what it produced, the timeline answers *when* and
              for how long. Both are built from `turn.activity`. */}
          <div className="ask__views" role="tablist" aria-label="Run steps view">
            {(['trace', 'timeline'] as const).map((option) => (
              <button
                key={option}
                type="button"
                role="tab"
                aria-selected={view === option}
                className="ask__view-tab"
                onClick={() => setView(option)}
              >
                {option === 'trace' ? 'Trace' : 'Timeline'}
              </button>
            ))}
          </div>
          {view === 'trace' ? (
            <Activity rows={turn.activity} />
          ) : (
            <RunTimeline rows={turn.activity} running={turn.running} />
          )}
        </div>
      ) : null}

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

      {/* Muted, with no error styling and no warning glyph: the developer
          asked for this, so presenting it as a failure would be the panel
          disagreeing with them. */}
      {turn.stopped ? (
        <p className="ask__stopped">
          {turn.stopped === 'paused'
            ? 'Stopped by you — this run was waiting for approval, so nothing was interrupted. It stays checkpointed on the server and can still be resumed.'
            : 'Stopped by you — nothing further is scheduled. Steps already dispatched finish in the background and their results are discarded.'}
        </p>
      ) : null}

      {turn.error ? (
        <p className="ask__error">
          <Icon glyph={TriangleAlert} size="sm" />
          {turn.error}
        </p>
      ) : null}

      {turn.result ? <Answer result={turn.result} text={turn.answerText} /> : null}

      {turn.suggestion ? (
        <SuggestionCard
          suggestion={turn.suggestion}
          decision={turn.suggestionDecision}
          onAccept={() => onApplySuggestion(turn.id, turn.suggestion as CapabilitySuggestion)}
          onDecline={() => onDeclineSuggestion(turn.id)}
        />
      ) : null}

      {/* What the editor did on the developer's behalf, in the thread where
          they are already looking — never only on the canvas. */}
      {turn.notice ? <p className="ask__did">{turn.notice}</p> : null}
    </div>
  );
}

/**
 * The capability-gap offer: "this workflow has no web access. Add it?"
 *
 * Deliberately a card in the thread rather than a modal or a canvas
 * affordance. The gap was discovered *in a conversation*, the developer is
 * reading that conversation, and the answer is one word — interrupting the
 * whole editor to ask it would be out of all proportion.
 *
 * Declining collapses it to a muted line rather than removing it: the offer
 * is part of what happened in this turn, and a thread that edits its own
 * history is a thread you cannot trust.
 */
function SuggestionCard({
  suggestion,
  decision,
  onAccept,
  onDecline,
}: {
  suggestion: CapabilitySuggestion;
  decision: 'accepted' | 'declined' | null;
  onAccept: () => void;
  onDecline: () => void;
}) {
  if (decision !== null) {
    return (
      <p className="ask__suggestion-settled">
        {decision === 'accepted' ? 'Added' : 'Declined'} — {suggestion.label}
      </p>
    );
  }

  return (
    <div className="ask__suggestion">
      <p className="ask__suggestion-headline">
        <Icon glyph={Lightbulb} size="sm" />
        <span>
          <strong>{suggestion.label}</strong> — {suggestion.reason}
        </span>
      </p>
      <div className="ask__suggestion-actions">
        <Button variant="primary" onClick={onAccept}>
          Add &amp; re-run
        </Button>
        <Button variant="secondary" onClick={onDecline}>
          No thanks
        </Button>
      </div>
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

function Answer({ result, text }: { result: RunResult; text?: string | null }) {
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

      {/* `text` is the answer with an honoured suggestion's fence removed —
          the card below says the same thing, and better. */}
      <RichText
        className="ask__answer"
        text={(text ?? result.answer) || '_No answer was produced._'}
      />

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
