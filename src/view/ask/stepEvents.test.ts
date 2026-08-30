/**
 * `memory-and-replay` 66 — every execution inside a node is a bar somewhere.
 *
 * The recording is a real 29.1 s `chinook-assistant` run on
 * `ollama:gpt-oss:120b-cloud`, captured off `/api/runs/stream` at audience
 * `developer` and trimmed to the frames a chart reads: the 93 `update` frames,
 * the 14 `invoked` frames and the 14 `token` frames that carry a tool's result.
 * The 372 `ai` token frames are dropped because no bar is built from one.
 *
 * It is the run the owner was looking at when they asked *"where are the tool
 * calls"*, so the numbers below are that question's answer and not a fixture
 * built to pass.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { buildLanes, buildTimeline, type TimelineRow } from './timeline';
import { chartRows } from './chartRows';
import { runProfile } from '../run/runProfile';
import recorded from './recordedToolLoopRun.json';

function rowsOf(frames: readonly Record<string, unknown>[]): TimelineRow[] {
  const rows: TimelineRow[] = [];
  for (const frame of frames) {
    const elapsedMs = frame.elapsedMs as number;
    const shared = {
      node: frame.node as string,
      taskId: null,
      namespace: frame.namespace as string[],
      activeNode: frame.activeNode as string,
      elapsedMs,
    };
    if (frame.type === 'update') {
      rows.push({
        ...shared,
        internal: frame.internal === true,
        output: (frame.output as string | null) ?? null,
      });
    } else if (frame.type === 'invoked') {
      rows.push({
        ...shared,
        internal: true,
        tool: { name: frame.name as string, callId: frame.callId as string, phase: 'invoked' },
      });
    } else if (frame.type === 'token') {
      const tool = frame.tool as { name: string; callId: string };
      rows.push({
        ...shared,
        internal: true,
        output: frame.content as string,
        tool: { name: tool.name, callId: tool.callId, phase: 'result' },
      });
    }
  }
  return rows;
}

const ROWS = rowsOf(recorded as unknown as Record<string, unknown>[]);
const TIMELINE = buildTimeline(ROWS);
const ROWS_DRAWN = chartRows(buildLanes(ROWS).lanes);
// The agent ran four laps, so it has four bars; its events are the union.
const AGENT = TIMELINE.steps
  .filter((step) => step.label === 'agent-sql')
  .flatMap((step) => step.events);

describe('what the run recorded as having executed', () => {
  it('pairs each tool call with its own result frame, on the two offsets the run stamped', () => {
    const calls = AGENT.filter((event) => event.kind === 'tool');
    expect(calls).toHaveLength(14);
    // The first three, verbatim from the wire: invoked at 2618 ms, its result
    // frame at 2625 ms. Both stamps are the server's own, so this bar is
    // `measured` in `57`'s sense rather than a span between arrivals.
    expect(calls[0]).toMatchObject({
      label: 'chinook_list_tables',
      startMs: 2618,
      durationMs: 7,
      measured: true,
    });
    expect(calls[1]).toMatchObject({
      label: 'chinook_get_table_schema',
      startMs: 3782,
      durationMs: 6,
      measured: true,
    });
    expect(calls.every((call) => call.measured)).toBe(true);
  });

  it('keeps what each call returned, so a selected bar has something to show', () => {
    const first = AGENT.find((event) => event.kind === 'tool');
    expect(first?.payload.output).toContain('| Table | Rows |');
  });

  it('draws a model call as a span and says so, because only its end is stamped', () => {
    const models = AGENT.filter((event) => event.kind === 'model');
    expect(models).toHaveLength(17);
    expect(models.every((model) => model.measured)).toBe(false);
    // Nothing on the wire attributes prose to one model call, and an empty
    // quotation would read as a call that produced nothing.
    expect(models.every((model) => model.payload.output === null)).toBe(true);
  });

  it('charges every event to the node the run said was active, not to whichever bar was open', () => {
    const elsewhere = TIMELINE.steps.filter(
      (step) => step.label !== 'agent-sql' && step.events.length > 0,
    );
    expect(elsewhere).toEqual([]);
  });

  it('leaves the bars and the run total exactly where they were', () => {
    // An event is an annotation on frames the fold already read; it must not
    // move the clock, or every duration on the chart changes underneath a
    // ticket that promised only to add rows.
    const without = buildTimeline(ROWS.filter((row) => row.tool === undefined));
    expect(TIMELINE.totalMs).toBe(without.totalMs);
    expect(TIMELINE.steps.map((step) => [step.label, step.durationMs])).toEqual(
      without.steps.map((step) => [step.label, step.durationMs]),
    );
  });
});

describe('a row is an identity and a bar is an occurrence', () => {
  const under = (name: string) => {
    const at = ROWS_DRAWN.findIndex((row) => row.name === name);
    const depth = ROWS_DRAWN[at]?.depth ?? 0;
    const after = ROWS_DRAWN.slice(at + 1);
    const ends = after.findIndex((row) => row.depth <= depth);
    return ends === -1 ? after : after.slice(0, ends);
  };

  it('gives one row per distinct component and one bar per time it ran', () => {
    // Fourteen calls across three tools are three rows, not fourteen — and
    // not one row with fourteen bars laid over each other.
    expect(under('agent-sql').map((row) => [row.name, row.steps.length])).toEqual([
      ['model', 17],
      ['chinook_list_tables', 4],
      ['chinook_get_table_schema', 10],
    ]);
  });

  it('indents them under the row of the node whose loop ran them', () => {
    const agent = ROWS_DRAWN.find((row) => row.name === 'agent-sql');
    expect(under('agent-sql').every((row) => row.depth === (agent?.depth ?? 0) + 1)).toBe(true);
  });

  it('grows no row for a node that recorded no event', () => {
    expect(under('in1')).toEqual([]);
    expect(ROWS_DRAWN.map((row) => row.name).filter((name) => name === 'in1')).toHaveLength(1);
  });

  it('never lets an event row carry a lane’s settled tick', () => {
    expect(under('agent-sql').every((row) => row.whole === false)).toBe(true);
  });
});

describe('the strip counts what the chart draws', () => {
  it('reports the calls the run made, not the laps its loop took', () => {
    const profile = runProfile(buildLanes(ROWS));
    // Every bar an event row draws, counted off the chart the reader sees.
    const drawn = ROWS_DRAWN.filter((row) => row.event).flatMap((row) => row.steps);
    // Not a dash: this recording carries `invoked` frames, so the run said
    // how many calls it made. `barVocabulary.test.ts` holds the other case.
    expect(profile.toolCalls).toBe(14);
    expect(drawn.filter((bar) => bar.kind === 'tool')).toHaveLength(14);
    expect(drawn.filter((bar) => bar.kind === 'model')).toHaveLength(profile.modelCalls);
  });
});

describe('an event bar does not repeat its own row', () => {
  it('is drawn unnamed, because the row is already the name', () => {
    // Seen live on a run whose agent made twelve model calls: the row read
    // `model model mo mo mod mo model ×7 model` — twelve clipped copies of a
    // word already printed in the gutter, and a `×7` counting occurrences of
    // the only thing that row contains. A node row keeps its labels: its bars
    // can each be different work.
    const chart = readFileSync(
      fileURLToPath(new URL('./RunTimeline.tsx', import.meta.url)),
      'utf8',
    );
    expect(chart).toMatch(/named=\{!row\.event\}/);
    expect(chart).toMatch(/\{named \? \(/);
  });
});
