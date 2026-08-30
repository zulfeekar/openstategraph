import type { PastRun, PastRunStep, PastRunToolCall, PastRunTruncation } from './RuntimeClient';

/**
 * How a past run reads on screen.
 *
 * Pure, and in `core/` rather than beside the component, for the reason every
 * other formatter here is: this is the part with rules — what counts as
 * identity, when a stamp is unreadable, which channels a person looks for
 * first — and rules deserve tests that need no DOM. The component is left
 * with markup.
 *
 * Nothing here re-executes anything. Every field was written while the run
 * happened; this module only chooses words for it.
 */

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/**
 * `2026-08-11T11:40:00Z` → `20 min ago`.
 *
 * An unparseable stamp is returned **verbatim**, never as "Invalid Date" and
 * never as a guess: the backend reads `ts` straight out of a checkpoint, and a
 * saver that writes some other format should show what it wrote rather than
 * have this function pretend to understand it.
 */
export function relativeTime(iso: string, now: number): string {
  if (!iso) return '';
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return iso;
  // Clamped at zero: a checkpoint stamped slightly ahead of this browser's
  // clock is skew, and "in 30 seconds" for something that already happened
  // reads as a bug in the history rather than in the clock.
  const age = Math.max(0, now - at);
  if (age < MINUTE) return 'just now';
  if (age < HOUR) return `${Math.floor(age / MINUTE)} min ago`;
  if (age < DAY) return `${Math.floor(age / HOUR)} h ago`;
  return `${Math.floor(age / DAY)} d ago`;
}

export interface RunDescription {
  readonly title: string;
  /** Who asked, when the run recorded it — empty when it recorded nobody. */
  readonly identity: string;
  readonly meta: string;
  readonly statusLabel: string;
}

/**
 * `sitting` is the session id of the tab doing the reading.
 *
 * It exists because `memory-and-replay/45` gave `session_id` a writer. Before
 * that the field was `""` on every run and this line printed nothing; after it,
 * printing the raw value would put an opaque `sess-…` token under every row of
 * a panel whose identity line means *who asked*. The id itself is not
 * information to a reader — **whether it is theirs** is. So a run from this
 * tab's own sitting says nothing, and one from another says so in words.
 *
 * Omitted means *this reader has no sitting* (a script, a test, a browser with
 * site data blocked), and then no run can be told apart from the reader's own —
 * so none of them claim to be.
 */
export function describeRun(run: PastRun, now: number, sitting = ''): RunDescription {
  const session = run.sessionId.trim();
  const elsewhere = session !== '' && sitting !== '' && session !== sitting;
  const parts = [run.userEmail.trim(), elsewhere ? 'another sitting' : ''].filter(Boolean);
  const when = relativeTime(run.updatedAt, now);
  const steps = `${run.steps} ${run.steps === 1 ? 'step' : 'steps'}`;
  return {
    title: run.question.trim() || '(no question recorded)',
    identity: parts.join(' · '),
    meta: when ? `${steps} · ${when}` : steps,
    // "waiting for you" rather than "paused": paused describes the server,
    // and the only thing a reader can act on is that it wants an answer.
    //
    // `failed` is a sibling of `status`, not a third value of it — a run can
    // be paused *and* have a failed node — so both read independently rather
    // than one crowding the other out. "ask again" rather than a bare
    // "failed" badge for the same reason "waiting for you" beat "paused":
    // the only thing a reader can do about a failed node is re-ask, and the
    // reason is in the steps below.
    statusLabel:
      run.status === 'paused'
        ? run.failed
          ? 'waiting for you · a step failed'
          : 'waiting for you'
        : run.failed
          ? 'ask again — a step failed'
          : 'finished',
  };
}

/**
 * The channels a reader scans for first, in the order they scan for them.
 * Everything else follows alphabetically, exactly as the backend sorted it —
 * so an unknown channel from a future node type still appears, just later.
 */
const LEADING = ['question', 'answer', 'outputs', 'feedback', 'decisions'] as const;

/**
 * A channel that carries nothing, however it was serialised.
 *
 * `{}` and `[]` are what an untouched dict or list channel renders as, and a
 * graph has several: `outputs`, `decisions`, `subtasks`, `worker_results`.
 * Printing them makes a checkpoint eight lines of punctuation with the one
 * line that changed buried inside it.
 */
