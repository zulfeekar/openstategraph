import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { transportOffered } from './replayTransport';

/**
 * A run in flight draws **no vertical line at all**.
 *
 * `memory-and-replay` 63, the owner: *"While running live there is no vertical
 * scrubber line; once the agent is done the user can scrub, move, replay."*
 *
 * `52` had already settled that a live run gets no *scrubber* — there is no
 * right-hand edge to reach — and that half shipped. What shipped beside it was
 * a playhead pinned to the head by `[data-live]`, gated on `totalMs !== null`
 * rather than on the transport. Read as a control, that is a control's whole
 * affordance with none of its behaviour: a bright rule down the chart that
 * cannot be moved, at the one place a growing chart already ends. Read as a
 * measurement — which is the harder charge, on a surface whose promise is that
 * it never claims what it did not measure — it is a mark at "now" on an axis
 * of *elapsed offsets*, and "now" is not one of them.
 *
 * So the rule is one predicate, not two: **the playhead and the scrubber are
 * offered together or not at all.** Two predicates for one decision is how the
 * live case ends up half-answered again.
 */
const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

describe('a live run', () => {
  it('is offered no transport, however long it has been running', () => {
    // The predicate itself, which `52` wrote and this ticket did not change.
    expect(transportOffered(true, 24_100)).toBe(false);
    expect(transportOffered(false, 24_100)).toBe(true);
    // And a recording with no clock has no axis to put a line on either
    // (`launch-readiness` 108) — an axis with no measurements is not a slow
    // axis.
    expect(transportOffered(false, null)).toBe(false);
  });

  it('gates the playhead on that same predicate, not on a second one', () => {
    const chart = read('../ask/RunTimeline.tsx');
    // The playhead is rendered under `offered`, which is `transportOffered`'s
    // one answer, read once at the top of the component.
    expect(chart).toMatch(/\{offered \? \(\s*\n\s*<div\s*\n\s*className="rtl__playhead"/);
    // And the shape it replaced does not come back under another name.
    expect(chart).not.toMatch(
      /totalMs !== null \? \(\s*\n\s*<div\s*\n\s*className="rtl__playhead"/,
    );
  });

  it('leaves no rule behind that only a live playhead could have used', () => {
    // `[data-live]` parked the line at the right-hand edge. With no live
    // playhead to park, a stylesheet still carrying the rule is a stylesheet
    // describing a state the component can no longer produce — which is the
    // reading a later session would take as permission to produce it again.
    const styles = read('./RunDock.css');
    expect(styles).toContain('.rtl__playhead');
    expect(styles).not.toMatch(/\.rtl__playhead\[data-live\]/);
    // The attribute, not the word: the line above the JSX says what used to be
    // there, and a test that forbade naming it would forbid the record of it.
    expect(read('../ask/RunTimeline.tsx')).not.toMatch(/data-live=/);
  });
});
