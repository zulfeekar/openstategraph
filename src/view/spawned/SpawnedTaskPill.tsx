import { Pill, ThinkingStack } from '@design/primitives';
import type { SpawnedChild } from '@core/model/contracts/node';
import { taskAccountNote } from './spawnedTasks';

/**
 * One spawned child, as a chip that opens its own account.
 *
 * `canvas-feels-right/07`. Extracted from `SpawnedPills` when the canvas
 * became the second surface, on `launch-readiness/140`'s standing precedent:
 * **one primitive, three surfaces, never three implementations.** The chat
 * panel and the node card differ in *where* a chip hangs and in nothing else
 * — the same brief, the same 420 px stack, the same honesty note — so the
 * difference is a stylesheet and a wrapper, not a second component with its
 * own drift.
 *
 * `startedBy` is a prop because the two surfaces have two right answers. In
 * the chat panel a reader is looking at the whole run and needs to be told
 * which card launched this; on a card they are already looking at the
 * launcher, so it names it by title rather than by id.
 */
export function SpawnedTaskPill({
  task,
  running,
  startedBy,
  placement,
  subscribeAnchorMoved,
}: {
  readonly task: SpawnedChild;
  readonly running: boolean;
  readonly startedBy: string;
  readonly placement?: 'top' | 'bottom';
  /** Only the canvas has one — see `Pill`. The chat panel passes nothing. */
  readonly subscribeAnchorMoved?: (update: () => void) => () => void;
}) {
  const note = taskAccountNote(task);
  return (
    <Pill
      label={task.label}
      // The one child that outlives the run says so in words, and in words
      // only. A pulse claims *happening now*, and the moment this run ends
      // nobody on this side has evidence either way — so the pulse stops with
      // the run for every kind, and the async pill is simply never called
      // finished. Animating a claim we cannot support is `140`'s own
      // paused-dot defect wearing a new hat.
      detail={task.detached ? 'in the background' : undefined}
      live={running && !task.reported}
      title={`${task.label} — started by ${startedBy}`}
      {...(placement ? { placement } : {})}
      {...(subscribeAnchorMoved ? { subscribeAnchorMoved } : {})}
    >
      {task.instruction ? <p className="pill-popover__brief">{task.instruction}</p> : null}
      <ThinkingStack lines={task.lines} live={running} label={task.label} />
      {note ? <p className="pill-popover__note">{note}</p> : null}
    </Pill>
  );
}
