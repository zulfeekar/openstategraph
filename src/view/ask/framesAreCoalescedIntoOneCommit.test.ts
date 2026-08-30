import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * An arriving frame is queued, not committed — `the-cost-of-one-more/20`.
 *
 * A **proxy**, declared as one, and for the same reason `15`'s
 * `runningReportIsAboutState.test.ts` is: the claim is about how many times
 * React commits during a burst, which needs a real React, real passive-effect
 * flushing and real chunk arrival with no macrotask between. The unit suite
 * runs in `node` with no DOM on purpose (`vite.config.ts`). The claim itself
 * is asserted where it is visible — `e2e/aBurstOfFramesFinishesInHumanTime.spec.ts`
 * drives ten thousand frames at a real browser.
 *
 * What this file adds is that it runs on **every change**, which the e2e suite
 * does not, and it fails on the one edit that would silently undo the fix:
 * putting a `setTurns` back into the append path. That edit is easy to make by
 * accident, because every other branch of `onEvent` legitimately calls
 * `setTurns` and the append branch used to look exactly like them.
 *
 * The three properties, and why each is load-bearing:
 *
 *  - the `update` and `spawn` branches **queue**;
 *  - every other event **flushes first**, so `settled`'s rewrite of the rows
 *    and `token`'s append to the thinking text see a drained buffer and the
 *    order on screen is the order the wire produced;
 *  - the stream's `finally` flushes, so a run that ends without a frame or a
 *    timer firing — a stop, a dropped socket — still lands its rows.
 */

const SOURCE = readFileSync(join(import.meta.dirname, 'AskPanel.tsx'), 'utf-8');

/** The body of `onEvent`, which is where all four properties live. */
function onEventBody(): string {
  const start = SOURCE.indexOf('const onEvent = (event: RunStreamEvent) => {');
  expect(start, 'onEvent has moved or been renamed').toBeGreaterThan(-1);
  const end = SOURCE.indexOf('\n      };', start);
  return SOURCE.slice(start, end);
}

/** One branch of the `if (event.type === …)` chain. */
function branch(type: string): string {
  const body = onEventBody();
  const start = body.indexOf(`event.type === '${type}'`);
  expect(start, `there is no ${type} branch any more`).toBeGreaterThan(-1);
  const next = body.indexOf('} else if (event.type ===', start + 1);
  return body.slice(start, next === -1 ? undefined : next);
}

describe('an arriving row is queued for the next paint, not committed on its own', () => {
  it('appends through the queue on both branches that append', () => {
    for (const type of ['update', 'spawn']) {
      expect(branch(type), `the ${type} branch stopped queueing`).toContain('queueRow(');
      expect(branch(type), `the ${type} branch commits per frame again`).not.toContain('setTurns(');
    }
  });

  it('drains the queue before every event that is not an append', () => {
    expect(onEventBody()).toContain(
      "if (event.type !== 'update' && event.type !== 'spawn') flushRows();",
    );
  });

  it('drains it once more whatever ended the stream', () => {
    const tail = SOURCE.slice(SOURCE.indexOf('outcome = await call(onEvent, signal);'));
    expect(tail.slice(0, tail.indexOf('streams.settle(id);'))).toContain('flushRows();');
  });

  it('schedules on a frame, with a timer behind it for a tab that gets no frames', () => {
    expect(SOURCE).toContain('pendingFrame = requestAnimationFrame(flushRows)');
    expect(SOURCE).toContain('pendingTimer = setTimeout(flushRows, 250)');
  });
});
