import { describe, expect, it } from 'vitest';
import { OpenStreams } from './OpenStreams';

/**
 * Install-experience ticket 07, at the seam that was missing.
 *
 * The Ask panel is conditionally rendered (`AppShell.tsx`), so closing it is a
 * real unmount. It held its `AbortController`s in a bare `Map` inside a
 * `useRef`, `abort()` was reached from exactly one place — the Stop handler —
 * and the only unmount effect reported *not running* and aborted nothing. So
 * closing the panel mid-run left the `fetch` open and the reader looping into
 * a dead component, while the toolbar's Stop disappeared because the unmount
 * had just said the run ended: unstoppable from the UI, and still billing.
 *
 * The bug was **ownership**, one layer above the reader, and ownership is a
 * thing an object can hold. The map with a name is that object, and it is
 * where the two guarantees live rather than being spread across a component:
 * disposing closes everything still open, and a settled stream is dropped on
 * every path rather than on the paths someone remembered.
 */
describe('OpenStreams', () => {
  it('hands out a signal that is not yet aborted', () => {
    const streams = new OpenStreams();

    expect(streams.begin('turn-1').aborted).toBe(false);
  });

  it('aborts one stream by id', () => {
    const streams = new OpenStreams();
    const signal = streams.begin('turn-1');

    expect(streams.abort('turn-1')).toBe(true);
    expect(signal.aborted).toBe(true);
  });

  it('reports nothing to abort for an id it does not hold', () => {
    const streams = new OpenStreams();

    expect(streams.abort('never-started')).toBe(false);
  });

  it('drops a settled stream, so a later stop is honest about doing nothing', () => {
    const streams = new OpenStreams();
    streams.begin('turn-1');

    streams.settle('turn-1');

    expect(streams.size).toBe(0);
    expect(streams.abort('turn-1')).toBe(false);
  });

  it('settles an id it does not hold without complaint', () => {
    // `settle` runs in a `finally`, which is reached on paths that never
    // began — it must never be the thing that throws out of one.
    expect(() => new OpenStreams().settle('never-started')).not.toThrow();
  });

  describe('abortAll — the missing call', () => {
    it('aborts every stream still open', () => {
      const streams = new OpenStreams();
      const first = streams.begin('turn-1');
      const second = streams.begin('turn-2');

      streams.abortAll();

      expect(first.aborted).toBe(true);
      expect(second.aborted).toBe(true);
    });

    it('leaves nothing open, so "not running" is then true', () => {
      // The other half of the ticket: the unmount already reported
      // `running: false` to the toolbar. That report was a lie *because*
      // nothing had been aborted — it is true only after this.
      const streams = new OpenStreams();
      streams.begin('turn-1');

      streams.abortAll();

      expect(streams.size).toBe(0);
      expect(streams.hasOpenStream).toBe(false);
    });

    it('does not abort a stream that already settled', () => {
      const streams = new OpenStreams();
      const signal = streams.begin('turn-1');
      streams.settle('turn-1');

      streams.abortAll();

      expect(signal.aborted).toBe(false);
    });

    it('is idempotent', () => {
      const streams = new OpenStreams();
      streams.begin('turn-1');

      streams.abortAll();

      expect(() => streams.abortAll()).not.toThrow();
      expect(streams.size).toBe(0);
    });

    it('leaves the owner usable, because the panel is a toggle', () => {
      // Closing the panel stops its runs; reopening it must be able to start
      // one. A one-shot owner would have to be rebuilt on a boolean.
      const streams = new OpenStreams();
      streams.begin('turn-1');
      streams.abortAll();

      const next = streams.begin('turn-2');

      expect(next.aborted).toBe(false);
      expect(streams.hasOpenStream).toBe(true);
    });
  });

  it('reports whether anything is open at all', () => {
    const streams = new OpenStreams();
    expect(streams.hasOpenStream).toBe(false);

    streams.begin('turn-1');
    expect(streams.hasOpenStream).toBe(true);

    streams.settle('turn-1');
    expect(streams.hasOpenStream).toBe(false);
  });

  it('replaces a controller begun twice under one id', () => {
    // Not expected — one turn, one stream — but a silently orphaned
    // controller is exactly the failure this class exists to make impossible.
    const streams = new OpenStreams();
    const first = streams.begin('turn-1');

    const second = streams.begin('turn-1');

    expect(first.aborted).toBe(true);
    expect(second.aborted).toBe(false);
    expect(streams.size).toBe(1);
  });
});
