import { describe, expect, it } from 'vitest';
import { spawnedTasks, taskAccountNote, type SpawnedTaskRow } from './spawnedTasks';

/* ------------------------------------------------------------------ *
 * Every fixture below is a frame shape **measured on the wire** on
 * 2026-08-28 (`canvas-feels-right/07`), not one invented to make the
 * fold pass. The two that matter most are the two that surprised:
 *
 * - a deep agent's `task` call announces `parent: "model"`, which is not
 *   a canvas node at all;
 * - an orchestrator's `Send` fan-out announces `parent: "lead1"` while
 *   every frame the children produce lands on `worker1`.
 * ------------------------------------------------------------------ */

const spawn = (
  over: Partial<SpawnedTaskRow> & { spawn: NonNullable<SpawnedTaskRow['spawn']> },
): SpawnedTaskRow => ({
  node: 'lead1',
  taskId: null,
  output: null,
  ...over,
});

const step = (over: Partial<SpawnedTaskRow>): SpawnedTaskRow => ({
  node: 'worker1',
  taskId: null,
  output: null,
  ...over,
});

const known =
  (...ids: string[]) =>
  (id: string) =>
    ids.includes(id);

describe('spawnedTasks', () => {
  it('opens one task per spawn that carried a task id', () => {
    const tasks = spawnedTasks(
      [
        spawn({
          node: 'lead1',
          taskId: 'task-1',
          spawn: { kind: 'fanout', label: 'analyst', instruction: 'List the pros.' },
        }),
        spawn({
          node: 'lead1',
          taskId: 'task-2',
          spawn: { kind: 'fanout', label: 'analyst', instruction: 'List the cons.' },
        }),
      ],
      known('lead1', 'worker1'),
    );

    expect(tasks.map((task) => task.taskId)).toEqual(['task-1', 'task-2']);
    // The whole point of the ticket: two identically-labelled workers must
    // not collapse into one chip, because on the canvas they are already
    // collapsed into one card.
    expect(new Set(tasks.map((task) => task.key)).size).toBe(2);
    expect(tasks.map((task) => task.instruction)).toEqual(['List the pros.', 'List the cons.']);
  });

  it('gives a mounted subgraph no pill at all', () => {
    // A mount **is** a node in the saved document, drawn on the canvas with
    // its own card. A chip for it would say "this is runtime-only", which is
    // exactly the lie this ticket exists to avoid.
    const tasks = spawnedTasks(
      [
        spawn({
          node: 'lead1',
          taskId: null,
          namespace: ['worker1:22803b05'],
          spawn: { kind: 'subgraph', label: 'worker1', instruction: '' },
        }),
      ],
      known('lead1', 'worker1'),
    );
    expect(tasks).toEqual([]);
  });

  it('does not believe a parent that is not a canvas node', () => {
    // Measured: a deep agent's `task` call is read off the *inner* graph
    // step, so the frame announced `parent: "model"`. Taking that at face
    // value would attribute every subagent to a node nobody can see.
    const tasks = spawnedTasks(
      [
        spawn({
          node: 'model',
          taskId: 'call_wzUt3jDD',
          namespace: ['agent1:c00c273d'],
          spawn: { kind: 'subagent', label: 'counter', instruction: 'Count mississippi' },
        }),
      ],
      known('agent1'),
    );
    expect(tasks[0]?.owner).toBe('agent1');
  });

  it('keeps the announced parent when it really is a canvas node', () => {
    const tasks = spawnedTasks(
      [
        spawn({
          node: 'lead1',
          taskId: 'task-1',
          spawn: { kind: 'fanout', label: 'analyst', instruction: '' },
        }),
      ],
      known('lead1'),
    );
    expect(tasks[0]?.owner).toBe('lead1');
  });

  it('collects the frames that came back carrying the task id', () => {
    const tasks = spawnedTasks(
      [
        spawn({
          node: 'lead1',
          taskId: 'task-2',
          spawn: { kind: 'fanout', label: 'analyst', instruction: 'List the cons.' },
        }),
        step({ node: 'worker1', taskId: 'task-2', output: 'Reduced hallway context.' }),
      ],
      known('lead1', 'worker1'),
    );

    expect(tasks[0]?.lines).toEqual(['Reduced hallway context.']);
    expect(tasks[0]?.reported).toBe(true);
  });

  it('reports nothing for a task whose frames never came back', () => {
    // A blocking subagent and a background worker both run off this stream
    // by construction — `create_deep_agent` hands the parent a single
    // `ToolMessage`, and the desk's loop is outside every run context. An
    // empty account is the truth, and the popover has to say so rather than
    // look broken.
    const tasks = spawnedTasks(
      [
        spawn({
          node: 'model',
          taskId: 'call_1',
          namespace: ['agent1:abc'],
          spawn: { kind: 'async', label: 'counter', instruction: 'Count mississippi' },
        }),
      ],
      known('agent1'),
    );
    expect(tasks[0]?.lines).toEqual([]);
    expect(tasks[0]?.reported).toBe(false);
  });

  it('marks only the background worker as outliving the run', () => {
    const rows: SpawnedTaskRow[] = [
      spawn({
        taskId: 'a',
        spawn: { kind: 'fanout', label: 'analyst', instruction: '' },
      }),
      spawn({
        taskId: 'b',
        spawn: { kind: 'subagent', label: 'researcher', instruction: '' },
      }),
      spawn({
        taskId: 'c',
        spawn: { kind: 'async', label: 'counter', instruction: '' },
      }),
    ];
    expect(spawnedTasks(rows, known('lead1')).map((task) => task.detached)).toEqual([
      false,
      false,
      true,
    ]);
  });

  it('ignores a spawn announced twice under one id', () => {
    const row = spawn({
      taskId: 'task-1',
      spawn: { kind: 'fanout', label: 'analyst', instruction: 'List the pros.' },
    });
    expect(spawnedTasks([row, row], known('lead1'))).toHaveLength(1);
  });

  it('separates two spawns that carried no id at all', () => {
    const rows: SpawnedTaskRow[] = [
      spawn({ taskId: null, spawn: { kind: 'subagent', label: 'helper', instruction: 'one' } }),
      spawn({ taskId: null, spawn: { kind: 'subagent', label: 'helper', instruction: 'two' } }),
    ];
    const tasks = spawnedTasks(rows, known('lead1'));
    expect(tasks).toHaveLength(2);
    expect(new Set(tasks.map((task) => task.key)).size).toBe(2);
  });

  it('never attaches a frame to a task by anything but its own id', () => {
    // `__turn_reset__` is a real task id on the wire and belongs to no
    // spawn. A fold that matched on the owning node instead would hand the
    // input node's text to a worker that never saw it.
    const tasks = spawnedTasks(
      [
        spawn({
          taskId: 'task-1',
          spawn: { kind: 'fanout', label: 'analyst', instruction: '' },
        }),
        step({ node: 'in1', taskId: '__turn_reset__', output: 'the question' }),
        step({ node: 'worker1', taskId: null, output: 'a joined answer' }),
      ],
      known('lead1', 'worker1', 'in1'),
    );
    expect(tasks[0]?.lines).toEqual([]);
  });

  it('drops an empty output rather than stacking a blank line', () => {
    const tasks = spawnedTasks(
      [
        spawn({
          taskId: 'task-1',
          spawn: { kind: 'fanout', label: 'analyst', instruction: '' },
        }),
        step({ taskId: 'task-1', output: '' }),
        step({ taskId: 'task-1', output: '   ' }),
      ],
      known('lead1', 'worker1'),
    );
    expect(tasks[0]?.lines).toEqual([]);
    // It still *reported* — a frame came back under this id, and that is a
    // different fact from whether it carried words.
    expect(tasks[0]?.reported).toBe(true);
  });
});

describe('taskAccountNote', () => {
  it('says a background worker is not waited for', () => {
    const note = taskAccountNote({ kind: 'async', reported: false });
    expect(note).toContain('background');
    expect(note).toContain('does not wait');
  });

  it('says a subagent reports back as one result and shares no context', () => {
    // The isolation rule, said on the surface rather than assumed: a
    // subagent is invoked as a tool and never sees this conversation.
    const note = taskAccountNote({ kind: 'subagent', reported: false });
    expect(note).toContain('nothing else about this conversation');
  });

  it('says nothing extra once the worker\u2019s own frames are here', () => {
    expect(taskAccountNote({ kind: 'fanout', reported: true })).toBe('');
  });

  it('explains an empty fan-out account rather than showing a blank box', () => {
    expect(taskAccountNote({ kind: 'fanout', reported: false })).not.toBe('');
  });
});
