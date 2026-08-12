/** One port sitting on a card's bottom edge, reduced to what placement needs. */
export interface BottomPort {
  readonly id: string;
  /** Drawn as the bus pill that straddles the edge, rather than a plain dot. */
  readonly isPill: boolean;
}

/** Where the rendered pill actually is, in card coordinates. */
export interface PillMetrics {
  readonly centre: number;
  /** The pill's left edge — the boundary of the space it leaves free. */
  readonly left: number;
}

/**
 * Where each dot goes along a card's bottom edge.
 *
 * **Why this is a function and not three lines in the effect.** The edge used
 * to hold exactly one port — an agent's tool bus — and two independent rules
 * agreed on where it went *by coincidence*: CSS draws `.node__pill` at
 * `left: 50%`, and an even spread of one port is also the halfway point. The
 * moment a second port joins the edge the spread moves the bus dot to two
 * thirds while its pill stays drawn at the middle, and the link arrives beside
 * the thing it binds to instead of on it.
 *
 * So the rule is inverted: **the dot follows the pill**, measured from the
 * rendered element rather than re-derived from a number that would have to be
 * kept in step with a stylesheet. Plain ports then take the space the pill
 * leaves. Nothing here knows what a pill looks like, which is the point — a
 * longer label widens the pill, the free band shrinks, and the plain dots move
 * without anyone editing a constant.
 *
 * Pure, so the arithmetic is tested rather than eyeballed through a browser at
 * two flow directions.
 */
export function bottomPortOffsets(
  ports: readonly BottomPort[],
  width: number,
  pill: PillMetrics | null,
): Map<string, number> {
  const offsets = new Map<string, number>();
  if (ports.length === 0) return offsets;

  const plain = ports.filter((port) => !port.isPill);

  // No measured pill — either there is none, or the first paint has not put it
  // in the DOM yet. The original even spread is right for both, and is what
  // vertical flow relies on when every flow output lands on this edge.
  if (!pill) {
    ports.forEach((port, index) => {
      offsets.set(port.id, Math.round((width * (index + 1)) / (ports.length + 1)));
    });
    return offsets;
  }

  for (const port of ports) {
    if (port.isPill) offsets.set(port.id, Math.round(pill.centre));
  }

  // The band to the pill's left is the space it demonstrably does not occupy.
  // Clamped above zero so a pill wider than its card still yields a usable
  // band rather than negative positions.
  const band = Math.max(pill.left, 0);
  plain.forEach((port, index) => {
    offsets.set(port.id, Math.round((band * (index + 1)) / (plain.length + 1)));
  });
  return offsets;
}
