import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { MARK } from '../tokens';

/**
 * The mark and the canvas are drawn from one pair of numbers.
 *
 * `--osg-node-ring: 5.5` and `--osg-node-r: 10` are shipped by the owner's
 * design system as *canvas* tokens — they sit in the authored file's
 * "Graph canvas — semantic node/edge states" block, beside the edge colours,
 * not beside the logo. The mark is built from the same two. That is the
 * identity, and it is the kind of agreement that decays quietly: somebody
 * nudges a stroke in the component, the stylesheet keeps the old value, and
 * nothing anywhere reports that the logo and the canvas have drifted apart.
 *
 * So the two descriptions are compared, rather than both being trusted.
 */
const TOKENS = readFileSync(
  fileURLToPath(new URL('../styles/tokens.css', import.meta.url)),
  'utf8',
);

/** The number `tokens.css` declares for a bare-number custom property. */
function declared(name: string): number {
  const match = new RegExp(`${name}\\s*:\\s*([0-9.]+)\\s*;`).exec(TOKENS);
  if (!match?.[1]) throw new Error(`${name} is not declared in tokens.css`);
  return Number(match[1]);
}

describe('the mark’s geometry', () => {
  it('takes its stroke from the token the design system ships', () => {
    expect(MARK.ring).toBe(declared('--osg-node-ring'));
  });

  it('takes its node radius from the token the design system ships', () => {
    expect(MARK.radius).toBe(declared('--osg-node-r'));
  });

  it('keeps the hollow node’s outer edge on the same circle as a filled one', () => {
    // The initial state is a ring, not a disc, and the spec says one weight:
    // a stroke centred on `radius - ring / 2` has its outer edge at `radius`.
    expect(MARK.hollowRadius).toBeCloseTo(MARK.radius - MARK.ring / 2, 6);
  });

  it('is square on a 100-unit grid, with the four nodes symmetric about it', () => {
    expect(MARK.near + MARK.far).toBe(MARK.grid);
  });
});
