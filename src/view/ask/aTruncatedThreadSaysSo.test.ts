import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { RuntimeClient } from '@core/runtime/RuntimeClient';
import { truncationLine } from '@core/runtime/pastRunView';

/**
 * A thread past the cap reads, in the editor, as a thread past the cap
 * (`the-cost-of-one-more/13`).
 *
 * Two halves, because the defect had two: the client parsed a response key it
 * never read, and the lane had nowhere to put it. The words themselves are
 * `pastRunView`'s and are tested there; this asserts that the fact travels
 * from the wire to the surface, which is the part `06` could not reach.
 *
 * The lane's half is asserted by **reading the component**, because this
 * repository has no DOM test harness and a component nobody renders in a test
 * is still a component that must call the function. Same idiom as
 * `nodes/compose/slugIsExplained.test.ts`.
 */
const panel = readFileSync(fileURLToPath(new URL('./PastRuns.tsx', import.meta.url)), 'utf8');

const response = {
  thread: { thread_id: 't', workflow_slug: 'w', status: 'finished', steps: 5000 },
  steps: [],
  truncation: {
    kept: 200,
    end: 'oldest',
    limit: 200,
    message: 'Only the newest 200 checkpoints of this run were read. Older ones are stored…',
  },
};

const clientReading = (payload: unknown): RuntimeClient =>
  new RuntimeClient('http://runtime', () =>
    Promise.resolve(new Response(JSON.stringify(payload), { status: 200 })),
  );

describe('a history that came back cut off', () => {
  it('is parsed off the response rather than dropped', async () => {
    const outcome = await clientReading(response).pastRun('t');

    expect(outcome.ok).toBe(true);
    expect(outcome.ok && outcome.value.truncation).toEqual({
      kept: 200,
      end: 'oldest',
      limit: 200,
      message: response.truncation.message,
    });
  });

  it('is null — not a zeroed row — when the whole thread came back', async () => {
    const whole = { ...response, truncation: null };
    const outcome = await clientReading(whole).pastRun('t');

    expect(outcome.ok && outcome.value.truncation).toBeNull();
  });

  it('reaches the History lane, where a reader is', () => {
    expect(panel).toContain('truncationLine');
    expect(panel).toContain('history.truncation');
  });

  it('is drawn at the oldest end, above the steps rather than after them', () => {
    // The gap is at the top of an oldest-first list, so the disclosure sits
    // where the missing supersteps would have been. A banner under the rows
    // would be true and in the wrong place.
    const note = panel.indexOf('truncationLine');
    const firstLane = panel.indexOf('past-runs__lane');

    expect(note).toBeGreaterThan(-1);
    expect(note).toBeLessThan(firstLane);
  });

  it('never repeats the server sentence, which offers a control this lane lacks', () => {
    // `truncation.message` is carried and deliberately not rendered — see
    // `PastRunTruncation.message`. The lane fetches with no `limit` and has no
    // way to raise one.
    expect(panel).not.toContain('truncation.message');
    expect(truncationLine({ kept: 200, end: 'oldest', limit: 200, message: 'x' })).not.toContain(
      'x',
    );
  });
});
