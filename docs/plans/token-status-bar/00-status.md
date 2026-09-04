# Status: token status bar

- Gate 1 — Product: APPROVED 2026-09-04
- Gate 2 — Architecture: APPROVED 2026-09-04
- Gate 3 — Program Design: APPROVED 2026-09-04
- Gate 4 — Slice plan: APPROVED 2026-09-04

## Slices
- [x] Slice 1 — tracer bullet: route with zeros, client, bar of dashes on screen
- [x] Slice 2 — real grand total, by-model, sessions from the store
- [x] Slice 3 — this session's block; refetch on run end and focus
- [x] Slice 4 — cached / cache-creation / reasoning tri-state; streaming opt-in test
- [x] Slice 5 — the modal
- [ ] Slice 6 — 10k-row measurement, docs, ceilings, closing commit

## Notes for a fresh session
- 2026-09-04: the owner delegated slice-boundary approvals ("as you recommend the best way to go"); stop only for a real fork.
- Owner decisions, 2026-09-04: *session* = the browser tab's session id
  (`sessionStorage`; survives refresh, ends with the tab). The bar sits at
  the bottom of the editor. Clicking it opens a modal with the breakdown.
- Ticket: `.scratch/stable-beta-public/tickets/03`.
- Follow `src/design/tokens.ts`; no raw values; flat, Miro-like, borders not
  shadows (map note).

## What slice 5 changed about 03

- **The dialog is two components, and the split is the test's.** `Dialog`
  renders through `createPortal(…, document.body)` and the suite runs in
  `node` on purpose (`vite.config.ts`), so `SpendDialog` cannot be rendered
  in a test at all. `SpendBreakdown` — the three tables, without the frame —
  is exported beside it and is what
  `aBreakdownMarksTheTabYouAreIn.test.ts` renders with
  `react-dom/server`, following slice 4's note.
- **The grand-total table carries `Reasoning` as well**, which 04's one-line
  sketch omitted and the mockup did not draw. Slice 4 published the field and
  the same tri-state rule governs it; a column the wire carries and the modal
  drops would be the only place the editor knows a figure and does not say
  it.
- **The footer row reads `grandTotal`/`cachedTotal` off the wire** rather than
  re-summing `byModel`. Two sums of one quantity agree the day they are
  written. Only `input`/`output`/`reasoning`, which the wire does not total,
  are summed here — `reasoning` under the same none rule (`null` unless some
  row reported one), never `?? 0`.
- **`reportedTokens` moved from private to exported in `spendModel.ts`.** The
  dash rule now has two readers (the bar and the three tables) and one owner;
  a second spelling of it is the duplication of *knowledge* the DRY rule
  forbids.
- **A sitting's span is sliced, never parsed.** `sessionSpan` reads the day
  and minute out of the stored stamp with a regex; `new Date()` would shift a
  stamp that carries an offset into the reader's own zone
  (`the-cost-of-one-more/11` again, one layer up). An unreadable stamp is
  shown as it arrived.
- **Three censuses fired and all three were right**:
  `aDialogSizeIsOptInOnly.test.ts` (a new `Dialog` caller, added to the list
  at the default size), `badgeExplanations.test.ts` (the *this tab* Badge
  needed an `explanation`), and `aBorderIsDraggableOrItIsNot.test.ts` —
  `--color-border-subtle` is a retired token, and `--color-rule` is **not**
  the lighter weight it sounds like: it is reserved for the three edges a
  pointer can drag. Row separators are `--color-border`.
- **One defect the tests could not see, found in the browser**: the number
  cells' `padding-left` lost on specificity to `.spend-table td`, so every
  gutter was zero and the header row read `RunsCachedTotal`. Selected as
  `.spend-table .spend-table__number` now. A markup test asserts text, and
  this was a cascade.
- **The modal does not open before the first answer lands** — there would be
  nothing to tabulate, and a table of dashes is not more honest than no
  table.

## What slice 4 changed about 03

- **`stream_usage` was missing**, and the answer was a new `ProviderSpec`
  field rather than a line in a node. `constructor_args` is env-sourced by
  construction (`ProviderArgument` names variables, and refuses secret-looking
  ones), so it could not carry a constant; `constructor_defaults:
  tuple[tuple[str, Any], ...]` is the constants table, merged *first* in
  `chat_model.model_kwargs` so anything the machine supplies still wins.
  `openai` and `azure_openai` declare `("stream_usage", True)`; every other
  provider is passed exactly what it was passed before.
  `docs/decisions/hermes-agent.md` said in as many words that `model_kwargs()`
  *"has no way to pass `stream_usage` today"* — that sentence is now corrected
  in place.
- **The cost is recorded, not hidden.** An OpenAI-compatible proxy that
  rejects `stream_options` is now sent it, and there is no environment
  variable to turn it off. That is the trade `langchain_openai` makes in the
  other direction (its own default disables the opt-in whenever a base URL is
  set, which is exactly how a gateway-configured machine stopped reporting
  what its runs cost). A proxy that needs the switch is a ticket, not a
  silent default.
- **Three gates fired on the new field, and all three were right**:
  `test_config_file.py`'s field census (a config-declared provider must carry
  it), `tests/public_api.txt` (the dataclass is semver-public — CHANGELOG
  entry added under *Changed*), and `test_module_size_ceiling.py`
  (`run_sinks.py` 803 → 829, argued in place).
