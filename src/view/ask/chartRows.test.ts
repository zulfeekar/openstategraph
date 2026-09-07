/**
 * `memory-and-replay` 64 — one row per node, and the gutter that says which
 * row is inside which.
 *
 * Read against `runLanes.test.ts`, which is the sibling and is not changed by
 * this ticket. That file asserts what the run **dispatched**; this one asserts
 * what the chart **draws**. `50` settled that a lane is an actor and a branch
 * is not one, and the run's own lane is therefore every top-level bar in
 * sequence — true, and not a drawing. The projection below is what turns it
 * into one, and it is a projection: every bar on a row is a bar on a lane.
 *
 * The recording is the same 55.4 s `stress-review` run, so the two files
 * cannot come to disagree about what ran.
 */
import { describe, expect, it } from 'vitest';
import { buildLanes, type RunLane, type TimelineRow } from './timeline';
import { axisLabels, axisTicks, chartRows } from './chartRows';
import recorded from './recordedFanOutRun.json';

function rowsOf(frames: readonly Record<string, unknown>[]): TimelineRow[] {
  const rows: TimelineRow[] = [];
  const bySpawn = new Map<string, number>();
  for (const frame of frames) {
    const elapsedMs = frame.elapsedMs as number;
    if (frame.type === 'update') {
      rows.push({
        node: frame.node as string,
        taskId: (frame.taskId as string | null) ?? null,
        internal: frame.internal === true,
        namespace: frame.namespace as string[],
        activeNode: frame.activeNode as string,
        elapsedMs,
      });
    } else if (frame.type === 'spawn') {
      bySpawn.set(frame.spawnId as string, rows.length);
      rows.push({
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
      });
    } else if (frame.type === 'settled') {
      const at = bySpawn.get(frame.spawnId as string);
      const open = at === undefined ? undefined : rows[at];
      if (at !== undefined && open?.spawn) {
        rows[at] = {
          ...open,
          spawn: { ...open.spawn, outcome: frame.outcome as 'ok', settledMs: elapsedMs },
        };
      }
    }
  }
  return rows;
}

const theRun = (): TimelineRow[] => rowsOf(recorded.frames as Record<string, unknown>[]);
const drawn = (): readonly { name: string; depth: number }[] =>
  chartRows(buildLanes(theRun()).lanes).map((row) => ({ name: row.name, depth: row.depth }));

describe('the chart draws a row per node, where it used to draw one row', () => {
  it('names every node of the run down the left, in the order it was first heard from', () => {
    // The reported symptom. Every one of these was a bar crowded onto a single
    // row called `The workflow`, and the name of the node that ran it appeared
    // only inside the bar, where a bar 5 ms wide has no room for it.
    expect(
      drawn()
        .filter((row) => row.depth === 0)
        .map((row) => row.name),
    ).toEqual(['in1', 'router', 'deep', 'lead', 'out2', 'join', 'grader', 'audit', 'out1']);
  });

  it('keeps a revise lap on the node’s own row, because it is the same node', () => {
    // `lead`, `join` and `grader` each ran twice. Two bars on one row is what
    // a lap looks like; two rows would say the graph had two of them.
    const rows = chartRows(buildLanes(theRun()).lanes);

    expect(rows.find((row) => row.name === 'grader')?.steps.map((step) => step.visit)).toEqual([
      1, 2,
    ]);
  });

  it('indents a dispatched child under the node that announced it', () => {
    // The four `impact-analyst` children were announced by `lead` at 5 060 ms
    // and 27 564 ms. They sit under `lead`, not beside it and not at the end.
    //
    // The `model` rows are `memory-and-replay` 66's, and this test is the one
    // that had to change for it, so the ordering rule is stated where it can
    // be checked: a node's **own** work is drawn directly under it, and a
    // child the run **dispatched** comes after — `lead`'s `model` row above
    // its four analysts. They are indented the same way and are not the same
    // thing, which is why `ChartRow.event` is a word rather than a depth.
    //
    // This recording predates `55`, so it carries no `invoked` frame and
    // therefore no tool row. Its model rows are still here, which is the
    // point: the two halves of 66 fail independently.
    expect(drawn()).toEqual([
      { name: 'in1', depth: 0 },
      { name: 'router', depth: 0 },
      { name: 'deep', depth: 0 },
      { name: 'model', depth: 1 },
      { name: 'lead', depth: 0 },
      { name: 'impact-analyst', depth: 1 },
      { name: 'model', depth: 2 },
      { name: 'impact-analyst', depth: 1 },
      { name: 'model', depth: 2 },
      { name: 'impact-analyst', depth: 1 },
      { name: 'model', depth: 2 },
      { name: 'impact-analyst', depth: 1 },
      { name: 'model', depth: 2 },
      { name: 'out2', depth: 0 },
      { name: 'join', depth: 0 },
      { name: 'grader', depth: 0 },
      { name: 'audit', depth: 0 },
      { name: 'model', depth: 1 },
      { name: 'out1', depth: 0 },
    ]);
  });

  it('draws a mount as a bar on its node’s row and never as a row', () => {
    // `50`'s table, unchanged: a mount is one node on the canvas, so `deep`
    // and `audit` are hatched bars at the length their own two dated frames
    // give them. A row for each would claim a shape the fold does not produce.
    const rows = chartRows(buildLanes(theRun()).lanes);
    const audit = rows.find((row) => row.name === 'audit');

    expect(audit?.depth).toBe(0);
    expect(audit?.steps.map((step) => step.kind)).toEqual(['mount']);
  });

  it('is a projection of the lanes, not a second derivation of them', () => {
    // Every bar on exactly one lane, and now on exactly one row. The two
    // cannot come to disagree about what ran, because the rows hold the lanes'
    // own steps.
    //
    // `event` rows are excluded and that is not a loosening: an event row
    // holds bars that live **inside** a lane's steps (`TimelineStep.events`,
    // `memory-and-replay` 66), so it is a projection of the same fold one
    // level down rather than a second reading of the frames. The property this
    // test protects — that nothing on the chart was derived a second time —
    // is asserted for those in `stepEvents.test.ts`, against the run that has
    // any.
    const { lanes } = buildLanes(theRun());
    const onLanes = lanes.flatMap((lane) => lane.steps.map((step) => step.key));
    const onRows = chartRows(lanes)
      .filter((row) => !row.event)
      .flatMap((row) => row.steps.map((step) => step.key));

    expect([...onRows].sort()).toEqual([...onLanes].sort());
  });

  it('marks the rows that are a whole lane, and only those', () => {
    // A settled tick and an open-ended strip belong to a lane the run
    // announced and closed. A node row is a slice of the run's own lane,
    // whose end is the recording's end — drawing a `settled` tick there would
    // say the run closed something it never announced.
    const rows = chartRows(buildLanes(theRun()).lanes);

    expect(rows.filter((row) => row.whole).map((row) => row.key)).toEqual([
      'spawn-1',
      'spawn-2',
      'spawn-4',
      'spawn-5',
    ]);
  });
});

