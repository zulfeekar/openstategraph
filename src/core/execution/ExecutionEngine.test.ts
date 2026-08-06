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

  it('a cyclic graph still emits run:start and run:finish, with a message that says to use Chat', async () => {
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
    expect(outcome.error).toMatch(/Chat/i);
    expect(events).toEqual(['start', 'finish:false']);
  });
});
