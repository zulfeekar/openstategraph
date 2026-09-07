/**
 * How a child's ending reads, and what it must never claim —
 * `memory-and-replay` 54.
 *
 * The `settled` frame's `outcome` is four words and two of them are about the
 * *recording* rather than about the child. A surface that flattens them into
 * "finished" or "failed" would report a background worker that is still
 * working, and a run whose recording stopped, as facts about a worker.
 */
import { describe, expect, it } from 'vitest';
import { spawnEnding, type SpawnDetail } from './traceTree';

describe('a spawn row says how its child ended', () => {
  it('says nothing at all while the child is still open', () => {
    // The absent case is the common one — a spawn arrives long before its
    // close — and inventing a word for it would make every live child read
    // as a finished one.
    expect(spawnEnding(undefined)).toBe('');
  });

  it('does not call a background worker finished', () => {
    // `async` is the kind nothing on the stream ever closes: the parent does
    // not wait, and the run ending is not the child ending.
    expect(spawnEnding('detached')).toBe('still running');
  });

  it('does not call an unaccounted child failed', () => {
    expect(spawnEnding('unknown')).toBe('no ending recorded');
  });

  it('reserves failure for a child that never ran', () => {
    expect(spawnEnding('error')).toBe('never ran');
    expect(spawnEnding('ok')).toBe('finished');
  });

  it('gives every outcome the contract declares a sentence of its own', () => {
    const outcomes: NonNullable<SpawnDetail['outcome']>[] = ['ok', 'error', 'detached', 'unknown'];
    const said = outcomes.map(spawnEnding);

    expect(new Set(said).size).toBe(outcomes.length);
    expect(said.filter((line) => line === '')).toEqual([]);
  });
});
