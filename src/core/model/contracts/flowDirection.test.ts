import { describe, expect, it } from 'vitest';
import { resolvePortSide, sideOf, type IPortDescriptor } from '@core/model/contracts/ports';

/**
 * Flow direction — ticket 45.
 *
 * The rule is a single rotation: a port's *effective horizontal side*
 * (explicit `side`, or the in→left / out→right default) turns 90° clockwise
 * in vertical flow. That one rule moves flow ports from left/right to
 * top/bottom AND swings the tool/worker buses from top/bottom to the card's
 * flanks — no per-port annotations, and every existing declaration keeps
 * meaning what it meant.
 */

const port = (extras: Partial<IPortDescriptor>): IPortDescriptor => ({
  id: 'p',
  direction: 'in',
  type: 'text',
  label: 'p',
  ...extras,
});

describe('resolvePortSide', () => {
  it('is exactly sideOf in horizontal flow', () => {
    const input = port({ direction: 'in' });
    const output = port({ direction: 'out' });
    expect(resolvePortSide(input, 'horizontal')).toBe(sideOf(input));
    expect(resolvePortSide(output, 'horizontal')).toBe('right');
  });

  it('rotates flow ports onto the top/bottom edges in vertical flow', () => {
    expect(resolvePortSide(port({ direction: 'in' }), 'vertical')).toBe('top');
    expect(resolvePortSide(port({ direction: 'out' }), 'vertical')).toBe('bottom');
  });

  it('rotates the tool bus onto the flanks in vertical flow', () => {
    // The agent's tools input sits on the bottom in horizontal flow…
    expect(resolvePortSide(port({ direction: 'in', side: 'bottom' }), 'vertical')).toBe('left');
    // …and a tool node's output sits on the top.
    expect(resolvePortSide(port({ direction: 'out', side: 'top' }), 'vertical')).toBe('right');
  });

  it('keeps an explicit side authoritative in horizontal flow', () => {
    expect(resolvePortSide(port({ direction: 'out', side: 'bottom' }), 'horizontal')).toBe(
      'bottom',
    );
  });
});
