import { describe, expect, it } from 'vitest';
import { bottomPortOffsets } from './bottomPorts';

const WIDTH = 252;

describe('bottomPortOffsets', () => {
  it('centres a lone bus, matching what CSS does to the pill graphic', () => {
    // `.node__pill` is `left: 50%`. With one bottom port the old
    // `spread(0, 1)` also gave width/2, which is why the two agreed by
    // accident for as long as a card had exactly one bus.
    const offsets = bottomPortOffsets([{ id: 'tools', isPill: true }], WIDTH, {
      centre: WIDTH / 2,
      left: 80,
    });
    expect(offsets.get('tools')).toBe(126);
  });

  it('keeps the bus dot on the bus when a second port joins the edge', () => {
    // The regression this function exists to prevent: `spread(1, 2)` would
    // put the tool bus dot at 168 while its pill stayed drawn at 126, so the
    // link would arrive at empty space beside the thing it binds to.
    const offsets = bottomPortOffsets(
      [
        { id: 'skill', isPill: false },
        { id: 'tools', isPill: true },
      ],
      WIDTH,
      { centre: WIDTH / 2, left: 80 },
    );
    expect(offsets.get('tools')).toBe(126);
  });

  it('places a plain port clear of the pill, in the space the pill leaves', () => {
    const offsets = bottomPortOffsets(
      [
        { id: 'skill', isPill: false },
        { id: 'tools', isPill: true },
      ],
      WIDTH,
      { centre: WIDTH / 2, left: 80 },
    );
    // Half of the 0–80 band the pill's left edge leaves free.
    expect(offsets.get('skill')).toBe(40);
    expect(offsets.get('skill')!).toBeLessThan(80);
  });

  it('follows a wide pill inward rather than overlapping a long label', () => {
    // Measured, not assumed: the free band is whatever the rendered pill
    // leaves, so a longer label pushes the plain dot further left on its own.
    const narrow = bottomPortOffsets(
      [
        { id: 'skill', isPill: false },
        { id: 'tools', isPill: true },
      ],
      WIDTH,
      { centre: WIDTH / 2, left: 100 },
    );
    const wide = bottomPortOffsets(
      [
        { id: 'skill', isPill: false },
        { id: 'tools', isPill: true },
      ],
      WIDTH,
      { centre: WIDTH / 2, left: 40 },
    );
    expect(wide.get('skill')!).toBeLessThan(narrow.get('skill')!);
  });

  it('spreads plain ports across the whole edge when there is no pill', () => {
    // Vertical flow puts every flow output on this edge and none of them is
    // a bus; the original even spread is still right for that case.
    const offsets = bottomPortOffsets(
      [
        { id: 'a', isPill: false },
        { id: 'b', isPill: false },
        { id: 'c', isPill: false },
      ],
      WIDTH,
      null,
    );
    expect([...offsets.values()]).toEqual([63, 126, 189]);
  });

  it('never stacks two ports on one point', () => {
    const offsets = bottomPortOffsets(
      [
        { id: 'skill', isPill: false },
        { id: 'feedback', isPill: false },
        { id: 'tools', isPill: true },
      ],
      WIDTH,
      { centre: WIDTH / 2, left: 80 },
    );
    expect(new Set(offsets.values()).size).toBe(3);
  });

  it('is empty for an edge with no ports on it', () => {
    expect(bottomPortOffsets([], WIDTH, null).size).toBe(0);
  });

  it('degrades to the even spread if the pill has not been measured yet', () => {
    // First paint: the rect is not available until the pill is in the DOM.
    // An unmeasured pill must not collapse every dot onto zero.
    const offsets = bottomPortOffsets(
      [
        { id: 'skill', isPill: false },
        { id: 'tools', isPill: true },
      ],
      WIDTH,
      null,
    );
    expect([...offsets.values()]).toEqual([84, 168]);
  });
});
