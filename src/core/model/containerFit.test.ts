import { describe, expect, it } from 'vitest';
import { GROUP } from '@design/tokens';
import { depthFirstOrder, fitContainers, type ContainerShape } from './containerFit';

const PAD = GROUP.padding;
const MIN = { width: GROUP.minWidth, height: GROUP.minHeight };

const rect = (x: number, y: number, width = 100, height = 60) => ({ x, y, width, height });

describe('fitContainers', () => {
  it('wraps its children with the padding, which is asymmetric on purpose', () => {
    // `top: 128` is the frame's title bar. A symmetric fit would tuck the
    // first card under the title, which is the one thing the padding exists
    // to prevent — so the test states the numbers rather than a shape.
    const containers: ContainerShape[] = [
      { id: 'g1', childIds: ['a', 'b'], rect: rect(0, 0, 280, 200) },
    ];
    const leaves = new Map([
      ['a', rect(500, 400)],
      ['b', rect(700, 500)],
    ]);
    const fits = fitContainers(containers, leaves, PAD, MIN);

    // children span x 500–800, y 400–560
    expect(fits.get('g1')).toEqual({
      x: 500 - PAD.left,
      y: 400 - PAD.top,
      width: 300 + PAD.left + PAD.right,
      height: 160 + PAD.top + PAD.bottom,
    });
  });

  it('leaves a childless container exactly where it is', () => {
    // Never collapse to zero: an empty frame is a label somebody placed, and
    // shrinking it to nothing would look like the layout deleted it.
    const before = rect(10, 20, 400, 300);
    const fits = fitContainers([{ id: 'g1', childIds: [], rect: before }], new Map(), PAD, MIN);
    expect(fits.get('g1')).toBeUndefined();
  });

  it('leaves a container alone when none of its children can be located', () => {
    const before = rect(10, 20, 400, 300);
    const fits = fitContainers(
      [{ id: 'g1', childIds: ['ghost'], rect: before }],
      new Map(),
      PAD,
      MIN,
    );
    expect(fits.get('g1')).toBeUndefined();
  });

  it('honours the minimum size without moving the top-left away from the children', () => {
    const fits = fitContainers(
      [{ id: 'g1', childIds: ['a'], rect: rect(0, 0) }],
      new Map([['a', rect(500, 400, 10, 10)]]),
      PAD,
      MIN,
    );
    const fitted = fits.get('g1')!;
    expect(fitted.width).toBe(GROUP.minWidth);
    expect(fitted.height).toBe(GROUP.minHeight);
    // The frame grows right and down; the padding above the first card is
    // still exactly the title-bar padding.
    expect(fitted.x).toBe(500 - PAD.left);
    expect(fitted.y).toBe(400 - PAD.top);
  });

  it('fits the innermost container first, so an outer frame wraps the fitted inner one', () => {
    // The ordering is the whole point of doing this as a graph rather than a
    // loop: an outer frame measured against the *old* inner rect would be
    // wrong by however much the inner one changed.
    const containers: ContainerShape[] = [
      { id: 'outer', childIds: ['inner', 'c'], rect: rect(0, 0, 280, 200) },
      { id: 'inner', childIds: ['a', 'b'], rect: rect(0, 0, 280, 200) },
    ];
    const leaves = new Map([
      ['a', rect(500, 400)],
      ['b', rect(700, 400)],
      ['c', rect(500, 900)],
    ]);
    const fits = fitContainers(containers, leaves, PAD, MIN);

    const inner = fits.get('inner')!;
    expect(inner).toEqual({
      x: 500 - PAD.left,
      y: 400 - PAD.top,
      width: 300 + PAD.left + PAD.right,
      height: 60 + PAD.top + PAD.bottom,
    });

    // The outer frame wraps the *fitted* inner rect, not the one it had.
    const outer = fits.get('outer')!;
    expect(outer.x).toBe(inner.x - PAD.left);
    expect(outer.y).toBe(inner.y - PAD.top);
    expect(outer.x + outer.width).toBe(Math.max(inner.x + inner.width, 600) + PAD.right);
  });

  it('does not hang on a container that contains itself', () => {
    // The model should never produce this. A pure function that loops forever
    // on bad input is still a bug, and a canvas that freezes is unrecoverable.
    const fits = fitContainers(
      [
        { id: 'a', childIds: ['b'], rect: rect(0, 0) },
        { id: 'b', childIds: ['a'], rect: rect(0, 0) },
      ],
      new Map(),
      PAD,
      MIN,
    );
    expect(fits.size).toBe(0);
  });

  it('rounds to whole units, because positions are compared for equality', () => {
    const fits = fitContainers(
      [{ id: 'g1', childIds: ['a'], rect: rect(0, 0) }],
      new Map([['a', { x: 500.4, y: 400.6, width: 100.2, height: 60.9 }]]),
      PAD,
      MIN,
    );
    const fitted = fits.get('g1')!;
    for (const value of Object.values(fitted)) expect(Number.isInteger(value)).toBe(true);
  });
});

describe('depthFirstOrder', () => {
  const parents = new Map([
    ['inner', 'outer'],
    ['a', 'inner'],
    ['b', 'inner'],
    ['c', 'outer'],
  ]);
  const parentOf = (id: string) => parents.get(id) ?? null;

  it('puts an ancestor before its descendants', () => {
    // Load-bearing, not tidiness. The adapter applies a container's move with
    // `{ deep: true }` — moving a frame translates its children in the graph
    // even though the model moved only the frame — so every descendant has to
    // be re-asserted at its absolute position *after* its ancestor moved.
    const order = depthFirstOrder(['a', 'b', 'inner', 'outer', 'c'], parentOf);
    expect(order.indexOf('outer')).toBeLessThan(order.indexOf('inner'));
    expect(order.indexOf('inner')).toBeLessThan(order.indexOf('a'));
    expect(order.indexOf('inner')).toBeLessThan(order.indexOf('b'));
    expect(order.indexOf('outer')).toBeLessThan(order.indexOf('c'));
  });

  it('keeps every id exactly once', () => {
    const ids = ['a', 'b', 'inner', 'outer', 'c'];
    expect([...depthFirstOrder(ids, parentOf)].sort()).toEqual([...ids].sort());
  });

  it('is stable for unparented nodes', () => {
    expect(depthFirstOrder(['x', 'y', 'z'], () => null)).toEqual(['x', 'y', 'z']);
  });

  it('does not hang on a parent cycle', () => {
    const cycle = new Map([
      ['p', 'q'],
      ['q', 'p'],
    ]);
    expect(depthFirstOrder(['p', 'q'], (id) => cycle.get(id) ?? null)).toHaveLength(2);
  });
});
