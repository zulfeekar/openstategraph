import { useMemo } from 'react';
import { Pill, ThinkingStack } from '@design/primitives';
import { useController } from '@app/WorkbenchContext';
import { spawnedTasks, taskAccountNote } from './spawnedTasks';
import type { ActivityRow } from './traceTree';

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
      {tasks.map((task) => {
        const note = taskAccountNote(task);
        return (
          <Pill
            key={task.key}
            label={task.label}
            // The one child that outlives the run says so in words, and in
            // words only. A pulse claims *happening now*, and the moment this
            // run ends nobody on this side has evidence either way — so the
            // pulse stops with the run for every kind, and the async pill is
            // simply never called finished. Animating a claim we cannot
            // support is `140`'s own paused-dot defect wearing a new hat.
            detail={task.detached ? 'in the background' : undefined}
            live={running && !task.reported}
            title={`${task.label} — started by ${task.owner}`}
          >
            {task.instruction ? <p className="pill-popover__brief">{task.instruction}</p> : null}
            <ThinkingStack lines={task.lines} live={running} label={task.label} />
            {note ? <p className="pill-popover__note">{note}</p> : null}
          </Pill>
        );
      })}
    </div>
  );
}
