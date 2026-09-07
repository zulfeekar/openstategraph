# Architecture: token status bar

## Fit
- **`backend/openstategraph/run_sinks.py`** already holds every number: the
  `runs` table has `session_id`, `total_tokens`, and `usage` (JSON, keyed by
  model, each with `input_tokens`/`output_tokens`/`total_tokens` plus whatever
  `input_token_details` the provider added — `cache_read` is LangChain's key
  for the cached figure when a provider reports one). `read_runs` already
  filters by `session_id`. The store is the truth; nothing new is written.
  Measured on this checkout: 25 runs, 11 sessions, none with a cache detail
  (the local Ollama-cloud runs report none), so *cached* must be tri-state.
- **`backend/openstategraph/api/routes/recordings.py`** owns the read-only `/api/runs/recorded*` routes; the new
  read joins that file as a sibling of `/api/runs/recorded`, not `runs.py` (which is the write side).
- **`src/core/runtime/RuntimeClient.ts`** gets one new read; the session id is
  the one it already sends on every run (`browserSession.ts`,
  `browserSessionId`, `sessionStorage`-backed).
- **`src/view/AppShell.tsx` / `AppShell.css`**: the shell is a column
  (`.app-shell` → `__stage` → `__body`); the bar is a new last child of
  `.app-shell`, below the stage, so canvas, panels and dock are untouched.
- **`src/view/run/RunDock.tsx`** already knows when this tab's run finishes
  (it renders the run's own usage) — that is the refresh trigger.

## Endpoints
- `GET /api/runs/spend?session_id=<id>` — one document: grand total by model,
  cached by model (or absent), this session by model, and the list of
  sessions with run count and total. Reads only. `session_id` optional; when
  absent the *session* block is empty, never invented.

## Data
No new tables. One query family over `runs`, in `run_sinks`:
- `SELECT session_id, min(at), max(at), count(*), sum(total_tokens) FROM runs
  GROUP BY session_id ORDER BY max(at) DESC` — the sessions list.
- Per-model totals are summed in Python from the `usage` JSON of every row
  (25 rows today; the ceiling map `the-cost-of-one-more` gets a note that this
  is O(runs) and a measured cost at 10k rows, with an index on `session_id`
  already present: `runs_session_utc`).
- *Cached* per model = sum of `usage[model]["input_token_details"]["cache_read"]`
  over rows that carry the key; `None` when no row for that model carries it.

## Flow
1. `AppShell` mounts `SpendBar` with the tab's session id.
2. `SpendBar` → `RuntimeClient.spend(sessionId)` → `GET /api/runs/spend` →
   `run_sinks.spend_summary(path, session_id)` → `SpendResponse`.
3. The bar renders four cells from the response; a `finished`/`failed` run in
   this tab (the dock's existing terminal frame) and window focus trigger a
   refetch; the modal opens on click and reads the same response — one fetch,
   two surfaces, the arrival-offer rule.
4. Nothing polls. A run made in another tab shows after the next refetch.

## External
None. No new environment variable.