- **`test_node_runtime.py`'s `fake_init_chat_model(key)` had to widen to
  `(key, **kwargs)`.** Not cosmetic: `NodeRuntime._base_model` wraps
  `build_chat_model` in `except Exception` and degrades to the shared default,
  so the fake's `TypeError` came back as a *silently degraded model*, not an
  error. The seven fakes in that file are the only callers that assumed
  `init_chat_model` takes one argument.
- **No wire change, so no `docs/openapi.json` regeneration.** Slice 1 already
  published all three detail fields as nullable (00's own slice-1 note), which
  is exactly the property that let this slice be a store change.
- **One test 03 did not list, added because the route could not otherwise
  fail**: `test_a_reported_cache_figure_reaches_the_wire` in
  `test_spend_route.py`. Every other route assertion is about `null`, which a
  route hardcoding `None` would satisfy.
- **`aSpendCellNeverSaysZeroForNothing.test.ts` renders with
  `react-dom/server`.** No DOM library is installed (slice 3's note) and
  `renderToStaticMarkup` needs none; the file is `.test.ts` rather than
  `.test.tsx` because that is the only pattern `vite.config.ts` collects, so
  the element is built with `createElement`.

## What slice 3 changed about 03
- **No renderer for `useSpend.test.ts`.** `vite.config.ts` sets
  `test.environment: 'node'` deliberately — the view layer is proven in the
  browser, not simulated — and no DOM library (`jsdom`, `happy-dom`,
  `@testing-library/react`, `react-test-renderer`) is in `node_modules`. So
  the hook itself is not rendered in the test; its two behaviours worth
  pinning were pulled out as plain functions the same way `useFloating.ts`
  already pulled `placeFloating` out — `nextSpendState` (error keeps the last
  good value) and `onWindowFocus` (a `FocusTarget` a fake object can drive).
  *Refetch on `refreshKey` change* is React's own dependency-array mechanism
  over `[client, sessionId, refreshKey, nonce]` and is proven in this slice's
  browser step rather than re-simulated.
- **`spend_summary`'s session branch reused `_by_model`** rather than a new
  query shape — `SELECT usage FROM runs WHERE kind = 'run' AND session_id = ?`,
  the same walk the all-time table already does, and `session_total` is the
  sum of that table's `total_tokens`. Pushed `run_sinks.py` from 792 to 803
  recorded code lines (`test_module_size_ceiling.py`, argued inline).
- **Proof used a curl of `/api/runs/spend?session_id=...`** rather than only
  the browser cell, and a simulated `window` `focus` event to trigger the
  frontend refetch without a page reload — both because the run in the
  browser landed with the run store's own timing and the fastest honest way
  to show the wire moved was to read it directly, then show the cell catch up
  live.

## What slice 2 changed about 03
- **A sitting's `first_at`/`last_at` are found by the derived key and
  returned as stored.** 03 asked for one `GROUP BY session_id`, and
  `min(at)`/`max(at)` over a column carrying an offset is a text comparison
  (`the-cost-of-one-more/11`). Sqlite's bare-column rule gives the stored
  spelling for free with *one* min/max and a span needs two, so the two
  stamps are correlated seeks ordered on `CHRONOLOGICAL` — still one
  statement, still on `runs_session_utc`.
- **Every reader filters `kind = 'run'`.** `RunRecord.kind` is the store's
  extension point and a future row (a human's verdict, `launch-readiness/142`)
  carries no usage; without the clause it would still have inflated a
  sitting's run count.
- **`spend_summary` lives in `run_sinks.py`**, which pushed that module's
  recorded length from 661 to 792 code lines. The argument is in
  `test_module_size_ceiling.py`: a third reader of the runs table beside
  `read_runs` and `read_run_bursts` is the same reason to change, and a
  separate module would hold a second copy of the column names and the sort
  key.

## What slice 1 changed about 03
- **The wire is snake_case**, as 03's `schemas.py` block writes it
  (`grand_total`, `cached_tokens`), and `RuntimeClient` maps it to camelCase
  the way `asPastRun` already maps `/api/threads`. Worth knowing because the
  route's own file-neighbours (`RecordedRun`, `RecordedUsage`) are camelCase on
  the wire: this module has both spellings in it now, and slices 2-6 must keep
  using 03's.
- **`ModelSpendResponse` carries all three detail figures** —
  `cached_tokens`, `cache_creation_tokens`, `reasoning_tokens`. 03's Python
  dataclass listed three and its `schemas.py` line listed one; the dataclass
  is the one that was right, since a field the wire never had cannot be added
  in slice 4 without a client that already reads it.
- **`spend(sessionId?)` defaults to the tab's own id.** 03 typed it required.
  The client already holds `browserSessionId` for every run, and two places
  deciding what a session is was the thing to avoid.
- **The bar shows `0`, not `—`, for the grand total on this slice.** The zero
  document is a *reported* zero, and the dash rule says a reported zero prints
  as a zero. Four dashes is what `cellsFor(null)` gives — the first paint,
  before the fetch lands — and that is what the test pins.
- **`AppShell.css` needed no change**: `.app-shell` is already a flex column,
  so `flex: 0 0 auto` on the bar was enough.
