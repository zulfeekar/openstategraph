import { describe, expect, it } from 'vitest';
import {
  addNode,
  connect,
  LOOPABLE_TYPE,
  makeWorkbench,
  registerLoopableType,
  TYPE,
} from '@core/testing/fixtures';

/**
 * Found live: pressing "Run" on a workflow with a blocking diagnostic (a
 * required input unwired) or a loop produced **no observable feedback at
 * all** — `engine.run()` returned `{ ok: false, error }`, but the two
 * pre-flight rejection paths returned before ever calling `bus.emit`, so
 * neither `run:start` nor `run:finish` fired. The toolbar's own
 * `run:finish` listener (which already turns a failure into a toast) never
 * got the chance to run. This pins that both paths now emit the same
 * `run:start`/`run:finish` pair a real run would, carrying the error.
 */
describe('ExecutionEngine.run — pre-flight rejection is observable', () => {
  it('a blocking diagnostic still emits run:start and run:finish with the error', async () => {
    const workbench = makeWorkbench();
    // agent.llm's `prompt` input is required and left unwired on purpose.
    addNode(workbench, TYPE.agent);

    const events: string[] = [];
    workbench.engine.on('run:start', () => events.push('start'));
    workbench.engine.on('run:finish', (payload) => events.push(`finish:${payload.ok}`));

    const outcome = await workbench.engine.run();

    expect(outcome.ok).toBe(false);
    expect(outcome.error).toMatch(/prompt/i);
    expect(events).toEqual(['start', 'finish:false']);
  });

  it('an unescapable cycle emits run:start/run:finish, without suggesting Chat', async () => {
    // Neither node has any edge leaving {a, b} — this loop cannot finish on
    // *any* engine, backend included, so "try Chat instead" would be wrong
    // advice. `acyclicGraphRule` reports this shape as a blocking `error`.
    const workbench = makeWorkbench();
    registerLoopableType(workbench);
    const a = addNode(workbench, LOOPABLE_TYPE);
    const b = addNode(workbench, LOOPABLE_TYPE, { at: { x: 200, y: 0 } });
    connect(workbench, a, 'out', b, 'in');
    connect(workbench, b, 'out', a, 'in');

    const events: string[] = [];
    workbench.engine.on('run:start', () => events.push('start'));
    workbench.engine.on('run:finish', (payload) => events.push(`finish:${payload.ok}`));

    const outcome = await workbench.engine.run();

    expect(outcome.ok).toBe(false);
    expect(outcome.error).toMatch(/loop/i);
    expect(outcome.error).toMatch(/no way out/i);
    expect(outcome.error).not.toMatch(/Chat/i);
    expect(events).toEqual(['start', 'finish:false']);
  });

  it('an escapable cycle (a revise loop with a way out) hands over to the backend runtime', async () => {
    // `a` fans out to both `b` (closing the cycle) and `c` (escaping it) —
    // the same shape as a grader's `pass` exiting a `revise` loop.
    // `acyclicGraphRule` reports this as a `warning`, not a blocking
    // `error`, so this path is only reachable via the engine's own
    // belt-and-suspenders `topologicalOrder()` check.
    const workbench = makeWorkbench();
    registerLoopableType(workbench);
    const a = addNode(workbench, LOOPABLE_TYPE);
    const b = addNode(workbench, LOOPABLE_TYPE, { at: { x: 200, y: 0 } });
    const c = addNode(workbench, LOOPABLE_TYPE, { at: { x: 400, y: 0 } });
    connect(workbench, a, 'out', b, 'in');
    connect(workbench, b, 'out', a, 'in');
    connect(workbench, a, 'out', c, 'in');

    const events: string[] = [];
    workbench.engine.on('run:start', () => events.push('start'));
    workbench.engine.on('run:finish', (payload) => events.push(`finish:${payload.ok}`));

    const outcome = await workbench.engine.run();

    expect(outcome.ok).toBe(false);
    expect(outcome.error).toMatch(/loop/i);
    // The machine-readable half is what the shell acts on: it opens the chat
    // panel and runs this graph on the real backend rather than dead-ending.
    // Asserted as a code, not by matching the message text.
    expect(outcome.reason).toBe('requires-backend-runtime');
    expect(events).toEqual(['start', 'finish:false']);
  });
});
