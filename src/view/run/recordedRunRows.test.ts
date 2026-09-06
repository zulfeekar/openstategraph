import { describe, expect, it } from 'vitest';
import type { RecordedBurst, RecordedRun } from '@core/runtime/RecordedRunsClient';
import { buildLanes, buildTimeline } from '../ask/timeline';
import { recordedRunRows, recordedRunView } from './recordedRunRows';

const burst = (over: Partial<RecordedBurst> = {}): RecordedBurst => ({
  node: 'agent1',
  activeNode: 'agent1',
  namespace: [],
  block: 'text',
  kind: 'model',
  withheld: false,
  firstMs: 100,
  lastMs: 900,
  chunks: 4,
  chars: 4,
  text: 'Rock',
  capped: false,
  ...over,
});

const run = (bursts: readonly RecordedBurst[]): RecordedRun => ({
  at: '2026-08-30T09:00:00+0000',
  workflowSlug: 'chinook-assistant',
  threadId: 't-a',
  sessionId: 's-1',
  question: 'Which genre earned most?',
  answer: 'Rock — $826.65',
  seconds: 2,
  attempts: 0,
  failed: false,
  usage: [{ model: 'gpt-oss:120b-cloud', inputTokens: 12, outputTokens: 28, totalTokens: 40 }],
  bursts,
  ...{},
});

