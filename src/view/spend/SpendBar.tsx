import type { Spend } from '@core/runtime/RuntimeClient';

import { cellsFor } from './spendModel';
import './SpendBar.css';

/**
 * The strip along the bottom of the editor that says what the work cost.
 *
 * `stable-beta-public/03`. Four cells, always on screen, never fetching
 * anything itself: the answer arrives as a prop so the bar and the modal it
 * opens read one response measured at one instant.
 *
 * **A cell that has nothing to say says `—`.** The judgement is `cellsFor`'s,
 * which is where it is tested; this file is the markup and the click.
 */
export function SpendBar(props: { spend: Spend | null; error: string | null; onOpen: () => void }) {
  const cells = cellsFor(props.spend);

  return (
    <button
      type="button"
      className="spend-bar"
      onClick={props.onOpen}
      // One control, so one label. The cells are read out by their own
      // `title`s; this says what pressing it does, which is the thing a
      // screen reader user cannot see from the numbers.
      aria-label="Token spend — open the breakdown"
      title={props.error ?? 'Open the spend breakdown'}
    >
      <Cell
        label="Total"
        value={cells.grandTotal}
        hint="Tokens across every run this project kept"
      />
      <Cell
        label="Cached"
        value={cells.cached}
        hint="Tokens served from cache — a dash means no provider reported one"
      />
      <Cell
        label="This tab"
        value={cells.session}
        hint="Tokens spent since this browser tab opened"
      />
      <Cell
        label="Models"
        value={cells.sessionModels === '' ? '—' : cells.sessionModels}
        hint="What this tab spent, model by model"
      />
    </button>
  );
}

function Cell(props: { label: string; value: string; hint: string }) {
  return (
    <span className="spend-bar__cell" title={props.hint}>
      <span className="spend-bar__label">{props.label}</span>
      <span className="spend-bar__value">{props.value}</span>
    </span>
  );
}
