# Program Design: token status bar

## Files
- `backend/openstategraph/run_sinks.py` — **changed**: `spend_summary()` and
  the three dataclasses it returns, beside `read_runs` (same store, same
  argument: the table is the truth, this is a query over it).
- `backend/openstategraph/api/schemas.py` — **changed**: `SpendResponse` and
  its parts, the Pydantic publication of the dataclasses.
- `backend/openstategraph/api/routes/recordings.py` — **changed**: `GET
  /api/runs/spend`, sibling of `/api/runs/recorded` (read side).
- `docs/openapi.json` — **regenerated** (`scripts/generate_openapi.py`).
- `backend/tests/test_spend_summary.py` — **new**: the store-level tests.
- `backend/tests/test_spend_route.py` — **new**: the route, including the
  fresh-install case.
- `src/core/runtime/RuntimeClient.ts` — **changed**: `spend()` and the mirrored
  types; `contractDrift.test.ts` pins them by the generic field census (31).
- `src/view/spend/spendModel.ts` — **new**: pure: response → what each cell
  says (formatting, the dash rule). No React.
- `src/view/spend/SpendBar.tsx` + `SpendBar.css` — **new**: the strip.
- `src/view/spend/SpendDialog.tsx` — **new**: the modal, on `overlays/Dialog`.
- `src/view/spend/useSpend.ts` — **new**: the one fetch; refetch triggers.
- `src/view/spend/aSpendCellNeverSaysZeroForNothing.test.ts` — **new**.
- `src/view/AppShell.tsx` / `AppShell.css` — **changed**: mount `SpendBar` as
  the last child of `.app-shell`; pass the run dock's terminal signal.
- `src/publicSurfaceCeiling.test.ts` — **changed**: `RuntimeClient` member
  count +1, dated row.
- `docs/on-the-canvas.md` — **changed**: one paragraph on the bar.
- `.scratch/the-cost-of-one-more/` — a note (not a ticket) recording the
  O(runs) walk and its measured cost at 10k rows.

## Types & signatures

```python
# run_sinks.py
@dataclass(frozen=True)
class ModelSpend:
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_tokens: int | None   # None = no row for this model carried input_token_details.cache_read
    cache_creation_tokens: int | None  # Anthropic's write-to-cache figure, same rule
    reasoning_tokens: int | None       # output_token_details.reasoning, same rule
    runs: int

@dataclass(frozen=True)
class SessionSpend:
    session_id: str
    first_at: str
    last_at: str
    runs: int
    total_tokens: int

@dataclass(frozen=True)
class SpendSummary:
    grand_total: int
    cached_total: int | None    # None when no run anywhere reported a cache figure
    by_model: tuple[ModelSpend, ...]          # all time, largest total first
    session_by_model: tuple[ModelSpend, ...]  # () when session_id is None/unknown
    session_total: int
    sessions: tuple[SessionSpend, ...]        # newest last_at first

def spend_summary(path: Path | str | None = None, *, session_id: str | None = None) -> SpendSummary: ...
def _cached_of(usage_for_model: dict[str, Any]) -> int | None: ...   # reads input_token_details.cache_read
```

```python
# schemas.py
class ModelSpendResponse(BaseModel): model, input_tokens, output_tokens, total_tokens, cached_tokens: int | None, runs
class SessionSpendResponse(BaseModel): session_id, first_at, last_at, runs, total_tokens
class SpendResponse(BaseModel): grand_total, cached_total: int | None, by_model, session_by_model, session_total, sessions

# recordings.py
@router.get("/api/runs/spend", response_model=SpendResponse, tags=["Runs"])
def spend_endpoint(services: Services, session_id: str | None = None) -> SpendResponse: ...
```

```ts
// RuntimeClient.ts
export interface ModelSpend { readonly model: string; readonly inputTokens: number; readonly outputTokens: number; readonly totalTokens: number; readonly cachedTokens: number | null; readonly runs: number }
export interface SessionSpend { readonly sessionId: string; readonly firstAt: string; readonly lastAt: string; readonly runs: number; readonly totalTokens: number }
export interface Spend { readonly grandTotal: number; readonly cachedTotal: number | null; readonly byModel: readonly ModelSpend[]; readonly sessionByModel: readonly ModelSpend[]; readonly sessionTotal: number; readonly sessions: readonly SessionSpend[] }
spend(sessionId: string): Promise<Result<Spend, string>>;

// spendModel.ts — pure
export interface SpendCells { readonly grandTotal: string; readonly cached: string /* '—' when null */; readonly session: string; readonly sessionModels: string /* 'model n · model n', '' when none */ }
export function cellsFor(spend: Spend | null): SpendCells;   // null → every cell '—'
export function formatTokens(n: number): string;              // 1,284,910 — locale-stable, tests pin it

// useSpend.ts
export function useSpend(input: { client: IRuntimeClient; sessionId: string; refreshKey: number }): { spend: Spend | null; error: string | null; refetch: () => void };

// SpendBar.tsx
export function SpendBar(props: { spend: Spend | null; error: string | null; onOpen: () => void }): JSX.Element;
// SpendDialog.tsx
export function SpendDialog(props: { spend: Spend; currentSessionId: string; onClose: () => void }): JSX.Element;
```

