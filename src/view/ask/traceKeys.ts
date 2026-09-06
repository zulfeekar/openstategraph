/**
 * A React key for one row of the trace.
 *
 * **The collision** (`every-workflow-green` 05b/08). The key was
 * `${step.node}-${step.taskId ?? index}`, and the console reported on every
 * second turn:
 *
 *     Encountered two children with the same key, `node:input.text-1-__turn_reset__`
 *
 * `__turn_reset__` is the turn marker the input node carries — deliberately,
 * and deliberately visible to developers (`customer_task_id`: *"To a developer
 * that is real information — it is how one turn is told from the next in a
 * thread"*). Being **the same string on every turn** is the entire point of it,
 * so using it as a discriminator is using the one value guaranteed not to
 * discriminate.
 *
 * React's warning names the cost: *"Non-unique keys may cause children to be
 * duplicated and/or omitted."* A trace that omits a row is a trace that lies,
 * and it is the surface a developer reads to find out what a run actually did.
 *
 * **The index always, the task id as well.** The index separates turns; the
 * task id separates `Send` fan-out tasks *within* a turn, where several rows
 * share one node and one position in the list. Neither alone is enough, which
 * is why the old `??` — one *or* the other — was the bug.
 */
export function traceStepKey(
  step: { readonly node: string; readonly taskId: string | null | undefined },
  index: number,
): string {
  return `${step.node}#${index}#${step.taskId ?? ''}`;
}
