/**
 * The run timeline: stream frames → bars.
 *
 * A sibling of `traceTree`, not a replacement for it. The trace answers
 * *what* ran and nests the machinery under the node that owned it; the
 * timeline answers *when* and *for how long*, which is the question a trace
 * tree is structurally bad at — a tree hides the fact that one step took four
 * seconds and the other eleven took forty milliseconds between them.
 *
 * Pure and framework-free on purpose: the whole interesting part is the
 * folding rules below, and they are unit-tested directly rather than through
 * a rendered component.
 *
 * # What a bar claims, exactly
 *
 * **The server's clock, and only the server's** (`launch-readiness` 108).
 * Every run frame carries `elapsedMs` — milliseconds since the stream opened,
 * minted on the backend as the frame was built (`memory-and-replay` 46). A
 * bar's duration is the span between the frame that opened it and the frame
 * that closed it, on that clock; the timeline's total is the last frame's own
 * `elapsedMs`, so it *is* the run's wall clock rather than a sum that can
 * drift away from one.
 *
 * The browser's arrival clock is deliberately not used here any more. It
 * answers a real and different question — what the user waited through, a
 * stalled network included — but it is measured after `RuntimeClient` has
 * drained a whole TCP chunk synchronously (`launch-readiness/105`), so several
 * frames share one gap and one frame absorbs it. It is still measured, and the
 * Inspector's badge still shows it; it is simply not what a profile is made of.
 *
 * A frame that carries no clock — a backend older than 46 — gets a bar with
 * `durationMs: null`, never `0`. The same choice `PastRunStep.durationMs`
 * makes, for the same reason: `0 ms` beside a ten-second bar is a claim, and a
 * visibly false number invalidates every honest number beside it.
 *
 * **It is still a span between frames, not a measured start and end.** The
 * `updates` stream reports a node only *after* it finishes, so nothing on this
 * wire marks a beginning, and for concurrently dispatched workers one shared
 * span is attributed to whichever frames arrived. The UI says so in a line
 * under the bars rather than implying otherwise with a precise-looking number.
 *
 * Until 2026-08-29 this paragraph blamed the library for the missing start,
 * and the blame was misplaced. LangGraph publishes seven stream modes and the
 * backend asks for three (`api/streaming.py`: `["updates", "messages",
 * "custom"]`). `stream_mode="tasks"` emits a task **start** event before a
 * node runs and a **finish** event after it, both carrying a runtime-minted
 * `id` that is distinct for every `Send`-dispatched worker — which is exactly
 * the identity this fold is reduced to guessing. So the missing start is a
 * subscription nobody made, not a library that cannot help.
 *
 * What `tasks` does *not* carry is a clock: no field of either payload holds a
 * time, so subscribing alone still leaves the stamping to whoever receives the
 * frame. That is ticket 46's question, and the two land together or not at
 * all. Both claims are pinned, against the installed LangGraph rather than
 * against a page, by
 * `backend/tests/test_the_tasks_stream_mode_is_a_start_event.py`.
 */

/** What the timeline needs from one stream frame. */
export interface TimelineRow {
  readonly node: string;
  readonly taskId: string | null;
  readonly internal: boolean;
  /** LangGraph's checkpoint namespace — non-empty inside a subgraph/team. */
  readonly namespace?: readonly string[];
  /**
   * The server's own offset for this frame, in ms since the stream opened
   * (`memory-and-replay` 46's `elapsedMs`).
   *
   * `null` or absent against a backend that sends none — and then this frame
   * buys no time for anybody, rather than a fabricated zero.
   */
  readonly elapsedMs?: number | null;
  /**
   * The top-level node this frame's work belongs to, as the *server* resolved
   * it — the stream's `activeNode`.
   *
   * Load-bearing for internal frames, and it is the whole of
   * `launch-readiness` 108: an agent's model and tool frames arrive before the
   * agent's own completion frame, so charging them to "the bar already open"
   * billed every second of an agent's thinking to the node before it. This
   * field is the run saying whose seconds they are.
   */
  readonly activeNode?: string;
  /** Set on a spawn row: a run announced a child. Never a bar of its own —
   * a spawn takes no time — but it is what a lane gets its *name* from. */
  readonly spawn?: {
    readonly kind: string;
    readonly label: string;
    readonly instruction: string;
  };
}

