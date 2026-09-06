import { describe, expect, it } from 'vitest';
import { buildLanes, buildTimeline, laneFold, overlappingBars, type TimelineRow } from './timeline';
import { reusableFold } from './incrementalFold';
import recorded from './recordedFanOutRun.json';
import { traceFold, type ActivityRow } from './traceTree';

/**
 * The two quadratics of `the-cost-of-one-more/04`, counted rather than timed.
 *
 * **Operations, never seconds.** A wall-clock assertion is flaky on a shared
 * machine and a flaky gate gets suppressed, and the claim worth defending here
 * is the complexity class rather than this laptop. Both counts below are
 * deterministic functions of the input, so they are asserted exactly wherever
 * an exact number exists — which is stronger than a ratio and says more.
 *
 * The instrument is checked against the *old* shape in the same file, which is
 * the anti-vacuity control this repository asks for: a meter that could not see
 * the quadratic it was built for would make every assertion beside it a
 * statement about nothing.
 */

/** Counts every indexed read of an array — how a fold visits a row. */
function counted<T>(rows: readonly T[]): { rows: readonly T[]; visits: () => number } {
  let visits = 0;
  const proxy = new Proxy(rows as T[], {
    get(target, property, receiver) {
      if (typeof property === 'string' && /^\d+$/.test(property)) visits += 1;
      return Reflect.get(target, property, receiver);
    },
  });
  return { rows: proxy, visits: () => visits };
}

/** A run of `n` frames of the shape the wire produces: one bar per twenty. */
function frames(n: number): TimelineRow[] {
  const rows: TimelineRow[] = [];
  for (let index = 0; index < n; index += 1) {
    const bar = Math.floor(index / 20);
    rows.push(
      index % 20 === 19
        ? { node: `node:step${bar}`, taskId: null, internal: false, elapsedMs: index * 10 }
        : {
            node: 'model',
            taskId: null,
            internal: true,
            activeNode: `node:step${bar}`,
            elapsedMs: index * 10,
          },
    );
  }
  return rows;
}

/** The same run as the trace view sees it. */
function activity(n: number): ActivityRow[] {
  return frames(n).map((row) => ({
    node: row.node,
    taskId: row.taskId,
    internal: row.internal,
    durationMs: 10,
    output: null,
    activeNode: row.activeNode ?? null,
  })) as ActivityRow[];
}

/**
 * The live loop as `AskPanel` runs it: a frame arrives, the array is rebuilt,
 * and whoever is reading it folds what there is. `fold` is the seam under test.
 */
function foldPerFrame<Row, Out>(all: readonly Row[], fold: (rows: readonly Row[]) => Out): number {
  let total = 0;
  for (let length = 1; length <= all.length; length += 1) {
    const prefix: Row[] = [];
    for (let index = 0; index < length; index += 1) prefix.push(all[index] as Row);
    const meter = counted(prefix);
    fold(meter.rows);
    total += meter.visits();
  }
  return total;
}

describe('the fold is paid once per frame, not once per frame per frame', () => {
  const N = 300;

  it('refolding the whole run on every frame visits every row again — the defect', () => {
    // The control. `1 + 2 + ... + N`, exactly, because the count is arithmetic
    // rather than a measurement. If this ever stops being quadratic the meter
    // has broken, not the fold.
    expect(foldPerFrame(frames(N), buildTimeline)).toBe((N * (N + 1)) / 2);
  });

  it('folds each timeline row once across the whole run', () => {
    const fold = reusableFold(laneFold);

    // N reads for the rows themselves plus at most one per call to check that
    // the array it was handed extends the one it already consumed.
    expect(foldPerFrame(frames(N), fold)).toBeLessThanOrEqual(2 * N);
  });

  it('folds each trace row once across the whole run', () => {
    const fold = reusableFold(traceFold);

    expect(foldPerFrame(activity(N), fold)).toBeLessThanOrEqual(2 * N);
  });

  it('is still linear when the run doubles', () => {
    const small = foldPerFrame(frames(N), reusableFold(laneFold));
    const large = foldPerFrame(frames(2 * N), reusableFold(laneFold));

    expect(large).toBeLessThan(small * 2.5);
  });

  it('re-answers without re-reading when the same array comes back', () => {
    // React renders twice under StrictMode, and a run that has ended still
    // re-renders. Neither may re-consume a row.
    const fold = reusableFold(laneFold);
    const meter = counted(frames(100));

    fold(meter.rows);
    const once = meter.visits();
    fold(meter.rows);
    fold(meter.rows);

    expect(meter.visits()).toBeLessThanOrEqual(once + 2);
  });

  it('starts again when the array it is given is a different run', () => {
    const fold = reusableFold(laneFold);
    fold(frames(100));

    // A stored run opened in the dock is not a continuation of the live one.
    expect(fold(frames(40))).toEqual(buildLanes(frames(40)));
  });
});