const BLANK = new Set(['', '{}', '[]']);

export function stepLines(step: PastRunStep): readonly { key: string; value: string }[] {
  const rank = (key: string) => {
    const index = LEADING.indexOf(key as (typeof LEADING)[number]);
    return index === -1 ? LEADING.length : index;
  };
  return Object.entries(step.values)
    .filter(([, value]) => !BLANK.has(value.trim()))
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
    .map(([key, value]) => ({ key, value }));
}

/**
 * `Step 3 · loop`.
 *
 * LangGraph numbers the checkpoint written before the first superstep `-1`;
 * calling that "Step -1" would invite the reader to work out what a negative
 * superstep is, when the answer is simply "the question, before anything ran".
 */
export function stepTitle(step: PastRunStep): string {
  const head = step.step < 0 ? 'Input' : `Step ${step.step}`;
  return step.source ? `${head} · ${step.source}` : head;
}

/**
 * One graph's own timeline within a run.
 *
 * The endpoint returns every checkpoint of every graph in one chronological
 * list, and each graph numbers its supersteps from `-1`, so a `morning-brief`
 * run reads as `Step 0 · loop` five times over. A lane is the fix: the
 * workflow itself, and one lane per subgraph *run*.
 */
export interface PastRunLane {
  /** The graph-node name that owns this lane; `''` is the workflow itself. */
  readonly node: string;
  readonly namespace: readonly string[];
  /** Which run of this node it is — 1-based, and > 1 only for a fan-out. */
  readonly occurrence: number;
  readonly steps: readonly PastRunStep[];
}

/** Where a graph starts counting. LangGraph stamps the checkpoint written
 *  before the first superstep `-1`. */
const FIRST_STEP = -1;

/**
 * The flat list, split into one lane per graph run, in first-appearance order.
 *
 * **Not by grouping neighbours.** The stored `example.com` run interleaves
 * genuinely — three workers ran at once, so their checkpoints alternate — and
 * a neighbour-grouping would produce a lane per checkpoint.
 *
 * A node dispatched twice gets two lanes, and the *step counter restarting* is
 * the only evidence of the boundary: the instance id is deliberately absent
 * from `namespace`, because for identity the two dispatches are one worker.
 * The break is on a **restart**, not on any non-increase — an `update` or
 * `fork` source can rewrite a superstep that has already been written, and
 * that is the same lane continuing.
 *
 * Every step comes out exactly once. Laning is a re-reading, never a filter.
 */
export function lanes(steps: readonly PastRunStep[]): readonly PastRunLane[] {
  const found: {
    node: string;
    namespace: readonly string[];
    occurrence: number;
    steps: PastRunStep[];
  }[] = [];
  const openLane = new Map<string, { occurrence: number; steps: PastRunStep[] }>();
  const runsSoFar = new Map<string, number>();

  for (const step of steps) {
    const key = step.namespace.join('|');
    const current = openLane.get(key);
    const restarted = current !== undefined && step.step === FIRST_STEP;
    if (current === undefined || restarted) {
      const occurrence = (runsSoFar.get(key) ?? 0) + 1;
      runsSoFar.set(key, occurrence);
      const lane = { node: step.node, namespace: step.namespace, occurrence, steps: [step] };
      found.push(lane);
      openLane.set(key, lane);
      continue;
    }
    current.steps.push(step);
  }
  return found;
}

/**
 * `The workflow` · `worker-web` · `worker-web · run 2` · `Chinook › model`.
 *
 * A lane is stored under its **graph-node name**, which is not the canvas node
 * id: the compiler mangles every non-alphanumeric character, so `worker-web`
 * is checkpointed as `worker_web`. `names` is how the open document answers
 * for its own nodes — built by `displayNamesByGraphName`, which reads the
 * mangling *forward* and therefore guesses nothing.
 *
 * Each segment is resolved on its own, and an unresolved one is shown exactly
 * as stored. That is not a fallback so much as the rule: a segment belonging
 * to a *mounted* document is not in this document's map, and the honest thing
 * to print for a node this canvas does not contain is what the run called it.
 *
 * `names` is optional so a caller with no document — a test, or a surface that
 * genuinely has none — reads what the run stored, as before.
 */
