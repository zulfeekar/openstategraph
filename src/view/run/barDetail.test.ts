/**
 * What the detail pane may say about a bar, and what it must say `—` to.
 *
 * `launch-readiness` 108's rule, applied one level up: a renderer must be able
 * to tell *instant* from *unknown*, and so must a reader.
 */
import { describe, expect, it } from 'vitest';
import { barFacts, formatMs, laneCaption } from './barDetail';
import { buildLanes, type RunLane, type TimelineStep } from '../ask/timeline';

const value = (lane: RunLane, step: TimelineStep, term: string): string =>
  barFacts(lane, step).find((fact) => fact.term === term)?.value ?? '';

const laneOf = (rows: Parameters<typeof buildLanes>[0], index: number): RunLane =>
  buildLanes(rows).lanes[index]!;

describe('a bar nobody timed', () => {
  it('reads as a dash and never as zero', () => {
    expect(formatMs(null)).toBe('—');
    expect(formatMs(0)).toBe('0 ms');
  });

  it('says so in every field a number would have gone in', () => {
    const lane = laneOf(
      [
        { node: 'in1', taskId: null, internal: false },
        { node: 'out1', taskId: null, internal: false },
      ],
      0,
    );
    const step = lane.steps[0]!;
    expect(value(lane, step, 'Opened')).toBe('—');
    expect(value(lane, step, 'Closed')).toBe('—');
    expect(value(lane, step, 'Span')).toBe('—');
  });
});

describe('a lane the run never closed', () => {
  const open = (outcome?: 'detached' | 'unknown' | 'error'): RunLane =>
    laneOf(
      [
        {
          node: 'lead',
          taskId: 'task-1',
          internal: false,
          elapsedMs: 100,
          spawn: {
            kind: 'fanout',
            label: 'analyst',
            instruction: '',
            spawnId: 's1',
            ...(outcome ? { outcome } : {}),
          },
        },
        { node: 'out1', taskId: null, internal: false, elapsedMs: 900 },
      ],
      1,
    );

  it('never claims an end, and says which kind of open it is', () => {
    // Three different facts about the *recording*, and never one word for all
    // of them — none of which is a failure, and none of which gets a number.
    // A bar on that lane whose end the run never dated. Written out rather
    // than folded, because the point is the *pane*: the same missing end has
    // to read as four different facts about the recording.
    const step: TimelineStep = {
      key: 'analyst#1',
      label: 'analyst',
      taskId: 'task-1',
      order: 1,
      startMs: 100,
      durationMs: null,
      count: 1,
      internalSteps: 0,
      kind: 'tool',
      modelCalls: 0,
      toolCalls: 0,
      namespace: null,
      visit: 1,
      measured: false,
      payload: { output: null, check: null, reason: null },
      concurrent: [],
    };
    expect(value(open('detached'), step, 'Closed')).toMatch(/still running/);
    expect(value(open('unknown'), step, 'Closed')).toMatch(/owing an account/);
    expect(value(open('error'), step, 'Closed')).toBe('never ran');
    expect(value(open(), step, 'Closed')).toBe('not yet');
  });

  it('names overlapping namesakes so a fan-out is not four readings of one worker', () => {
    expect(laneCaption({ ...open(), sibling: { index: 2, of: 3 } })).toBe('analyst 2 of 3');
    expect(laneCaption(open())).toBe('analyst');
  });
});

describe('a bar that was dated at both ends', () => {
  it('says which claim it is making, because the two are not the same claim', () => {
    const lane = laneOf(
      [
        { node: 'in1', taskId: null, internal: false, elapsedMs: 100 },
        { node: 'out1', taskId: null, internal: false, elapsedMs: 900 },
      ],
      0,
    );
    expect(value(lane, lane.steps[0]!, 'Ends')).toMatch(/not a measured start and end/);
  });

  it('calls concurrency a floor and never a ceiling', () => {
    const lane = laneOf(
      [
        { node: 'in1', taskId: null, internal: false, elapsedMs: 100 },
        { node: 'out1', taskId: null, internal: false, elapsedMs: 900 },
      ],
      0,
    );
    const step = { ...lane.steps[0]!, concurrent: ['other#1'] };
    expect(value(lane, step, 'Alongside')).toMatch(/^at least 1 other bar$/);
  });
});
