# Status: token status bar

- Gate 1 — Product: APPROVED 2026-09-04
- Gate 2 — Architecture: APPROVED 2026-09-04
- Gate 3 — Program Design: APPROVED 2026-09-04
- Gate 4 — Slice plan: APPROVED 2026-09-04

## Slices
- [x] Slice 1 — tracer bullet: route with zeros, client, bar of dashes on screen
- [ ] Slice 2 — real grand total, by-model, sessions from the store
- [ ] Slice 3 — this session's block; refetch on run end and focus
- [ ] Slice 4 — cached / cache-creation / reasoning tri-state; streaming opt-in test
- [ ] Slice 5 — the modal
- [ ] Slice 6 — 10k-row measurement, docs, ceilings, closing commit

## Notes for a fresh session
- Owner decisions, 2026-09-04: *session* = the browser tab's session id
  (`sessionStorage`; survives refresh, ends with the tab). The bar sits at
  the bottom of the editor. Clicking it opens a modal with the breakdown.
- Ticket: `.scratch/stable-beta-public/tickets/03`.
- Follow `src/design/tokens.ts`; no raw values; flat, Miro-like, borders not
  shadows (map note).

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
