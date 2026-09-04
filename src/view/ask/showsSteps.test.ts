import { describe, expect, it } from 'vitest';

import { showsSteps } from './showsSteps';

/**
 * `stable-beta-public/08` — a finished turn with steps (now in the run dock,
 * `memory-and-replay/51`) but no live line and no hand-off pill still opened
 * the sunken `.ask__steps` strip around nothing.
 */
describe('showsSteps', () => {
  it('shows the box while the turn is running', () => {
    expect(showsSteps({ running: true, hasPills: false })).toBe(true);
  });

  it('shows the box for a finished turn that spawned a pill', () => {
    expect(showsSteps({ running: false, hasPills: true })).toBe(true);
  });

  it('hides the box for a finished turn with no pills — the empty-box case', () => {
    expect(showsSteps({ running: false, hasPills: false })).toBe(false);
  });
});
