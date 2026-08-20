import { describe, expect, it } from 'vitest';
import type { PastRun, PastRunStep } from './RuntimeClient';
import {
  describeRun,
  laneTitle,
  lanes,
  relativeTime,
  stepLines,
  stepTitle,
  toolCallLine,
} from './pastRunView';

const NOW = Date.parse('2026-08-11T12:00:00Z');

const run = (patch: Partial<PastRun> = {}): PastRun => ({
  threadId: 'th-1',
  workflowSlug: 'chinook-assistant',
  sessionId: '',
  userEmail: '',
  updatedAt: '2026-08-11T11:59:30Z',
  steps: 4,
  question: 'Which genre earned the most revenue?',
  answer: 'Rock, $826.65.',
  status: 'finished',
  ...patch,
});

describe('relativeTime', () => {
  it('says just now inside a minute', () => {
    expect(relativeTime('2026-08-11T11:59:30Z', NOW)).toBe('just now');
  });

  it('counts minutes, then hours, then days', () => {
    expect(relativeTime('2026-08-11T11:40:00Z', NOW)).toBe('20 min ago');
    expect(relativeTime('2026-08-11T09:00:00Z', NOW)).toBe('3 h ago');
    expect(relativeTime('2026-08-09T12:00:00Z', NOW)).toBe('2 d ago');
  });

  it('falls back to the raw stamp rather than inventing a time', () => {
    expect(relativeTime('', NOW)).toBe('');
    expect(relativeTime('not a date', NOW)).toBe('not a date');
  });

  it('never reports a negative age — a clock skew reads as just now', () => {
    expect(relativeTime('2026-08-11T12:00:30Z', NOW)).toBe('just now');
  });
});

describe('describeRun', () => {
  it('titles a run by its question', () => {
    expect(describeRun(run(), NOW).title).toBe('Which genre earned the most revenue?');
  });

  it('says so plainly when a run recorded no question', () => {
    expect(describeRun(run({ question: '' }), NOW).title).toBe('(no question recorded)');
  });

  it('shows identity only when the run carried it', () => {
    expect(describeRun(run(), NOW).identity).toBe('');
    expect(describeRun(run({ userEmail: 'me@example.com' }), NOW).identity).toBe('me@example.com');
    expect(describeRun(run({ sessionId: 'sess-7' }), NOW).identity).toBe('sess-7');
    expect(
      describeRun(run({ userEmail: 'me@example.com', sessionId: 'sess-7' }), NOW).identity,
    ).toBe('me@example.com · sess-7');
  });

  it('reads a paused run as resumable and a finished one as done', () => {
    expect(describeRun(run({ status: 'paused' }), NOW).statusLabel).toBe('waiting for you');
    expect(describeRun(run(), NOW).statusLabel).toBe('finished');
  });

  it('counts steps in words a reader can act on', () => {
    expect(describeRun(run({ steps: 1 }), NOW).meta).toBe('1 step · just now');
    expect(describeRun(run({ steps: 4 }), NOW).meta).toBe('4 steps · just now');
  });
});

describe('stepLines', () => {
  const step = (values: Record<string, string>): PastRunStep => ({
    checkpointId: 'cp-1',
    step: 2,
    at: '2026-08-11T11:59:00Z',
    source: 'loop',
    values,
    namespace: [],
    node: '',
    wrote: [],
    toolCalls: [],
  });

  it('drops a channel that serialized to an empty container', () => {
    // `{}` and `[]` are what an untouched dict/list channel renders as. They
    // are blank facts printed as punctuation, and a checkpoint of eight of
    // them buries the one line that changed.
    expect(stepLines(step({ outputs: '{}', subtasks: '[]', answer: 'Rock' }))).toEqual([
      { key: 'answer', value: 'Rock' },
    ]);
  });

  it('keeps a container that actually holds something', () => {
    expect(stepLines(step({ outputs: '{"in1": "hi"}' }))).toEqual([
      { key: 'outputs', value: '{"in1": "hi"}' },
    ]);
  });

  it('drops empty values — a blank channel is noise, not history', () => {
    expect(stepLines(step({ question: 'q', answer: '', feedback: '   ' }))).toEqual([
      { key: 'question', value: 'q' },
    ]);
  });

  it('leads with the channels a reader looks for first', () => {
    const lines = stepLines(step({ zeta: 'z', answer: 'a', question: 'q', outputs: 'o' }));
    expect(lines.map((line) => line.key)).toEqual(['question', 'answer', 'outputs', 'zeta']);
  });

  it('is empty for a checkpoint that recorded nothing readable', () => {
    expect(stepLines(step({}))).toEqual([]);
  });
});

describe('stepTitle', () => {
  /** `stepTitle` reads only the counter and the source; the lane above it
   *  carries the identity, so these literals name the fields it uses. */
  const titled = (step: number, source: string): PastRunStep => ({
    checkpointId: 'c',
    step,
    at: '',
    source,
    values: {},
    namespace: [],
    node: '',
    wrote: [],
    toolCalls: [],
  });

  it('names the superstep and where it came from', () => {
    expect(stepTitle(titled(3, 'loop'))).toBe(
      'Step 3 · loop',
    );
  });

  it('calls the pre-run checkpoint what it is', () => {
    expect(stepTitle(titled(-1, 'input'))).toBe(
      'Input · input',
    );
  });

  it('omits an unrecorded source rather than printing an empty tail', () => {
    expect(stepTitle(titled(1, ''))).toBe(
      'Step 1',
    );
  });
});

