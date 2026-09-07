import { useMemo } from 'react';
import { useController } from '@app/WorkbenchContext';
import { SpawnedTaskPill } from './SpawnedTaskPill';
import { spawnedTasks } from './spawnedTasks';
import type { ActivityRow } from '@view/ask/traceTree';

/**
 * What this run spawned, one pill each — the chat panel's half of
 * `canvas-feels-right/07`.
 *
 * **Why the chat panel first.** The ticket says so, and the reason is
 * mechanical: a popover on the canvas competes with JointJS for panning,
 * zooming and click-outside, while the chat panel has no such conflict. So
 * the interaction is proved where it can be proved, on a `design/` primitive
 * written for both — `Pill` portals out of the DOM and closes on the capture
 * phase already, which is what `Menu` needed to survive the paper.
 *
 * **Why it fixes something real.** `launch-readiness/140` recorded the
 * limitation this closes: a `Send` fan-out creates tasks, not canvas nodes,
 * so three parallel workers stack in the one card that dispatched them and a
 * reader cannot see that three things are happening. Measured live on
 * 2026-08-28 against `parallel-workers-join`: two `spawn` frames carrying
 * `task-1` and `task-2`, and every frame either child produced landing on the
 * single node `worker1`.
 *
 * Nothing here writes anything. It is a `useMemo` over the rows the panel
 * already holds.
 */
export function SpawnedPills({
  rows,
  running,
}: {
  rows: readonly ActivityRow[];
  running: boolean;
}) {
  const controller = useController();
  const tasks = useMemo(
    () => spawnedTasks(rows, (id) => controller.model.node(id) != null),
    [rows, controller],
  );

  if (tasks.length === 0) return null;

  return (
    <div className="ask__spawned">
      <span className="ask__spawned-label">
        {/* Named as a count, because the count is the information the canvas
            cannot give: "3 workers" is the sentence a reader is missing when
            three of them are drawn as one card. */}
        {tasks.length === 1
          ? '1 worker this run started'
          : `${tasks.length} workers this run started`}
      </span>
      {tasks.map((task) => (
        <SpawnedTaskPill key={task.key} task={task} running={running} startedBy={task.owner} />
      ))}
    </div>
  );
}