describe('depth comes from the run, and is never guessed', () => {
  const lane = (patch: Partial<RunLane>): RunLane => ({
    key: 'spawn-x',
    name: 'child',
    kind: 'subagent',
    parent: null,
    taskId: null,
    startMs: 0,
    endMs: null,
    durationMs: null,
    openEnded: true,
    ending: null,
    sibling: null,
    instruction: null,
    steps: [],
    ...patch,
  });

  it('puts a child whose parent this run never drew at the top level', () => {
    // Not under an invented row, and not dropped. The run named a parent this
    // recording has no bar for; the honest drawing is a row with no gutter.
    const rows = chartRows([
      lane({ key: 'run', kind: 'run', name: 'The workflow', steps: [] }),
      lane({ parent: 'a-node-that-never-reported' }),
    ]);

    expect(rows.map((row) => [row.name, row.depth])).toEqual([['child', 0]]);
  });

  it('resolves a nested child under the row that was open, not its namesake', () => {
    // Two rows carry a bar labelled `worker`: a top-level one early in the run
    // and a dispatched child's own later on. A subagent announced by `worker`
    // at 900 ms belongs under the second, because that is the one that was
    // open when the run announced it.
    const rows = buildLanes([
      { node: 'worker', taskId: null, internal: false, elapsedMs: 100 },
      {
        node: 'worker',
        taskId: 't1',
        internal: false,
        elapsedMs: 200,
        spawn: { kind: 'fanout', label: 'desk', instruction: '', spawnId: 's1' },
      },
      { node: 'worker', taskId: 't1', internal: false, elapsedMs: 800 },
      {
        node: 'worker',
        taskId: 't1',
        internal: false,
        elapsedMs: 900,
        spawn: { kind: 'subagent', label: 'checker', instruction: '', spawnId: 's2' },
      },
      { node: 'out1', taskId: null, internal: false, elapsedMs: 1000 },
    ]);

    expect(chartRows(rows.lanes).map((row) => [row.name, row.depth])).toEqual([
      ['worker', 0],
      ['desk', 1],
      ['checker', 2],
      ['out1', 0],
    ]);
  });
});

describe('the axis is the row model’s, not the renderer’s', () => {
  it('lands on round offsets a reader can add up', () => {
    expect(axisTicks(24_100)).toEqual([0, 5000, 10_000, 15_000, 20_000]);
  });

  it('gives a run with no length a single tick rather than an empty loop', () => {
    expect(axisTicks(0)).toEqual([0]);
  });
});

describe('the axis reads in one unit', () => {
  it('picks the unit from the step, so no two ticks are in different ones', () => {
    // `memory-and-replay` 68. The shipped axis read `0 ms · 5.0 s · 10.0 s`,
    // because each tick went through `formatMs`, which switches unit at a
    // second. A reader compares an axis's numbers to each other.
    expect(axisLabels(24_100).map(([, label]) => label)).toEqual(['0s', '5s', '10s', '15s', '20s']);
    // A sub-second run is a millisecond axis all the way across, including
    // the tick that happens to be a round second.
    expect(axisLabels(900).map(([, label]) => label)).toEqual([
      '0ms',
      '200ms',
      '400ms',
      '600ms',
      '800ms',
    ]);
    // Never a decimal place, because `axisTicks` steps in `[1,2,5,10]·10^n`
    // and a step of a second or more is therefore whole seconds. This is the
    // assertion that would fail if the step rule changed under `axisLabels`.
    expect(
      [900, 2_400, 12_000, 24_100, 300_000].every((total) =>
        axisLabels(total).every(([, label]) => !label.includes('.')),
      ),
    ).toBe(true);
  });

  it('labels exactly the ticks the axis has', () => {
    expect(axisLabels(24_100).map(([at]) => at)).toEqual([...axisTicks(24_100)]);
  });
});