export function laneTitle(lane: PastRunLane, names?: ReadonlyMap<string, string>): string {
  if (lane.namespace.length === 0) return 'The workflow';
  // The whole path, because the innermost name alone would claim a nested
  // graph's node belongs to this canvas.
  const path = lane.namespace.map((name) => names?.get(name) ?? name).join(' \u203a ');
  return lane.occurrence > 1 ? `${path} · run ${lane.occurrence}` : path;
}

/**
 * `web_fetch({"url": "…"}) \u2192 Error: web_fetch is not a valid tool`.
 *
 * One line, because a tool call is one event. The arguments and the result are
 * the parts a reader came for — a run that answered wrongly usually asked for
 * the wrong thing, or was refused, and the name alone says neither.
 *
 * The two degenerate cases are stated rather than smoothed over: a request the
 * run never got an answer to says so, because an empty tail would read as
 * "returned nothing"; and an answer whose request is no longer in the stored
 * history shows the answer without inventing arguments for it.
 */
export function toolCallLine(call: PastRunToolCall): string {
  const name = call.name || 'a tool';
  const head = call.arguments ? `${name}(${call.arguments})` : name;
  return call.result ? `${head} \u2192 ${call.result}` : `${head} \u2014 no result stored`;
}

/**
 * The two numbers a profiler exists for, on one line: how long, and what it
 * cost (`memory-and-replay` 37, part 2).
 *
 * **Empty when neither is known, and never a zero.** The endpoint withholds a
 * duration it could not measure — the first step of a graph, an unreadable
 * timestamp — and printing `0 ms` there would make up the one claim it
 * declined to make. Same for tokens: a bookkeeping superstep did not spend
 * nothing, it called no model.
 *
 * Units chosen for what a person can hold rather than for precision: a
 * sub-second step is the milliseconds it was, a normal step is one decimal of
 * seconds, and anything past a minute is minutes — nobody reads `195000ms`.
 */
export function stepCost(step: PastRunStep): string {
  const parts: string[] = [];
  if (step.durationMs !== null) parts.push(duration(step.durationMs));
  if (step.tokens) {
    const { inputTokens, outputTokens, totalTokens } = step.tokens;
    parts.push(
      `${count(totalTokens)} tokens (${count(inputTokens)} in \u00b7 ${count(outputTokens)} out)`,
    );
  }
  return parts.join(' \u00b7 ');
}

function duration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const seconds = Math.round(ms / 1000);
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function count(value: number): string {
  return value.toLocaleString('en-US');
}

/**
 * What a history that came back cut off says, in the words of a reader who can
 * only look at it.
 *
 * `the-cost-of-one-more/13`. The backend has said this since `06`, and the
 * editor read the response's first two keys and no third — so a 5,000-superstep
 * run and the last 200 of one drew identically, which is exactly the state `06`
 * was filed to end.
 *
 * **Not the server's own sentence, and that is a decision rather than a
 * rewrite.** `_truncation` ends *"ask again with a higher limit (up to 2000) to
 * see more"*, which is true of `openstategraph threads show` and of anything
 * holding the URL, and false here: this lane fetches with no `limit` and offers
 * no control that could raise one. Printing it would describe a button that
 * does not exist. The two facts a reader here can act on are that the missing
 * end is the *oldest* — so the run began before what they are looking at — and
 * that a tool result whose request fell outside is listed with no arguments,
 * which otherwise reads as a tool called with nothing.
 *
 * `end` is a string on the wire and not an enum, so an end this client has
 * never seen still yields a true sentence rather than a wrong direction — the
 * repository's tolerant-reading rule, one field wide.
 */
export function truncationLine(truncation: PastRunTruncation | null): string {
  if (truncation === null) return '';
  const opening =
    truncation.end === 'oldest'
      ? `Older supersteps are not shown \u2014 this reads the newest ${count(truncation.kept)}`
      : `Some supersteps are not shown \u2014 this reads ${count(truncation.kept)} of them`;
  return `${opening} of a longer run. A tool result whose request fell outside them is listed without its arguments.`;
}
