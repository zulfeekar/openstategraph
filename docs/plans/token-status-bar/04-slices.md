# Slices: token status bar

Build order. Each slice ends running, testable, and shown.

1. **Tracer bullet.** `GET /api/runs/spend` answers a real `SpendResponse`
   with zeros and `null`s (no store read yet); `docs/openapi.json`
   regenerated; `RuntimeClient.spend()` mirrors it; `SpendBar` mounts as the
   last row of the shell and shows four dashes. Proof: the bar is on screen
   in the browser and `curl` shows the document. Tests: route answers,
   contract drift green, `cellsFor(null)` is all dashes.
2. **Real grand total and by-model.** `spend_summary()` walks the store:
   `grand_total`, `by_model`, `sessions`. The bar shows the real grand total
   on this checkout (25 runs). Tests: fresh store, sum across sessions, two
   models kept apart, a run that reported nothing, newest-first sessions.
3. **This session, and refresh.** `session_by_model` / `session_total` for the
   tab's id; refetch on the run dock's terminal frame and on window focus.
   Proof: run a workflow, watch the session cell move without a reload.
   Tests: session filter, unknown session, `useSpend` refetch on key change.
4. **Cached, cache-creation, reasoning — tri-state.** Detail keys summed only
   where present; `null` otherwise; the bar prints `—` for `null` and `0`
   for a reported zero. Tests: the `None` rule for each detail, the OpenAI
   streaming opt-in test, `aSpendCellNeverSaysZeroForNothing`.
5. **The modal.** `SpendDialog` on `overlays/Dialog`: grand total by model
   (input / output / cached / total), this session by model, sessions list
   with the current tab marked. Opens on click of the bar, closes on Escape.
   Proof: screenshot, light and dark. Tests: renders from the same `spend`
   object, marks the current session, shows `—` where `null`.
6. **Cost and paper.** The ten-thousand-row measurement with its pinned
   budget; a note in `.scratch/the-cost-of-one-more/`; `docs/on-the-canvas.md`
   paragraph; ceiling rows (`publicSurfaceCeiling`, module size if any file
   crosses); final `npm run verify` + backend suite; commit with
   `Ticket: stable-beta-public/03`.

Each slice: prove it, tick it in `00-status.md`, ask *continue or re-steer*.
Slices 1–5 may each be their own commit; 6 closes the ticket.
