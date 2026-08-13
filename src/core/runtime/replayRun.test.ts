import { describe, expect, it } from 'vitest';
import { replayRun, turnToReplay, type ReplayFrame } from './replayRun';
import { parseMountAddress } from '@core/model/MountAddress';

const address = (raw: string) => parseMountAddress(raw)!;

const documentWith =
  (...ids: string[]) =>
  (id: string) =>
    ids.includes(id);

const QUESTION = 'Which five artists earn the most?';

/**
 * The frames a real mounted run puts on the wire, in order.
 *
 * Both documents have `in1` and `router1` — `concierge` and
 * `chinook-assistant` really do — which is why `pathSlugs` is here and why the
 * child must not inherit the parent's first two steps.
 */
const MOUNTED_RUN: readonly ReplayFrame[] = [
  {
    node: 'in1',
    activeNode: 'in1',
    path: ['in1'],
    pathSlugs: ['concierge'],
    output: QUESTION,
  },
  {
    node: 'router1',
    activeNode: 'router1',
    path: ['router1'],
    pathSlugs: ['concierge'],
    output: 'music_store',
  },
  // …and now inside the mount. `node` is the runtime's name, not a canvas id.
  {
    node: 'in1',
    activeNode: 'wf-music',
    path: ['wf-music', 'in1'],
    pathSlugs: ['concierge', 'chinook-assistant'],
    output: QUESTION,
  },
  {
    node: 'tools',
    activeNode: 'wf-music',
    path: ['wf-music', 'agent-sql'],
    pathSlugs: ['concierge', 'chinook-assistant'],
    output: null,
  },
];

const PARENT = documentWith('in1', 'router1', 'wf-music', 'out1');
const CHILD = documentWith('in1', 'router1', 'agent-sql', 'out1');

describe('replayRun — catching a newly-opened document up to the run', () => {
  it('gives the child the steps it never saw, and only its own', () => {
    // The ticket: opening the mount mid-run showed a static diagram, because
    // every frame before the click had been projected onto the parent. The
    // parent's `in1` and `router1` steps must not come along for the ride.
    expect(replayRun(MOUNTED_RUN, CHILD, true, address('chinook-assistant'))).toEqual([
      { nodeId: 'in1', status: 'success', output: QUESTION },
      { nodeId: 'agent-sql', status: 'running' },
    ]);
  });

  it('gives the child the question the run is carrying, not its saved one', () => {
    // The sharper half of the ticket. `in1`'s output *is* the question the
    // graph received, and it is the only place the child's card can learn it.
    const [input] = replayRun(MOUNTED_RUN, CHILD, true, address('chinook-assistant'));
    expect(input?.output).toBe(QUESTION);
  });

  it('leaves the parent showing the mount, as it already did', () => {
    expect(replayRun(MOUNTED_RUN, PARENT, true, address('concierge'))).toEqual([
      { nodeId: 'in1', status: 'success', output: QUESTION },
      { nodeId: 'router1', status: 'success', output: 'music_store' },
      { nodeId: 'wf-music', status: 'running' },
    ]);
  });

  it('glows nothing once the run has finished', () => {
    const done = replayRun(MOUNTED_RUN, PARENT, false, address('concierge'));
    expect(done.map((write) => write.status)).toEqual(['success', 'success', 'success']);
  });

  it('keeps a node in the position it was first reached', () => {
    // A revise loop returns to a node it already ran. The replay is the path
    // taken, so the second visit must not reorder the first.
    const loop: ReplayFrame[] = [
      { node: 'a', path: ['a'], output: 'first' },
      { node: 'b', path: ['b'], output: null },
      { node: 'a', path: ['a'], output: 'second' },
    ];
    expect(replayRun(loop, documentWith('a', 'b'), false)).toEqual([
      { nodeId: 'a', status: 'success', output: 'second' },
      { nodeId: 'b', status: 'success' },
    ]);
  });

  it('does not erase an output when the node is passed through again', () => {
    const loop: ReplayFrame[] = [
      { node: 'a', path: ['a'], output: 'the answer' },
      { node: 'a', path: ['a'], output: null },
    ];
    expect(replayRun(loop, documentWith('a'), false)).toEqual([
      { nodeId: 'a', status: 'success', output: 'the answer' },
    ]);
  });

  it('writes no output onto a card the frame was not reporting for', () => {
    // A frame from inside a mount has nothing to say about the mount's own
    // card — the text belongs to a step one level down.
    expect(replayRun([MOUNTED_RUN[3] as ReplayFrame], PARENT, true)).toEqual([
      { nodeId: 'wf-music', status: 'running' },
    ]);
  });

  it("gives a mounted node the output the frame reported for it", () => {
    // The other half of the same ticket, and the half that survived it: the
    // *value*. `node` is the runtime's name for the step (`tools`, `model`,
    // or `safe_name(id)`) and it is never a canvas id inside a mount — so an
    // `output` was correctly routed to `agent-sql` and then dropped on the
    // floor by a guard comparing it against `node`. The card glowed, and
    // stayed empty for the whole run.
    const settled: ReplayFrame = {
      node: 'agent_sql',
      activeNode: 'wf-music',
      path: ['wf-music', 'agent-sql'],
      pathSlugs: ['concierge', 'chinook-assistant'],
      output: 'Iron Maiden, with $138.60.',
    };
    expect(replayRun([settled], CHILD, false, address('chinook-assistant'))).toEqual([
      { nodeId: 'agent-sql', status: 'success', output: 'Iron Maiden, with $138.60.' },
    ]);
    // ...and the parent still learns nothing about the inside of its mount.
    expect(replayRun([settled], PARENT, false, address('concierge'))).toEqual([
      { nodeId: 'wf-music', status: 'success' },
    ]);
  });

  it('skips frames belonging to a document nobody has open', () => {
    expect(replayRun(MOUNTED_RUN, documentWith('unrelated'), true, address('something-else'))).toEqual([]);
  });

  it('is empty for a run that has produced no frames yet', () => {
    expect(replayRun([], PARENT, true)).toEqual([]);
  });
});

