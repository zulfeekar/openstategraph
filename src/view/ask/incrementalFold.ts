/**
 * A fold whose answer survives the next frame.
 *
 * `the-cost-of-one-more/04`. `AskPanel` appends an arriving frame by rebuilding
 * the array, so every reader of it gets a new identity per frame and refolds a
 * history that is one frame longer each time: F folds of O(F). A real run
 * emitted 866 frames in 55 seconds and a long one could emit 80,000, which is
 * the axis on that map with the most headroom.
 *
 * # What was traded, precisely
 *
 * **The folds stay pure.** `buildTimeline`, `buildLanes` and `buildTrace` are
 * still functions of a row list and nothing else, still tested directly, and
 * still the definition of what a bar and a trace node are — that purity is why
 * they are testable at all, and it is not what was in the way. What was in the
 * way is that a pure function has nowhere to put what it already knows.
 *
 * So the state moves into a **collaborator**, not into the fold: a `Fold` is
 * the same rules with the loop turned inside out, and `reusableFold` is the one
 * place that remembers. The cost is real and is named here rather than in a
 * commit message: *the answer now depends on the sequence of calls, not only on
 * the argument*. Two things pay for it —
 *
 * - the pure function is **defined** by the incremental one
 *   (`buildTimeline(rows)` runs the same `Fold` over the same rows), so the two
 *   cannot disagree about the rules without disagreeing in a test that already
 *   exists; and
 * - the extension check is **identity**, and it is deliberately narrow. A row
 *   object is minted per frame and never reused, so a longer array whose last
 *   already-consumed element is still the same object is the one already folded
 *   plus a tail. Anything else falls back to a whole fold and is merely as slow
 *   as it used to be.
 *
 * The narrowness is not caution for its own sake, and the case that forced it
 * is real: a `settled` frame does not append, it runs `turn.activity.map(closed)`
 * (`AskPanel`), which returns a **new array of the same length** in which one
 * row somewhere in the middle now carries the child's `settledMs` — the other
 * end of a lane's bar. A witness that only looked at the tail would accept that
 * array as "nothing new" and the lane would stay open-ended for the rest of the
 * run. So an array that did not grow is a re-read only when it is *the same
 * array object*; anything else of the same length is folded again from the
 * start. That costs one whole fold per spawned child and buys the guarantee
 * that a row's content is read as it was when the fold consumed it.
 *
 * A `Fold`'s `result()` may therefore be called any number of times between
 * pushes and must not disturb what it is folding: everything that reads the
 * accumulated state to finish it does so into a copy. That is the whole
 * discipline this interface asks of an implementation.
 */
export interface Fold<Row, Out> {
  /** Consume one more row. Called once per row, ever. */
  push(row: Row): void;
  /**
   * The answer for everything pushed so far.
   *
   * Callable repeatedly and in any order with `push`, and never destructive:
   * an implementation that finishes by mutating its own accumulator would
   * make the second call disagree with the first.
   */
  result(): Out;
}

/**
 * Turns a `Fold` into the function signature the pure fold already had.
 *
 * Hand it a growing array once per frame and each row is consumed once across
 * the whole run. Hand it something that is not an extension of what it has
 * already seen and it starts again — correctness never depends on the guess.
 */
export function reusableFold<Row, Out>(
  create: () => Fold<Row, Out>,
): (rows: readonly Row[]) => Out {
  let fold = create();
  let consumed = 0;
  let last: Row | undefined;
  let folded: readonly Row[] | null = null;

  return (rows: readonly Row[]): Out => {
    const grew = rows.length > consumed;
    const extends_ = consumed === 0 || (grew && rows[consumed - 1] === last);
    const same = rows === folded && rows.length === consumed;
    if (!extends_ && !same) {
      fold = create();
      consumed = 0;
    }
    for (let index = consumed; index < rows.length; index += 1) {
      const row = rows[index] as Row;
      fold.push(row);
      last = row;
    }
    consumed = rows.length;
    folded = rows;
    return fold.result();
  };
}
