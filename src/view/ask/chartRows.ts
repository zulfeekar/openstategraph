/**
 * The lanes, projected into the rows a chart draws — `memory-and-replay` 64,
 * and the events beneath them, `66`.
 *
 * Split out of `timeline.ts` when `66` added the event rows: the fold and the
 * projection are two jobs, and the module was 461 code lines against a ceiling
 * of 500 before this ticket started. Nothing moved except its address —
 * `chartRows` was already named as the seam by 64's own resolution.
 */
import type { RunLane, TimelineStep } from './timeline';

/**
 * One drawn row of the chart — `memory-and-replay` 64.
 *
 * A lane and a row are not the same thing, and the difference is the whole of
 * this ticket. **A lane is what the run dispatched**: announced, owned,
 * closed, and `50` settled that a branch through this same graph is not one.
 * **A row is what the chart draws.** The run's own lane holds every top-level
 * bar in sequence, which is true and is not a drawing: fifteen nodes crowded
 * onto one line called `The workflow`, with a fan-out reading as overlapping
 * bars rather than as parallel rows.
 *
 * So the run's lane is split **by node**, and every dispatched child is
 * indented under the row that announced it. Nothing here is a second
 * derivation of a bar: a row holds the lanes' own steps, which is what
 * `chartRows` is asserted to preserve.
 */
export interface ChartRow {
  /** Stable within a run; safe as a React key. */
  readonly key: string;
  /**
   * The node's own name, or the name the run put on the child it announced.
   *
   * A `whole` row's siblings are not spelled here: "1 of 2" is a caption the
   * pane beside the chart also prints, and one sentence written twice is the
   * defect this repository names most often.
   */
  readonly name: string;
  /** 0 at the top level; one more for each row this one sits inside. */
  readonly depth: number;
  /** The lane these bars came off — a child's own, or the run's. */
  readonly lane: RunLane;
  readonly steps: readonly TimelineStep[];
  /**
   * This row *is* a whole lane, so the lane's `settled` tick and open-ended
   * strip belong to it.
   *
   * `false` for a node row, which is a slice of the run's own lane. That
   * lane's end is the recording's end, so drawing a settled tick on every
   * node row would say the run closed fifteen things it never announced —
   * which is what the single-row chart did once, at the right-hand edge.
   */
  readonly whole: boolean;
  /**
   * This row draws what ran *inside* a node rather than the node itself —
   * `memory-and-replay` 66.
   *
   * The owner's rule is that **a row is a component's identity and a bar is an
   * occurrence**, and this flag says which level of it a row is at. It exists
   * because the two are read differently and the difference cannot be got from
   * the depth: a dispatched child is also indented, and it *is* an actor the
   * run announced, with a lane, an ending and a settled tick. An event row is
   * none of those — it is a slice of its parent's bar, and `whole` is already
   * `false` for a node row, so a second word is needed rather than a reuse.
   */
  readonly event: boolean;
}

/**
 * The lanes, projected into the rows a chart draws.
 *
 * Ordering is depth-first and comes from the run twice over: a node row sits
 * where the run first heard from that node, and a child row sits directly
 * under the row that announced it, in the order the run announced them.
 *
 * # Which row a child belongs under
 *
 * A child lane records the canvas node that announced it (`RunLane.parent`)
 * and the millisecond it was announced. The parent row is therefore the row
 * carrying a bar with that label **whose window contains the spawn** — which
 * is what resolves a nested subagent under its own parent rather than under
 * the top-level namesake, since rows are added parents-first and the deepest
 * match is the last one.
 *
 * With no window match the named top-level row is taken, and with no named
 * row at all the child sits at the top level. Neither is a guess dressed as a
 * fact: a child whose parent this recording has no bar for gets a row with no
 * gutter, rather than a gutter under a row that was invented for it.
 *
 * # A mount is still not a row
 *
 * `50`'s table, unchanged. A mount is one node on the canvas, so it folds into
 * that node's bar and draws hatched at the length its own two dated frames
 * give it (`buildTimeline` rule 6). Giving it a row would claim a shape the
 * fold deliberately does not produce.
 */
