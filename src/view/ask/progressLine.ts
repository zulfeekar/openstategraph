/**
 * What a `progress` frame reads as, on one line.
 *
 * A pure function rather than three lines inside `AskPanel`'s event handler,
 * for the reason `thread.ts` and `timeline.ts` are: the thing that goes wrong
 * here is invisible from the panel. `current` and `total` are independently
 * nullable — `int | None` each, because a tool that knows it is on page three
 * of an unknown number of pages is a real and common shape — and the obvious
 * `${current}/${total}` renders that as `3/null`, or, worse, a `0/0` invented
 * to fill the format. Neither would fail a build and neither would look wrong
 * in a screenshot taken from a tool that happened to know both.
 */
export interface ProgressFrame {
  readonly message: string;
  readonly current: number | null;
  readonly total: number | null;
}

/**
 * `"Reading 3 of 12"` → the message plus whichever count is actually true.
 *
 * Three shapes, and no fourth: both numbers give `(3/12)`, a count with no
 * total gives `(3)`, and a total with no count gives nothing — "of 12" alone
 * says less than the message already did, and a bare `(12)` would read as
 * progress rather than as the size of the job.
 */
export function progressLine(frame: ProgressFrame): string {
  const count =
    frame.current != null
      ? frame.total != null
        ? ` (${frame.current}/${frame.total})`
        : ` (${frame.current})`
      : '';
  return `${frame.message}${count}`;
}
