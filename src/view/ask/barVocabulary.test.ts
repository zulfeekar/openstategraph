/**
 * The bar vocabulary — `memory-and-replay` 58.
 *
 * A chart whose bars all look alike proves nothing, and neither does a test
 * that only checks a class name exists. What is asserted here is that the
 * *fold* can tell a model call from a step that spent no model time from a
 * mount from a refusal, **against the recorded run rather than against a
 * fixture written to agree with it** — and that it does so from frames that
 * were already on the wire, which is why 58 added no field to the stream.
 */
import { describe, expect, it } from 'vitest';
import { buildLanes, buildTimeline, isModelStep, isToolStep, type TimelineRow } from './timeline';
import { runProfile } from '../run/runProfile';
import recorded from './recordedFanOutRun.json';

function rowsOf(frames: readonly Record<string, unknown>[]): TimelineRow[] {
  const rows: TimelineRow[] = [];
  const bySpawn = new Map<string, number>();
  for (const frame of frames) {
    const elapsedMs = frame['elapsedMs'] as number;
    if (frame['type'] === 'update') {
      rows.push({
        node: frame['node'] as string,
        taskId: (frame['taskId'] as string | null) ?? null,
        internal: frame['internal'] === true,
        namespace: frame['namespace'] as string[],
        activeNode: frame['activeNode'] as string,
        elapsedMs,
      });
    } else if (frame['type'] === 'spawn') {
      bySpawn.set(frame['spawnId'] as string, rows.length);
      rows.push({
        node: frame['parent'] as string,
        taskId: (frame['taskId'] as string | null) ?? null,
        internal: false,
        namespace: frame['namespace'] as string[],
        elapsedMs,
        spawn: {
          kind: frame['kind'] as string,
          label: frame['label'] as string,
          instruction: '',
          spawnId: frame['spawnId'] as string,
        },
      });
    } else if (frame['type'] === 'settled') {
      const at = bySpawn.get(frame['spawnId'] as string);
      const open = at === undefined ? undefined : rows[at];
      if (at !== undefined && open?.spawn) {
        rows[at] = {
          ...open,
          spawn: { ...open.spawn, outcome: frame['outcome'] as 'ok', settledMs: elapsedMs },
        };
      }
    }
  }
  return rows;
}

const theRun = (): TimelineRow[] => rowsOf(recorded.frames as unknown as Record<string, unknown>[]);

describe('a bar knows what kind of bar it is', () => {
  it('reads the loop’s own node names, which is where the evidence already was', () => {
    expect(isModelStep('model')).toBe(true);
    // A middleware hook wrapping a model call is proof a model step exists in
    // this node's loop — read tolerantly, exactly as this repository reads a
    // model's replies.
    expect(isModelStep('NarrationMiddleware.before_model')).toBe(true);
    expect(isToolStep('tools')).toBe(true);
    // Trusted strictly: an unrecognised internal step contributes nothing
    // rather than being guessed at.
    expect(isModelStep('PatchToolCallsMiddleware.before_agent')).toBe(false);
    expect(isToolStep('linter')).toBe(false);
  });

  it('draws a mount as a mount and a model-spending node as a model call', () => {
    const byLabel = new Map(buildTimeline(theRun()).steps.map((step) => [step.label, step.kind]));
    // `deep` and `audit` are the run's two `subgraph` spawns.
    expect(byLabel.get('deep')).toBe('mount');
    expect(byLabel.get('audit')).toBe('mount');
    // `in1`, `router`, `join` and `out1` produced no internal frame at all in
    // this recording, so nothing says a model was asked. Hollow is the honest
    // drawing and it means *no model time was spent here* — never *no data*.
    for (const plain of ['in1', 'router', 'join', 'out1']) {
      expect(byLabel.get(plain)).toBe('tool');
    }
  });

  it('counts a model call once, however many middlewares wrapped it', () => {
    // The recording holds 22 `model` frames and 53 middleware hooks around
    // them. Counting the hooks reported 75 model calls in a strip whose whole
    // job is to be quotable — found in the browser, not in a test.
    expect(runProfile(buildLanes(theRun())).modelCalls).toBe(22);
    expect(runProfile(buildLanes(theRun())).toolCalls).toBe(15);
  });

  it('spends the accent only on a refusal the run actually reported', () => {
    const withCheck = buildTimeline([
      { node: 'grader', taskId: null, internal: false, elapsedMs: 10 },
      { node: 'grader', taskId: null, internal: false, elapsedMs: 20, check: 'no-source' },
    ]);
    expect(withCheck.steps.map((step) => step.kind)).toEqual(['tool', 'refusal']);
    // An empty `check` is the value on every frame that did not refuse, and it
    // must not colour a bar — that is the difference between "a rule rejected
    // this" and "no deterministic check fired".
    const empty = buildTimeline([
      { node: 'grader', taskId: null, internal: false, elapsedMs: 10, check: '' },
    ]);
    expect(empty.steps[0]?.kind).toBe('tool');
  });

  it('lets a refusal outrank every other reading, because it is the only verdict', () => {
    const steps = buildTimeline([
      { node: 'agent', taskId: null, internal: true, activeNode: 'agent', elapsedMs: 5 },
      { node: 'model', taskId: null, internal: true, activeNode: 'agent', elapsedMs: 9 },
      { node: 'agent', taskId: null, internal: false, elapsedMs: 12, check: 'rule' },
    ]).steps;
    expect(steps[0]?.kind).toBe('refusal');
    // The model call is still counted — the strip above the chart says what
    // the run spent, and a refusal does not unspend it.
    expect(steps[0]?.modelCalls).toBe(1);
  });
});
