/**
 * `memory-and-replay` 50 — a fan-out has no single timeline.
 *
 * **Reproduced against a real run, not a hand-written one.**
 * `recordedFanOutRun.json` is 55.4 s of `stress-review` off
 * `POST /api/runs/stream` against `ollama:gpt-oss:120b-cloud`. Its supervisor
 * fanned out twice — `task-1` and `task-2` announced together at 5 060 ms,
 * then `task-1-1` and `task-1-2` together at 27 564 ms after the grader sent
 * the plan back — and all four children are labelled `impact-analyst`.
 *
 * What the run itself says happened, from the `spawn`/`settled` pairs:
 *
 * ```
 *   task-1     5 060 -> 20 947      task-1-1   27 564 -> 41 376
 *   task-2     5 060 -> 17 728      task-1-2   27 564 -> 40 122
 * ```
 *
 * Two pairs of children, each pair starting on the *same millisecond* and
 * overlapping for twelve seconds.
 *
 * What `buildTimeline` drew, before this module existed:
 *
 * ```
 *    7  impact-analyst  start 13 332  dur 4 396  visit 1  task-2
 *    8  impact-analyst  start 17 728  dur 3 219  visit 2  task-1
 *   12  impact-analyst  start 27 564  dur 12 558 visit 3  task-1-2
 *   13  impact-analyst  start 40 122  dur 1 254  visit 4  task-1-1
 * ```
 *
 * Four bars laid end to end, in a column read top to bottom, numbered
 * `visit 1..4` — which is this panel's badge for *a revise lap*. So the drawing
 * made two false claims at once: that four simultaneous workers ran one after
 * another, and that they were one worker running four times. It also started
 * the first of them eight seconds after it began and gave the longest-running
 * child (15.9 s) the shortest bar (3.2 s), because a span between whichever
 * frames arrived is not a duration.
 */
import { describe, expect, it } from 'vitest';
import { buildLanes, buildTimeline, type TimelineRow } from './timeline';
import recorded from './recordedFanOutRun.json';

/**
 * The captured wire frames as rows, exactly as `AskPanel` composes them.
 *
 * Three branches and no fourth, which is the whole of the mirroring: an
 * `update` becomes a row, a `spawn` becomes a row under its parent, and a
 * `settled` **closes the row its spawn opened** rather than adding one — it is
 * matched on `spawnId` and on nothing else, because the label is shared by all
 * four children here and `taskId` is `null` for a mount.
 */
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
          spawn: {
            ...open.spawn,
            outcome: frame.outcome as 'ok',
            settledMs: elapsedMs,
          },
        };
      }
    }
  }
  return rows;
}

const theRun = (): TimelineRow[] => rowsOf(recorded.frames as Record<string, unknown>[]);

/** The four children, by the id their orchestrator minted for them. */
const laneFor = (task: string) => buildLanes(theRun()).lanes.find((lane) => lane.taskId === task);

describe('the run said four workers ran at once, and now the model says so too', () => {
  it('gives every dispatched child a lane of its own, keyed on its spawn', () => {
    const { lanes } = buildLanes(theRun());

    expect(lanes.map((lane) => lane.key)).toEqual([
      'run',
      'spawn-1',
      'spawn-2',
      'spawn-4',
      'spawn-5',
    ]);
  });

  it('measures a child between its own two dated frames, not between arrivals', () => {
    // The reported symptom, in four numbers. `task-1` used to draw 3 219 ms.
    expect(laneFor('task-1')).toMatchObject({ startMs: 5060, endMs: 20_947, durationMs: 15_887 });
    expect(laneFor('task-2')).toMatchObject({ startMs: 5060, endMs: 17_728, durationMs: 12_668 });
    expect(laneFor('task-1-1')).toMatchObject({ startMs: 27_564, endMs: 41_376 });
    expect(laneFor('task-1-2')).toMatchObject({ startMs: 27_564, endMs: 40_122 });
  });

  it('lets the two children of one wave overlap, because they did', () => {
    const first = laneFor('task-1')!;
    const second = laneFor('task-2')!;

    expect(second.startMs).toBe(first.startMs);
    expect(second.endMs!).toBeLessThan(first.endMs!);
  });

  it('does not let a sibling’s bar carry a revise-lap number', () => {
    // `buildTimeline` counts a visit across the whole run, so the four
    // children came out `visit 1..4` — the panel's badge for a fourth lap of
    // one node. On its own lane each of them is the first and only lap.
    const children = buildLanes(theRun()).lanes.filter((lane) => lane.kind === 'fanout');

    expect(children.flatMap((lane) => lane.steps.map((step) => step.visit))).toEqual([1, 1, 1, 1]);
  });

  it('never calls a concurrent sibling a revise lap', () => {
    // `visit` is the badge for a second lap of one node. Four children with
    // one name used to carry visits 1..4; a lane says `2 of 2` instead, and
    // the two waves are two groups rather than one run of four.
    const children = buildLanes(theRun()).lanes.filter((lane) => lane.kind === 'fanout');

    expect(children.map((lane) => [lane.name, lane.sibling])).toEqual([
      ['impact-analyst', { index: 1, of: 2 }],
      ['impact-analyst', { index: 2, of: 2 }],
      ['impact-analyst', { index: 1, of: 2 }],
      ['impact-analyst', { index: 2, of: 2 }],
    ]);
  });

  it('moves a worker’s own step out of the run’s lane and onto its child’s', () => {
    const { lanes } = buildLanes(theRun());
    const run = lanes[0]!;

    expect(run.steps.every((step) => step.label !== 'impact-analyst')).toBe(true);
    expect(laneFor('task-1')!.steps.map((step) => step.taskId)).toEqual(['task-1']);
  });
});

