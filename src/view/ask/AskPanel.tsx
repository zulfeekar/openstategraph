import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { showsThinking } from './settledThinking';
import { attemptsLine } from './attemptsLine';
import { rectOfAdded } from './revealAdded';
import { doorHeadline } from './doorHeadline';
import { graderVerdictLine } from './graderVerdictLine';
import { moduleBrief } from './moduleBrief';
import { usePaperController } from '@app/WorkbenchContext';
import {
  History,
  Info,
  Lightbulb,
  MessageSquarePlus,
  Send,
  Square,
  TriangleAlert,
} from 'lucide-react';
import { Button, Icon, Panel, PanelBody, PanelHeader, TextArea } from '@design/primitives';
import {
  RuntimeClient,
  isCancelled,
  type RunOutcome,
  type RunResult,
  type RunStreamEvent,
} from '@core/runtime/RuntimeClient';
import type { OpenStreams } from '@core/runtime/OpenStreams';
import { useController, useModelEvents, useWorkbench } from '@app/WorkbenchContext';
import { entryQuestion } from '@nodes/inputs/entryQuestion';
import { composerPlaceholder } from './composerPlaceholder';
import { IDLE_RUNTIME } from '@core/model/contracts/node';
import { defaultsFrom } from '@core/model/contracts/fields';
import { collectRuntimeCredentials } from '@core/runtime/providerCredentials';
import { frameOwnsOutput, frameTarget } from '@core/runtime/frameTarget';
import {
  getOpenAddress,
  OPEN_ADDRESS_KEY,
  openSubject,
  subscribeOpenAddress,
} from '@app/openAddress';
import { parseMountAddress } from '@core/model/MountAddress';
import { replayRun, turnToReplay } from '@core/runtime/replayRun';
import { CURRENT_SLUG_KEY } from '@app/workflowFileWatch';
import { RichText } from '@view/common/RichText';
import { Activity, exportTrace, type ActivityRow } from './traceTree';
import { ToolResults, appendToolChunk, type ToolResult } from './toolResults';
import { RunTimeline } from './RunTimeline';
import { PastRuns } from './PastRuns';
import { displayNamesByGraphName } from '@core/runtime/graphName';
import { busKey, suggestionOutcome, unreadyFields, type CapabilitySuggestion } from './suggestion';
import { acceptAction, type AcceptAction } from './acceptAction';
import { ConversationStore } from './conversationStore';
import { clearRunInFlight, markRunInFlight } from './interruptedRun';
import { progressLine } from './progressLine';
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
 * Which conversation this tab is having — the **address**, falling back to the
 * class slug (`openSubject`).
 *
 * Read fresh per call for the same reason `currentWorkflowSlug` is: a drill-in
 * or a workflow switch changes it while the panel is open, and a captured
 * subject would keep writing a new document's turns into the old one's
 * conversation.
 */
function currentSubject(): string | null {
  try {
    return openSubject({
      openAddress: sessionStorage.getItem(OPEN_ADDRESS_KEY),
      classSlug: currentWorkflowSlug() ?? null,
    });
  } catch {
    return null; // sessionStorage can throw in restricted contexts
  }
}

/**
 * Every conversation this editor is having, one per open workflow.
 *
 * **Module scope, not component state** — that is the whole of
 * `memory-and-replay` 35. The Ask panel is conditionally rendered, so closing
 * it is an unmount, and a thread held in `useState` died with it: the canvas'
 * Run button and the panel's composer are two doors onto one conversation,
 * and only one of them was remembering. `conversationStore.ts` carries the
 * argument, including why the transcript moves with the thread rather than
 * without it.
 */
const conversations = new ConversationStore<ChatTurn>();

/**
 * The last toolbar Run press this load has already executed — see the effect
 * that reads it for why it outlives the panel.
 */
let honouredRunNonce = 0;

/** The store's channel and the open-workflow channel, as one subscription. */
function subscribeConversation(listener: () => void): () => void {
  const unstore = conversations.subscribe(listener);
  const unopen = subscribeOpenAddress(listener);
  return () => {
    unstore();
    unopen();
  };
}

/**
 * The browser-held provider keys, read fresh per send.
 *
 * Fresh rather than captured: a developer who hits "no model configured",
 * opens "Models and credentials" and pastes a key expects the very next send
 * to work, without reloading the editor. Omitted entirely when nothing is
 * stored, so a deployment with server-side keys sends no field at all.
 */
function credentialsPatch(providers: Parameters<typeof collectRuntimeCredentials>[0]): {
  credentials?: Readonly<Record<string, string>>;
} {
  const credentials = collectRuntimeCredentials(providers);
  return credentials ? { credentials } : {};
}

/** One row in a turn's live "Activity" feed — a node that has started running. */

/** A run paused at a `human.approval` node, waiting on this turn. */
interface PendingApproval {
  readonly threadId: string;
  readonly message: string;
  readonly candidate: string;
  /** The upstream grader's judgement of `candidate`, or `''` if none judged it. */
  readonly verdict: string;
  readonly reason: string;
}

/** One question-and-answer exchange in the chat thread. */
interface ChatTurn {
  readonly id: string;
  readonly question: string;
  /**
   * True when this turn opened a new conversation rather than continuing the
   * one above it — the developer pressed "New conversation", or they switched
   * the open workflow, which starts one for them.
   *
   * Recorded on the turn instead of erasing the thread above it, for the same
   * reason a declined suggestion collapses rather than disappears: what
   * happened in this panel is a record, and a record that rewrites itself
   * cannot be read. It renders as a rule across the thread, so the boundary
   * between "this had context" and "this did not" is visible at the moment it
   * matters — reading back an answer and wondering what it knew.
   */
  readonly freshThread: boolean;
  readonly running: boolean;
  readonly activity: readonly ActivityRow[];
  /**
   * What the step currently working last said about *itself* — the `progress`
   * frame, which the editor used to drop on the floor (production-ready 56).
   *
   * One live line, not a row. A trace row records that something *finished*
   * and stays; this says "still going" and is replaced by the next report or
   * by the step's own completion. It is therefore not part of `activity` and
   * not in the exported trace: nothing about it is a fact about the run
   * afterwards, which is the same reason `chat.html` keeps it out of the
   * timeline.
   *
   * Rendered only while `running`, so every ending clears it without any
   * ending having to remember to — a run stopped mid-tool must not leave
   * "page 3 of 12" on screen forever.
   */
  readonly progress: string | null;
  /**
   * Streamed *model* text, concatenated live — "how the agent thinks".
   *
   * Model text only, since ticket 02: tool results arrive on the same stream
   * and used to land here too, which both mixed two voices into one paragraph
   * and destroyed the tools' formatting when the settled blob was rendered as
   * Markdown. They now have their own record below.
   */
  readonly thinking: string;
  /** What each tool returned this turn, in the order the tools were called. */
  readonly toolResults: readonly ToolResult[];
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
  /**
   * What the run needed when **nothing in the library provides it**.
   *
   * Its own field beside `suggestion`, never folded into it: one places a tool
   * that exists, the other opens an interview to build a workflow-scoped one
   * (`every-workflow-green` 34). A card that cannot tell them apart cannot
   * tell the developer which is about to happen.
   */
  readonly capabilityGap: string | null;
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
  /**
   * The workflow this turn was asked about — `null` for a never-saved one.
   *
   * Ticket 25. A conversation outlives the document: opening another workflow
   * starts a fresh *thread* but keeps the turns on screen, so without this the
   * panel held a run with no address, and the canvas projection (`replayRun`)
   * repainted whichever document was open next by matching node ids that two
   * unrelated files happen to share. Recorded at send, from the same
   * `currentWorkflowSlug()` the request itself is addressed with, so the
   * record and the run cannot disagree.
   */
  readonly slug: string | null;
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
/**
 * The document changes that can change a lane's name: a node appearing,
 * disappearing, or being renamed. Hoisted to a module constant because
 * `useModelEvents` keys its subscription on the array's contents.
 */
const NAMING_EVENTS = ['node:added', 'node:removed', 'node:title'] as const;

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
  /**
   * Who holds the abort handle for every stream this panel opens.
   *
   * Owned by the shell rather than by this component, because this component
   * is conditionally rendered — closing the panel is a real unmount, and a
   * handle that dies with the panel is a run nobody can stop
   * (install-experience ticket 07). The shell aborts on the close *gesture*;
   * see `OpenStreams` for why an unmount effect cannot do that job.
   */
  readonly streams: OpenStreams;
  /**
   * Open showing History rather than the live thread (ticket 55.6).
   *
   * Set by the shell when this editor came back from a reload that killed a
   * run: the thread it would show is empty, and the run it is about is on the
   * server, which is exactly what History reads.
   */
  readonly openHistory?: boolean;
}

