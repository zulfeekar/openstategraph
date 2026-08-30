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
 * **It is still a span between frames, not a measured start and end** — for
 * every bar except one. The `updates` stream reports a node only *after* it
 * finishes, so nothing on this wire marks a beginning, and for concurrently
 * dispatched workers one shared span is attributed to whichever frames
 * arrived. The UI says so in a line under the bars rather than implying
 * otherwise with a precise-looking number.
 *
 * The exception is a **mount** (`memory-and-replay` 57). A mounted workflow is
 * announced by a `spawn` frame of kind `subgraph` and closed by a `settled` —
 * the same dated pair 54 gave a dispatched child and 50 built a child lane's
 * bar from — so a mount's bar is a measured start and end even though it sits
 * in the run's own lane. `TimelineStep.measured` is which of the two a bar is,
 * per bar, rather than a caveat said about all of them at once.
 *
 * That admission used to end here, with the sentence *"the UI must not claim
 * otherwise"* — and a column of bars read top to bottom claims otherwise
 * whatever the caption says. `buildLanes` at the foot of this module is the
 * answer to it (`memory-and-replay` 50): a dispatched child gets a lane of its
 * own, and its bar is a **measured** start and end, because 46 dated every
 * frame and 54 gave every `spawn` a `settled` to close it. The sentence above
 * still binds every bar in the run's own lane, and nothing else.
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
  /**
   * The deterministic check that rejected this node's candidate before any
   * model was invoked (`production-ready` 92) — empty, or absent, on every
   * other frame.
   *
   * Read here for one reason: it is the only thing on this wire that says a
   * step **refused**, and a refusal is the one place the design system spends
   * its accent. Nothing else is inferred to be one — a step that merely took
   * a long time, or a lane whose child never ran, is not drawn as a refusal
   * on the strength of a guess.
   */
  readonly check?: string;
  /** Set on a spawn row: a run announced a child. Never a bar of its own —
   * a spawn takes no time — but it is what a lane gets its *name* from. */
  readonly spawn?: {
    readonly kind: string;
    readonly label: string;
    readonly instruction: string;
    /** This child's identity for the run — the join a `settled` frame carries
     * back (`memory-and-replay` 54). A lane is keyed on it rather than on the
     * label, because a fan-out dispatches several children under one. */
    readonly spawnId?: string;
    /** How it ended, once the run said so. Absent while the child is still
     * open, and absent for good against a backend that closes nothing —
     * which is why it is optional rather than defaulted to a word. */
    readonly outcome?: 'ok' | 'error' | 'detached' | 'unknown';
    /**
     * The server's offset on the `settled` frame that closed this child — the
     * *other end of the bar*, and the reason 50 waited for 54.
     *
     * Written onto the spawn row by `AskPanel` when the close arrives, rather
     * than arriving as a row of its own: a child that started and a child that
     * stopped are one lane, and a second row would read as a second child.
     * Absent exactly when `outcome` is, and for the same reasons.
     */
    readonly settledMs?: number | null;
  };
}

/**
 * What a bar *is*, which is what makes a chart readable without a legend.
 *
 * Four words, each drawn differently and each derived from frames that were
 * already on the wire — `memory-and-replay` 58 added no field to the stream.
 *
 * | | drawn as | said by |
 * | --- | --- | --- |
 * | `model` | solid ink | an internal frame named `model`, or a middleware hook around one |
 * | `tool` | hollow, an ink ring | the absence of the above — **no model time was spent in this bar** |
 * | `mount` | hatched | a checkpoint namespace, or a `subgraph` spawn: another document, not this one |
 * | `refusal` | accent fill | a frame carrying `check` — a rule rejected the candidate |
 *
 * `tool` is the honest default and its name is about the *ring*, not about a
 * tool call: an input node, an output node and a join all spend no model time
 * and all draw hollow, which is the fact a reader is being told. `toolCalls`
 * below is the narrower question, and it is a number rather than a word.
 *
 * Precedence is refusal, then mount, then model, then tool. A refusal wins
 * outright because it is the only one of the four that is a *verdict*.
 */