describe('a stored recording, through the fold the live run already uses', () => {
  it('gives every burst a bar under the node that produced it', () => {
    const { steps } = buildTimeline(
      recordedRunRows(run([burst(), burst({ node: 'out1', activeNode: 'out1' })])),
    );
    expect(steps.map((step) => step.label)).toEqual(['agent1', 'out1']);
  });

  it('bills an agent’s loop to the agent, not to a bar called “model”', () => {
    // The recording of a real `chinook-assistant` turn is nine bursts, and
    // eight of them come from LangGraph's own `model` and `tools` nodes inside
    // the agent's loop. Labelled by `node` the chart reads
    // `model / tools / model / tools …`; labelled by the owner the run named,
    // it reads `agent-sql`, once, which is the node somebody drew.
    // `launch-readiness/108` settled this for the live chart — *"this field is
    // the run saying whose seconds they are"* — and `memory-and-replay/74` is
    // the store finally keeping it.
    const { steps } = buildTimeline(
      recordedRunRows(
        run([
          burst({ node: 'model', activeNode: 'agent-sql', text: '' }),
          burst({
            node: 'tools',
            activeNode: 'agent-sql',
            kind: 'tool',
            firstMs: 1000,
            lastMs: 1100,
            text: 'rows',
          }),
          burst({
            node: 'model',
            activeNode: 'agent-sql',
            firstMs: 2000,
            lastMs: 2600,
            text: 'Rock',
          }),
        ]),
      ),
    );
    expect(steps.map((step) => [step.label, step.modelCalls, step.toolCalls])).toEqual([
      ['agent-sql', 2, 1],
    ]);
  });

  it('falls back to the graph node when the recording named no owner', () => {
    // A run stored before `74`. The bar keeps the only name it has rather than
    // going unlabelled, and rather than being attributed to a node the
    // recording never mentioned.
    const { steps } = buildTimeline(
      recordedRunRows(run([burst({ node: 'model', activeNode: '' })])),
    );
    expect(steps.map((step) => step.label)).toEqual(['model']);
  });

  it('draws the bar between the offsets the store measured', () => {
    // The first burst's bar runs from the stream opening to its last chunk,
    // which is what the live path claims for a node's first frame too. The
    // second runs from where the first ended — a span, not a measurement, and
    // exactly the semantics the caveat line under the bars already states.
    const { steps, totalMs } = buildTimeline(
      recordedRunRows(
        run([burst(), burst({ node: 'out1', activeNode: 'out1', firstMs: 1000, lastMs: 1200 })]),
      ),
    );
    expect(steps.map((step) => [step.startMs, step.durationMs])).toEqual([
      [0, 900],
      [900, 300],
    ]);
    expect(totalMs).toBe(1200);
  });

  it('counts a model burst as a model call and a tool burst as a tool call', () => {
    const { steps } = buildTimeline(
      recordedRunRows(run([burst(), burst({ node: 'tool1', activeNode: 'tool1', kind: 'tool' })])),
    );
    expect(steps.map((step) => [step.kind, step.modelCalls, step.toolCalls])).toEqual([
      ['model', 1, 0],
      ['tool', 0, 1],
    ]);
  });

  it('keeps a withheld burst as a bar with nothing in it', () => {
    // The recorder empties a withheld frame before building it, so the text is
    // genuinely absent. The burst is kept because it still says a node was
    // working: a customer's replay must show the stall, never a hole.
    const { steps } = buildTimeline(recordedRunRows(run([burst({ withheld: true, text: '' })])));
    expect(steps).toHaveLength(1);
    expect(steps[0]?.payload.output).toBeNull();
  });

  it('does not call a namespaced burst a mount, because it cannot know', () => {
    // Found by running it. `create_agent` compiles its own tool-calling loop
    // into a subgraph, so every burst of a real `chinook-assistant` turn
    // carries `namespace: ["agent_sql:…"]` — and read as the fold reads a
    // namespace, the whole run drew as one hatched box called
    // `agent_sql:b65e7270-…`. The frames that tell a mount from an agent are
    // the `spawn` and `settled` pair, and `47` records neither.
    const { steps } = buildTimeline(
      recordedRunRows(
        run([
          burst({ node: 'model', activeNode: 'agent-sql', namespace: ['agent_sql:b65e7270'] }),
          burst({
            node: 'tools',
            activeNode: 'agent-sql',
            kind: 'tool',
            namespace: ['agent_sql:b65e7270'],
            firstMs: 1000,
            lastMs: 1200,
          }),
        ]),
      ),
    );
    expect(steps.map((step) => [step.label, step.kind])).toEqual([['agent-sql', 'model']]);
  });

  it('quotes what each visit produced, not one answer against every bar', () => {
    // A revise loop reaches one node twice, with the grader in between.
    // `RunRecord.answer` is one string for the whole run and would show the
    // second draft against the first bar, which is why the live fold keeps
    // output per frame and this keeps it per burst.
    const { steps } = buildTimeline(
      recordedRunRows(
        run([
          burst({ text: 'first draft' }),
          burst({
            node: 'grader1',
            activeNode: 'grader1',
            firstMs: 1000,
            lastMs: 1100,
            text: 'revise',
          }),
          burst({ firstMs: 2000, lastMs: 2400, text: 'second draft' }),
        ]),
      ),
    );
    expect(steps.map((step) => [step.label, step.payload.output])).toEqual([
      ['agent1', 'first draft'],
      ['grader1', 'revise'],
      ['agent1', 'second draft'],
    ]);
  });

  it('gives a run with no recording no bars at all', () => {
    // An absence, and an answer: an old row, a workflow with no model in it, a
    // recording this audience was refused. Never a run that took zero ms.
    expect(recordedRunRows(run([]))).toEqual([]);
    expect(buildLanes(recordedRunRows(run([]))).totalMs).toBeNull();
  });
});

describe('what the dock is handed', () => {
  it('is a stored run, and says so', () => {
    const view = recordedRunView(run([burst()]));
    expect(view.source).toBe('stored');
    expect(view.running).toBe(false);
  });

  it('carries the identity and the question the store kept', () => {
    const view = recordedRunView(run([burst()]));
    expect(view.threadId).toBe('t-a');
    expect(view.question).toBe('Which genre earned most?');
  });

  it('passes the spend through per model, exactly as the store kept it', () => {
    expect(recordedRunView(run([burst()])).usage).toEqual([
      { model: 'gpt-oss:120b-cloud', inputTokens: 12, outputTokens: 28, totalTokens: 40 },
    ]);
  });

  it('passes an untold spend through as untold, never as zero', () => {
    expect(recordedRunView({ ...run([burst()]), usage: null }).usage).toBeNull();
  });
});