describe('overlapping bars are found by a sweep, not by every pair', () => {
  /** Bars laid end to end — the ordinary case, and the one with no output. */
  function bars(n: number): { key: string; startMs: number | null; durationMs: number | null }[] {
    return Array.from({ length: n }, (_, index) => ({
      key: `bar#${index}`,
      startMs: index * 10,
      durationMs: 10,
    }));
  }

  /** Counts how many times a bar's window is looked at. */
  function watched(
    steps: readonly { key: string; startMs: number | null; durationMs: number | null }[],
  ): {
    steps: readonly { key: string; startMs: number | null; durationMs: number | null }[];
    reads: () => number;
  } {
    let reads = 0;
    const watchedSteps = steps.map((step) => ({
      key: step.key,
      get startMs() {
        reads += 1;
        return step.startMs;
      },
      get durationMs() {
        return step.durationMs;
      },
    }));
    return { steps: watchedSteps, reads: () => reads };
  }

  it('does not quadruple the work when the bar count doubles', () => {
    const small = watched(bars(500));
    overlappingBars(small.steps);
    const large = watched(bars(1000));
    overlappingBars(large.steps);

    expect(large.reads()).toBeLessThan(small.reads() * 2.5);
  });

  it('finds exactly the pairs the every-pair comparison finds', () => {
    // Differential, on random windows, because the sweep is a different
    // algorithm and not a tidier spelling of the same loop. Same rule
    // `the-cost-of-one-more/03` applied to `capacityRule`.
    const pairwise = (
      steps: readonly { key: string; startMs: number | null; durationMs: number | null }[],
    ): string[][] => {
      const found: string[][] = steps.map(() => []);
      const endOf = (step: { startMs: number | null; durationMs: number | null }): number =>
        (step.startMs ?? 0) + (step.durationMs ?? 0);
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
      return found;
    };

    let seed = 7;
    const random = (): number => {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      return seed / 2147483648;
    };

    for (let trial = 0; trial < 200; trial += 1) {
      const steps = Array.from({ length: 1 + Math.floor(random() * 30) }, (_, index) => ({
        key: `b${index}`,
        startMs: random() < 0.1 ? null : Math.floor(random() * 100),
        durationMs: random() < 0.1 ? null : Math.floor(random() * 40),
      }));

      expect(overlappingBars(steps)).toEqual(pairwise(steps));
    }
  });
});

/**
 * The differential, on a real run rather than on generated frames.
 *
 * `recordedFanOutRun.json` is 55.4 s of `stress-review` — 128 of its frames
 * are ones this fold consumes, a
 * supervisor that fanned out twice, seven `settled` frames, four of which close a
 * child lane. It is replayed here **the way `AskPanel` composes it**, which is the
 * part that matters: an `update` and a `spawn` append, and a `settled` runs
 * `activity.map(closed)`, returning a new array of the same length with one
 * row in the middle rewritten. That last shape is the one an incremental fold
 * can silently get wrong, and it is the one this run has four of.
 *
 * Asserted at **every prefix**, not only at the end: the panel draws each of
 * them, so each of them has to be the answer the pure fold gives.
 */
describe('the incremental fold answers what the pure fold answers', () => {
  /** The run, as a snapshot of the rows after each arriving frame. */
  function snapshots(): TimelineRow[][] {
    const frames = recorded.frames as Record<string, unknown>[];
    const bySpawn = new Map<string, string>();
    let rows: TimelineRow[] = [];
    const taken: TimelineRow[][] = [];
    for (const frame of frames) {
      const elapsedMs = frame.elapsedMs as number;
      if (frame.type === 'update') {
        rows = [
          ...rows,
          {
            node: frame.node as string,
            taskId: (frame.taskId as string | null) ?? null,
            internal: frame.internal === true,
            namespace: frame.namespace as string[],
            activeNode: frame.activeNode as string,
            elapsedMs,
          },
        ];
      } else if (frame.type === 'spawn') {
        bySpawn.set(frame.spawnId as string, frame.spawnId as string);
        rows = [
          ...rows,
          {
            node: frame.parent as string,
            taskId: (frame.taskId as string | null) ?? null,
            internal: false,
            namespace: frame.namespace as string[],
            elapsedMs,
            spawn: {
              kind: frame.kind as string,
              label: frame.label as string,
              instruction: '',
              spawnId: frame.spawnId as string,
            },
          },
        ];
      } else if (frame.type === 'settled') {
        // `AskPanel`'s own `closed`: same array length, one row replaced, every
        // other row the identical object.
        rows = rows.map((row) =>
          row.spawn && row.spawn.spawnId === frame.spawnId
            ? {
                ...row,
                spawn: { ...row.spawn, outcome: frame.outcome as 'ok', settledMs: elapsedMs },
              }
            : row,
        );
      } else {
        continue;
      }
      taken.push(rows);
    }
    return taken;
  }

  it('agrees at every frame of a recorded run, settled frames included', () => {
    const fold = reusableFold(laneFold);
    const run = snapshots();

    // Anti-vacuity: a replay that produced no `settled` rewrite would prove
    // only the easy half, and the rewrite is the half that can go wrong.
    expect(run.length).toBeGreaterThan(100);
    expect(
      run.filter(
        (rows, index) => index > 0 && rows.length === (run[index - 1] as TimelineRow[]).length,
      ),
    ).toHaveLength(7);

    for (const rows of run) expect(fold(rows)).toEqual(buildLanes(rows));
  });

  it('closes a child lane on the frame that settles it, not never', () => {
    // The regression the witness in `reusableFold` exists to stop, said in the
    // vocabulary of the surface: a lane whose `settled` arrived is a lane with
    // an end, and one whose fold ignored the rewrite would run to the right
    // edge for ever.
    const fold = reusableFold(laneFold);
    const run = snapshots();
    for (const rows of run) fold(rows);

    const children = fold(run[run.length - 1] as TimelineRow[]).lanes.filter(
      (lane) => lane.key !== 'run',
    );

    expect(children).toHaveLength(4);
    expect(children.every((lane) => lane.openEnded)).toBe(false);
    expect(children.map((lane) => lane.endMs)).toEqual(
      buildLanes(run[run.length - 1] as TimelineRow[])
        .lanes.filter((lane) => lane.key !== 'run')
        .map((lane) => lane.endMs),
    );
  });
});
