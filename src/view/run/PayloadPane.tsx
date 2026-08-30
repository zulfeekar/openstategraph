import type { RunLane } from '../ask/timeline';
import { findStep } from '../ask/RunTimeline';
import { askedAndProduced } from './stepPayload';

/**
 * What the selected bar asked, and what it produced — `memory-and-replay` 59.
 *
 * Under the bar's facts rather than beside them, which continues the grain
 * `58` set for this column: *what this bar is*, then *what it said*, then
 * *everything that ran*. A reader who has just clicked a bar has already said
 * which grain they want first.
 *
 * The pane is **always two headings**, present whether or not there is a
 * quotation under them, because the alternative is a section that disappears
 * — and a section that disappears reads as a bar with no payload rather than
 * as a run that recorded none. Every empty half carries the sentence saying
 * which of those it is; `stepPayload` is where those sentences are decided and
 * asserted.
 *
 * Nothing is rendered as Markdown here, unlike the trace's own output. A
 * payload is being quoted, and a quotation that reflows its own asterisks is
 * no longer evidence — the `pre-wrap` in the stylesheet is the same choice
 * `toolResults` made for the same reason.
 */
export function PayloadPane({
  lanes,
  selected,
}: {
  readonly lanes: readonly RunLane[];
  readonly selected: string | null;
}) {
  const found = findStep(lanes, selected);
  if (!found) return null;
  return (
    <div className="rtl__payload">
      {askedAndProduced(found.lane, found.step).map((half) => (
        <section key={half.heading}>
          <h4>{half.heading}</h4>
          <p className="rtl__payload-caption">{half.caption}</p>
          {half.text === null ? null : <p className="rtl__payload-text">{half.text}</p>}
        </section>
      ))}
    </div>
  );
}
