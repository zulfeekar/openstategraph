import type { WorkflowSummary } from './WorkflowFileClient';

/**
 * The project's workflows, in the order an arriving reader should see them —
 * `install-experience` 28.
 *
 * ## Two clocks, and neither of them wins by default
 *
 * The ticket asks for *"most recently opened or edited first"*, which is a
 * `max` of two events that come from two different places:
 *
 * | Clock | Where it lives | Who can see it |
 * | --- | --- | --- |
 * | **edited** | `WorkflowSummary.savedAt`, off the package on disk | everyone |
 * | **opened** | this browser's own record (`app/lastOpened`) | this browser |
 *
 * They disagree constantly and both disagreements are ordinary. A colleague
 * pulls a branch and three packages move on disk without this browser having
 * opened any of them; a person opens the same workflow every morning and never
 * saves it. Picking one clock as authoritative gets one of those two cases
 * wrong, so this takes the **later** of the two and puts `from` on the row
 * saying which it was. A list sorted by a fact the reader cannot see is a list
 * they cannot argue with, and the ordering claim is the only thing this module
 * asserts about a workflow.
 *
 * Neither clock is required. An empty stamp map — a private window, a browser
 * whose storage throws, a first visit — orders by the disk clock alone, which
 * is still an order. A row with no usable stamp at either end reports `never`
 * rather than sorting from the epoch as though it were ancient: it is not old,
 * it is unknown, and the row says so.
 *
 * ## Why here
 *
 * Pure, framework-free, and next to the client whose rows it consumes. The
 * decision is data — it needs no DOM to test and no React to state — and the
 * dialog that shows it is left with markup, which is the split
 * `pastRunView.ts` next door already draws.
 */
export interface ArrivalChoice {
  readonly slug: string;
  readonly name: string;
  /** Where the package lives, so a reader can find it outside this editor. */
  readonly location: string;
  /** The instant this row is sorted by, ISO — `''` when neither clock knows. */
  readonly at: string;
  /** Which clock produced `at`. */
  readonly from: 'opened' | 'edited' | 'never';
  /** Whether a customer surface advertises it — see `WorkflowSummary.hidden`. */
  readonly hidden: boolean;
}

/**
 * Where a package's directory is, relative to the project root.
 *
 * A function rather than a string built at each call site, because
 * `workflows/<slug>/` is the settled layout and this is not the only surface
 * that prints it. It is derived from the slug alone: the summary row carries
 * no path, and inventing one the backend did not send would be a sentence that
 * goes wrong the day a project moves its workflows root. What this promises is
 * the layout, which is what a reader needs in order to find the directory.
 */
export function packageLocation(slug: string): string {
  return `workflows/${slug}/`;
}

/** An ISO stamp as milliseconds, or `null` for absent and unparseable alike. */
function instant(iso: string | undefined): number | null {
  if (!iso) return null;
  const at = Date.parse(iso);
  return Number.isNaN(at) ? null : at;
}

/**
 * Every row the project holds, most recently opened or edited first.
 *
 * `openedAt` is keyed by slug and may name packages that no longer exist — a
 * deleted one leaves its stamp behind. A stamp with no row is ignored rather
 * than conjuring a row for a directory that is not there.
 *
 * Ties break on `name`, ascending, so two packages saved in the same commit
 * come out in the same order on every load. An arrival list that reshuffles
 * itself between visits is one nobody learns the shape of.
 */
export function arrivalChoices(
  rows: readonly WorkflowSummary[],
  openedAt: Readonly<Record<string, string>>,
): readonly ArrivalChoice[] {
  return rows
    .map((row) => {
      const edited = instant(row.savedAt);
      const opened = instant(openedAt[row.slug]);
      // Strictly later, so a package saved and opened in the same second reads
      // as edited: the file moving is the fact a second reader can check.
      const newer = opened !== null && (edited === null || opened > edited);
      const at = newer ? opened : edited;
      return {
        slug: row.slug,
        name: row.name,
        location: packageLocation(row.slug),
        at: at === null ? '' : new Date(at).toISOString(),
        from: at === null ? ('never' as const) : newer ? ('opened' as const) : ('edited' as const),
        hidden: row.hidden,
        sortAt: at ?? Number.NEGATIVE_INFINITY,
      };
    })
    .sort((a, b) => b.sortAt - a.sortAt || a.name.localeCompare(b.name))
    .map(({ sortAt: _sortAt, ...choice }) => choice);
}