describe('lanes', () => {
  /**
   * `memory-and-replay` 37. A `morning-brief` run stores forty checkpoints
   * under five namespaces — the workflow itself and four agent subgraphs — and
   * the endpoint returns them in one chronological list. Each subgraph numbers
   * its own supersteps from `-1`, so the flat list reads:
   *
   *     Input · input   ×5
   *     Step 0 · loop   ×5
   *     Step 3 · loop   ×5
   *
   * Five different graphs, printed as though one graph had repeated itself.
   * Lanes are what make it readable: each graph's own timeline, in the order
   * the graphs first appear.
   *
   * The real ordering, taken from the stored `example.com` run, is genuinely
   * interleaved — three workers ran at once — so lanes cannot be built by
   * grouping neighbours.
   */
  const at = (node: string, step: number): PastRunStep => ({
    checkpointId: `cp-${node}-${step}`,
    step,
    at: '2026-08-20T06:33:06Z',
    source: step < 0 ? 'input' : 'loop',
    values: {},
    namespace: node ? [node] : [],
    node,
    wrote: [],
    toolCalls: [],
  });

  it('puts the workflow itself in a lane with no owner', () => {
    const [lane, ...rest] = lanes([at('', -1), at('', 0)]);

    expect(rest).toEqual([]);
    expect(lane?.node).toBe('');
    expect(lane?.steps).toHaveLength(2);
  });

  it('separates interleaved subgraphs that ran at the same time', () => {
    const found = lanes([
      at('', 2),
      at('worker_web', -1),
      at('worker_handbook', -1),
      at('worker_web', 0),
      at('worker_handbook', 0),
      at('', 3),
    ]);

    expect(found.map((lane) => lane.node)).toEqual(['', 'worker_web', 'worker_handbook']);
    expect(found.map((lane) => lane.steps.length)).toEqual([2, 2, 2]);
  });

  it('orders lanes by when each graph first appears', () => {
    const found = lanes([at('worker_handbook', -1), at('', -1), at('worker_web', -1)]);

    expect(found.map((lane) => lane.node)).toEqual(['worker_handbook', '', 'worker_web']);
  });

  it('splits one node dispatched twice into two lanes', () => {
    // `morning-brief` sent two subtasks to `worker_web`. They are one node
    // that ran twice, and the step counter restarting is the only evidence
    // of the boundary — the instance id is deliberately not in `namespace`,
    // because for *identity* the two are the same worker.
    const found = lanes([
      at('worker_web', -1),
      at('worker_web', 0),
      at('worker_web', -1),
      at('worker_web', 0),
      at('worker_web', 1),
    ]);

    expect(found).toHaveLength(2);
    expect(found.map((lane) => lane.occurrence)).toEqual([1, 2]);
    expect(found.map((lane) => lane.steps.length)).toEqual([2, 3]);
  });

  it('does not split on a step number that merely repeats within one lane', () => {
    // A superstep can be written twice — `update` and `fork` sources both do
    // it. A lane breaks on a **restart**, which is the counter going back to
    // where a graph begins, not on any non-increase.
    const found = lanes([at('worker_web', -1), at('worker_web', 0), at('worker_web', 0)]);

    expect(found).toHaveLength(1);
  });

  it('keeps every step, so nothing is lost by laning', () => {
    const steps = [at('', -1), at('worker_web', -1), at('', 0), at('worker_web', 0)];

    expect(lanes(steps).flatMap((lane) => lane.steps)).toHaveLength(steps.length);
  });

  it('has a name for each lane a reader can act on', () => {
    expect(laneTitle({ node: '', namespace: [], occurrence: 1, steps: [] })).toBe(
      'The workflow',
    );
    expect(
      laneTitle({ node: 'worker_web', namespace: ['worker_web'], occurrence: 1, steps: [] }),
    ).toBe('worker_web');
    // The second dispatch of one worker has to be distinguishable from the
    // first, or the split above buys nothing on screen.
    expect(
      laneTitle({ node: 'worker_web', namespace: ['worker_web'], occurrence: 2, steps: [] }),
    ).toBe('worker_web · run 2');
  });

  it('names a nested lane by its whole path', () => {
    // A mounted workflow's agent is two levels deep and "worker_web" alone
    // would claim it belongs to this canvas, which it does not.
    expect(
      laneTitle({
        node: 'model',
        namespace: ['mount1', 'model'],
        occurrence: 1,
        steps: [],
      }),
    ).toBe('mount1 › model');
  });
});


describe('toolCallLine', () => {
  /**
   * The execution point a reader most often came for. A run that answered
   * wrongly usually asked for the wrong thing, or was refused — and both of
   * those are in the arguments and the result, not in the name.
   */
  it('reads as a call and its answer', () => {
    expect(
      toolCallLine({
        name: 'web_fetch',
        arguments: '{"url": "https://example.com"}',
        result: 'Error: web_fetch is not a valid tool',
      }),
    ).toBe('web_fetch({"url": "https://example.com"}) \u2192 Error: web_fetch is not a valid tool');
  });

  it('says nothing came back rather than inventing an arrow to nowhere', () => {
    // A run stopped mid-call leaves a request with no answer. That is a fact
    // about the run, and an empty tail would read as "returned nothing".
    expect(toolCallLine({ name: 'web_search', arguments: '{"q": "a"}', result: '' })).toBe(
      'web_search({"q": "a"}) \u2014 no result stored',
    );
  });

  it('shows an answer whose request is gone without pretending to know it', () => {
    expect(toolCallLine({ name: 'counter', arguments: '', result: '42' })).toBe(
      'counter \u2192 42',
    );
  });

  it('names an unnamed call rather than printing a bare arrow', () => {
    expect(toolCallLine({ name: '', arguments: '', result: '42' })).toBe('a tool \u2192 42');
  });
});
