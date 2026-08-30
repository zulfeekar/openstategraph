/**
 * The transport, and the four things it must refuse to claim.
 *
 * `memory-and-replay` 52. Every assertion here is a claim about *time*, which
 * is what a transport is: a set of them, each of which can be false.
 */
import { describe, expect, it } from 'vitest';
import {
  REPLAY_SPEEDS,
  ReplayTransport,
  nextStop,
  previousStop,
  stopsOf,
  transportOffered,
} from './replayTransport';
import { buildLanes, type TimelineRow } from '../ask/timeline';

const clocked: TimelineRow[] = [
  { node: 'in1', taskId: null, internal: false, elapsedMs: 100 },
  { node: 'agent', taskId: null, internal: false, elapsedMs: 900 },
  { node: 'out1', taskId: null, internal: false, elapsedMs: 1200 },
];

describe('the stops a step moves between', () => {
  it('are frame offsets, never a grid of seconds', () => {
    // The owner settled the unit: "the useful unit is what happened next, and
    // a 10-second model call is one thing happening". A second-grid would cost
    // ten presses to cross one event and would invent a granularity the
    // recording does not have.
    const { lanes, totalMs } = buildLanes(clocked);
    expect(stopsOf(lanes, totalMs)).toEqual([0, 100, 900, 1200]);
  });

  it('give an unclocked bar no stop rather than a stop at zero', () => {
    const { lanes, totalMs } = buildLanes([
      { node: 'in1', taskId: null, internal: false },
      { node: 'out1', taskId: null, internal: false },
    ]);
    expect(totalMs).toBeNull();
    expect(stopsOf(lanes, totalMs)).toEqual([0]);
  });

  it('walk forward and back and stop at the ends', () => {
    const stops = [0, 100, 900, 1200];
    expect(nextStop(stops, 0, 1200)).toBe(100);
    expect(nextStop(stops, 1200, 1200)).toBe(1200);
    expect(previousStop(stops, 900)).toBe(100);
    expect(previousStop(stops, 0)).toBe(0);
  });
});

describe('what the control refuses to exist for', () => {
  it('is a live run, which has no right-hand edge to reach', () => {
    expect(transportOffered(true, 1200)).toBe(false);
  });

  it('is a recording with no clock, which is not a slow axis but no axis', () => {
    expect(transportOffered(false, null)).toBe(false);
    expect(transportOffered(false, 0)).toBe(false);
  });
});

describe('the transport itself', () => {
  const fresh = (): ReplayTransport => {
    const transport = new ReplayTransport();
    transport.attach([0, 100, 900, 1200], 1200);
    return transport;
  };

  it('opens paused at zero — there is no autoplay', () => {
    // "Someone opening a finished run is usually looking for a moment, not
    // watching a film."
    expect(fresh().read()).toMatchObject({ playing: false, atMs: 0, rate: 1 });
  });

  it('rewinds when it is pointed at a different recording', () => {
    const transport = fresh();
    transport.seek(900);
    transport.attach([0, 50], 50);
    // A playhead left at 900 ms over a 50 ms run is a control pointing at
    // nothing.
    expect(transport.read()).toMatchObject({ atMs: 0, playing: false, totalMs: 50 });
  });

  it('stays silent when handed the same recording twice, so a live run does not stutter', () => {
    const transport = fresh();
    transport.seek(900);
    let woken = 0;
    transport.subscribe(() => {
      woken += 1;
    });
    transport.attach([0, 100, 900, 1200], 1200);
    expect(woken).toBe(0);
    expect(transport.read().atMs).toBe(900);
  });

  it('clamps a seek to the recording rather than running off either end', () => {
    const transport = fresh();
    transport.seek(-500);
    expect(transport.read().atMs).toBe(0);
    transport.seek(99_999);
    expect(transport.read().atMs).toBe(1200);
  });

  it('stops the film whenever the reader points at something', () => {
    const transport = fresh();
    transport.toggle();
    expect(transport.read().playing).toBe(true);
    transport.seek(300);
    expect(transport.read().playing).toBe(false);
    transport.toggle();
    transport.stepForward();
    expect(transport.read()).toMatchObject({ playing: false, atMs: 900 });
  });

  it('replays from the start once it has reached the end', () => {
    const transport = fresh();
    transport.seek(1200);
    transport.toggle();
    expect(transport.read()).toMatchObject({ playing: true, atMs: 0 });
  });

  it('does nothing at all without an end to move towards', () => {
    const transport = new ReplayTransport();
    transport.attach([0], null);
    transport.toggle();
    expect(transport.read().playing).toBe(false);
  });

  it('offers three rates, because a fourth button is width and not a choice', () => {
    expect(REPLAY_SPEEDS).toEqual([1, 2, 8]);
    const transport = fresh();
    transport.setRate(8);
    expect(transport.read().rate).toBe(8);
  });
});