export function chartRows(lanes: readonly RunLane[]): readonly ChartRow[] {
  type Draft = { -readonly [K in keyof ChartRow]: ChartRow[K] } & { steps: TimelineStep[] };
  type Node = { readonly row: Draft; readonly kids: Node[] };

  const added: Node[] = [];
  const roots: Node[] = [];
  const byLabel = new Map<string, Node>();

  const run = lanes.find((lane) => lane.kind === 'run');
  if (run) {
    for (const step of run.steps) {
      let node = byLabel.get(step.label);
      if (!node) {
        node = {
          row: {
            key: `node:${step.label}`,
            name: step.label,
            depth: 0,
            lane: run,
            steps: [],
            whole: false,
            event: false,
          },
          kids: [],
        };
        byLabel.set(step.label, node);
        added.push(node);
        roots.push(node);
      }
      node.row.steps.push(step);
    }
  }

  for (const lane of lanes) {
    if (lane.kind === 'run') continue;
    const parent = parentRow(added, lane);
    const node: Node = {
      row: {
        key: lane.key,
        name: lane.name,
        depth: parent === null ? 0 : parent.row.depth + 1,
        lane,
        steps: [...lane.steps],
        whole: true,
        event: false,
      },
      kids: [],
    };
    (parent === null ? roots : parent.kids).push(node);
    added.push(node);
  }

  const drawn: ChartRow[] = [];
  const walk = (nodes: readonly Node[]): void => {
    for (const node of nodes) {
      drawn.push(node.row);
      // Directly under the row whose loop ran them, and above any child the
      // run *dispatched*: these are that row's own work, and a dispatched
      // child is a separate actor that happens to be indented the same way.
      drawn.push(...eventRows(node.row));
      walk(node.kids);
    }
  };
  walk(roots);
  return drawn;
}

/**
 * The rows for what ran inside one row's bars — `memory-and-replay` 66.
 *
 * The owner's rule, in one sentence and one sketch:
 *
 * > A row is a component's identity. Repeats of the same component share that
 * > row, separated by real time. A different component gets its own row.
 *
 * ```
 * [tool1]  <temporal space>  [tool1]
 *               [tool2]
 *                               [tool3]  <temporal space>  [tool3]
 * ```
 *
 * So fourteen calls across three tools are **three** rows carrying four, one
 * and ten bars at the offsets the run stamped — never fourteen rows, and never
 * one row with fourteen bars laid over each other.
 *
 * # This is not a second mechanism
 *
 * `chartRows` above already folds a repeat one level up: a revise lap draws
 * `agent-sql ×2` on the agent's own row rather than as a second row. This is
 * that rule applied downward, and the general statement of both is the one
 * sentence they share — an identity is a row, an occurrence is a bar.
 *
 * # What identity is keyed on
 *
 * **The label of the component that executed** — a tool's own name, or the
 * internal frame's node name for everything else. Never the `callId`, which is
 * an occurrence and would give fourteen rows; never the arguments, because two
 * calls to one tool with different arguments are one component, which is the
 * owner's first clause. Ordered by first touch, so a row appears where the run
 * first reached that component.
 *
 * A row is grown only for a component that actually ran. An absent row and an
 * empty row are two facts, and a node that spent no model time and called no
 * tool grows neither.
 */
function eventRows(parent: ChartRow): readonly ChartRow[] {
  const byLabel = new Map<string, TimelineStep[]>();
  for (const step of parent.steps) {
    for (const each of step.events) {
      const found = byLabel.get(each.label);
      if (found) found.push(each);
      else byLabel.set(each.label, [each]);
    }
  }
  // Ordered by when the run first reached each component, not by which frame
  // arrived first. They differ, and the difference is not cosmetic: `invoked`
  // is emitted just *before* the `update` frame that reports the model step
  // that asked for it, so arrival order puts a tool above the model call that
  // called it. A row belongs where its first bar sits.
  const first = (steps: readonly TimelineStep[]): number =>
    Math.min(...steps.map((step) => step.startMs ?? Number.POSITIVE_INFINITY));
  return [...byLabel]
    .sort(([, a], [, b]) => first(a) - first(b))
    .map(([label, steps]) => ({
      key: `${parent.key}/${label}`,
      name: label,
      depth: parent.depth + 1,
      lane: parent.lane,
      steps,
      // Never a whole lane: the settled tick and the open-ended strip say a
      // *dispatched child* closed or did not, and an event is neither
      // dispatched nor closed by the run (`64`, on the same mark drawn
      // wrongly on every node row).
      whole: false,
      event: true,
    }));
}

