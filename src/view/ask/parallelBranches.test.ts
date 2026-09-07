/**
 * `memory-and-replay` 57 — two top-level branches run at once.
 *
 * 50 gave a *dispatched child* a lane because a `spawn` frame announces it and
 * a `settled` frame closes it. It left the third source of concurrency in the
 * same recording out of reach: `stress-review`'s classifier router matched
 * **both** desks in one superstep, so the `deep` mount ran from 2 775 ms to
 * 13 317 ms while the supervisor branch was already working.
 *
 * What the panel drew:
 *
 * ```
 *    3  deep    start  2 775  dur 2 285  visit 1
 *    4  lead    start  5 060  dur     0  visit 1
 *    5  deep    start  5 060  dur 8 257  visit 2
 * ```
 *
 * `lead`'s completion frame landed in the middle of the mount, so the mount
 * came out as two bars badged `×2` — this panel's badge for *a revise lap*.
 * A mount that ran once was drawn as a node that ran twice, which is the same
 * false claim 50 removed for children, arriving by a different road.
 *
 * The finding this test pins: **the run already said so.** A mount is
 * announced by a `subgraph` spawn and closed by a `settled`, both dated by 46
 * — the identical pair 50 leaned on. Nothing new is needed on the wire for
 * the mount half, and a bar built from that pair overlaps the supervisor's
 * bar honestly instead of being cut in two by it.
 *
 * Built against the captured run, not against frames written by hand.
 */
import { describe, expect, it } from 'vitest';
import { caveatFor } from './RunTimeline';
import { buildTimeline, type TimelineRow } from './timeline';
import recorded from './recordedFanOutRun.json';

/** The captured wire frames as rows, exactly as `runLanes.test.ts` composes them. */
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
const barsCalled = (label: string) =>
  buildTimeline(theRun()).steps.filter((s) => s.label === label);

describe('a mount on a parallel branch is one bar, and the run dated both its ends', () => {
  it('draws the mount once, not once per interruption', () => {
    // The reported symptom: `deep` came out twice, `visit 1` and `visit 2`,
    // because `lead` reported in the middle of it.
    expect(barsCalled('deep')).toHaveLength(1);
    expect(barsCalled('deep')[0]!.visit).toBe(1);
  });

  it('measures the mount between its own spawn and settled, not between arrivals', () => {
    // spawn-0: 2 775 -> 13 317, both dated by 46, joined by 54's `spawnId`.
    expect(barsCalled('deep')[0]).toMatchObject({
      startMs: 2775,
      durationMs: 10_542,
      measured: true,
    });
  });

  it('says the mount and the supervisor branch overlapped', () => {
    const deep = barsCalled('deep')[0]!;
    const lead = barsCalled('lead')[0]!;

    expect(deep.concurrent).toContain(lead.key);
    expect(lead.concurrent).toContain(deep.key);
  });

  it('claims nothing about overlap where the run ran one thing at a time', () => {
    // `audit` is a mount too, and a measured one — but it is the only thing
    // running at 44 647 ms, so no bar names it and it names none.
    const audit = barsCalled('audit')[0]!;

    expect(audit).toMatchObject({ startMs: 44_647, durationMs: 7845, measured: true });
    expect(audit.concurrent).toEqual([]);
  });

  it('leaves a revise lap counted as a lap, because that one really is sequence', () => {
    // The supervisor ran twice — the grader sent the plan back. Two bars, and
    // `visit 2` on the second is the truth about it. `visit` still means
    // sequence and nothing here widens it (50's line, and 57 falls on the
    // same side of it).
    expect(barsCalled('lead').map((s) => s.visit)).toEqual([1, 2]);
    expect(barsCalled('lead')[1]!.concurrent).toEqual([]);
  });

  it('leaves an ordinary span-attributed bar saying it was not measured', () => {
    // The residual, stated rather than papered over: a branch made only of
    // ordinary nodes still has no start on this wire. `lead` is one, and its
    // bar says so.
    expect(barsCalled('lead')[0]!.measured).toBe(false);
  });
});

describe('the line under the bars stays true of every bar above it', () => {
  it('stops saying no bar is measured once one of them is', () => {
    const { steps, totalMs } = buildTimeline(theRun());

    expect(caveatFor(steps, totalMs)).toContain('except where the run dated both ends');
  });

  it('keeps the flat claim for a run in which nothing was dated at both ends', () => {
    expect(caveatFor([{ measured: false }], 1000)).toBe(
      'Server time, measured between stream frames — not a measured start and end.',
    );
  });

  it('says nothing about spans at all when the run reported no clock', () => {
    expect(caveatFor([{ measured: true }], null)).toContain('no clock');
  });
});
