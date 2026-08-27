import { describe, expect, it } from 'vitest';

import { stoppedLine, type StoppedHow } from './stoppedLine';

/**
 * `async-first/07` — a run that was cancelled and a run that was abandoned
 * looked identical from the browser, and always had.
 *
 * The stop itself is instant either way, so nothing on the clock ever told
 * them apart. What differs is the work: measured live on 2026-08-27 against a
 * three-worker fan-out disconnected 12 s in, a cancellable step ended
 * 0.41–1.08 s after the stop and an uncancellable one 12.65–24.16 s. Until
 * this module the panel printed the *abandoned* sentence for both.
 */
describe('stoppedLine', () => {
  const of = (how: StoppedHow) => stoppedLine(how);

  it('tells a cancelled run apart from an abandoned one', () => {
    expect(of('cancelled')).not.toBe(of('abandoned'));
  });

  it('does not tell an abandoned run that nothing is still running', () => {
    expect(of('abandoned')).toMatch(/background/i);
    expect(of('abandoned')).toMatch(/discarded/i);
  });

  it('says a cancelled step was cancelled, and does not overclaim', () => {
    const line = of('cancelled');
    expect(line).toMatch(/cancelled/i);
    // A cancelled body still finishes the provider call it had already
    // issued, so "nothing is running" would be the next false readout.
    expect(line).not.toMatch(/nothing is (still )?running/i);
    expect(line).not.toMatch(/background/i);
  });

  it('keeps the paused sentence, which is about neither', () => {
    const line = of('paused');
    expect(line).toMatch(/resumed|resumable/i);
    expect(line).toMatch(/checkpointed/i);
  });

  it('opens every case the same way, because the developer did the same thing', () => {
    for (const how of ['cancelled', 'abandoned', 'paused'] as const) {
      expect(of(how)).toMatch(/^Stopped by you/);
    }
  });

  it('says nothing when the run was not stopped', () => {
    expect(stoppedLine(null)).toBe('');
  });
});

/**
 * The other half: how the panel decides which of the two it was. A stop lands
 * on whatever node was in charge, so the answer is the last thing the server
 * said about that node — never a guess from the document.
 */
describe('howAStopEnded', () => {
  it('is abandoned when nothing said otherwise', async () => {
    const { howAStopEnded } = await import('./stoppedLine');
    // The claim every run could always make, and the one a backend that
    // predates the field still earns.
    expect(howAStopEnded(false)).toBe('abandoned');
  });

  it('is cancelled when the node in charge was cancellable', async () => {
    const { howAStopEnded } = await import('./stoppedLine');
    expect(howAStopEnded(true)).toBe('cancelled');
  });
});
