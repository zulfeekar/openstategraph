/**
 * What the record beside an answer may honestly say each router did.
 *
 * `decisions[node]` is **one** label — the one the compiled graph's
 * conditional edge dispatched on — and a router in `matchMode: "all"` opens a
 * desk per match in the same superstep. So this panel printed
 * `router1 → b-cost` for a run where the cost desk *and* the risk desk had
 * both answered, and printed the identical row for a run where only one had
 * (`launch-readiness/175`). Two runs, one row.
 *
 * **This is the surface the fix is for, and the canvas is not.** Cards light
 * from per-node run status as the stream reports them (`CanvasStage`), so
 * both branches already glow while they run and neither `decisions` nor
 * `routes` is consulted to do it; a persistent path tint was tried there and
 * removed for reasons that have nothing to do with routers. The lie was never
 * on the canvas — it was in the record, which outlives the glow.
 *
 * So every branch that ran is named, and they are joined with `+` rather than
 * `,`: a comma reads as a list of alternatives considered, and these are
 * desks that all answered. A single-branch row is left exactly as it was —
 * `routes` carries a row for every router, and rendering `b2` as `b2` is what
 * a reader has always seen for the ordinary case.
 */
export function decisionRows(result: {
  readonly decisions: Readonly<Record<string, string>>;
  readonly routes: Readonly<Record<string, readonly string[]>>;
}): readonly { readonly nodeId: string; readonly branch: string }[] {
  return Object.entries(result.decisions).map(([nodeId, branch]) => {
    const matched = result.routes[nodeId] ?? [];
    return {
      nodeId: nodeId.replace(/^node:/, ''),
      // The dispatched label is always one of the matched ones, so a row of
      // one says nothing the fallback does not — and a router whose row this
      // client could not read (an older server, a malformed payload) falls
      // back to exactly what it used to print rather than to nothing.
      branch: matched.length > 1 ? matched.join(' + ') : branch,
    };
  });
}
