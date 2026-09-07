/**
 * `launch-readiness` 108 — the timeline showed `agent1 0ms` beside `in1 21.4s`.
 *
 * **The defect is in this fold, not on the wire**, and the frames say so.
 * Captured server-side from a live `chinook-assistant` run (`gpt-oss:120b-cloud`,
 * 38.4 s, 296 frames, every one carrying the server clock `memory-and-replay`
 * 46 mints), the run reads:
 *
 * ```
 *   in1        0.01 s      router1   1.19 s
 *   agent-sql 10.48 s      grader    1.58 s     … three revise laps …
 * ```
 *
 * and the panel drew:
 *
 * ```
 *   in1        0.01 s      router1  11.66 s
 *   agent-sql  0.00 s      grader   16.01 s
 * ```
 *
 * One rule produced all of it: **an internal frame was charged to the bar
 * already open.** An agent's model calls, tool calls and middleware all arrive
 * *before* the agent's own completion frame — LangGraph's `updates` mode
 * reports a node only after it finishes — so every second of an agent's work
 * was billed to whichever node the stream had last named, and the agent itself
 * was left with the gap between its last internal frame and its own, which is
 * microseconds.
 *
 * The frames already carried the answer. `activeNode` is the top-level owner
 * the *server* resolved for the frame, and on all thirty-nine of that run's
 * first-lap internal frames it read `agent-sql`. The fold simply never looked
 * at it.
 */
import { describe, expect, it } from 'vitest';
import { buildTimeline, type TimelineRow } from './timeline';

/** A frame, as the panel hands it over: the server's offset, and whose work it was. */
const at = (
  elapsedMs: number | null,
  node: string,
  patch: Partial<TimelineRow> = {},
): TimelineRow => ({
  node,
  taskId: null,
  internal: false,
  namespace: [],
  elapsedMs,
  ...patch,
});

/**
 * The shape of the captured run, shortened to one agent lap: an input, a
 * router, then thirty-nine milliseconds-apart internal frames while the agent
 * thinks for ten seconds, then the agent's own completion frame.
 */
const aRunWithAnAgent = (): TimelineRow[] => [
  at(10, 'node:in1'),
  at(1200, 'node:router1'),
  at(1260, 'model', { internal: true, activeNode: 'node:agent1', namespace: ['agent1:abc'] }),
  at(9000, 'tools', { internal: true, activeNode: 'node:agent1', namespace: ['agent1:abc'] }),
  at(11670, 'model', { internal: true, activeNode: 'node:agent1', namespace: ['agent1:abc'] }),
  at(11680, 'node:agent1'),
  at(12000, 'node:out1'),
];

describe('an agent is charged for the work it did', () => {
  it('does not bill the agent’s thinking to the node before it', () => {
    const { steps } = buildTimeline(aRunWithAnAgent());
    const byLabel = new Map(steps.map((step) => [step.label, step.durationMs]));

    // The reported symptom, in one line: this used to be 10 470.
    expect(byLabel.get('router1')).toBeLessThan(1500);
  });

  it('gives the agent the seconds it actually spent, not the gap after them', () => {
    const { steps } = buildTimeline(aRunWithAnAgent());
    const agent = steps.find((step) => step.label === 'agent1');

    // The reported symptom's other half: this used to be 10.
    expect(agent?.durationMs).toBeGreaterThan(10_000);
    expect(agent?.internalSteps).toBe(3);
  });

  it('gives the agent exactly one bar, not one for its work and one for its frame', () => {
    const { steps } = buildTimeline(aRunWithAnAgent());

    expect(steps.map((step) => step.label)).toEqual(['in1', 'router1', 'agent1', 'out1']);
  });

  it('lays the bars end to end on the server’s own clock', () => {
    const { steps, totalMs } = buildTimeline(aRunWithAnAgent());

    expect(steps.map((step) => [step.label, step.startMs, step.durationMs])).toEqual([
      ['in1', 0, 10],
      ['router1', 10, 1190],
      ['agent1', 1200, 10_480],
      ['out1', 11_680, 320],
    ]);
    // The check the ticket asks for: the timeline's total is the run's own
    // wall clock, not a sum that drifted away from it.
    expect(totalMs).toBe(12_000);
    expect(steps.reduce((sum, step) => sum + (step.durationMs ?? 0), 0)).toBe(totalMs);
  });
});

describe('a bar that cannot be honest says so', () => {
  it('reports no duration at all against a backend that sends no clock', () => {
    const { steps, totalMs } = buildTimeline([at(null, 'node:in1'), at(null, 'node:agent1')]);

    expect(steps.map((step) => step.durationMs)).toEqual([null, null]);
    expect(steps.map((step) => step.startMs)).toEqual([null, null]);
    // `null`, never `0` — the same choice `PastRunStep.durationMs` made, and
    // for the same reason: `0 ms` beside a ten-second bar is a claim, and it
    // is the claim this ticket exists to remove.
    expect(totalMs).toBeNull();
  });
});

describe('the run’s own wall clock is what the total reports', () => {
  it('counts the time before a spawn rather than dropping it', () => {
    const { steps, totalMs } = buildTimeline([
      at(100, 'node:orch'),
      at(400, 'node:orch', {
        spawn: { kind: 'fanout', label: 'researcher', instruction: 'go' },
        taskId: 't1',
      }),
      at(900, 'node:worker', { taskId: 't1' }),
    ]);

    expect(totalMs).toBe(900);
    expect(steps.reduce((sum, step) => sum + (step.durationMs ?? 0), 0)).toBe(900);
  });
});

/**
 * The same symptom in the fan-out shape, captured from a live `morning-brief`
 * run (17.1 s): a dispatched worker's internal frames say
 * `activeNode: worker-web`, while its own completion frame resolves — rightly,
 * by rule 4 — to the name the spawn announced, `web-researcher`. Matching the
 * bar on its label drew `worker-web 14.6 s` beside `web-researcher 0 ms`,
 * which is 108 again with different words on it.
 */
describe('a dispatched worker is one lane, under the name its spawn gave it', () => {
  const aFanOut = (): TimelineRow[] => [
    at(4, 'node:in1'),
    at(2403, 'node:lead1', {
      spawn: { kind: 'fanout', label: 'web-researcher', instruction: 'search' },
      taskId: 'task-1',
    }),
    at(2409, 'node:lead1'),
    at(4252, 'model', {
      internal: true,
      activeNode: 'node:worker-web',
      namespace: ['worker_web:0ff3'],
    }),
    at(17_053, 'tools', {
      internal: true,
      activeNode: 'node:worker-web',
      namespace: ['worker_web:0ff3'],
    }),
    at(17_055, 'node:worker-web', { taskId: 'task-1', activeNode: 'node:worker-web' }),
    at(17_057, 'node:out1'),
  ];

  it('gives the worker one bar, not a named empty one beside a nameless full one', () => {
    const { steps } = buildTimeline(aFanOut());

    expect(steps.map((step) => step.label)).toEqual(['in1', 'lead1', 'web-researcher', 'out1']);
  });

  it('puts the worker’s seconds on it, and its task id', () => {
    const worker = buildTimeline(aFanOut()).steps[2]!;

    expect(worker.durationMs).toBe(14_646);
    expect(worker.taskId).toBe('task-1');
    expect(worker.internalSteps).toBe(2);
  });

  it('still adds up to the run', () => {
    const { steps, totalMs } = buildTimeline(aFanOut());

    expect(steps.reduce((sum, step) => sum + (step.durationMs ?? 0), 0)).toBe(totalMs);
  });
});