describe('where a lane’s name comes from', () => {
  it('takes the name the run announced, never the compiler’s', () => {
    // Ticket 39's rule, applied at the source rather than reversed at the end:
    // `impact-analyst` is the archetype the orchestrator chose, carried on the
    // spawn frame. `safe_name` never touched it — `impact_analyst` appears
    // nowhere in this recording.
    const names = buildLanes(theRun()).lanes.map((lane) => lane.name);

    expect(names).toContain('impact-analyst');
    expect(names.some((name) => name.includes('_'))).toBe(false);
  });

  it('names the run’s own lane rather than leaving it anonymous', () => {
    expect(buildLanes(theRun()).lanes[0]).toMatchObject({ key: 'run', name: 'The workflow' });
  });

  it('falls back to the child’s own id, never to a bare counter', () => {
    // Ticket 40: `1` names nothing a reader can act on. A subtask with no
    // archetype arrives labelled with its own id, which is the string that
    // appears in `worker_results`, on the card chip and in the trace.
    const { lanes } = buildLanes([
      {
        node: 'lead',
        taskId: 'task-7',
        internal: false,
        elapsedMs: 10,
        spawn: { kind: 'fanout', label: 'task-7', instruction: '', spawnId: 's0' },
      },
    ]);

    expect(lanes[1]!.name).toBe('task-7');
  });
});

describe('a mount is not a fan-out, and the data says which is which', () => {
  it('folds a mounted workflow into the lane that runs it', () => {
    // Three `subgraph` spawns in this recording — `deep`, `worker` and the
    // two-level `audit` — and not one of them is a lane. A mount is one node
    // on the canvas; the parent blocks inside it.
    const { lanes } = buildLanes(theRun());

    expect(lanes.some((lane) => lane.name === 'audit')).toBe(false);
    expect(lanes[0]!.steps.map((step) => step.label)).toContain('audit');
  });

  it('leaves a revise lap in the run’s lane, where sequence is the truth', () => {
    // The grader ran twice and the supervisor ran twice. Both are the same
    // node reporting again — no spawn frame at all — so they stay bars in one
    // lane and keep the `visit` counter that says which lap they are.
    const run = buildLanes(theRun()).lanes[0]!;
    const graders = run.steps.filter((step) => step.label === 'grader');

    expect(graders.map((step) => step.visit)).toEqual([1, 2]);
  });
});

describe('a child that never ended does not draw a bar that did', () => {
  const open = (patch: Record<string, unknown>): TimelineRow[] => [
    {
      node: 'agent',
      taskId: 'call-1',
      internal: false,
      elapsedMs: 100,
      spawn: { kind: 'async', label: 'nightly-sweep', instruction: '', spawnId: 's0', ...patch },
    },
    { node: 'out1', taskId: null, internal: false, elapsedMs: 900 },
  ];

  it('reports no duration for a detached child, and never a zero', () => {
    const lane = buildLanes(open({ outcome: 'detached' })).lanes[1]!;

    expect(lane).toMatchObject({
      startMs: 100,
      endMs: null,
      durationMs: null,
      openEnded: true,
      ending: 'detached',
    });
  });

  it('keeps “nothing said yet” apart from “the run said it is still running”', () => {
    // Both are open-ended bars and they are different claims: one is a
    // recording that ended owing an account, the other is a child working on
    // its own desk. `ending` carries the difference; absent is its own state
    // and is not defaulted to a word.
    expect(buildLanes(open({})).lanes[1]).toMatchObject({ openEnded: true, ending: null });
    expect(buildLanes(open({ outcome: 'unknown' })).lanes[1]).toMatchObject({
      openEnded: true,
      ending: 'unknown',
    });
  });

  it('still tells the reader where the recording stopped', () => {
    // What a renderer needs to run an open bar to the edge and mark it there,
    // rather than inventing an end for it.
    expect(buildLanes(open({ outcome: 'detached' })).totalMs).toBe(900);
  });
});

describe('the sequential fold is untouched', () => {
  it('still folds the recording into the bars it always did', () => {
    // `buildLanes` partitions `buildTimeline`'s steps; it does not re-derive
    // them. Every bar the old fold produced is on exactly one lane.
    const rows = theRun();
    const { steps } = buildTimeline(rows);
    const { lanes } = buildLanes(rows);

    expect(lanes.flatMap((lane) => lane.steps).length).toBe(steps.length);
  });
});
