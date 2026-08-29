import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';

/**
 * `canvas-feels-right/07`. The ticket's hardest constraint is a *look*, and a
 * look has no way to fail on its own:
 *
 * > Whatever it looks like must be **visibly not-savable**… A ghost node
 * > risks reading as part of the document — which is the failure this ticket
 * > exists to avoid.
 *
 * So the properties that carry that promise are pinned here rather than
 * described in the stylesheet's own comment, for the reason CLAUDE.md gives
 * twice: an argument with no way to fail is a story. The three below are the
 * ones a later restyle would quietly take away.
 *
 * The rest of this component — that the popover opens, that it closes on
 * click-outside — is verified in the browser, which is this repository's
 * stated approach for `view/` and `design/` (`vite.config.ts`: the suite runs
 * in `node`, on purpose). What a unit test *can* hold is the source.
 */

const css = readFileSync(new URL('./Pill.css', import.meta.url), 'utf8');
const tsx = readFileSync(new URL('./Pill.tsx', import.meta.url), 'utf8');

describe('a pill is visibly not a node', () => {
  it('is a stadium, which no node card on this canvas is', () => {
    expect(css).toMatch(/border-radius:\s*999px/);
  });

  it('wears a dashed outline, which nothing savable does', () => {
    expect(css).toMatch(/border:\s*1px dashed/);
  });

  it('borrows no node styling at all', () => {
    // A pill that reached for `.node`'s tokens would drift back towards
    // looking like a card every time those tokens moved.
    expect(css).not.toMatch(/^\s*\.node/m);
    expect(css).not.toMatch(/--radius-node/);
  });
});

describe('a pill writes nothing', () => {
  it('reaches no controller, command, or model', () => {
    // "Nothing here writes to the graph. Not one gesture, not one temporary
    // node." A primitive that imported a controller could not make that
    // promise, whatever its props said.
    expect(tsx).not.toMatch(/useController|ICommand|Workbench|@core\//);
  });

  it('keeps whether a popover is open out of run state', () => {
    // Uncontrolled by design: a reader having one open is not a fact about
    // the run, so there is no prop by which it could become one.
    expect(tsx).toMatch(/useState\(false\)/);
    expect(tsx).not.toMatch(/onOpenChange/);
  });
});

describe('a pill survives the canvas', () => {
  it('closes on the capture phase, the way `Menu` had to', () => {
    // JointJS installs its own document-level pointer handlers, and a
    // popover that lost that race would sit open under a pan it never saw.
    expect(tsx).toMatch(/addEventListener\('pointerdown', onPointerDown, true\)/);
  });

  it('portals out, so no paper viewport can clip it', () => {
    expect(tsx).toMatch(/createPortal\(/);
    expect(tsx).toMatch(/document\.body/);
  });

  it('swallows the gestures the canvas would otherwise take', () => {
    // A wheel over the popover must scroll the account, not zoom the paper;
    // a pointer-down on the chip must not start a node drag.
    expect(tsx).toMatch(/onWheel=\{\(event\) => event\.stopPropagation\(\)\}/);
    expect(tsx).toMatch(/onPointerDown=\{\(event\) => event\.stopPropagation\(\)\}/);
  });

  it('closes on Escape as well as on click-outside', () => {
    expect(tsx).toMatch(/'Escape'/);
  });
});

describe('a pill keeps its popover on a chip the canvas moved', () => {
  it('takes a subscription rather than knowing what a paper is', () => {
    // `design/` imports neither React-canvas nor JointJS, so it cannot ask
    // the paper anything. It is *told*, by whoever knows — which on the
    // canvas is `CardSpawnedPills` handing in `paper.viewport.onChange`.
    expect(tsx).toMatch(/subscribeAnchorMoved\?:\s*\(update: \(\) => void\) => \(\) => void/);
    // Prose may name the paper — the reason is the point. Code may not
    // reach for it.
    expect(tsx).not.toMatch(/from '@(canvas|joint)/);
    expect(tsx).not.toMatch(/viewport\./);
  });

  it('leaves a surface that passes nothing exactly as it was', () => {
    // The chat panel has no such signal and needs none: its chips sit in an
    // ordinary scrolling panel, which `scroll` and `resize` already cover.
    expect(tsx).toMatch(
      /\.\.\.\(subscribeAnchorMoved \? \{ subscribe: subscribeAnchorMoved \} : \{\}\)/,
    );
  });
});