describe('turnToReplay — which turn a newly-opened document catches up to', () => {
  const frame: ReplayFrame = { node: 'a', path: ['a'], output: 'x' };
  const turn = (
    over: Partial<{ running: boolean; stopped: 'streaming' | 'paused' | null; activity: ReplayFrame[] }>,
  ) => ({ running: false, stopped: null, activity: [frame], ...over });

  it('prefers the run in progress', () => {
    // Unchanged: a live turn is still the one to project, and it is the only
    // one whose last card should glow.
    const live = turn({ running: true });
    const settled = turn({});
    expect(turnToReplay([settled, live])).toEqual({ turn: live, running: true });
  });

  it('falls back to the last finished run', () => {
    // Ticket 43. The gate used to stop here and show a static diagram, on the
    // reasoning that "a finished run leaves nothing to catch up to". The turn
    // keeps every frame — the trace and timeline are built from them — so the
    // history is right there, and the editor was showing a developer the run
    // only if they were quick enough to click.
    const older = turn({ activity: [{ node: 'old', path: ['old'], output: 'o' }] });
    const newer = turn({ activity: [{ node: 'new', path: ['new'], output: 'n' }] });
    expect(turnToReplay([older, newer])).toEqual({ turn: newer, running: false });
  });

  it('never resurrects a run the developer stopped', () => {
    // `AskPanel` marks every node `idle` on stop, deliberately (ticket 33).
    // Replaying it as a series of successes would undo that on the next
    // document opened, claiming steps completed that were abandoned.
    expect(turnToReplay([turn({ stopped: 'streaming' })])).toBeNull();
  });

  it('leaves a paused run alone', () => {
    // A run waiting on an approval is mid-flight, and its interrupt node is
    // `paused` — a state this projection does not model. Painting it as
    // finished would be a worse lie than painting nothing.
    expect(turnToReplay([turn({ stopped: 'paused' })])).toBeNull();
  });

  it('skips a stopped turn to reach a good one behind it', () => {
    const good = turn({ activity: [{ node: 'good', path: ['good'], output: 'g' }] });
    expect(turnToReplay([good, turn({ stopped: 'streaming' })])?.turn).toBe(good);
  });

  it('ignores a turn that produced no frames', () => {
    // A question that failed before its first frame has no history to show,
    // and an empty replay would blank a canvas rather than leave it alone.
    expect(turnToReplay([turn({ activity: [] })])).toBeNull();
  });

  it('is null for a conversation that has not run anything', () => {
    expect(turnToReplay([])).toBeNull();
  });
});
