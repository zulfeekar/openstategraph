import { Badge } from '@design/primitives';
import type { Spend } from '@core/runtime/RuntimeClient';

import { Dialog } from '../overlays/Dialog';
import { ALL_MODELS, tablesFor } from './spendDialogModel';
import './SpendDialog.css';

/**
 * What the work cost, in three tables.
 *
 * `stable-beta-public/03`, slice 5. Opened by the status bar and rendered
 * from **the same `Spend` object the bar holds**, so the strip and the
 * breakdown can never disagree about an instant — there is one fetch, in
 * `AppShell`, and this reads its answer.
 *
 * Escape, the focus trap and the backdrop rule are `Dialog`'s, which is why
 * this is a `Dialog` and not a panel of its own. The size is left at the
 * default on purpose (`overlays/dialogSize.ts`): 520px is what the mockup was
 * drawn against and what every other modal in the product is, and `large`
 * exists for the board.
 */
export function SpendDialog(props: {
  spend: Spend;
  currentSessionId: string;
  onClose: () => void;
}) {
  return (
    <Dialog
      title="Tokens spent"
      subtitle="Counted from every recorded run this project kept. A dash means no provider reported that figure."
      onClose={props.onClose}
    >
      <SpendBreakdown spend={props.spend} currentSessionId={props.currentSessionId} />
    </Dialog>
  );
}

/**
 * The three tables, without the frame around them.
 *
 * Separate from `SpendDialog` so the claims can be rendered in a test:
 * `Dialog` portals into `document.body` and the suite runs in `node`
 * (`vite.config.ts`), so the frame cannot be rendered there and the content
 * — the half that makes claims — can.
 */
export function SpendBreakdown(props: { spend: Spend; currentSessionId: string }) {
  const tables = tablesFor(props.spend, props.currentSessionId);

  return (
    <div className="spend-tables">
      <table className="spend-table">
        <thead>
          <tr>
            <th scope="col">Grand total, by model</th>
            <NumberHead>Input</NumberHead>
            <NumberHead>Output</NumberHead>
            <NumberHead>Cached</NumberHead>
            <NumberHead>Reasoning</NumberHead>
            <NumberHead>Total</NumberHead>
          </tr>
        </thead>
        <tbody>
          {tables.byModel.map((row) => (
            <tr key={row.model}>
              <td className="spend-table__name">{row.model}</td>
              <Number>{row.input}</Number>
              <Number>{row.output}</Number>
              <Number>{row.cached}</Number>
              <Number>{row.reasoning}</Number>
              <Number>{row.total}</Number>
            </tr>
          ))}
        </tbody>
        {/* The footer is the answer the wire published, not a second sum of
            the rows above it — see `SpendTables.allModels`. */}
        <tfoot>
          <tr>
            <td className="spend-table__name">{ALL_MODELS}</td>
            <Number>{tables.allModels.input}</Number>
            <Number>{tables.allModels.output}</Number>
            <Number>{tables.allModels.cached}</Number>
            <Number>{tables.allModels.reasoning}</Number>
            <Number>{tables.allModels.total}</Number>
          </tr>
        </tfoot>
      </table>

      <table className="spend-table">
        <thead>
          <tr>
            <th scope="col">This tab, by model</th>
            <NumberHead>Runs</NumberHead>
            <NumberHead>Cached</NumberHead>
            <NumberHead>Total</NumberHead>
          </tr>
        </thead>
        <tbody>
          {tables.session.length === 0 ? (
            <tr>
              {/* Not a row of zeros: this tab has not run anything, which is
                  a different statement from having run something free. */}
              <td className="spend-table__empty" colSpan={4}>
                Nothing has run in this tab yet.
              </td>
            </tr>
          ) : (
            tables.session.map((row) => (
              <tr key={row.model}>
                <td className="spend-table__name">{row.model}</td>
                <Number>{row.runs}</Number>
                <Number>{row.cached}</Number>
                <Number>{row.total}</Number>
              </tr>
            ))
          )}
        </tbody>
      </table>

      <table className="spend-table">
        <thead>
          <tr>
            <th scope="col">Sessions, newest first</th>
            <NumberHead>Runs</NumberHead>
            <NumberHead>Total</NumberHead>
          </tr>
        </thead>
        <tbody>
          {tables.sessions.map((row) => (
            // `aria-current` rather than a colour alone: "the one you are in"
            // is a state a screen reader has a word for, and the Badge beside
            // it says the same thing in the sighted reader's copy.
            <tr key={row.sessionId} {...(row.current ? { 'aria-current': true as const } : {})}>
              <td className="spend-table__name">
                {row.span}
                {row.current ? (
                  <Badge
                    tone="accent"
                    explanation="The sitting this browser tab is making right now — it ends when the tab closes."
                    className="spend-table__mark"
                  >
                    this tab
                  </Badge>
                ) : null}
              </td>
              <Number>{row.runs}</Number>
              <Number>{row.total}</Number>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A figure: right-aligned and tabular, so columns of digits line up. */
function Number(props: { children: string }) {
  return <td className="spend-table__number">{props.children}</td>;
}

function NumberHead(props: { children: string }) {
  return (
    <th scope="col" className="spend-table__number">
      {props.children}
    </th>
  );
}