export type StepKind = 'model' | 'tool' | 'mount' | 'refusal';

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
  /** How this bar draws — see `StepKind`. */
  readonly kind: StepKind;
  /**
   * Internal frames named `model`, or a middleware hook around one.
   *
   * The expensive thing, counted rather than merely flagged, because the
   * profile strip above the chart has to add them up and a boolean cannot be
   * summed. Zero is a real answer and is what makes a bar hollow.
   */
  readonly modelCalls: number;
  /** Internal frames named `tools` — the loop's tool step, counted the same way. */
  readonly toolCalls: number;
  /** Set when this bar is a subgraph/team lane rather than one canvas node. */
  readonly namespace: string | null;
  /** Which visit to this label this is — >1 marks a revise-loop lap. */
  readonly visit: number;
  /**
   * Both ends of this bar were dated by the run, rather than inferred from
   * the gap between whichever frames arrived (`memory-and-replay` 57).
   *
   * True for a **mount**, and today for nothing else in the run's lane: a
   * `subgraph` spawn frame opens it and a `settled` frame closes it, the same
   * dated pair 50 built a child lane's bar from. Every other bar here is a
   * span, and says so by being `false` — which is the distinction the panel's
   * one-line caveat could only make about all of them at once.
   */
  readonly measured: boolean;
  /**
   * The keys of the bars whose windows this bar's window overlaps — the run
   * ran them at the same time.
   *
   * Empty is the ordinary case and is not a promise: two span-attributed bars
   * are laid end to end by construction, so they can never be found to
   * overlap even when they did. What is here is therefore always true and
   * never complete, and the honest reading is "these definitely overlapped",
   * never "everything else definitely did not".
   */
  readonly concurrent: readonly string[];
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

/**
 * Whether an internal frame's name is a model call.
 *
 * The names are LangGraph's own — `create_agent` compiles a loop whose nodes
 * are `model` and `tools`, and a middleware hook arrives as
 * `NarrationMiddleware.before_model`. Read tolerantly and trusted strictly, the
 * rule this repository already applies to a model's replies: the hook is
 * accepted as *proof a model step exists in this node's loop*, and anything
 * that is not one of these two shapes contributes nothing rather than being
 * guessed at.
 *
 * Read here rather than on the wire because the frame already carries it and
 * `48` priced what putting a second spelling of it on the wire would cost.
 */
export function isModelStep(node: string): boolean {
  const name = stepLabel(node);
  return name === 'model' || name.endsWith('_model');
}