/** One bar. */
export interface TimelineStep {
  /** Stable within a run; safe as a React key. */
  readonly key: string;
  readonly label: string;
  readonly taskId: string | null;
  /** 1-based position in the order steps fired. */
  readonly order: number;
  /** Offset from the stream's opening, in ms. `null` with no server clock. */
  readonly startMs: number | null;
  /** Span on the server's clock. `null` with no server clock — never `0`. */
  readonly durationMs: number | null;
  /** Frames folded into this bar — >1 only for a collapsed namespace lane. */
  readonly count: number;
  /** Internal loop steps (model calls, tool calls, middleware) folded on. */
  readonly internalSteps: number;
  /** Set when this bar is a subgraph/team lane rather than one canvas node. */
  readonly namespace: string | null;
  /** Which visit to this label this is — >1 marks a revise-loop lap. */
  readonly visit: number;
}

export interface Timeline {
  readonly steps: readonly TimelineStep[];
  /** The run's own wall clock: the last frame's `elapsedMs`, not a sum. */
  readonly totalMs: number | null;
}

/** Strips the `node:` prefix the canvas ids carry, for display. */
export function stepLabel(node: string): string {
  return node.replace(/^node:/, '');
}

/** `a + b`, where `null` means "nothing was measured" rather than zero. */
function add(a: number | null, b: number | null): number | null {
  if (a === null) return b;
  if (b === null) return a;
  return a + b;
}

/**
 * Folds a run's frames into bars.
 *
 * Five rules, and each earns its place:
 *
 * 1. **An internal frame is charged to the node it names, and opens that
 *    node's bar if the node has not been heard from yet.** A twenty-call tool
 *    loop is still one node's work rather than twenty steps — it becomes a
 *    count on that node's bar — but the bar it lands on is the one the
 *    server's `activeNode` names, not whichever bar happened to be open.
 *    Getting that wrong is `launch-readiness` 108: an agent's frames all
 *    precede its completion frame, so the previous node was billed for the
 *    agent's thinking and the agent was billed for the microseconds after it.
 * 2. **A subgraph or team collapses to one lane.** Everything sharing a
 *    checkpoint namespace is, on the canvas, a single mounted node — showing
 *    its internals as peers of the parent graph's nodes would misrepresent
 *    the drawing the developer is looking at. Checked before rule 1, so an
 *    internal frame from inside a mount stays in the mount's lane.
 * 3. **A repeated node gets a repeated bar.** This is the whole reason to
 *    build a timeline for an evaluator-optimizer graph: a second bar for the
 *    same agent *is* the revise lap, and merging them would erase it.
 * 4. **A spawn row names a lane, it does not occupy one.** A spawn is an
 *    announcement, not work: it takes no time and gets no bar. What it
 *    contributes is the child's *name*, so a lane reads `researcher` rather
 *    than `wf_music:5f2ab…` or a bare task id. The time *before* it is still
 *    charged to the bar in progress — dropping it would make the bars stop
 *    adding up to the run.
 * 5. **The total is the run's, not the bars'.** `totalMs` is the last frame's
 *    own `elapsedMs`, so "do these bars account for the run?" is a question a
 *    reader can answer by looking.
 */
