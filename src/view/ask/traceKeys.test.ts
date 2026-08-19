import { describe, expect, it } from 'vitest';
import { traceStepKey } from './traceKeys';

/**
 * Two turns of one node must not collide (`every-workflow-green` 05b/08).
 *
 * The console reported, on every second turn:
 *
 *     Encountered two children with the same key, `node:input.text-1-__turn_reset__`
 *
 * The key was `${step.node}-${step.taskId ?? index}`. `__turn_reset__` is the
 * turn marker every turn's input node carries — deliberately, and deliberately
 * developer-only (`customer_task_id` in `api/streaming.py`: *"To a developer
 * that is real information — it is how one turn is told from the next in a
 * thread"*). So it is the **same string on every turn**, and a second turn
 * produced a key identical to the first's.
 *
 * React's own warning states the cost: *"Non-unique keys may cause children to
 * be duplicated and/or omitted."* A trace that silently omits a row is a trace
 * that lies, and this one is the surface a developer uses to find out what a
 * run did.
 *
 * The fix is the index, always — a task id disambiguates *within* a turn and
 * cannot disambiguate *across* turns, because a stable marker is the whole
 * point of it.
 */
describe('a trace step key', () => {
  it('separates two turns of the same node carrying the same marker', () => {
    // The exact collision from the console.
    const first = traceStepKey({ node: 'node:input.text-1', taskId: '__turn_reset__' }, 0);
    const second = traceStepKey({ node: 'node:input.text-1', taskId: '__turn_reset__' }, 3);
    expect(first).not.toBe(second);
  });

  it('still separates two tasks within one turn', () => {
    // Fan-out: one node, several `Send` tasks, same index space. The task id is
    // what tells those apart and must survive.
    const a = traceStepKey({ node: 'node:worker-1', taskId: 'task-1' }, 2);
    const b = traceStepKey({ node: 'node:worker-1', taskId: 'task-2' }, 2);
    expect(a).not.toBe(b);
  });

  it('handles a step with no task id at all', () => {
    expect(traceStepKey({ node: 'node:agent.llm-1', taskId: null }, 1)).toBeTruthy();
    expect(traceStepKey({ node: 'node:agent.llm-1', taskId: null }, 1)).not.toBe(
      traceStepKey({ node: 'node:agent.llm-1', taskId: null }, 2),
    );
  });

  it('is stable for the same step at the same position', () => {
    // A key that changed between renders would remount the row and collapse a
    // `<details>` the reader had opened.
    const step = { node: 'node:agent.llm-1', taskId: 'task-9' };
    expect(traceStepKey(step, 4)).toBe(traceStepKey(step, 4));
  });
});
