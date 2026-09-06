/**
 * What the examples journey says, in one place (production-ready ticket 23).
 *
 * The gallery ships 23 worked packages and the owner's QA found the journey to
 * them silent: the shelf collapses by default (install-experience wave 3 —
 * right call for prominence, wrong without a signpost), the empty canvas taught
 * the starter and never mentioned examples, and no surface said the three verbs
 * that matter — **browse, copy, it becomes yours**.
 *
 * Four surfaces now point at the same place: the empty canvas, the shelf's own
 * header, a once-only first-run hint on the Workflows button, and
 * `docs/getting-started.md`. Four surfaces is four chances to drift, so the
 * words they share live here and are imported rather than retyped — the same
 * reason `emptyStateCopy.ts` exists, and it composes its line from
 * `EXAMPLES_ROUTE` below rather than spelling the route a second way.
 *
 * ## The count is a parameter, never a constant
 *
 * `GET /api/examples` is the only thing that knows how many there are, and
 * `index.json` has been miscounted in prose three separate times in this
 * repository (twenty, twenty-one, twenty-two, against an actual 23). So no
 * string here contains a number: the shelf passes the length of the list it
 * just rendered, and the empty canvas — which has no list — names no count at
 * all rather than guessing one.
 */

/**
 * The route, named exactly once and spelled the same on every surface. A
 * signpost that names a control by a word the UI does not use sends a beginner
 * looking for something that is not there.
 */
export const EXAMPLES_ROUTE = 'Workflows → Examples';

/**
 * The collapsed shelf's own line — an invitation with the count in it, not a
 * bare number on a chevron.
 *
 * It used to be the digit `23` on a ghost button, which says how much is behind
 * the control and nothing about why anyone would press it. The count stays,
 * because a shelf that will not say how much it is hiding is a control nobody
 * has a reason to open; the verbs are what is new.
 */
export function examplesShelfToggleLabel(count: number, open: boolean): string {
  if (open) return 'Hide the examples';
  return count === 1
    ? '1 example — copy it to make it yours'
    : `${count} examples — copy one to make it yours`;
}

/**
 * The first-run popover, pointing at the Workflows button.
 *
 * Says all three verbs in order, because the thing a first-time reader does not
 * know is not where the examples are — it is that taking one is a *copy* and
 * that the copy is theirs. Deliberately not "load an example": nothing is
 * loaded from the gallery, and a workflow that seemed to open from a shelf it
 * cannot be saved back into is the confusion this replaces.
 */
export function examplesHintText(count: number): string {
  const many = count === 1 ? '1 worked example' : `${count} worked examples`;
  return `${many} ship inside OpenStateGraph. Browse them under ${EXAMPLES_ROUTE}, copy one, and the copy is yours — a draft you can edit and run.`;
}

/** The popover's button. The verb is the first of the three. */
export const EXAMPLES_HINT_ACTION = 'Browse examples';