export function AskPanel({
  notice = null,
  focusNonce = 0,
  runRequest = null,
  stopRequest = null,
  onRunningChange,
  streams,
  openHistory = false,
}: AskPanelProps) {
  const controller = useController();
  const workbench = useWorkbench();
  const [question, setQuestion] = useState('');
  /**
   * The conversation this tab is having about the open workflow — its
   * transcript and its thread, read from the store above rather than held
   * here. A snapshot, so an unmount takes nothing with it.
   */
  const conversation = useSyncExternalStore(subscribeConversation, () =>
    conversations.read(currentSubject()),
  );
  const turns = conversation.turns;
  /**
   * The same functional-updater shape the panel's own `useState` had, so every
   * caller reads unchanged — the subject is resolved at write time, never
   * captured, for the reason `currentSubject` gives.
   */
  const setTurns = useCallback((updater: (all: readonly ChatTurn[]) => readonly ChatTurn[]) => {
    conversations.setTurns(currentSubject(), updater);
  }, []);
  /**
   * Whether the panel is showing history instead of the live thread.
   *
   * A swap, not a second panel: the two are the same subject at different
   * times, and a side-by-side would halve the width of both. The live thread's
   * state is untouched while history is up, so closing it returns to exactly
   * the conversation that was there — a run streaming in the background keeps
   * streaming into a thread that is merely not on screen.
   */
  const [historyOpen, setHistoryOpen] = useState(openHistory);
  /**
   * What the open canvas calls each node the runtime named, for History's
   * lane headers (`memory-and-replay` 39).
   *
   * Computed here rather than in `PastRuns` because this is where the document
   * is. A stored run is read against whatever the document says **now** — that
   * is the whole point of resolving it client-side rather than in the
   * checkpointer, which has never seen this canvas — so it has to follow a
   * rename while the panel is open, which is what the subscription buys.
   *
   * Three events, not `useWorkflowVersion`: the map depends on which nodes
   * exist and what they are called, and re-rendering on every drag would cost
   * a pass over the panel per mouse-move for a map that cannot have changed.
   * The hook is called for the re-render, not for a value — the same shape
   * `DrillBanner` and `WorkflowManager` use — and the map is then derived
   * plainly, being one pass over a document of tens of nodes.
   */
  useModelEvents(NAMING_EVENTS);
  const laneNames = displayNamesByGraphName(workbench.model.nodes());
  /**
   * The conversation in progress lives in `conversations`, not here.
   *
   * It was `useState` in this component until `memory-and-replay` 35, and the
   * docblock that stood here defended holding it no longer than the transcript
   * — rightly, and for reasons that still stand and are now recorded on the
   * store:
   *
   * 1. A thread restored without the turns that filled it is an answer with an
   *    antecedent the developer cannot see, which is worse than losing it.
   * 2. This is an editor, and a reload usually follows an edit; the
   *    checkpointed `messages` belong to the graph as it was. So neither the
   *    thread nor the transcript is persisted across a reload — the store is
   *    in memory for this load, and `production-ready` 90 is where that
   *    question is asked properly.
   *
   * What was wrong was the *scope* it concluded from them. A panel close is
   * not a reload: nothing was edited, the document on the canvas is the one
   * that ran, and the developer who pressed Run from the toolbar with the
   * panel shut was continuing the same conversation by every measure except
   * the one the code used. So both move together, one step out — out of the
   * component that unmounts, into the module that does not.
   */
  const threadRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);

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

  /*
   * The abort handles for this panel's streams live in `streams`, which the
   * **shell** owns (`OpenStreams`, prop above). They used to be a bare `Map`
   * in a ref here, and that comment recorded a decision worth keeping half
   * of: they are deliberately NOT aborted from an unmount effect, because
   * React's development StrictMode mounts effects twice and the toolbar's Run
   * both opens this panel and starts a run from a mount effect — so
   * abort-on-cleanup killed the very run the mount had started, and the turn
   * said "Stopped by you" before a single node reported.
   *
   * What that decision got wrong was the conclusion: it left the handle
   * *inside* a conditionally rendered component, so closing the panel orphaned
   * the stream (install-experience ticket 07) — the fetch stayed open, the
   * reader kept writing into a dead component, and the unmount's "not running"
   * report retired the only button that could have stopped it. An effect
   * cleanup cannot tell a close from a remount. The close *gesture* can, and
   * that is where the abort now hangs (`AppShell`'s Ask toggle). Stop still
   * means the only deliberate stop; closing the panel you are watching the run
   * in is now the other one, and it says so by actually ending the run.
   */

  const updateTurn = useCallback(
    (id: string, patch: Partial<ChatTurn>) => {
      setTurns((all) => all.map((turn) => (turn.id === id ? { ...turn, ...patch } : turn)));
    },
    [setTurns],
  );

  const scrollToEnd = useCallback(() => {
    // Newest turn at the bottom, so a growing thread reads like a chat rather
    // than requiring a manual scroll to see what just arrived.
    requestAnimationFrame(() => {
      const el = threadRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }, []);

  /**
   * Retires the canvas's paused mark (UX-01) when the pause is over.
   *
   * Keyed off the model rather than off remembered node ids, because the
   * model is where the state actually lives — one node is paused at a time,
   * and asking it is what keeps this correct if a later edit ever pauses a
   * different node than the one this panel last highlighted.
   */
  const clearPausedNodes = useCallback(
    (status: 'idle' | 'running') => {
      for (const node of controller.model.nodes()) {
        if (node.runtime.status === 'paused') {
          controller.model.setNodeRuntime(node.id, { status });
        }
      }
    },
    [controller],
  );

  /**
   * Returns every card to "nothing has run yet", at the moment a run starts.
   *
   * Ticket 33, and the half of it that made Run *feel* dead. Stop leaves the
   * canvas exactly as the interrupted run painted it — the nodes that
   * completed stay green, the output card keeps the last answer — and nothing
   * used to clear that. So pressing Run again changed nothing visible for the
   * several seconds before the first frame arrived: the same greens, the same
   * stale answer, the same numbers. "It feels like it's not starting again" is
   * a precise description of a canvas that looks identical to the one you were
   * just looking at.
   *
   * The deeper reason it belongs here rather than in a Stop handler: a canvas
   * showing a *finished* run while a *different* run streams is the same
   * defect as a card showing a saved prompt while a live question is in
   * flight. What is on screen must be this run, and at the start of a run this
   * run has produced nothing.
   *
   * `IDLE_RUNTIME` rather than `{ status: 'idle' }`: the status is not the
   * only stale thing on the card. `output` is the previous answer, `durationMs`
   * the previous timing, `error` a failure that has been superseded.
   */
  const resetRunState = useCallback(() => {
    for (const node of controller.model.nodes()) {
      controller.model.setNodeRuntime(node.id, IDLE_RUNTIME);
    }
  }, [controller]);

  /**
   * Runs the shared tail of both a fresh send and a resumed approval: wires
   * `onEvent` to the canvas highlight/activity feed, then settles the turn
   * into a result, an error, or — new for `human.approval` — a paused
   * `pendingApproval` state instead of either. Same shape for both callers
   * because a resumed run can itself pause again at a later approval node.
   *
   * It is also the single place the panel learns **which thread it is in**.
   * Every one of the three terminal frames names the same thread (`done`,
   * `interrupt`, `error` — ticket 11 put it on all of them, where before only
   * `interrupt` disclosed it), so remembering it here rather than at each
   * caller means no ending can forget it. A failed turn matters as much as a
   * finished one: the question still reached the graph, so the next send must
   * continue that conversation rather than quietly opening a second.
   */
  const streamAndSettle = useCallback(
    async (
      id: string,
      /** The workflow this stream is running against, bound to the thread it
       * reports back — see `ThreadBinding`. */
      slug: string | undefined,
      call: (
        onEvent: (event: RunStreamEvent) => void,
        signal: AbortSignal,
      ) => Promise<{
        readonly ok: boolean;
        readonly value?: RunOutcome;
        readonly error?: string;
      }>,
    ) => {
      // Registered here rather than by each caller, so every stream this
      // panel opens is stoppable by construction and none can be forgotten —
      // and registered with the *shell's* owner, so closing the panel stops it
      // too. The caller never holds a controller; it only ever gets a signal.
      const signal = streams.begin(id);
      // A reload from here on would take the panel with it. The mark is what
      // lets the next load say so instead of coming back blank (55.6); it is
      // cleared in the same `finally` that settles the stream, so every
      // ending — answered, stopped, failed, paused — clears it.
      markRunInFlight({ ...(slug ? { slug } : {}), at: Date.now() });
      // The rules — an empty id leaves what is held alone, a different one
      // rebinds — live in `thread.ts` where they are unit-tested; a thread is
      // a server object, so getting them wrong changes nothing on screen.
      const remember = (threadId: string) => {
        conversations.remember(currentSubject(), slug, threadId);
      };
      const seen = new Set<string>();
      let activeNode: string | null = null;
      // Read at call time, never captured: "Edit team" swaps the whole
      // document under a run that is still streaming, and the projection must
      // follow the developer rather than the document it started on.
      const hasNode = (id: string) => controller.model.node(id) != null;
      // Read at call time for the same reason `hasNode` is: a drill-in
      // changes which workflow is on screen while this stream is still open,
      // and the projection must follow the developer. This is what lets a
      // frame be matched to the *document* it happened in rather than to an
      // id two documents may share — see `frameTarget`.
      //
      // The **address**, not the slug (ticket 42, tranche 6): `concierge` can
      // mount one package twice, and a slug cannot say which of the two is on
      // screen. The class slug is the fallback for a tab showing a document
      // that is not in this run's tree at all.
      const openAddress = () =>
        getOpenAddress() ?? parseMountAddress(currentWorkflowSlug() ?? '') ?? undefined;

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
      /**
       * Set the moment a stop is known, and read by every queued highlight.
       *
       * Ticket 33's lag, and the thing that made a second Run press vanish.
       * The queue below sleeps `MIN_HIGHLIGHT_MS` per node, and the turn is
       * only marked `running: false` after the whole of it has drained — so
       * after a stop the toolbar went on showing **Stop** for as long as the
       * backlog took. A press in that window resolves through `runIntent` to
       * `stop`, and stopping an already-stopped run aborts a controller that
       * has already been dropped: the press did nothing, silently, which is
       * exactly what the repo's own "no gesture that silently does nothing"
       * standard forbids.
       *
       * A stopped run has no last node to hold visible, because the developer
       * asked for it to end. So the queue is abandoned rather than drained:
       * the pending entries neither paint nor sleep, `await highlightChain`
       * returns on the next tick, and the button is a Run again immediately.
       */
      let abandoned = false;
      const activate = (nodeId: string, output: string | null) => {
        const now = performance.now();
        const durationMs = Math.round(now - lastEventAt);
        lastEventAt = now;

        highlightChain = highlightChain.then(async () => {
          if (abandoned) return;
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
          // Resolved against the *open* document, so opening a mounted Team
          // or Workflow mid-run shows that run inside it rather than a static
          // diagram — see `frameTarget`. On the parent canvas this still
          // answers with the mount, because a parent never holds its child's
          // node ids.
          const target = frameTarget(event, hasNode, openAddress());
          if (target && (!event.internal || target !== queuedActive)) {
            seen.add(target);
            // The output belongs to the frame's own node; a frame reporting
            // from inside a mount has nothing to write onto the mount's card.
            // `frameOwnsOutput`, not `event.node === target`: `node` is the
            // runtime's name for the step, so inside a mount it never equals a
            // canvas id and every nested card glowed empty.
            activate(target, frameOwnsOutput(event, target) ? event.output : null);
            queuedActive = target;
          }
          // Data collection is never delayed by the animation pacing above —
          // only the visual glow is paced, not the record of what happened.
          setTurns((all) =>
            all.map((turn) =>
              turn.id === id
                ? {
                    ...turn,
                    // A step completed, so whatever it was last saying about
                    // itself is no longer true. Cleared on every `update`,
                    // internal ones included: an agent's inner `tools` step
                    // finishing is exactly the end of the tool call whose
                    // "Calling search_docs on langchain-docs" is on screen.
                    progress: null,
                    activity: [
                      ...turn.activity,
                      {
                        node: event.node,
                        taskId: event.taskId,
                        internal: event.internal,
                        namespace: event.namespace,
                        // Carried onto the row so this frame can be projected
                        // again later, onto a document that was not open when
                        // it arrived — see `ActivityRow.path` and `replayOnto`.
                        path: event.path,
                        // Without the slugs the replay cannot use the exact
                        // rule and falls back to the ambiguous id walk — two
                        // rules for one wire format, which is the drift
                        // `frameTarget` exists to prevent.
                        pathSlugs: event.pathSlugs,
                        activeNode: event.activeNode,
                        durationMs,
                        output: event.output,
                        // A grader that reached its verdict without invoking a
                        // model says so here (`production-ready` 92); empty on
                        // every other frame.
                        check: event.check,
                        reason: event.reason,
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
          // Tokens move the glow too (ticket 02). This is what makes the
          // highlight say "is working" instead of "has finished": an `update`
          // frame is only emitted once a node completes, so on a real run the
          // mounted analyst streamed 100+ tokens over ~20s while the last
          // update frame — and therefore the glow — still said `router1`.
          //
          // Coalesced against `queuedActive`, which is the whole reason that
          // variable is the *queued* node rather than the glowing one: the
          // server repeats `activeNode` on every frame (its meaning must not
          // vary by frame type), so without this compare one model turn would
          // push 100+ identical entries onto a highlight chain that sleeps
          // `MIN_HIGHLIGHT_MS` between each — a queue minutes long, and a
          // canvas still animating after the answer arrived.
          //
          // No output is written: a token frame carries a fragment of text,
          // never the node's finished result, and the `update` frame that
          // follows is what fills the card.
          const tokenTarget = frameTarget(event, hasNode, openAddress());
          if (tokenTarget && tokenTarget !== queuedActive) {
            seen.add(tokenTarget);
            activate(tokenTarget, null);
            queuedActive = tokenTarget;
          }
          setTurns((all) =>
            all.map((turn) =>
              turn.id === id
                ? event.kind === 'tool'
                  ? { ...turn, toolResults: appendToolChunk(turn.toolResults, event) }
                  : { ...turn, thinking: turn.thinking + event.content }
                : turn,
            ),
          );
          scrollToEnd();
        } else if (event.type === 'progress') {
          // The frame the editor dropped while the customer page rendered it
          // — the inverse of what the architecture review believed
          // (production-ready 56). `update` fires when a node *completes* and
          // `token` only while a model types, so an MCP call or a web fetch
          // produced neither and the panel read as stopped.
          //
          // It moves the glow for the same reason `token` does: it is the
          // other frame that arrives while a node is still working, and it is
          // the only one a *tool* can send.
          const progressTarget = frameTarget(event, hasNode, openAddress());
          if (progressTarget && progressTarget !== queuedActive) {
            seen.add(progressTarget);
            activate(progressTarget, null);
            queuedActive = progressTarget;
          }
          const line = progressLine(event);
          setTurns((all) =>
            all.map((turn) => (turn.id === id ? { ...turn, progress: line } : turn)),
          );
          scrollToEnd();
        } else if (event.type === 'error') {
          // The one terminal frame that does not arrive as an outcome — the
          // client settles it into `Err(detail)`, which carries prose and not
          // a thread. Taken here instead.
          remember(event.threadId);
        }
      };

      // The stream is settled either way; nothing is left to abort. In a
      // `finally` because the comment here used to *claim* "no path can leak
      // the entry" while sitting outside one — the guarantee was really held
      // a layer away by `streamFrom` never throwing, with nothing enforcing
      // it. A stale entry is a Stop that appears to act and does nothing.
      let outcome: Awaited<ReturnType<typeof call>>;
      try {
        outcome = await call(onEvent, signal);
      } finally {
        streams.settle(id);
        clearRunInFlight();
      }

      const stopped = outcome.ok && outcome.value != null && isCancelled(outcome.value);
      // A stop abandons the backlog; a natural ending drains it. See
      // `abandoned` — the pacing exists so the last node to act does not
      // flash and vanish, and a run the developer stopped has no such node.
      if (stopped) abandoned = true;
      await highlightChain;

      if (stopped) {
        // Stopped. Not `success` (nothing completed) and not `error` (nothing
        // failed) — the node returns to rest, which is the same state a
        // canvas that never ran is in.
        if (activeNode) controller.model.setNodeRuntime(activeNode, { status: 'idle' });
        updateTurn(id, { running: false, pendingApproval: null, stopped: 'streaming' });
        scrollToEnd();
        return;
      }

      if (outcome.ok && outcome.value && 'interrupted' in outcome.value) {
        // Paused, not finished — and now said in those words (UX-01).
        //
        // Not `success` (the node has not completed), not `idle` (the run is
        // still live, checkpointed, and resumable), and above all not
        // `running`, which is what it used to be left as: the canvas kept
        // sweeping its run glow over the very node that was waiting for this
        // person to decide, while the approval card asked them to. `paused`
        // is a static amber ring plus a "Waiting for you" label, and nothing
        // about it animates.
        // The approval node itself when the backend names it (it never
        // appears in an `update` frame, having never completed), falling back
        // to the last node that acted — which is one box early, but is what
        // the frame alone can support.
        remember(outcome.value.threadId);
        const waiting = outcome.value.node || activeNode;
        // The node still glowing did finish; only the approval is waiting. If
        // it were left `running` the sweep would simply move one box and the
        // original lie would survive the fix.
        if (activeNode && activeNode !== waiting) {
          controller.model.setNodeRuntime(activeNode, { status: 'success' });
        }
        if (waiting) controller.model.setNodeRuntime(waiting, { status: 'paused' });
        updateTurn(id, {
          running: false,
          pendingApproval: {
            threadId: outcome.value.threadId,
            message: outcome.value.message,
            candidate: outcome.value.candidate,
            verdict: outcome.value.verdict,
            reason: outcome.value.reason,
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
        remember(result.threadId);
        // The suggestion arrives structured, on the run's developer channel —
        // it was never in `result.answer`, because the backend splits it out
        // on every run whatever the audience (`api/audience.py`). All that is
        // left to decide here is whether *this* canvas can honour it: an
        // `attachTo` the document does not contain comes back `none` and no
        // card is offered.
        //
        // **A `nodeType` the registry does not know comes back `gap`
        // instead** (`the-agent-asks-for-what-it-cannot-get` 04, half 1). The
        // backend already declined to open the "build one" door here, because
        // it saw a well-formed fence and assumed the editor could place it —
        // only the browser knows the type does not exist. Route it into the
        // same `CapabilityGapCard` the compile-side gap uses, so a developer
        // is told rather than watching the run end with nothing.
        //
        // **And a tool already on that bus comes back `duplicate`** — refused
        // before it is offered rather than after it is pressed
        // (`the-agent-asks-for-what-it-cannot-get` 01). Accepting the same
        // suggestion three times produced three Email Send nodes, three
        // identical failures and no progress; a card that would add a second
        // copy is a button that cannot help, which is the thing
        // `suggestion.ts` already refuses to offer.
        const wired = new Map<string, Set<string>>();
        for (const edge of controller.model.edges()) {
          const type = controller.model.node(edge.source.nodeId)?.type;
          if (type === undefined) continue;
          const key = busKey(edge.target.nodeId, edge.target.portId);
          const set = wired.get(key) ?? new Set<string>();
          set.add(type);
          wired.set(key, set);
        }
        const outcomeForCard = suggestionOutcome(result.developer?.suggestion, {
          nodeTypes: new Set(workbench.registry.nodeTypes.list().map((type) => type.id)),
          nodeIds: new Set(controller.model.nodes().map((node) => node.id)),
          wired,
        });
        updateTurn(id, {
          running: false,
          result,
          pendingApproval: null,
          suggestion: outcomeForCard.kind === 'apply' ? outcomeForCard.suggestion : null,
          // Only when nothing could be placed — a gap with a tool that fits is
          // a suggestion, not something to build. And an unregistered type is
          // its own reason to open the door, ahead of whatever the compile
          // side inferred: the browser knows something the backend does not.
          capabilityGap:
            outcomeForCard.kind === 'apply'
              ? null
              : outcomeForCard.kind === 'gap'
                ? outcomeForCard.reason
                : (result.developer?.capabilityGap ?? null),
          ...(outcomeForCard.kind === 'duplicate' ? { notice: outcomeForCard.message } : {}),
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
    [controller, scrollToEnd, setTurns, streams, updateTurn, workbench],
  );

  const respondToApproval = useCallback(
    async (turnId: string, decision: 'approve' | 'reject', note = '') => {
      const turn = turns.find((t) => t.id === turnId);
      if (!turn || !turn.pendingApproval) return;
      const { threadId } = turn.pendingApproval;

      // Answered: the node the run parked on is about to execute again, so it
      // stops saying "Waiting for you" now rather than at whatever moment the
      // first frame of the resumed stream happens to arrive.
      clearPausedNodes('running');
      updateTurn(turnId, { running: true, pendingApproval: null, stopped: null });
      const document = JSON.parse(controller.document.exportJSON()) as unknown;
      const slug = currentWorkflowSlug();

      await streamAndSettle(turnId, slug, (onEvent, signal) =>
        client.resume(
          {
            threadId,
            workflow: document,
            decision,
            // Only on a rejection, and only when the reviewer wrote something:
            // the backend states the absence itself rather than being handed
            // an empty string to interpret (`every-workflow-green` 11).
            ...(decision === 'reject' && note.trim() ? { feedback: note.trim() } : {}),
            workflowSlug: slug,
            // A resume must be entitled to what the run it continues was, or
            // approving a run silently downgrades it to a customer's.
            audience: 'developer',
            ...credentialsPatch(workbench.providers),
          },
          onEvent,
          { signal },
        ),
      );
    },
    [client, clearPausedNodes, controller, streamAndSettle, turns, updateTurn, workbench],
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
      // Before anything else: the canvas must stop showing the *last* run the
      // instant this one begins. See `resetRunState` — an unchanged canvas is
      // what made a second Run look like it had not started.
      resetRunState();

      // The entry Text Input is the workflow's own "first contact", and this
      // used to write the question onto it so the chat and the canvas agreed
      // about what was asked. They did agree — and so did autosave, which
      // carried it to `workflow.json`, so *running* a workflow rewrote the
      // vendor-neutral artifact `git diff` and the CLI read (ticket 42).
      //
      // The question rides in run state instead, exactly as a mounted child's
      // already did: the SSE `update` frame writes `node.runtime.output` and
      // `LiveInputBody` projects it above the stored field when the two
      // differ. `liveInputValue`'s own docblock had held this rule since
      // ticket 34 — "that would edit a saved document to display a fact about
      // a run" — and applied it only to children. The open parent was the
      // exception nobody argued for. Pinned by `runDoesNotEditTheDocument`.

      // Read here, at the moment it decides something, rather than watched:
      // whether this question continues the conversation is a question only a
      // send can ask, so there is nothing to subscribe to and no window in
      // which the two can disagree. A slug that has changed since the last
      // answer means the developer opened a different workflow, and this is a
      // different conversation — the checkpointer being keyed by thread id
      // alone, continuing would replay the other document's history in here.
      const slug = currentWorkflowSlug();
      const continuing = conversations.continuing(currentSubject(), slug);

      const id = `turn-${nextTurnId++}`;
      setTurns((all) => [
        ...all,
        {
          id,
          question: trimmed,
          // Only worth drawing when there is something above to be separated
          // from; the first turn of an empty panel begins nothing.
          freshThread: continuing === undefined && all.length > 0,
          running: true,
          activity: [],
          progress: null,
          thinking: '',
          toolResults: [],
          result: null,
          error: null,
          pendingApproval: null,
          stopped: null,
          suggestion: null,
          capabilityGap: null,
          suggestionDecision: null,
          notice: null,
          // The document this run is about (ticket 25) — the same value the
          // request is addressed with, two lines above.
          slug: slug ?? null,
        },
      ]);
      scrollToEnd();

      // Serialised through the same path as “export”, so the runtime receives
      // exactly the bytes that would be saved — no second representation.
      // Read *here*, per run: a re-run after a suggestion was applied must
      // post the canvas as it now is, with the new tool wired in.
      const document = JSON.parse(controller.document.exportJSON()) as unknown;

      await streamAndSettle(id, slug, (onEvent, signal) =>
        client.runStream(
          {
            workflow: document,
            question: trimmed,
            workflowSlug: slug,
            // The conversation this question belongs to. Omitted on the first
            // turn only — the server mints one and names it back on the
            // terminal frame, which is what `streamAndSettle` remembers. Until
            // this line existed every send was turn one, `messages` was always
            // empty, and "how did you get that?" was answered as if it were a
            // fresh question (ticket 17; the recorded contrast is
            // `backend/tests/data/recorded_chinook_followup_thread.json`).
            ...(continuing ? { threadId: continuing } : {}),
            // This panel IS the workflow editor, so its runs are a
            // developer's: that is what entitles them to the developer
            // channel and what lets an agent name a capability gap and offer
            // the fix. The customer `/chat` page never sets it, and the
            // backend defaults to `customer`.
            audience: 'developer',
            ...credentialsPatch(workbench.providers),
          },
          onEvent,
          { signal },
        ),
      );
    },
    [client, controller, resetRunState, scrollToEnd, setTurns, streamAndSettle, workbench],
  );

  /**
   * Start over: the next question opens a new conversation.
   *
   * Forgetting the thread is the whole of it — the transcript stays. A run's
   * trace is evidence (it is exportable, and the History panel is built on the
   * same premise), and a button that silently deleted it would make "start a
   * new conversation" and "throw away what the last one showed me" the same
   * gesture. The next turn draws its own boundary instead.
   */
  const newConversation = useCallback(() => conversations.newSession(currentSubject()), []);

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
      streams.abort(streaming.id);
      return;
    }
    const paused = turns.find((turn) => turn.pendingApproval);
    if (paused) {
      // Walking away from the prompt clears the canvas's "Waiting for you"
      // mark: nothing is waiting on this editor any more. The thread is still
      // checkpointed server-side, which the rendered line says — but the
      // canvas must not keep asking a question nobody will answer here.
      clearPausedNodes('idle');
      updateTurn(paused.id, { pendingApproval: null, stopped: 'paused' });
    }
  }, [clearPausedNodes, streams, turns, updateTurn]);

  /**
   * Repaints the canvas for a document opened during a run — or after one.
   *
   * The last piece of ticket 34, and the one no amount of per-frame projection
   * can cover. Clicking "Edit workflow" on a mount loads the child into this
   * same editor, and everything that already streamed was projected onto the
   * parent — correctly, as the mount's one glowing card. The child arrives
   * with a fresh import and therefore a blank runtime: live from that instant
   * forward, and grey behind. The entry Input card was the loudest symptom,
   * still showing its saved prompt because the frame carrying the real
   * question had gone by before anyone opened it.
   *
   * The frames are not lost — the turn keeps every one of them, because the
   * trace and timeline views are built from that record. Replaying it through
   * the same `frameTarget` gives the newly opened document the state it would
   * have had if it had been open all along. The decision is `replayRun`, in
   * `core/`, where it is a pure function and unit-testable; this is only the
   * subscription and the writes.
   *
   * Ticket 43 widened *which* turn that is. This used to project only a
   * running one, on the reasoning that "a finished run leaves nothing to catch
   * up to" — true of the stream, false of the record, since the frames are all
   * still held. A developer who opened a mount a second too late got a static
   * diagram, which is the very symptom ticket 34 existed to remove. The choice
   * moved to `turnToReplay`, which also refuses the two turns that must not be
   * repainted: a stopped one (its nodes were set `idle` on purpose) and a
   * paused one (mid-flight, in a state this projection cannot express).
   */
  const turnsRef = useRef(turns);
  useEffect(() => {
    turnsRef.current = turns;
  }, [turns]);
  useEffect(() => {
    const project = () => {
      const open = getOpenAddress() ?? parseMountAddress(currentWorkflowSlug() ?? '') ?? undefined;
      // The run in progress if there is one, else the last that finished
      // (ticket 43) — and, since ticket 25, only among the turns that ran
      // *this* document or reached it. The rule is `turnToReplay`, in `core/`,
      // for the same reason `replayRun` is: it is a decision over data, and a
      // decision buried in a subscription is a decision nobody can test.
      const chosen = turnToReplay(turnsRef.current, {
        // The **root**, not the class slug: a run is rooted where it was
        // started, so drilling into a mount of the running document still
        // matches, while another workflow entirely does not.
        root: open?.root ?? null,
        slug: currentWorkflowSlug() ?? null,
      });
      if (!chosen) return;
      const writes = replayRun(
        chosen.turn.activity,
        (id) => controller.model.node(id) != null,
        chosen.running,
        // The address, same rule as the live path — a replay onto a canvas
        // that is one of two mounts of the same package must land on the one
        // actually open.
        open,
      );
      for (const write of writes) {
        controller.model.setNodeRuntime(write.nodeId, {
          status: write.status,
          ...(write.output !== undefined ? { output: write.output } : {}),
        });
      }
    };

    // Two signals, because two things can put a different document on screen
    // and the projection has to follow both.
    //
    // `workflow:reset` is the real one: every import fires it, including a
    // draft restore that lands *after* a load has finished. It only resolves
    // correctly because `loadMountIntoEditor` now records the address before
    // importing — with the old ordering it projected through the address of
    // the document being left behind, and since a mount address indexes a run
    // by position, the writes went to a node the new document does not have.
    //
    // The address change is belt-and-braces for the reverse order, and costs
    // one extra pass: `replayRun` is a pure function of the same frames, so
    // projecting twice writes the same thing twice.
    const off = [controller.model.on('workflow:reset', project), subscribeOpenAddress(project)];
    return () => off.forEach((stop) => stop());
  }, [controller]);

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
  //
  // **Module scope, not a ref** (`memory-and-replay` 35). A ref dies with the
  // panel, and the shell's `runRequest` does not: closing the panel and
  // reopening it replayed the last Run press against a nonce nothing
  // remembered honouring, so merely looking at the conversation again spent a
  // run's worth of tokens. Found while verifying this ticket, because a
  // transcript that now survives the close is what made the duplicate turn
  // visible — the same defect this ticket is about, in the neighbouring
  // variable.
  useEffect(() => {
    if (runNonce <= 0 || honouredRunNonce === runNonce) return;
    const trimmed = (runRequest?.question ?? '').trim();
    if (trimmed === '' || runningRef.current) return;
    honouredRunNonce = runNonce;
    void askRef.current(trimmed);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the nonce is the trigger; see above
  }, [runNonce]);

  // The toolbar owns the Run button but not the run, so the one place that
  // knows a stream is open tells it.
  useEffect(() => {
    onRunningChange?.(running);
  }, [running, onRunningChange]);

  // A closed panel cannot report from its own state — `turns` goes with it —
  // so the last thing it says is read from the owner that outlives it.
  //
  // It used to say `false` unconditionally, and that was the second half of
  // ticket 07: nothing had been aborted, so the report retired the toolbar's
  // Stop while a run was still streaming. It is `false` now on the ordinary
  // path *because* the close gesture aborted first, and if some future path
  // unmounts this panel with a stream still open it says so instead of
  // covering for it — the shell holds the handle, so a Stop the toolbar keeps
  // showing is one it can still deliver.
  const runningChangeRef = useRef(onRunningChange);
  useEffect(() => {
    runningChangeRef.current = onRunningChange;
  }, [onRunningChange]);
  useEffect(() => () => runningChangeRef.current?.(streams.hasOpenStream), [streams]);

  /**
   * Honours a suggestion: add the node, wire it, say so, ask again.
   *
   * Every mutation goes through the controller's command layer, so the canvas
   * projects the change the same way it would for a hand-drawn one and the
   * whole thing is a single undo away — which matters more here than
   * anywhere else in the editor, since this is the one edit the *developer*
   * did not draw.
   */
  // The canvas, for bringing a newly added node into view (ticket 31).
  const paper = usePaperController();

  /**
   * What the card's primary button will really do (ticket 74).
   *
   * Computed from the node *type*, before the press: a required field with no
   * default is a fact about the type, so a card can say "Add & set Recipient"
   * instead of promising a re-run `applySuggestion` will decline to start.
   */
  const acceptActionFor = useCallback(
    (suggestion: CapabilitySuggestion) => {
      const definition = workbench.registry.nodeTypes.get(suggestion.nodeType);
      const fields = definition?.fields ?? [];
      return acceptAction(definition?.label ?? suggestion.label, fields, defaultsFrom(fields));
    },
    [workbench],
  );
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
      // **Refused before it is offered, and re-checked here.** Accepting the
      // same suggestion three times produced three `Email Send` nodes on one
      // bus, three identical failures and no progress
      // (`the-agent-asks-for-what-it-cannot-get` 01). The fact needed to refuse
      // was already computed on the next line and spent on *positioning*.
      const onBus = new Set(
        controller.model
          .edgesInto({ nodeId: suggestion.attachTo, portId: suggestion.port })
          .map((edge) => controller.model.node(edge.source.nodeId)?.type)
          .filter((type): type is string => typeof type === 'string'),
      );
      if (onBus.has(suggestion.nodeType)) {
        updateTurn(turnId, {
          suggestionDecision: 'declined',
          notice: `${definition.label} is already wired to ${target.title || suggestion.attachTo}. If it is not working, open it and check its settings — a second one would not help.`,
        });
        return;
      }

      // Offsetting stays: two *different* tools on one bus is legitimate and is
      // exactly what this count was written for.
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
        created = controller.model.nodes().find((node) => !before.has(node.id))?.id ?? null;
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

      // **Take focus** (`every-workflow-green` 31). The node is placed *below*
      // the agent it attaches to, so the lower that agent already sits, the
      // more reliably it lands outside the viewport — measured at 1033px in a
      // 723px window. Correct, wired, and invisible, which from the chair is
      // indistinguishable from nothing having happened.
      //
      // Before the re-run, not after: the run's own highlight chain starts
      // immediately and walks the nodes that *ran*, so anything selected
      // afterwards is overwritten by a path that does not include the new
      // node.
      controller.selectionActions.selectNodes([created]);
      const rect = rectOfAdded(controller.model, created);
      if (rect) paper?.viewport.centerOn(rect);

      // **Do not re-run something that cannot work.** The suggested Email Send
      // was added with an empty `to`, wired, and the flow re-run at once —
      // straight into "No recipient configured". That failure was knowable
      // before the run and cost a model call to discover. A required field with
      // no value is a pre-run fact, and `required` on the field schema is what
      // makes it one.
      const unready = unreadyFields(
        definition.fields ?? [],
        controller.model.node(created)?.data ?? {},
      );
      if (unready.length > 0) {
        controller.selectionActions.selectNodes([created]);
        updateTurn(turnId, {
          suggestionDecision: 'accepted',
          notice: `Added ${definition.label} and wired it to ${target.title || suggestion.attachTo}. It needs ${unready.join(' and ')} before it can run — set that on the card, then ask again.`,
        });
        scrollToEnd();
        return;
      }

      updateTurn(turnId, {
        suggestionDecision: 'accepted',
        notice: `Added ${definition.label} and wired it to ${target.title || suggestion.attachTo}. Re-running…`,
      });
      scrollToEnd();
      await ask(turns.find((turn) => turn.id === turnId)?.question ?? '');

      // The centre placed above does not survive the re-run: `runStarted()`
      // clears the follower's latch, and every `update` frame calls
      // `setActive`, which walks the camera to whatever just ran — the new
      // node only if it happens to be the last thing the run touches, never
      // otherwise (measured: `agent-world, in1, out-world, router1` glowed,
      // the added tool did not). Re-ordering the two calls was tried and does
      // not survive the chain either, because the chain starts *after* this
      // function returns control, not after `ask` resolves.
      //
      // So centre again once the run has actually settled: `ask` above only
      // resolves after its own `highlightChain` has drained, which is the
      // same moment the follower stops moving the camera on its own. Select
      // the node fresh too — the highlight chain's own final selection
      // (`seen`, ticket 08) does not include a node that never ran.
      controller.selectionActions.selectNodes([created]);
      const settledRect = rectOfAdded(controller.model, created);
      if (settledRect) paper?.viewport.centerOn(settledRect);
    },
    [ask, controller, paper, scrollToEnd, turns, updateTurn, workbench],
  );

  const declineSuggestion = useCallback(
    (turnId: string) => updateTurn(turnId, { suggestionDecision: 'declined' }),
    [updateTurn],
  );

  /**
   * Open the build interview, by putting its first message where the developer
   * can read and edit it (`every-workflow-green` 34).
   *
   * Seeding rather than sending: the brief asks four questions about *their*
   * business logic, and they know it. Sending it for them would start an
   * interview with an answer they never gave.
   */
  const startBuild = useCallback(
    (gap: string) => {
      setQuestion(moduleBrief(gap, currentWorkflowSlug()));
      scrollToEnd();
    },
    [scrollToEnd],
  );

  return (
    <Panel side="right" className="ask" style={{ width: 'var(--layout-inspector-width)' }}>
      <PanelHeader
        bordered
        title="Chat"
        actions={
          <>
            {/* Beside History rather than in the composer: it acts on the
                conversation as a whole, which is what this header is about,
                and the composer is for the next message. Disabled when there
                is no conversation to end — pressing it would do nothing, and a
                control that does nothing teaches nothing. */}
            <Button
              variant="ghost"
              size="sm"
              icon={<Icon glyph={MessageSquarePlus} size="xs" />}
              disabled={conversation.thread === null || running}
              title={
                conversation.thread === null
                  ? 'The next question already starts a new conversation'
                  : 'Forget what was said so far — the next question starts fresh. The transcript stays.'
              }
              onClick={newConversation}
            >
              New
            </Button>
            <Button
              variant="ghost"
              size="sm"
              icon={<Icon glyph={History} size="xs" />}
              active={historyOpen}
              aria-pressed={historyOpen}
              title="Past runs of this workflow — read only, nothing re-executes"
              onClick={() => setHistoryOpen((open) => !open)}
            >
              History
            </Button>
          </>
        }
      />
      <PanelBody>
        {historyOpen ? (
          <PastRuns
            slug={currentWorkflowSlug()}
            names={laneNames}
            onClose={() => setHistoryOpen(false)}
          />
        ) : null}
        {/* Above history too, not only above the live thread (ticket 55.6).
            The notice explains why the panel opened, and the one case that
            opens it *on* history — coming back from a reload that killed a
            run — is precisely the one whose explanation would otherwise be
            hidden by the view it sent you to. */}
        {notice ? (
          <p className="ask__notice">
            <Icon glyph={Info} size="sm" />
            <span>{notice}</span>
          </p>
        ) : null}
        {/* Hidden, never unmounted, while history is up: a turn streaming in
            the background must keep streaming into its thread, and unmounting
            would throw away the scroll position and the live activity feed of
            a run the developer only stepped away from. */}
        <div className="ask__thread" ref={threadRef} hidden={historyOpen}>
          {turns.length === 0 ? (
            <div className="ask__empty">
              <p className="ask__empty-title">Ask anything</p>
              <p className="ask__meta">
                Your question runs against the workflow on the canvas, live — the cards light up as
                each step takes its turn. Follow-ups continue the same conversation, which lasts
                until you press New, open a different workflow, or reload the editor.
              </p>
            </div>
          ) : null}
          {turns.map((turn) => (
            <Turn
              key={turn.id}
              turn={turn}
              onRespond={respondToApproval}
              onApplySuggestion={applySuggestion}
              acceptActionFor={acceptActionFor}
              onDeclineSuggestion={declineSuggestion}
              onStartBuild={startBuild}
            />
          ))}
        </div>

        {/* One control, not a labelled field plus a detached button: the
            composer is the panel's primary affordance and should read as a
            single place to type and send, the way every chat does. The label
            is carried by the placeholder and `aria-label`, so nothing is lost
            to a screen reader. */}
        <div className="ask__composer" data-running={running || undefined} hidden={historyOpen}>
          {/* Multi-line, and it grows with what is in it
              (`every-workflow-green` 40).

              A single-line `<input>` cannot hold a newline: the HTML value
              sanitisation algorithm strips CR and LF, silently. So the
              "build one for this workflow" card — whose whole justification
              is *it seeds, it does not send*, because the developer is meant
              to read and edit the brief — delivered its twelve lines as one
              909-character run-on: `provides it.What`, `SlackBefore`,
              `logicThen`. The five shape clauses, which are the contract a
              generated module is checked against, arrived unreadable.

              Enter still sends, so nothing a developer does today changes;
              Shift+Enter now types a newline instead of doing nothing. That
              is not a new answer to an open question — it is the answer this
              product already ships one surface away, in `/chat`'s textarea
              composer (`api/static/chat.html`), and the `!event.shiftKey`
              guard below was already written for it. */}
          <TextArea
            ref={composerRef}
            className="ask__composer-input"
            value={question}
            aria-label="Message"
            // One row at rest, so an empty composer looks exactly as it did.
            // The ceiling keeps a long brief from eating the transcript it is
            // supposed to be read beside — past it the box scrolls.
            minRows={1}
            maxRows={8}
            // The workflow's own entry question, never a fixed sentence: a
            // placeholder borrowed from another workflow teaches the wrong
            // thing about the one in front of you (`every-workflow-green` 04).
            placeholder={composerPlaceholder(entryQuestion(controller.model))}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              // Enter sends it; Shift+Enter falls through to the textarea and
              // types a newline. `preventDefault` is what stops Enter doing
              // both — sending *and* leaving a blank line in a composer that
              // is about to be cleared anyway.
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                void send();
              }
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
  acceptActionFor,
  onDeclineSuggestion,
  onStartBuild,
}: {
  turn: ChatTurn;
  onRespond: (turnId: string, decision: 'approve' | 'reject', note?: string) => void;
  onApplySuggestion: (turnId: string, suggestion: CapabilitySuggestion) => void;
  /** What accepting this suggestion would really do — see `acceptAction`. */
  acceptActionFor: (suggestion: CapabilitySuggestion) => AcceptAction;
  onDeclineSuggestion: (turnId: string) => void;
  /** Seeds the composer with the brief that opens the build interview. */
  onStartBuild: (gap: string) => void;
}) {
  // Per turn, and ephemeral: a run's timeline is a fact about that run, and
  // nothing about it deserves to be persisted.
  const [view, setView] = useState<'trace' | 'timeline'>('trace');

  return (
    <div className="ask__turn">
      {/* The one place the thread's shape is visible: everything above this
          rule is a conversation this question knows nothing about. */}
      {turn.freshThread ? (
        <p className="ask__break">
          <span>New conversation</span>
        </p>
      ) : null}
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
          {/* Below both views and outside either record: what the working step
              is saying about itself right now is not a step that ran and not a
              bar on a timeline. Gated on `running` so every ending — answered,
              stopped, failed, paused — clears it without having to remember
              to. `aria-live` because for a screen reader this line is the only
              evidence the run has not died. */}
          {turn.running && turn.progress ? (
            <p className="ask__live" aria-live="polite">
              {turn.progress}
            </p>
          ) : null}
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

      {/* Above the reasoning, because the tools are what the reasoning is
          reasoning about — and in their own blocks, so a long result scrolls
          on its own instead of pushing the model's prose out of one shared
          region (ticket 02). */}
      <ToolResults results={turn.toolResults} />

      {showsThinking({
        thinking: turn.thinking,
        running: turn.running,
        answer: turn.result?.answer ?? '',
        awaitingApproval: turn.pendingApproval !== null,
      }) ? (
        // Raw tokens while streaming (legible mid-arrival), markdown once
        // settled — the "improperly formatted chat" fix (ticket 62).
        //
        // `showsThinking` rather than `turn.thinking`: a settled block ends
        // with the answer by construction, so rendering both printed the whole
        // answer twice (`every-workflow-green` 10). It survives only for a turn
        // that settled without publishing one.
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
          onReject={(note) => onRespond(turn.id, 'reject', note)}
        />
      ) : null}

      {/* Muted, with no error styling and no warning glyph: the developer
          asked for this, so presenting it as a failure would be the panel
          disagreeing with them. */}
      {turn.capabilityGap !== null && !turn.suggestion ? (
        <CapabilityGapCard
          gap={turn.capabilityGap}
          onStart={() => onStartBuild(turn.capabilityGap ?? '')}
        />
      ) : null}

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

      {turn.result ? <Answer result={turn.result} /> : null}

      {turn.suggestion ? (
        <SuggestionCard
          suggestion={turn.suggestion}
          accept={acceptActionFor(turn.suggestion as CapabilitySuggestion)}
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
/**
 * The other door: nothing in the library does this, so build one.
 *
 * A gap with a tool that fits is a `SuggestionCard` — one click and it is
 * wired. A gap with **no** tool was a dead end until now: an honest refusal
 * and nowhere to go (`every-workflow-green` 34).
 *
 * The button seeds the composer rather than starting a build, and that is
 * deliberate. A button that promised to write code and did not would be worse
 * than no card; seeding the chat is a real action the product can honour
 * today, the developer can edit the brief before sending, and the interview
 * happens where they are already looking.
 */
function CapabilityGapCard({ gap, onStart }: { gap: string; onStart: () => void }) {
  // Two routes open this door and they know different amounts, so the headline
  // is `doorHeadline`'s call rather than one fixed sentence — see its own file
  // for why an over-claiming card is worse than no card.
  const headline = doorHeadline(gap);
  return (
    <div className="ask__suggestion ask__suggestion--build">
      <p className="ask__suggestion-headline">
        <Icon glyph={Lightbulb} size="sm" />
        <span>
          <strong>{headline.lead}</strong> {headline.detail}
        </span>
      </p>
      <div className="ask__suggestion-actions">
        <Button variant="secondary" onClick={onStart}>
          Build one for this workflow
        </Button>
      </div>
    </div>
  );
}

function SuggestionCard({
  suggestion,
  accept,
  decision,
  onAccept,
  onDecline,
}: {
  suggestion: CapabilitySuggestion;
  accept: AcceptAction;
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
      {accept.note ? <p className="ask__suggestion-note">{accept.note}</p> : null}
      <div className="ask__suggestion-actions">
        <Button variant="primary" onClick={onAccept}>
          {accept.label}
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
  onReject: (note: string) => void;
}) {
  const [note, setNote] = useState('');
  const verdictLine = graderVerdictLine(approval);

  return (
    <div className="ask__approval">
      <p className="ask__approval-message">{approval.message}</p>
      {approval.candidate ? <RichText className="ask__answer" text={approval.candidate} /> : null}
      {/* What the machine that just judged this text thought of it
          (`workflow-gallery` 32). Below the draft and above the note field,
          which is the order the reviewer reads in: the thing being decided,
          the existing opinion of it, then their own. Absent entirely when no
          grader produced the candidate — see `graderVerdictLine`. */}
      {verdictLine ? <p className="ask__approval-verdict">{verdictLine}</p> : null}
      {/* The card's own message has always told the reviewer to reject with a
          note, and until `every-workflow-green` 11 there was nowhere to write
          one — so the held record was written from an empty string, and read
          as a quotation of a person who had said nothing.

          Optional on purpose. A mandatory field here would stand between a
          reviewer and stopping a bad reply, which is the one thing this card
          exists to make easy; the backend states the absence in its own words
          when nothing is typed. */}
      <textarea
        className="ask__approval-note"
        value={note}
        onChange={(event) => setNote(event.target.value)}
        placeholder="If you reject: what is wrong with it? (optional)"
        aria-label="Reason for rejecting, which becomes the reason on the held ticket"
        rows={2}
      />
      <div className="ask__approval-actions">
        <Button variant="primary" onClick={onApprove}>
          Approve
        </Button>
        <Button variant="secondary" onClick={() => onReject(note)}>
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

      {/* `result.answer` is already prose: the backend split any suggestion
          fence out of it before the frame left the runtime, so there is no
          second, fence-free copy of the answer to keep in sync here. */}
      <RichText className="ask__answer" text={result.answer || '_No answer was produced._'} />

      {attemptsLine(result) ? (
        // Surfaced because a silent retry hides real cost — but it no longer
        // names a grader. `attempts` is incremented by every model-driven
        // node, so `chained-summarizer`, which has no grader at all, printed
        // "2 attempts before the grader passed it"
        // (`every-workflow-green` 21). See `attemptsLine`.
        <p className="ask__meta">{attemptsLine(result)}</p>
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
