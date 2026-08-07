Type: task
Status: resolved (2026-08-07) — fixed in commit `7cd4bc1`, this ticket records the contract

## Question

Ticket 20 gave Router branches stable ids on the frontend (`[{id,name}]`,
ports named `branch:<id>`) and never told Python. `_router` parsed a newline
string, got `[]`, fell back to `"default"`, and `_router_for` sent **every**
question to the first destination — silently, with all 316 tests green,
because no test loaded a v2 document. A second mismatch hid underneath:
conditional-edge labels are branch *ids* while `Router.classify` returns
branch *names*.

## Resolution

The contract, now pinned by `backend/tests/test_router_branches.py` (43 tests):

- `Branch.of` accepts a bare name (v1), a `{id,name}` mapping (v2), or a
  `Branch`; a missing half borrows the other.
- `IRouter.branches` stays `list[str]` of **names** — the prompt never shows
  an opaque id, because the model would try to emit it.
- `BaseRouter.route_key(name)` is the one place the name→id mapping lives;
  `NodeRuntime._router` writes `route_key(decision.branch)` to
  `state["decisions"]`, which is what the conditional edge dispatches on.
- Unknown names pass through untouched — a misroute is recoverable, an
  exception in the entry node is an outage.

Standing rule this enforces: **any contract change to a serialized field is a
two-sided change**; the real-file E2E suite is the guard that catches drift.