/** Whether an internal frame's name is the loop's tool step. */
export function isToolStep(node: string): boolean {
  return stepLabel(node) === 'tools';
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
 *    internal frame from inside a mount stays in the mount's lane — and, by
 *    rule 6, stays in it even when a node on another branch reports in the
 *    middle of the mount's work.
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
 * 6. **A mount's bar is its own two dated frames, and one interruption does
 *    not make it two bars** (`memory-and-replay` 57). A classifier router may
 *    open several branches in one superstep, and then the run's lane is not a
 *    sequence: in the recorded run `lead`'s completion frame landed in the
 *    middle of the `deep` mount, so rules 2 and 3 between them drew the mount
 *    as `deep ×1` and `deep ×2` — a node that ran once, badged as a node that
 *    ran twice, which is what `visit` means. A mount is bound to its bar from
 *    its `spawn` frame until its `settled`, so an interleaving sibling cannot
 *    split it, and the bar takes its start and length from that pair rather
 *    than from the spans charged to it.
 *
 *    That is also the whole of what this wire announces about a parallel
 *    branch. A branch made only of ordinary nodes still has no start — see
 *    `buildLanes` for why a branch is not a lane and what the missing half
 *    would cost.
 */
export function buildTimeline(rows: readonly TimelineRow[]): Timeline {
  type Draft = { -readonly [K in keyof TimelineStep]: TimelineStep[K] };
  const steps: Draft[] = [];
  const visits = new Map<string, number>();
  const spawnNames = new Map<string, string>();
  /** The last frame's server offset — where the next span is measured from. */
  let clock: number | null = null;
  /**
   * The mounts the run has announced, by checkpoint namespace, each with the
   * window its own two dated frames give it and the bar its frames land on.
   *
   * This is rule 6 (`memory-and-replay` 57). A mount is the one thing in the
   * run's own lane whose start *is* on the wire, so its bar does not have to
   * be a span between arrivals and must not be cut in two when a node on
   * another branch reports in the middle of it.
   */
  const mounts = new Map<
    string,
    { readonly startMs: number | null; readonly endMs: number | null; bar: Draft | null }
  >();
  /** A bar opened by internal frames and still awaiting its own node frame. */
  let pending: Draft | null = null;
  /** Whose work opened it — the `activeNode` those frames named. */
  let pendingOwner: string | null = null;

  const mutable = (): Draft | undefined => steps[steps.length - 1];

  /**
   * What this frame tells the bar it landed on about *what kind of bar it is*.
   *
   * One place, called from every branch that charges a frame to a bar, because
   * the alternative is five branches that each have to remember — and the one
   * that forgets draws a model call as a plain step for ever.
   */
  const charge = (bar: Draft, row: TimelineRow): void => {
    if ((row.check ?? '').trim() !== '') bar.kind = 'refusal';
    if (!row.internal) return;
    if (isModelStep(row.node)) {
      // A middleware hook is *evidence* that a model step exists in this
      // node's loop; it is not a second model call. Counting it would have
      // reported the recorded run's 22 model calls as 75, because three
      // middlewares wrap each one.
      if (stepLabel(row.node) === 'model') bar.modelCalls += 1;
      if (bar.kind === 'tool') bar.kind = 'model';
    } else if (isToolStep(row.node)) bar.toolCalls += 1;
  };

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
      // A namespace *is* a mount, so a collapsed lane knows what it is the
      // moment it opens; every other bar starts hollow and earns `model` by
      // folding a model frame, which is the only evidence of one there is.
      kind: namespace === null ? 'tool' : 'mount',
      modelCalls: 0,
      toolCalls: 0,
      namespace,
      visit,
      measured: false,
      concurrent: [],
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
    // The mount this frame belongs to, if the run had not yet closed it. A
    // frame arriving after the `settled` is outside the window and claims
    // nothing — that is how one namespace reused by a second lap of a fan-out
    // stays two bars.
    const mount = namespace === null ? undefined : openMountAt(mounts, namespace, elapsed);

    if (row.spawn) {
      // Keyed by whichever handle the child's own frames will carry: a
      // `Send`-dispatched worker is told apart by `taskId`, a mounted
      // subgraph by its namespace head.
      if (row.taskId) spawnNames.set(`task:${row.taskId}`, row.spawn.label);
      if (namespace) spawnNames.set(`ns:${namespace}`, row.spawn.label);
      // A `subgraph` spawn is not an announcement of a child that will get a
      // lane of its own (`buildLanes` skips this kind for that reason) — it is
      // this graph's own mounted node beginning work, and the `settled` frame
      // written back onto this row is it ending. Two dated ends, so the bar is
      // measured rather than inferred.
      if (namespace !== null && row.spawn.kind === 'subgraph') {
        const settled = Number.isFinite(row.spawn.settledMs as number)
          ? (row.spawn.settledMs as number)
          : null;
        mounts.set(namespace, { startMs: elapsed, endMs: settled, bar: null });
      }
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
        (mount?.bar ?? null) !== null ||
        (last !== undefined && namespace !== null && last.namespace === namespace);
      const owner = row.activeNode ? stepLabel(row.activeNode) : null;
      let bar: Draft | undefined = mount?.bar ?? last;
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
        charge(bar, row);
        bar.durationMs = add(bar.durationMs, duration);
        if (mount) {
          // The mount's frames have a bar now, and keep it until the run says
          // the mount closed. Re-arming `pending` is what lets the mount's own
          // completion frame close this bar rather than open a second one
          // after a sibling branch reported in between.
          mount.bar ??= bar;
          pending = bar;
          pendingOwner = bar.label;
        }
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
      charge(pending, row);
      pending.durationMs = add(pending.durationMs, duration);
      pending = null;
      pendingOwner = null;
      continue;
    }
    pending = null;
    pendingOwner = null;

    // A node *inside* an open mount reporting: it belongs to the mount's bar,
    // wherever that bar now sits in the list. The `last`-only form of this
    // check is what let `lead` cut `deep` in two (`memory-and-replay` 57).
    const bound = mount?.bar ?? null;
    if (bound !== null) {
      bound.count += 1;
      charge(bound, row);
      bound.durationMs = add(bound.durationMs, duration);
      pending = bound;
      pendingOwner = bound.label;
      continue;
    }

    const last = mutable();
    if (namespace !== null && last && last.namespace === namespace && last.taskId === row.taskId) {
      last.count += 1;
      charge(last, row);
      last.durationMs = add(last.durationMs, duration);
      continue;
    }

    const draft = open(label, row.taskId, namespace, startedAt);
    charge(draft, row);
    draft.durationMs = duration;
  }

  // Rule 6, second half: a mount's bar is its own two dated frames, not the
  // spans that happened to be charged to it. The two agree whenever nothing
  // interleaved, and where something did the pair is the one that is right.
  for (const mount of mounts.values()) {
    if (mount.bar === null || mount.startMs === null) continue;
    mount.bar.startMs = mount.startMs;
    if (mount.endMs === null) continue;
    mount.bar.durationMs = Math.max(0, mount.endMs - mount.startMs);
    mount.bar.measured = true;
  }
  // The kind, last, because it is a reading of the whole bar rather than of
  // any one frame: a mount is a mount whichever frame opened it, and a bar is
  // `model` on the evidence of a model frame it folded at any point. A refusal
  // is already set and wins outright — it is the only one of the four that is
  // a verdict rather than a description.
  for (const mount of mounts.values()) {
    if (mount.bar !== null && mount.bar.kind !== 'refusal') mount.bar.kind = 'mount';
  }
  for (const draft of steps) {
    if (draft.kind === 'tool' && draft.modelCalls > 0) draft.kind = 'model';
  }
  assignConcurrency(steps);

  return { steps, totalMs: clock };
}

