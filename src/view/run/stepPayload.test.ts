/**
 * `memory-and-replay` 59 — what the selected step asked, and what it produced.
 *
 * The pane is decided here rather than eyeballed in a rendered dock, for the
 * reason `barDetail.test.ts` gives: every honesty rule on this surface is a
 * statement about a string, and a statement about a string is testable.
 */
import { describe, expect, it } from 'vitest';
import { buildLanes, type TimelineRow } from '../ask/timeline';
import { askedAndProduced } from './stepPayload';

const row = (over: Partial<TimelineRow> & { node: string }): TimelineRow => ({
  taskId: null,
  internal: false,
  ...over,
});

/** The one lane every plain run has, and the bar at `index` on it. */
function bar(rows: readonly TimelineRow[], index = 0) {
  const { lanes } = buildLanes(rows);
  const lane = lanes[0]!;
  return { lane, step: lane.steps[index]! };
}

describe('what a bar produced', () => {
  it('is the output the run reported on that bar’s own frames', () => {
    const { lane, step } = bar([
      row({ node: 'agent1', elapsedMs: 10, output: 'Dublin is sunny.' }),
    ]);
    const [, produced] = askedAndProduced(lane, step);

    expect(produced.heading).toBe('Produced');
    expect(produced.text).toBe('Dublin is sunny.');
  });

  /**
   * The load-bearing one. `outputs` on the terminal record is keyed by node
   * and merged, so a node that ran twice has one row there; the frames are
   * per-lap. A pane fed from the record would show a revise loop's second
   * answer against its first bar.
   */
  it('is this lap’s answer, not the node’s last', () => {
    const rows = [
      row({ node: 'writer', elapsedMs: 10, output: 'first draft' }),
      row({ node: 'grader', elapsedMs: 20, output: 'revise' }),
      row({ node: 'writer', elapsedMs: 30, output: 'second draft' }),
    ];
    const first = bar(rows, 0);
    const second = bar(rows, 2);
    expect(askedAndProduced(first.lane, first.step)[1].text).toBe('first draft');
    expect(askedAndProduced(second.lane, second.step)[1].text).toBe('second draft');
  });

  it('says why the box is empty rather than showing an empty box', () => {
    const { lane, step } = bar([row({ node: 'in1', elapsedMs: 5 })]);
    const [, produced] = askedAndProduced(lane, step);

    expect(produced.text).toBeNull();
    expect(produced.caption).not.toBe('');
    expect(produced.caption.toLowerCase()).toContain('recorded no output');
  });

  it('never renders an absence as an empty string', () => {
    const { lane, step } = bar([row({ node: 'in1', elapsedMs: 5, output: '' })]);
    expect(askedAndProduced(lane, step)[1].text).toBeNull();
  });
});

describe('what a bar asked', () => {
  it('is the task the run handed a spawned child', () => {
    const rows = [
      row({
        node: 'supervisor',
        taskId: 't1',
        elapsedMs: 10,
        spawn: {
          kind: 'fanout',
          label: 'impact-analyst',
          instruction: 'Assess the blast radius of the schema change.',
          spawnId: 's1',
        },
      }),
      row({ node: 'worker', taskId: 't1', elapsedMs: 20, output: 'Three services break.' }),
    ];
    const { lanes } = buildLanes(rows);
    const child = lanes.find((candidate) => candidate.key === 's1');
    expect(child, 'the fan-out child got no lane').toBeDefined();

    const [asked, produced] = askedAndProduced(child!, child!.steps[0]!);
    expect(asked.text).toBe('Assess the blast radius of the schema change.');
    expect(produced.text).toBe('Three services break.');
  });

  /**
   * The half the wire genuinely does not carry. A top-level node's prompt is
   * assembled inside the runtime and never leaves it, so the honest answer is
   * a sentence saying so — not a blank, and not the question the *run* was
   * asked, which is a different question from what this step was asked.
   */
  it('says the run records none for a step nobody spawned', () => {
    const { lane, step } = bar([row({ node: 'agent1', elapsedMs: 10, output: 'done' })]);
    const [asked] = askedAndProduced(lane, step);

    expect(asked.heading).toBe('Asked');
    expect(asked.text).toBeNull();
    expect(asked.caption).toMatch(/only for a step it spawned/i);
  });
});

describe('a refusal', () => {
  const refused = () =>
    bar([
      row({
        node: 'grader1',
        elapsedMs: 10,
        check: 'length',
        reason: 'The draft is under the 200-word floor.',
        output: 'revise',
      }),
    ]);

  it('produces the verdict and the reason, not the routed word alone', () => {
    const { lane, step } = refused();
    expect(step.kind).toBe('refusal');

    const [, produced] = askedAndProduced(lane, step);
    expect(produced.text).toContain('The draft is under the 200-word floor.');
    expect(produced.caption).toContain('length');
  });

  /** A refusal spends no model call, so its caption must not imply one. */
  it('says the check rejected it without a model call', () => {
    const { lane, step } = refused();
    expect(askedAndProduced(lane, step)[1].caption).toMatch(/without a model call/i);
  });

  it('still reports the check when the run wrote no sentence for it', () => {
    const { lane, step } = bar([row({ node: 'grader1', elapsedMs: 10, check: 'length' })]);
    const [, produced] = askedAndProduced(lane, step);
    expect(produced.text).toBeNull();
    expect(produced.caption).toContain('length');
  });
});

describe('a mount', () => {
  it('is worded as another document’s answer, not as this one’s', () => {
    const rows = [
      row({
        node: 'wf1',
        elapsedMs: 10,
        namespace: ['wf-music'],
        spawn: { kind: 'subgraph', label: 'wf-music', instruction: '', spawnId: 'g1' },
      }),
      row({ node: 'agent-sql', elapsedMs: 20, namespace: ['wf-music'], output: '42 albums.' }),
    ];
    const { lane, step } = bar(rows, 0);
    expect(step.kind).toBe('mount');

    const [asked, produced] = askedAndProduced(lane, step);
    expect(produced.text).toBe('42 albums.');
    expect(produced.caption).toMatch(/mounted workflow/i);
    // The task handed to the package is assembled by the compiler and is not
    // on the wire. Saying "none" is the claim; saying nothing is the defect.
    expect(asked.text).toBeNull();
    expect(asked.caption).not.toBe('');
  });
});

describe('every half', () => {
  it('always carries a caption, whatever the bar is', () => {
    const rows = [
      row({ node: 'in1', elapsedMs: 1 }),
      row({ node: 'agent1', elapsedMs: 2, output: 'x' }),
      row({ node: 'g1', elapsedMs: 3, check: 'c', reason: 'r' }),
    ];
    const { lanes } = buildLanes(rows);
    for (const lane of lanes) {
      for (const step of lane.steps) {
        for (const half of askedAndProduced(lane, step)) {
          expect(half.caption.trim(), `${step.label} ${half.heading}`).not.toBe('');
        }
      }
    }
  });
});
