import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';

/**
 * `canvas-feels-right/07`, the canvas half.
 *
 * The ticket's fourth boundary is a *layout* promise, and a layout promise
 * has no way to fail on its own:
 *
 * > **Layout.** The canvas is JointJS and node positions are the user's. An
 * > overlay that moves their nodes is worse than no overlay.
 *
 * On this canvas that is mechanical rather than aesthetic. `NodeCard`
 * measures its own `getBoundingClientRect()`, reports the height to
 * `paper.adapter.applyGeometry`, and hands it to
 * `controller.nodes.applyMeasuredSize` — so a rail rendered into the card's
 * *flow* would grow the element on the paper, move every port dot on it and
 * re-route its links, because a run happened. The saved file would survive
 * (`production-ready/69`, `measuredHeightIsNotDocument.test.ts`); the
 * layout on screen would not.
 *
 * The one property that carries the promise is that the rail is out of the
 * card's box, and one CSS declaration is the whole of it. This suite pins
 * that declaration, in the spirit `pillIsNotANode.test.ts` established:
 * the rest — that the popover opens, that a pan closes it — is verified in
 * the browser, because this suite runs in `node` on purpose.
 */

const css = readFileSync(new URL('./CardSpawnedPills.css', import.meta.url), 'utf8');
const rail = readFileSync(new URL('./CardSpawnedPills.tsx', import.meta.url), 'utf8');
const card = readFileSync(new URL('../nodes/NodeCard.tsx', import.meta.url), 'utf8');

describe('a chip hangs off a card without moving anybody’s layout', () => {
  it('is taken out of flow, so the card measures what it measured before', () => {
    expect(css).toMatch(/\.node__spawned\s*\{[^}]*position:\s*absolute/);
  });

  it('hangs above the top edge, because the bottom edge is a port anchor', () => {
    // `.node__pill` — the tool bus capsule — straddles the bottom edge and
    // *is* measured, as the anchor a bus port's dot is placed from. The
    // ports footer is there too. Nothing hangs above the header.
    expect(css).toMatch(/\.node__spawned\s*\{[^}]*bottom:\s*100%/);
  });

  it('wraps upward rather than scrolling, so forty children are forty chips', () => {
    // The ticket worried about the forty-spawn case. Answered by layout, not
    // by a rule: a horizontal scroller would hide the tail at exactly the
    // moment the count is the point.
    expect(css).toMatch(/flex-wrap:\s*wrap/);
    expect(css).toMatch(/align-content:\s*end/);
  });

  it('lets a pan or a marquee through the space beside a chip', () => {
    // The rail spans the card's whole width and is mostly empty. If that
    // empty space took the pointer, a drag begun beside a chip would hit an
    // invisible box instead of the paper.
    expect(css).toMatch(/\.node__spawned\s*\{[^}]*pointer-events:\s*none/);
    expect(css).toMatch(/\.node__spawned\s*>\s*\*\s*\{[^}]*pointer-events:\s*auto/);
  });

  it('carries no `data-port-row`, so the measurement pass never finds it', () => {
    // `NodeCard.report()` walks `[data-port-row]` to place every port dot.
    // A rail wearing one would be measured as an anchor and would place a
    // port in mid-air.
    expect(rail).not.toMatch(/data-port-row/);
  });
});

describe('a popover survives what JointJS does to its chip', () => {
  it('is told when the paper moved, because the DOM will not raise it', () => {
    // Measured live on `parallel-workers-join`: a wheel-zoom over the paper
    // moved the chip from y=406 to y=540 and left the popover at y=427. A
    // wheel is not a pointer-down, so the close never fired; and JointJS
    // zooms by rewriting an SVG transform, so neither `scroll` nor `resize`
    // fired either. `paper.viewport.onChange` is the only signal there is,
    // and the canvas layer is the only place that holds it — which is why
    // this arrives at `design/` as a subscription and not as a flag.
    expect(rail).toMatch(/paper\?\.viewport\.onChange\(update\)/);
    expect(rail).toMatch(/subscribeAnchorMoved=\{subscribeAnchorMoved\}/);
  });

  it('opens downward, so the account covers the card it is about', () => {
    // The chip already sits above the card. A popover above the chip would
    // be a second thing climbing away from the node it describes.
    expect(rail).toMatch(/placement="bottom"/);
  });
});

describe('a chip is run state, and nothing else', () => {
  it('is drawn from `node.runtime.spawned`, never from the document', () => {
    expect(card).toMatch(/spawned=\{node\.runtime\.spawned\}/);
  });

  it('reaches no controller and issues no command', () => {
    // "Nothing here writes to the graph. Not one gesture, not one temporary
    // node." A rail that imported a controller could not make that promise,
    // whatever its props said.
    expect(rail).not.toMatch(/useController|ICommand|useWorkbench|dispatch\(/);
  });
});