/** The mount this namespace names, if the run had not yet closed it at `at`. */
function openMountAt<T extends { endMs: number | null }>(
  mounts: ReadonlyMap<string, T>,
  namespace: string,
  at: number | null,
): T | undefined {
  const mount = mounts.get(namespace);
  if (mount === undefined) return undefined;
  if (mount.endMs !== null && at !== null && at > mount.endMs) return undefined;
  return mount;
}

/**
 * Names, on each bar, the bars it overlapped in time.
 *
 * Strictly overlapped: a bar that begins exactly where another ends is a
 * sequence, and the span model produces a great many of those. So the only
 * pairs this can find are ones where at least one end came from a dated frame
 * rather than from an arrival — which is the point. It is a floor on the
 * concurrency in a run and never a ceiling, and `TimelineStep.concurrent`
 * says so where a reader will meet it.
 */
function assignConcurrency(
  steps: readonly { -readonly [K in keyof TimelineStep]: TimelineStep[K] }[],
): void {
  const found = steps.map((): string[] => []);
  const endOf = (step: TimelineStep): number => (step.startMs ?? 0) + (step.durationMs ?? 0);
  for (let i = 0; i < steps.length; i += 1) {
    const a = steps[i]!;
    if (a.startMs === null) continue;
    for (let j = i + 1; j < steps.length; j += 1) {
      const b = steps[j]!;
      if (b.startMs === null) continue;
      if (a.startMs < endOf(b) && b.startMs < endOf(a)) {
        found[i]!.push(b.key);
        found[j]!.push(a.key);
      }
    }
  }
  steps.forEach((step, index) => {
    step.concurrent = found[index]!;
  });
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

// ---------------------------------------------------------------------------
// Lanes — `memory-and-replay` 50
// ---------------------------------------------------------------------------

/**
 * How a lane ended, in the run's own words (`memory-and-replay` 54's
 * `outcome`). `null` is a real state and not a fifth word: the child is still
 * open, or the backend closes nothing at all.
 */
export type LaneEnding = 'ok' | 'error' | 'detached' | 'unknown';

/** One row of the chart: a thing whose bar may legitimately overlap another's. */
export interface RunLane {
  /** `'run'` for the graph's own lane, otherwise the child's `spawnId`. */
  readonly key: string;
  /** What to call it — see `buildLanes` for where the word comes from. */
  readonly name: string;
  readonly kind: 'run' | 'fanout' | 'subagent' | 'async';
  /** The canvas node that announced this child. `null` on the run's lane. */
  readonly parent: string | null;
  readonly taskId: string | null;
  /** The lane's own start on the server's clock: the `spawn` frame's offset. */
  readonly startMs: number | null;
  /** The `settled` frame's offset. `null` while the lane is open-ended. */
  readonly endMs: number | null;
  /**
   * A **measured** span between two dated frames — not a gap between whichever
   * frames arrived, which is what a bar in the run's lane still is.
   *
   * `null` whenever either end is missing, never `0`: `launch-readiness` 108's
   * rule, and the whole reason this ticket was blocked on 54.
   */
  readonly durationMs: number | null;
  /** The run never said this lane ended. A different claim from a bar that
   * has an end, and a renderer must draw it as one. */
  readonly openEnded: boolean;
  readonly ending: LaneEnding | null;
  /**
   * One of several lanes that share a name **and overlap in time** — "the 2nd
   * of 3 `impact-analyst`s". `null` when the name is unambiguous while this
   * lane is open.
   *
   * Deliberately not `visit`. `visit` counts laps of one node and means
   * *sequence*; this counts siblings and means *simultaneity*, and a chart on
   * which they render alike is the drawing this ticket exists to stop.
   */
  readonly sibling: { readonly index: number; readonly of: number } | null;
  /** The bars that belong to this lane, in the order they fired. */
  readonly steps: readonly TimelineStep[];
}

export interface RunLanes {
  /** The run's own lane first, then children in the order they were announced. */
  readonly lanes: readonly RunLane[];
  /** The recording's own wall clock — where an open-ended bar reaches. */
  readonly totalMs: number | null;
}

/** The run's own lane, named as the History panel already names it. */
const RUN_LANE = 'The workflow';

/**
 * Folds a run's frames into lanes: rows whose bars may overlap.
 *
 * A partition of `buildTimeline`'s bars, never a second derivation of them —
 * every bar that fold produces lands on exactly one lane, so the two cannot
 * come to disagree about what ran.
 *
 * # What a lane is, and what the other candidates became
 *
 * **A lane is a `spawn` of kind `fanout`, `subagent` or `async`**, keyed on
 * `spawnId`. The other candidates the data offers are all real and none of
 * them is the axis:
 *
 * - A **`taskId`** is the join *within* a lane, not the lane. It is `null` for
 *   a `subgraph` spawn, and 54 settled that a join for three kinds out of four
 *   is not a join.
 * - A **checkpoint namespace** is a mount, and a mount is not a lane — below.
 * - A **canvas node** is what a lane's steps are drawn from, not the lane: one
 *   `worker` node wears four concurrent children in the recorded run.
 *
 * Everything else — every top-level step, every revise lap, every mount —
 * stays on the run's own lane, where sequence is the truth.
 *
 * # Fan-out, mount and revise loop, told apart in the data
 *
 * The three look identical on a chart and are three different claims, so the
 * discriminator is never the shape:
 *
 * | | what says so |
 * | --- | --- |
 * | a fan-out child | a `spawn` frame with `kind: "fanout"`, minted from an entry in the orchestrator's own `subtasks` plan. Siblings arrive on one frame carrying one `elapsedMs`, so their overlap is recorded rather than inferred |
 * | a mounted workflow | a `spawn` frame with `kind: "subgraph"`, minted from a checkpoint namespace appearing for the first time. **Not a lane**: it is one node on the canvas, so it folds into that node's bar exactly as `buildTimeline`'s rules 2 and 6 fold it. That also settles the collapse depth — `nested-mounts` is three documents and yields one lane, because the rule is about what a mount *is* rather than about how deep a reader can bear to look. Its pair is not wasted for being a bar rather than a row: it is what makes that bar a **measured** one (57) |
 * | a revise lap | **no spawn frame at all** — the same top-level node reporting again. It keeps its `visit` counter and stays a second bar in the run's lane |
 *
 * # Where a lane's name comes from
 *
 * From the `label` the **run** put on the `spawn` frame, and from nowhere
 * else: the orchestrator's chosen archetype for a `fanout` child, the
 * `subagent_type` the model asked for for the other two. Read against the two
 * tickets that were already paid for here —
 *
 * - **39** (a lane named by the compiler): this name never passes through
 *   `safe_name`. It is minted where the run resolved it, so nothing is
 *   reversed and nothing is guessed; a run that gives no name gives its own
 *   subtask id instead, and that is left exactly as stored.
 * - **40** (a lane called `1`): the fallback is a domain id a reader can act
 *   on — the string that appears in `worker_results`, on the card's chip and
 *   in the trace — never an invocation counter, which names nothing.
 *
 * **A name is not an identity**, which is the second half and the one a
 * fan-out breaks: `stress-review` dispatched four children all called
 * `impact-analyst`. So the lane is *keyed* on `spawnId` and *named* by the
 * label, and overlapping namesakes carry `sibling` to say which of them this
 * is.
 *
 * # What a lane claims about time
 *
 * A child lane's bar is a **measured** start and end — two dated frames, the
 * `spawn` and the `settled` (46 and 54 together). That is a stronger claim
 * than any bar in the run's lane can make, which is still a span between
 * whichever frames arrived, and the difference is worth keeping visible.
 *
 * A lane the run never closed has `endMs: null`, `durationMs: null` and
 * `openEnded: true`, and its `ending` says which kind of open it is —
 * `detached` for a background child still working outside this run, `unknown`
 * for a recording that ended owing an account, `null` for a child that has
 * simply not finished yet. None of them is given a number, because the run
 * measured none.
 *
 * ## Two top-level branches running in parallel — and why neither is a lane
 *
 * `memory-and-replay` 57, and the answer is *not* a row. A dispatched child
 * is an actor: it is announced, it is closed, it has an owner and an end, and
 * a row is what that shape wants. A **branch is a path through this same
 * graph** — the nodes on it are this graph's own nodes, drawn on this canvas,
 * belonging to this run. Giving `deep` a row and `lead` a row would say the
 * workflow had two actors in it, which is a claim about the document rather
 * than about the run, and it would be made afresh on every branching
 * classifier. So a branch stays bars in the run's lane, and what a bar owes a
 * reader is an honest **position**, not a row of its own.
 *
 * Half of that position was already on the wire and simply not read.
 * `stress-review`'s router opened both desks in one superstep and the `deep`
 * mount ran from 2 775 ms to 13 317 ms alongside the supervisor branch —
 * dated at both ends by its `subgraph` `spawn`/`settled` pair, exactly as a
 * child lane is. `buildTimeline`'s rule 6 now reads it, so that mount draws
 * once, in the right place, at its real length, and `TimelineStep.concurrent`
 * names the bar it overlapped.
 *
 * **The half that is still missing is a start for an ordinary node.** A
 * branch of plain agent nodes carries no pair, so its bars remain spans laid
 * end to end and two of them can never be *found* to overlap even when they
 * did. That is 48's finding, priced and deliberately not shipped:
 * `stream_mode="tasks"` emits a per-task start, and putting it on the wire is
 * a new frame kind — a Pydantic model, a regenerated `docs/openapi.json`, the
 * hand-written mirror in `RuntimeClient.ts` and `contractDrift.test.ts`.
 * Inferring those starts here instead would be the guess 46 exists to stop,
 * so nothing here invents one. `concurrent` is therefore a floor and never a
 * ceiling, and its own doc comment says so where a reader will meet it.
 */
export function buildLanes(rows: readonly TimelineRow[]): RunLanes {
  const { steps, totalMs } = buildTimeline(rows);

  type Child = { -readonly [K in keyof RunLane]: RunLane[K] } & { steps: TimelineStep[] };
  const children: Child[] = [];

  for (const row of rows) {
    const spawn = row.spawn;
    // A mount folds; the run's own steps are the run's own lane. Only a child
    // that can outlive the frame that announced it earns a row.
    if (!spawn || spawn.kind === 'subgraph') continue;
    const startMs = Number.isFinite(row.elapsedMs as number) ? (row.elapsedMs as number) : null;
    const endMs = Number.isFinite(spawn.settledMs as number) ? (spawn.settledMs as number) : null;
    children.push({
      // A backend older than 54 mints no `spawnId`; the lane still exists and
      // is still keyed uniquely, it simply can never be closed.
      key: spawn.spawnId ?? `spawn@${children.length}`,
      name: spawn.label,
      kind: spawn.kind === 'subagent' || spawn.kind === 'async' ? spawn.kind : 'fanout',
      parent: stepLabel(row.node),
      taskId: row.taskId,
      startMs,
      endMs,
      durationMs: startMs === null || endMs === null ? null : Math.max(0, endMs - startMs),
      openEnded: endMs === null,
      ending: spawn.outcome ?? null,
      sibling: null,
      steps: [],
    });
  }

  const runLane: Child = {
    key: 'run',
    name: RUN_LANE,
    kind: 'run',
    parent: null,
    taskId: null,
    startMs: steps.length > 0 ? (steps[0]?.startMs ?? null) : null,
    endMs: totalMs,
    durationMs: totalMs,
    // The reference frame: the recording's end *is* its end, so it is never
    // the open-ended shape even while the run is still streaming.
    openEnded: false,
    ending: null,
    sibling: null,
    steps: [],
  };

  for (const step of steps) {
    const lane = claim(children, step) ?? runLane;
    // `visit` is renumbered **within the lane**, and that is not tidiness.
    // `buildTimeline` counts visits across the whole run, so the recorded
    // fan-out's four children came out `visit 1..4` — the panel's badge for
    // *a fourth revise lap of one node*, said about four workers that ran two
    // at a time. A lap is a lap of this lane or it is nothing.
    lane.steps.push(
      lane === runLane
        ? step
        : { ...step, visit: lane.steps.filter((seen) => seen.label === step.label).length + 1 },
    );
  }
  assignSiblings(children, totalMs);

  return { lanes: [runLane, ...children], totalMs };
}

/**
 * The child lane a bar belongs to, or nothing — it is the run's own.
 *
 * Matched on the task id **inside the lane's window**, not on the task id
 * alone. The window is what makes a second wave of the same fan-out a second
 * set of lanes rather than a re-entry of the first: a worker's completion
 * frame lands between its child's two dated frames by construction, and a run
 * that reuses a subtask id across laps still resolves to the lap that was open.
 */
function claim<T extends { taskId: string | null; startMs: number | null; endMs: number | null }>(
  lanes: readonly T[],
  step: TimelineStep,
): T | undefined {
  if (step.taskId === null) return undefined;
  const named = lanes.filter((lane) => lane.taskId === step.taskId);
  const within = named.find(
    (lane) =>
      lane.startMs !== null &&
      step.startMs !== null &&
      step.startMs >= lane.startMs &&
      (lane.endMs === null || step.startMs <= lane.endMs),
  );
  // With no clock there is no window, so an unambiguous name is all there is;
  // an ambiguous one claims nothing rather than claiming wrongly (ticket 39's
  // rule, one level down).
  return within ?? (named.length === 1 ? named[0] : undefined);
}

/**
 * Numbers the lanes that share a name **and are open at the same time**.
 *
 * Per overlapping group, never per run: `stress-review` fanned out twice under
 * one archetype, and "1 of 2, 2 of 2, 1 of 2, 2 of 2" is what happened, while
 * "1 of 4 … 4 of 4" would say the second wave was still waiting on the first.
 * An open-ended lane is treated as reaching the end of the recording, which is
 * as far as anything is known to have been running.
 */
function assignSiblings(
  lanes: readonly { -readonly [K in keyof RunLane]: RunLane[K] }[],
  totalMs: number | null,
): void {
  const byName = new Map<string, (typeof lanes)[number][]>();
  for (const lane of lanes) {
    const group = byName.get(lane.name) ?? [];
    group.push(lane);
    byName.set(lane.name, group);
  }
  for (const group of byName.values()) {
    if (group.length < 2) continue;
    const end = (lane: (typeof group)[number]): number =>
      lane.endMs ?? totalMs ?? Number.MAX_SAFE_INTEGER;
    let cluster: (typeof group)[number][] = [];
    let reach = -1;
    const close = (): void => {
      if (cluster.length > 1) {
        cluster.forEach((lane, index) => {
          lane.sibling = { index: index + 1, of: cluster.length };
        });
      }
      cluster = [];
      reach = -1;
    };
    for (const lane of group) {
      const start = lane.startMs ?? 0;
      if (cluster.length > 0 && start > reach) close();
      cluster.push(lane);
      reach = Math.max(reach, end(lane));
    }
    close();
  }
}