## Call stack
**Bar at rest:** `AppShell` → `useSpend({client, sessionId: browserSessionId(), refreshKey})` → `client.spend(sessionId)` → `GET /api/runs/spend?session_id=` → `spend_endpoint` → `spend_summary(services.run_store_path, session_id=…)` → `SELECT … GROUP BY session_id` + one pass over `usage` JSON → `SpendSummary` → `SpendResponse` → `Spend` → `cellsFor` → `SpendBar`.

**After a run:** run dock's terminal frame (`finished` | `failed`) → `AppShell` bumps `refreshKey` → `useSpend` refetches. `window` `focus` → same.

**Click:** `SpendBar.onOpen` → `AppShell` state → `SpendDialog` renders from the same `spend`.

## Test plan
Backend, `test_spend_summary.py` (fixture store written through `SqliteRunSink`, never hand-inserted):
- `test_a_fresh_store_is_zero_not_missing` — no file → `grand_total == 0`, `cached_total is None`, empty tuples.
- `test_grand_total_sums_every_run_across_sessions` — 3 runs, 2 sessions → sum matches `sum(total_tokens)`.
- `test_by_model_keeps_two_models_apart` — one run on two models → two rows, not one.
- `test_cached_is_none_when_nobody_reported` — usage without `input_token_details` → `cached_tokens is None`, `cached_total is None`.
- `test_cached_sums_only_rows_that_carry_the_key` — one run with `cache_read: 100`, one without → `100`, not `100 + 0`.
- `test_session_block_is_only_that_session` — `session_id` filter excludes other sessions' rows.
- `test_unknown_session_is_empty_not_error` — `session_by_model == ()`, `session_total == 0`.
- `test_sessions_are_newest_first_by_last_at` — order by derived sort key (`the-cost-of-one-more/11`), not text.
- `test_a_run_that_reported_nothing_counts_zero_tokens_and_one_run` — `usage == {}` adds to `runs`, not to totals.
- `test_ten_thousand_runs_answer_under_a_recorded_budget` — measured, number pinned with its argument.
- `test_reasoning_and_cache_creation_follow_the_same_none_rule` — present on one row → summed; absent everywhere → `None`.
- `test_an_openai_stream_without_the_usage_opt_in_reads_as_not_reported` — a stream whose final chunk carries no `usage_metadata` records `usage == {}` for that model, never zeros; and the slice that lands this asserts the runtime's streaming call opts in (`stream_usage`) where the provider needs it (LangChain docs: OpenAI and Azure chat completions require the opt-in).

Backend, `test_spend_route.py`:
- `test_route_answers_on_a_fresh_install` — 200, zeros/None.
- `test_route_passes_session_id_through` — session block present for a known id.
- `test_openapi_publishes_every_field` — the regenerated document carries `cached_tokens` as nullable.

Frontend:
- `spendModel.test.ts`: `null` spend → all dashes; `cachedTotal: null` → `'—'`; `0` → `'0'`; thousands grouping; `sessionModels` order = response order, joined with ` · `.
- `aSpendCellNeverSaysZeroForNothing.test.ts`: renders `SpendBar` with `cachedTotal: null` and asserts the DOM shows `—` and never `0`.
- `useSpend.test.ts`: refetches when `refreshKey` changes; error → `spend` stays at last good value, `error` set.
- `contractDrift.test.ts`: passes unchanged (generic census sees `/api/runs/spend`).
- `publicSurfaceCeiling.test.ts`: row updated.

## Least confident decisions
1. **Only LangChain's `UsageMetadata` keys are read** — `input_token_details.cache_read` / `cache_creation`, `output_token_details.reasoning` (confirmed against the docs 2026-09-04: OpenAI and Anthropic both land on these). A provider that spells a detail differently reads as *none reported*. Money is not on any vendor's wire; LangSmith computes it from a price table we do not hold — out of scope, on the map as fog.
2. **Sessions list is all sessions, uncapped.** 11 today. A cap needs a "more" affordance; deferred until a store shows hundreds.
3. **The bar refreshes on the run dock's terminal frame and window focus, not on an SSE.** Another tab's run appears late. Cheap and honest; an `/api/events` frame for runs is the upgrade path and is not built here.
4. **Audience: the endpoint answers the developer channel only.** The editor is the developer's; a customer-facing surface would use `run_usage(record.usage, audience)` the way `/api/runs/recorded` does. Not wired, so the route takes no `audience` parameter — adding one later is additive.
5. **`formatTokens` is locale-stable (`en-US` grouping) rather than `toLocaleString()`**, so tests do not depend on the machine.
