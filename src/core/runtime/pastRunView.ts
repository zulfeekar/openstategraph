import type { PastRun, PastRunStep, PastRunToolCall } from './RuntimeClient';

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

export function describeRun(run: PastRun, now: number): RunDescription {
  const parts = [run.userEmail.trim(), run.sessionId.trim()].filter(Boolean);
  const when = relativeTime(run.updatedAt, now);
  const steps = `${run.steps} ${run.steps === 1 ? 'step' : 'steps'}`;
  return {
    title: run.question.trim() || '(no question recorded)',
    identity: parts.join(' · '),
    meta: when ? `${steps} · ${when}` : steps,
    // "waiting for you" rather than "paused": paused describes the server,
    // and the only thing a reader can act on is that it wants an answer.
    statusLabel: run.status === 'paused' ? 'waiting for you' : 'finished',
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
  const found: { node: string; namespace: readonly string[]; occurrence: number; steps: PastRunStep[] }[] = [];
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
 * `The workflow` · `worker_web` · `worker_web · run 2` · `mount1 › model`.
 *
 * The name is the **graph-node name**, which is not always the canvas node id:
 * the compiler mangles hyphens, so `worker-web` is stored as `worker_web`. It
 * is shown as stored rather than guessed back, because the reverse is
 * ambiguous — a node id may legitimately contain an underscore — and a label
 * that quietly names the wrong node is worse than one that looks technical.
 * Resolving it properly needs the document, which this surface does not have;
 * that is a follow-up, recorded on the ticket rather than approximated here.
 */
export function laneTitle(lane: PastRunLane): string {
  if (lane.namespace.length === 0) return 'The workflow';
  // The whole path, because the innermost name alone would claim a nested
  // graph's node belongs to this canvas.
  const path = lane.namespace.join(' \u203a ');
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
