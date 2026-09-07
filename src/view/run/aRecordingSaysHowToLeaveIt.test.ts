import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const dock = readFileSync(fileURLToPath(new URL('./RunDock.tsx', import.meta.url)), 'utf8');

/**
 * The way back, pinned on the surface that still exists after the picker is
 * closed — `memory-and-replay` 73.
 *
 * The owner asked for it explicitly: *"there must be a UX way to get back to
 * the selected / current workflow timeline at any time."* The list has one
 * too, and the list is a popover: it closes on a click outside, on Escape, and
 * on the control that opened it. So a control that lives only there is a
 * control a reader loses the moment they look at the chart they came for,
 * which is exactly *the* moment they want it.
 *
 * Asserted against the source for the reason `topbarSurface.test.ts` is: this
 * is a claim about a control existing on a surface, and a rendered-DOM test
 * for it needs the whole shell, a store and a stylesheet to say one thing.
 */
describe('the dock offers the way out of a recording', () => {
  it('carries a control back to the live run', () => {
    expect(dock).toContain('Back to this tab');
    expect(dock).toContain('runView.release()');
  });

  it('offers it only over a recording', () => {
    // A live run has nothing to go back *to*, and a control that is always
    // there and does nothing most of the time is a control nobody reads.
    expect(dock).toMatch(/view\.source === 'stored'[\s\S]{0,400}Back to this tab/);
  });

  it('still calls a recording a stored run, rather than growing a second word', () => {
    // `runView.source` has said `stored` since 51 and the header has printed
    // *Stored run* since 61. A recording is that, and inventing a second
    // vocabulary for it is how one surface comes to have two.
    expect(dock).toContain("view.source === 'stored' ? 'Stored run'");
  });
});
