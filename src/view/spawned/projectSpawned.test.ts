import { describe, expect, it } from 'vitest';
import type { SpawnedChild } from '@core/model/contracts/node';
import { projectSpawned } from './projectSpawned';
import type { SpawnedTaskRow } from './spawnedTasks';

const spawn = (
  over: Partial<SpawnedTaskRow> & { spawn: NonNullable<SpawnedTaskRow['spawn']> },
): SpawnedTaskRow => ({ node: 'lead1', taskId: null, output: null, ...over });

const known =
  (...ids: string[]) =>
  (id: string) =>
    ids.includes(id);

/** A stand-in for the model's runtime slice — read and write, nothing else. */
function fakeCards(seed: Record<string, readonly SpawnedChild[]> = {}) {
  const held = new Map<string, readonly SpawnedChild[]>(Object.entries(seed));
  const writes: string[] = [];
  return {
    held,
    writes,
    read: (id: string) => held.get(id) ?? [],
    write: (id: string, spawned: readonly SpawnedChild[]) => {
      writes.push(id);
      held.set(id, spawned);
    },
  };
}

const twoWorkers: readonly SpawnedTaskRow[] = [
  spawn({
    node: 'lead1',
    taskId: 'task-1',
    spawn: { kind: 'fanout', label: 'analyst', instruction: 'Pros.' },
  }),
  spawn({
    node: 'lead1',
    taskId: 'task-2',
    spawn: { kind: 'fanout', label: 'analyst', instruction: 'Cons.' },
  }),
];

describe('projectSpawned', () => {
  it('writes each card the children it launched', () => {
    const cards = fakeCards();
    projectSpawned(twoWorkers, known('lead1'), cards.read, cards.write);
    expect(cards.writes).toEqual(['lead1']);
    expect(cards.held.get('lead1')).toHaveLength(2);
  });

  it('writes nothing the second time nothing changed', () => {
    // The fold runs on every frame; an unconditional write would re-render
    // every card that ever spawned anything, and a `NodeCard` re-render
    // measures itself and reports geometry back to the canvas.
    const cards = fakeCards();
    projectSpawned(twoWorkers, known('lead1'), cards.read, cards.write);
    projectSpawned(twoWorkers, known('lead1'), cards.read, cards.write);
    expect(cards.writes).toEqual(['lead1']);
  });

  it('writes again when a child’s own account arrives', () => {
    // A fan-out child's lines land after its chip does. Keying the guard on
    // identity alone would leave the popover on the empty note for ever.
    const cards = fakeCards();
    projectSpawned(twoWorkers, known('lead1'), cards.read, cards.write);
    projectSpawned(
      [...twoWorkers, { node: 'worker1', taskId: 'task-1', output: 'Broader talent pool.' }],
      known('lead1', 'worker1'),
      cards.read,
      cards.write,
    );
    expect(cards.writes).toEqual(['lead1', 'lead1']);
    expect(cards.held.get('lead1')?.[0]?.lines).toEqual(['Broader talent pool.']);
  });

  it('never clears a card, because clearing is the next run’s job', () => {
    // `AskPanel.resetRunState` wipes every card with `IDLE_RUNTIME` at the
    // start of a run. Clearing here as well would make a chip vanish
    // mid-run the moment a reconnect replayed fewer rows.
    const cards = fakeCards();
    projectSpawned(twoWorkers, known('lead1'), cards.read, cards.write);
    projectSpawned([], known('lead1'), cards.read, cards.write);
    expect(cards.held.get('lead1')).toHaveLength(2);
    expect(cards.writes).toEqual(['lead1']);
  });

  it('touches no card for a run that spawned nothing', () => {
    const cards = fakeCards();
    projectSpawned([], known('lead1'), cards.read, cards.write);
    expect(cards.writes).toEqual([]);
  });
});