export function buildTimeline(rows: readonly TimelineRow[]): Timeline {
  type Draft = { -readonly [K in keyof TimelineStep]: TimelineStep[K] };
  const steps: Draft[] = [];
  const visits = new Map<string, number>();
  const spawnNames = new Map<string, string>();
  /** The last frame's server offset — where the next span is measured from. */
  let clock: number | null = null;
  /** A bar opened by internal frames and still awaiting its own node frame. */
  let pending: Draft | null = null;
  /** Whose work opened it — the `activeNode` those frames named. */
  let pendingOwner: string | null = null;

  const mutable = (): Draft | undefined => steps[steps.length - 1];

  const open = (
    label: string,
    taskId: string | null,
    namespace: string | null,
    startMs: number | null,
  ): Draft => {
    const visit = (visits.get(label) ?? 0) + 1;
    visits.set(label, visit);
    const draft: Draft = {
      key: `${label}#${visit}${taskId ? `@${taskId}` : ''}`,
      label,
      taskId,
      order: steps.length + 1,
      startMs,
      durationMs: null,
      count: 1,
      internalSteps: 0,
      namespace,
      visit,
    };
    steps.push(draft);
    return draft;
  };

  /**
   * A bar opened by a node's *work* takes the identity its own completion
   * frame brings — which is the only frame that carries the run's resolved
   * name for it (a spawn's label, rule 4) and its task id. Opened under the
   * `activeNode` the internal frames named, because that is all they say.
   */
  const rename = (draft: Draft, label: string, taskId: string | null): void => {
    if (draft.label !== label) {
      visits.set(draft.label, Math.max(0, (visits.get(draft.label) ?? 1) - 1));
      const visit = (visits.get(label) ?? 0) + 1;
      visits.set(label, visit);
      draft.label = label;
      draft.visit = visit;
    }
    draft.taskId = taskId;
    draft.key = `${draft.label}#${draft.visit}${taskId ? `@${taskId}` : ''}`;
  };

  for (const row of rows) {
    // The span this frame closes: from the last frame the server dated to
    // this one. The first dated frame is measured from the stream's own
    // opening, which is what `elapsedMs` is relative to. `null` propagates
    // rather than collapsing to zero.
    const elapsed = Number.isFinite(row.elapsedMs as number) ? (row.elapsedMs as number) : null;
    const previous = clock;
    const startedAt = previous ?? (elapsed !== null ? 0 : null);
    const duration = elapsed === null ? null : Math.max(0, elapsed - (previous ?? 0));
    if (elapsed !== null) clock = elapsed;

    const namespace = row.namespace?.[0] ?? null;

    if (row.spawn) {
      // Keyed by whichever handle the child's own frames will carry: a
      // `Send`-dispatched worker is told apart by `taskId`, a mounted
      // subgraph by its namespace head.
      if (row.taskId) spawnNames.set(`task:${row.taskId}`, row.spawn.label);
      if (namespace) spawnNames.set(`ns:${namespace}`, row.spawn.label);
      // No bar — but the time up to the announcement was somebody's, and it
      // was the bar in progress (rule 4).
      const last: Draft | undefined = pending ?? mutable();
      if (last) last.durationMs = add(last.durationMs, duration);
      continue;
    }

    if (row.internal) {
      const last: Draft | undefined = pending ?? mutable();
      // Rule 2 first: a frame from inside a mount belongs to the mount's
      // lane, whatever the run resolved its top-level owner to be.
      const insideTheOpenLane =
        last !== undefined && namespace !== null && last.namespace === namespace;
      const owner = row.activeNode ? stepLabel(row.activeNode) : null;
      let bar: Draft | undefined = last;
      if (!insideTheOpenLane && owner !== null && (bar === undefined || bar.label !== owner)) {
        // The run has named a node whose own frame has not arrived yet: this
        // is that node working, so its bar opens here rather than at the end
        // of its work (rule 1).
        bar = open(owner, row.taskId, null, startedAt);
        pending = bar;
        pendingOwner = owner;
      }
      // An internal frame that names nobody and has nothing to belong to is
      // dropped rather than given a phantom bar; the clock has already moved.
      if (bar) {
        bar.internalSteps += 1;
        bar.durationMs = add(bar.durationMs, duration);
      }
      continue;
    }

    const spawned =
      (row.taskId ? spawnNames.get(`task:${row.taskId}`) : undefined) ??
      (namespace ? spawnNames.get(`ns:${namespace}`) : undefined);
    const label = spawned ?? (namespace !== null ? namespace : undefined) ?? stepLabel(row.node);

    // The node whose work already opened a bar is now reporting that it
    // finished. It closes that bar; it does not open a second one.
    //
    // Matched on the owner the run named, not on the label: a dispatched
    // worker's frames say `activeNode: worker-web` while its completion frame
    // resolves — correctly, by rule 4 — to the spawn's `web-researcher`. Left
    // on the label, that run drew `worker-web 14.6 s` beside
    // `web-researcher 0 ms`, which is this ticket's own symptom in the
    // fan-out shape.
    const owner = row.activeNode ? stepLabel(row.activeNode) : null;
    if (pending && pendingOwner !== null && (owner ?? label) === pendingOwner) {
      rename(pending, label, row.taskId);
      pending.durationMs = add(pending.durationMs, duration);
      pending = null;
      pendingOwner = null;
      continue;
    }
    pending = null;
    pendingOwner = null;

    const last = mutable();
    if (namespace !== null && last && last.namespace === namespace && last.taskId === row.taskId) {
      last.count += 1;
      last.durationMs = add(last.durationMs, duration);
      continue;
    }

    const draft = open(label, row.taskId, namespace, startedAt);
    draft.durationMs = duration;
  }

  return { steps, totalMs: clock };
}

/** A bar's width as a percentage of the run, floored so a fast step is still visible. */
export function barWidthPercent(step: TimelineStep, totalMs: number | null): number {
  if (totalMs === null || totalMs <= 0) return 100;
  if (step.durationMs === null) return 1.5;
  return Math.max(1.5, (step.durationMs / totalMs) * 100);
}

/** A bar's left offset as a percentage of the run. */
export function barOffsetPercent(step: TimelineStep, totalMs: number | null): number {
  if (totalMs === null || totalMs <= 0 || step.startMs === null) return 0;
  return Math.min(98.5, (step.startMs / totalMs) * 100);
}
