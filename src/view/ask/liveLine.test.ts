import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { liveLineAfterStep, type LiveLine } from './liveLine';

/**
 * `launch-readiness/110`. The owner's report against the MCP demo was "I
 * cannot see the narration", and the frames were on the wire the whole time —
 * ten `progress` frames in one captured run. What the panel did with them was
 * the defect: **every** `update` blanked the live line, and a narration line
 * is written by a middleware that is *itself* a traced step, so the very next
 * frame after each line was that middleware's own completion. The line was on
 * screen for milliseconds.
 *
 * The captured order, which is what these cases are built from:
 *
 * ```
 * progress  NarrationMiddleware.before_model  "Thinking about the next step."
 * update    NarrationMiddleware.before_model      <- erased its own line
 * token x624                                      <- 40s of silence
 * update    model
 * ```
 */
describe('liveLineAfterStep', () => {
  const thinking: LiveLine = {
    node: 'NarrationMiddleware.before_model',
    text: 'Thinking about the next step.',
  };

  it('keeps the line when the step that spoke is the step that completed', () => {
    // A step cannot make its own announcement stale: `before_model` says what
    // the *model* is about to do, and then the hook ends. The model has not
    // run yet.
    expect(liveLineAfterStep(thinking, 'NarrationMiddleware.before_model')).toEqual(thinking);
  });

  it('clears the line when any other step completes', () => {
    // The model call the line was about has now finished, so the line is
    // spent. This is the half that was always right and must not regress.
    expect(liveLineAfterStep(thinking, 'model')).toBeNull();
  });

  it('clears a tool line once a later step completes', () => {
    // The case the original comment named: "Calling mcp_list_lenses on
    // http://localhost:8080/mcp/" must not outlive the tool call. `tools`
    // completing does not clear it any more — the step that spoke never
    // clears itself — but the next step's `update` does, which is one frame
    // and a few milliseconds later.
    const calling: LiveLine = {
      node: 'tools',
      text: 'Calling mcp_list_lenses on http://localhost:8080/mcp/',
    };
    expect(liveLineAfterStep(calling, 'tools')).toEqual(calling);
    expect(liveLineAfterStep(calling, 'SummarizationMiddleware.before_model')).toBeNull();
  });

  it('has nothing to clear when no line is showing', () => {
    expect(liveLineAfterStep(null, 'model')).toBeNull();
  });
});

/**
 * The pure function above is worth nothing if the panel keeps its own copy of
 * the rule — which is exactly how this defect existed: the clear was a bare
 * `progress: null` inlined in the `update` handler, invisible from every test
 * in this directory. Pinned at the source, in the spirit of `progressLine`'s
 * own note that the thing that goes wrong here cannot be seen from the panel.
 */
describe('AskPanel uses it', () => {
  const source = readFileSync(new URL('./AskPanel.tsx', import.meta.url), 'utf8');

  it('clears the live line through liveLineAfterStep, never by hand', () => {
    expect(source).toContain('liveLineAfterStep(');
    // One `progress: null` is legitimate — a fresh turn starts with no line.
    // Two means the `update` handler is blanking it again.
    expect(source.match(/progress: null/g) ?? []).toHaveLength(1);
  });
});