/**
 * The row a dispatched child belongs under, in three attempts and no guesses.
 *
 * 1. **A lane that was open on the child's own task.** This is `claim`'s rule
 *    one level up: a child announced from inside another child carries that
 *    child's task id, and its spawn lands inside that child's dated window. It
 *    is tried first because it is the only one of the three that reads a value
 *    the run wrote down rather than a name it repeated.
 * 2. **The row that was drawing `lane.parent` when the spawn arrived.** Rows
 *    are added parents-first, so the deepest match is the last one.
 * 3. **The row named `lane.parent`**, whichever it is.
 *
 * `null` — the top level — when the recording has no bar by that name at all.
 * A gutter under a row invented for the occasion would be worse than none.
 */
function parentRow<
  T extends { readonly row: { readonly lane: RunLane; readonly steps: readonly TimelineStep[] } },
>(rows: readonly T[], lane: RunLane): T | null {
  const at = lane.startMs;
  const opened = (row: T): boolean => {
    const host = row.row.lane;
    return (
      host !== lane &&
      host.taskId !== null &&
      host.taskId === lane.taskId &&
      host.startMs !== null &&
      at !== null &&
      at >= host.startMs &&
      (host.endMs === null || at <= host.endMs)
    );
  };
  const inherited = rows.filter(opened).at(-1);
  if (inherited) return inherited;

  const parent = lane.parent;
  if (parent === null) return null;
  const named = rows.filter((row) => row.row.steps.some((step) => step.label === parent));
  const within =
    at === null
      ? []
      : named.filter((row) =>
          row.row.steps.some(
            (step) =>
              step.label === parent &&
              step.startMs !== null &&
              step.startMs <= at &&
              step.startMs + (step.durationMs ?? 0) >= at,
          ),
        );
  return within.at(-1) ?? named[0] ?? null;
}

/**
 * Five or so round offsets across the run — never more than the width can hold.
 *
 * Here rather than in the chart because an axis tick is a number the run has,
 * not a rectangle somebody draws: it is decidable, so it is tested directly
 * (`memory-and-replay` 64).
 */
export function axisTicks(totalMs: number): readonly number[] {
  if (totalMs <= 0) return [0];
  const raw = totalMs / 5;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((n) => n * magnitude).find((n) => n >= raw) ?? raw;
  const ticks: number[] = [];
  for (let at = 0; at < totalMs; at += step) ticks.push(at);
  return ticks;
}

/**
 * The axis ticks with their labels, in **one unit across the whole axis** —
 * `memory-and-replay` 68.
 *
 * The shipped axis read `0 ms · 5.0 s · 10.0 s`, because each tick was passed
 * through `formatMs`, which switches unit at a second. That is right for one
 * duration in a table and wrong for a scale: a reader compares the numbers
 * along an axis to each other, and two units in one row is a comparison they
 * have to do arithmetic for. The design's `0s 4s 8s 12s 16s 20s 24s` is one
 * unit, and the unit is a property of the axis rather than of any tick on it.
 *
 * Chosen from the **step**, not from the largest tick: an axis stepping in
 * hundreds of milliseconds is a millisecond axis even when it reaches four
 * seconds. `0` keeps the unit like every other tick, because a bare `0` beside
 * `5s` reads as a different kind of thing.
 *
 * No decimal place, and that is a fact about `axisTicks` rather than a taste:
 * its step is `[1, 2, 5, 10] * 10^n`, so a step of a second or more is always
 * a whole number of seconds. A `toFixed(1)` here would be a branch no input
 * can reach — the shape this repository has twice found dressed as a
 * safeguard. If the step rule ever changes, this is the line that has to.
 */
export function axisLabels(totalMs: number): readonly (readonly [number, string])[] {
  const ticks = axisTicks(totalMs);
  const step = ticks.length > 1 ? (ticks[1] ?? 0) - (ticks[0] ?? 0) : totalMs;
  if (step < 1000) return ticks.map((at) => [at, `${Math.round(at)}ms`] as const);
  return ticks.map((at) => [at, `${Math.round(at / 1000)}s`] as const);
}
