import { describe, expect, it } from 'vitest';
import type { PastRun, PastRunStep } from './RuntimeClient';
import {
  describeRun,
  laneTitle,
  lanes,
  relativeTime,
  pauseLines,
  stepLines,
  stepCost,
  truncationLine,
  stepTitle,
  toolCallLine,
} from './pastRunView';

const NOW = Date.parse('2026-08-11T12:00:00Z');

const aStep: PastRunStep = {
  checkpointId: 'cp-1',
  step: 2,
  at: '2026-08-11T11:59:00Z',
  source: 'loop',
  values: {},
  namespace: [],
  node: '',
  wrote: [],
  toolCalls: [],
  durationMs: null,
  tokens: null,
};

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
  failed: false,
  pause: null,
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
  });

  /**
   * `memory-and-replay/45`. The session id used to be `""` on every run, so
   * this line printed nothing; now that it is written, printing it raw would
   * stamp an opaque `sess-…` under every row. What a reader can use is not the
   * token, it is whether the run is theirs.
   */
  it('says nothing about a run from the reader’s own sitting', () => {
    expect(describeRun(run({ sessionId: 'sess-7' }), NOW, 'sess-7').identity).toBe('');
  });

  it('says a run came from another sitting, in words rather than in a token', () => {
    expect(describeRun(run({ sessionId: 'sess-7' }), NOW, 'sess-9').identity).toBe(
      'another sitting',
    );
    expect(
      describeRun(run({ userEmail: 'me@example.com', sessionId: 'sess-7' }), NOW, 'sess-9')
        .identity,
    ).toBe('me@example.com · another sitting');
  });

  it('claims nothing when the reader has no sitting to compare against', () => {
    // A script, a test, or a browser with site data blocked. Nothing can be
    // told apart from the reader's own run, so nothing pretends to be.
    expect(describeRun(run({ sessionId: 'sess-7' }), NOW).identity).toBe('');
  });

  it('reads a paused run as resumable and a finished one as done', () => {
    expect(describeRun(run({ status: 'paused' }), NOW).statusLabel).toBe('waiting for you');
    expect(describeRun(run(), NOW).statusLabel).toBe('finished');
  });

  it('reads a failed run as something to re-ask, not a bare status word', () => {
    expect(describeRun(run({ failed: true }), NOW).statusLabel).toBe('ask again — a step failed');
  });

  it('keeps paused and failed independent — a run can be both at once', () => {
    expect(describeRun(run({ status: 'paused', failed: true }), NOW).statusLabel).toBe(
      'waiting for you · a step failed',
    );
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
    durationMs: null,
    tokens: null,
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
    durationMs: null,
    tokens: null,
  });

  it('names the superstep and where it came from', () => {
    expect(stepTitle(titled(3, 'loop'))).toBe('Step 3 · loop');
  });

  it('calls the pre-run checkpoint what it is', () => {
    expect(stepTitle(titled(-1, 'input'))).toBe('Input · input');
  });

  it('omits an unrecorded source rather than printing an empty tail', () => {
    expect(stepTitle(titled(1, ''))).toBe('Step 1');
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
    durationMs: null,
    tokens: null,
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
    expect(laneTitle({ node: '', namespace: [], occurrence: 1, steps: [] })).toBe('The workflow');
    expect(
      laneTitle({ node: 'worker_web', namespace: ['worker_web'], occurrence: 1, steps: [] }),
    ).toBe('worker_web');
    // The second dispatch of one worker has to be distinguishable from the
    // first, or the split above buys nothing on screen.
    expect(
      laneTitle({ node: 'worker_web', namespace: ['worker_web'], occurrence: 2, steps: [] }),
    ).toBe('worker_web · run 2');
  });

  /**
   * `memory-and-replay` 39. Given the open document, the compiler's mangling
   * is read *forward* — never guessed back — so a lane is called what the card
   * is called.
   */
  it('says what the open document calls the node, when it can', () => {
    const names = new Map([['worker_web', 'Web researcher']]);
    expect(
      laneTitle({ node: 'worker_web', namespace: ['worker_web'], occurrence: 1, steps: [] }, names),
    ).toBe('Web researcher');
    expect(
      laneTitle({ node: 'worker_web', namespace: ['worker_web'], occurrence: 2, steps: [] }, names),
    ).toBe('Web researcher · run 2');
  });

  it('leaves a name it cannot resolve exactly as stored', () => {
    // A namespace segment from inside a *mounted* document: the parent's node
    // map does not contain the child's ids, and inventing one would name the
    // wrong card.
    const names = new Map([['worker_web', 'Web researcher']]);
    expect(
      laneTitle({ node: 'model', namespace: ['mount1', 'model'], occurrence: 1, steps: [] }, names),
    ).toBe('mount1 \u203a model');
  });

  it('resolves each segment of a path independently', () => {
    const names = new Map([['mount1', 'Chinook']]);
    expect(
      laneTitle({ node: 'model', namespace: ['mount1', 'model'], occurrence: 1, steps: [] }, names),
    ).toBe('Chinook \u203a model');
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

/**
 * `memory-and-replay` 37, part 2 — the two numbers a profiler exists for.
 *
 * Both are read straight off the checkpoints (`ts` deltas per namespace,
 * `AIMessage.usage_metadata`), so what is left here is purely how a row *reads*
 * — and the thing worth pinning is the distinction the backend went to trouble
 * to preserve: **unknown is not zero.** A step with nothing to measure against
 * must not print `0 ms`, because `0 ms` is a claim.
 */
describe('stepCost', () => {
  it('reads a duration in the unit a person can hold', () => {
    expect(stepCost({ ...aStep, durationMs: 1791, tokens: null })).toBe('1.8s');
    expect(stepCost({ ...aStep, durationMs: 86, tokens: null })).toBe('86ms');
    expect(stepCost({ ...aStep, durationMs: 195_000, tokens: null })).toBe('3m 15s');
  });

  it('says nothing at all when nothing was measured', () => {
    expect(stepCost({ ...aStep, durationMs: null, tokens: null })).toBe('');
  });

  it('never prints a zero for a step it could not time', () => {
    expect(stepCost({ ...aStep, durationMs: null, tokens: null })).not.toContain('0');
  });

  it('reports what the call cost, in and out', () => {
    expect(
      stepCost({
        ...aStep,
        durationMs: 5000,
        tokens: { inputTokens: 1436, outputTokens: 86, totalTokens: 1522 },
      }),
    ).toBe('5.0s · 1,522 tokens (1,436 in · 86 out)');
  });

  it('reports tokens on a step that was never timed', () => {
    expect(
      stepCost({
        ...aStep,
        durationMs: null,
        tokens: { inputTokens: 10, outputTokens: 2, totalTokens: 12 },
      }),
    ).toBe('12 tokens (10 in · 2 out)');
  });
});

describe('truncationLine', () => {
  const cut = { kept: 200, end: 'oldest', limit: 200, message: 'server sentence' };

  it('says nothing when the whole thread came back', () => {
    expect(truncationLine(null)).toBe('');
  });

  it('says which end is missing and how much came back', () => {
    const line = truncationLine(cut);
    expect(line).toContain('Older');
    expect(line).toContain('200');
  });

  it('names the cost of the missing end, which is the orphaned tool call', () => {
    // `docs/api.md`: a tool *result* whose request fell outside the window is
    // listed with an empty `arguments`. A reader who is not told that reads a
    // blank argument list as a tool called with nothing.
    expect(truncationLine(cut)).toContain('arguments');
  });

  it('does not offer a control this editor does not have', () => {
    // The server's own message ends "ask again with a higher limit (up to
    // 2000)". The CLI and a direct API caller can; the History lane has no
    // limit control, so repeating that sentence would describe something
    // unbuilt.
    const line = truncationLine(cut);
    expect(line).not.toContain('limit');
    expect(line).not.toContain('server sentence');
  });

  it('reads a truncation of some other end without inventing a direction', () => {
    // `end` is a string on the wire, not an enum. Tolerant in reading: an end
    // this client has never seen still produces a true sentence.
    expect(truncationLine({ ...cut, end: 'newest' })).toContain('Some');
  });
});

describe('pauseLines', () => {
  /**
   * The payload is `dict[str, str] | None` and nothing narrows it further: an
   * `interrupt()` in a package this editor did not write puts whatever it
   * likes on the wire. So these cases are the contract — not a schema.
   */
  it('says nothing about a run that is not parked', () => {
    expect(pauseLines(null)).toEqual([]);
  });

  it('survives an empty payload without claiming a question was asked', () => {
    expect(pauseLines({})).toEqual([]);
  });

  it('leads with the sentence the gate asks, then the text being stood behind', () => {
    // The two keys `_human_approval` always writes, in the order a reviewer
    // reads them: what am I being asked, and about what.
    expect(pauseLines({ candidate: 'Rock, $826.65.', message: 'Approve this result?' })).toEqual([
      { key: 'message', value: 'Approve this result?' },
      { key: 'candidate', value: 'Rock, $826.65.' },
    ]);
  });

  it('puts the grader opinion that reached the gate after the ask', () => {
    expect(
      pauseLines({
        reason: 'no citation',
        verdict: 'revise',
        message: 'Approve this result?',
        check: 'sourced',
      }).map((line) => line.key),
    ).toEqual(['message', 'verdict', 'reason', 'check']);
  });

  it('shows a key it has never seen rather than dropping it', () => {
    // Tolerant in reading. A package's own gate names its own fields, and a
    // lane that only printed the five keys this repository writes would hide
    // the whole question from every workflow it did not ship.
    expect(pauseLines({ severity: 'high', message: 'Sign off?' })).toEqual([
      { key: 'message', value: 'Sign off?' },
      { key: 'severity', value: 'high' },
    ]);
  });

  it('orders the keys it does not know alphabetically, as the step lines do', () => {
    expect(pauseLines({ zone: 'b', alpha: 'a' }).map((line) => line.key)).toEqual([
      'alpha',
      'zone',
    ]);
  });

  it('drops a key whose value is blank or an untouched container', () => {
    // `candidate` is `_upstream_text(...) or state["answer"]`, and both can be
    // empty. A row reading `candidate` against nothing is a question with no
    // subject.
    expect(pauseLines({ message: 'Approve?', candidate: '   ', outputs: '{}' })).toEqual([
      { key: 'message', value: 'Approve?' },
    ]);
  });

  it('refuses a payload that is not a mapping of strings', () => {
    // Strict in trusting. The wire type is `dict[str, str]`, but this lane is
    // the last reader before a screen and a nested object rendered by
    // `String()` would print `[object Object]` at a person.
    const hostile = { message: 'Approve?', nested: { a: 1 }, count: 3 } as unknown as Record<
      string,
      string
    >;
    expect(pauseLines(hostile)).toEqual([{ key: 'message', value: 'Approve?' }]);
  });
});
