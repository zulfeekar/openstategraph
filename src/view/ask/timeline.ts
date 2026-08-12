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
 * Honest about its numbers. `durationMs` is the wall-clock gap since the
 * previous frame, the same approximation the Inspector's badge and the trace
 * tree already use, because LangGraph's `updates` stream reports a node only
 * *after* it finishes — there is no start event to subtract. For a sequential
 * chain that is close; for concurrently dispatched workers it attributes one
 * shared gap to whichever frame arrived, and the UI must not claim otherwise.
 */

/** What the timeline needs from one stream frame. */
export interface TimelineRow {
  readonly node: string;
  readonly taskId: string | null;
  readonly internal: boolean;
  /** LangGraph's checkpoint namespace — non-empty inside a subgraph/team. */
  readonly namespace?: readonly string[];
  readonly durationMs: number;
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
  /** Offset from the first frame, in ms. */
  readonly startMs: number;
  readonly durationMs: number;
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
  readonly totalMs: number;
}

/** Strips the `node:` prefix the canvas ids carry, for display. */
export function stepLabel(node: string): string {
  return node.replace(/^node:/, '');
}

/**
 * Folds a run's frames into bars.
 *
 * Three rules, and each earns its place:
 *
 * 1. **Internal frames never get a bar.** A twenty-call tool loop is one
 *    node's work, not twenty steps; it becomes a count on the bar that owns
 *    it, and its time is charged there.
 * 2. **A subgraph or team collapses to one lane.** Everything sharing a
 *    checkpoint namespace is, on the canvas, a single mounted node — showing
 *    its internals as peers of the parent graph's nodes would misrepresent
 *    the drawing the developer is looking at.
 * 3. **A repeated node gets a repeated bar.** This is the whole reason to
 *    build a timeline for an evaluator-optimizer graph: a second bar for the
 *    same agent *is* the revise lap, and merging them would erase it.
 * 4. **A spawn row names a lane, it does not occupy one.** A spawn is an
 *    announcement, not work: it takes no time and gets no bar. What it
 *    contributes is the child's *name*, so a lane reads `researcher` rather
 *    than `wf_music:5f2ab…` or a bare task id.
 */
export function buildTimeline(rows: readonly TimelineRow[]): Timeline {
  type Draft = { -readonly [K in keyof TimelineStep]: TimelineStep[K] };
  const steps: Draft[] = [];
  const visits = new Map<string, number>();
  const spawnNames = new Map<string, string>();
  let clock = 0;

  const mutable = (): Draft | undefined => steps[steps.length - 1];

  for (const row of rows) {
    const duration = Number.isFinite(row.durationMs) ? Math.max(0, row.durationMs) : 0;

    if (row.spawn) {
      // Keyed by whichever handle the child's own frames will carry: a
      // `Send`-dispatched worker is told apart by `taskId`, a mounted
      // subgraph by its namespace head.
      if (row.taskId) spawnNames.set(`task:${row.taskId}`, row.spawn.label);
      const head = row.namespace?.[0];
      if (head) spawnNames.set(`ns:${head}`, row.spawn.label);
      continue;
    }

    if (row.internal) {
      const last = mutable();
      // An internal frame before any node frame has nothing to belong to;
      // charge the clock and drop it rather than inventing a phantom bar.
      if (last) {
        last.internalSteps += 1;
        last.durationMs += duration;
      }
      clock += duration;
      continue;
    }

    const namespace = row.namespace?.[0] ?? null;
    const last = mutable();

    if (namespace !== null && last && last.namespace === namespace && last.taskId === row.taskId) {
      last.count += 1;
      last.durationMs += duration;
      clock += duration;
      continue;
    }

    const spawned =
      (row.taskId ? spawnNames.get(`task:${row.taskId}`) : undefined) ??
      (namespace ? spawnNames.get(`ns:${namespace}`) : undefined);
    const label = spawned ?? (namespace !== null ? namespace : undefined) ?? stepLabel(row.node);
    const visit = (visits.get(label) ?? 0) + 1;
    visits.set(label, visit);

    steps.push({
      key: `${label}#${visit}${row.taskId ? `@${row.taskId}` : ''}`,
      label,
      taskId: row.taskId,
      order: steps.length + 1,
      startMs: clock,
      durationMs: duration,
      count: 1,
      internalSteps: 0,
      namespace,
      visit,
    });
    clock += duration;
  }

  return { steps, totalMs: clock };
}

/** A bar's width as a percentage of the run, floored so a fast step is still visible. */
export function barWidthPercent(step: TimelineStep, totalMs: number): number {
  if (totalMs <= 0) return 100;
  return Math.max(1.5, (step.durationMs / totalMs) * 100);
}

/** A bar's left offset as a percentage of the run. */
export function barOffsetPercent(step: TimelineStep, totalMs: number): number {
  if (totalMs <= 0) return 0;
  return Math.min(98.5, (step.startMs / totalMs) * 100);
}
