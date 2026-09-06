"""Which capabilities act outside the run, and how a graph runs one twice.

`launch-readiness/121`. Two graph-assembly facts meet one tool here, and until
this module existed nothing in the compiler noticed the meeting:

- **Every node is retried.** `workflow_compiler.build` hands
  `set_node_defaults` a `RetryPolicy` built from `DEFAULT_MAX_ATTEMPTS` below,
  and LangGraph's own description of what that does is *"a retry policy
  automatically re-runs a failed node attempt"* — the **whole node body**. An
  agent that sent a mail and then failed sends it again on attempt two.
- **A drawn cycle re-enters the node.** `router1 -> a-account -> grader1 ->
  router1` is the evaluator-optimizer pattern this product exists to make
  easy, and a grader asking for a revision after the mail went out gets a
  second mail.

Neither mechanism carries any memory of what already happened, and neither is
a defect on its own: retry is load-bearing for the transient provider failures
it was added for (a live Ollama 500, ticket 61), and a revision loop is the
point of a grader. What makes them a hazard is the *third* fact — that the
node can act outside the run — and that is the fact nothing declared.

**A leaf module on purpose.** It imports nothing from `compile/`, so
`workflow_compiler` can take `DEFAULT_MAX_ATTEMPTS` from here without a cycle,
and the plan is read structurally (`.edges`, `.conditional`,
`.tool_bindings`) rather than by importing `CompiledPlan`.
"""

from __future__ import annotations

from typing import Any, Mapping


#: Attempts every node gets from `set_node_defaults`, unless its own card says
#: otherwise. **Three, and deliberately not one** — the trap the ticket names.
#: Retry exists for transient failures and lowering it graph-wide trades a rare
#: duplicate for a common failure. Declared here rather than inline in `build`
#: so the finding and the policy cannot drift into two different numbers, which
#: is the same rule the `recording_attempts` wrapper is placed by.
DEFAULT_MAX_ATTEMPTS = 3


def acts_outside_the_run(tool: Any) -> bool:
    """Whether calling this tool changes something a re-run cannot take back.

    **Conservative, and the default is the whole decision.** The alternative
    on the table was a naming convention — `tool.email-send`, `tool.slack-send`
    — which is cheap and is wrong the first time somebody writes
    `tool.notify-oncall`, and wrong *silently*, in the direction that ships a
    duplicate. A `getattr` default of `True` is wrong in the other direction:
    it costs a sentence a developer answers once, in their own tool class.

    `getattr` rather than an attribute access, because `ITool` is a `Protocol`
    and a registry may legitimately hold something that never inherited from
    `BaseTool`. Such an object gets the same safe answer.
    """
    return bool(getattr(tool, "side_effecting", True))


def max_attempts(data: Mapping[str, Any]) -> int:
    """How many times this node's body can run for one arrival.

    Mirrors `workflow_compiler._node_overrides`' reading of `maxRetries`,
    which is the card field that becomes a per-node `RetryPolicy` — and per
    LangGraph, *"per-node values always win"* over `set_node_defaults`. Same
    tolerance for the same reason: blank, non-numeric or non-positive means
    "no override", never zero.
    """
    raw = str(data.get("maxRetries") or "").strip()
    if not raw:
        return DEFAULT_MAX_ATTEMPTS
    try:
        attempts = int(raw)
    except ValueError:
        return DEFAULT_MAX_ATTEMPTS
    return attempts if attempts > 0 else DEFAULT_MAX_ATTEMPTS


def _successors(plan: Any) -> dict[str, set[str]]:
    """Every drawn hop, static and conditional, as one adjacency map.

    Both kinds, for `_guarded_upstream`'s reason one direction over: a
    grader's `revise` is a **conditional** edge and absent from `plan.edges`,
    and it is the edge that closes every revision loop in this repository.
    """
    forward: dict[str, set[str]] = {}
    for src, dst in plan.edges:
        forward.setdefault(src, set()).add(dst)
    for src, branches in (plan.conditional or {}).items():
        forward.setdefault(src, set()).update((branches or {}).values())
    return forward


def reaches_itself(node_id: str, plan: Any) -> bool:
    """Whether any drawn path leaves this node and comes back to it."""
    forward = _successors(plan)
    seen: set[str] = set()
    stack = list(forward.get(node_id, ()))
    while stack:
        current = stack.pop()
        if current == node_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(forward.get(current, ()))
    return False


def upstream_of(node_id: str, plan: Any) -> set[str]:
    """Every node some drawn path reaches this one from, transitively.

    Cycle-safe, and never contains `node_id` itself unless a path genuinely
    leaves it and returns — which is the honest answer, not an artefact.
    """
    backward: dict[str, set[str]] = {}
    for src, dsts in _successors(plan).items():
        for dst in dsts:
            backward.setdefault(dst, set()).add(src)
    found: set[str] = set()
    stack = list(backward.get(node_id, ()))
    while stack:
        current = stack.pop()
        if current in found:
            continue
        found.add(current)
        stack.extend(backward.get(current, ()))
    return found


def repetition_clause(attempts: int, *, cyclic: bool) -> str:
    """How this node comes to run twice, in the words of its own fix.

    Both halves when both apply, because **they have different fixes** and a
    reader given one sentence would take the nearer one: lowering `maxRetries`
    does nothing about a loop, and the ticket names that as the trap. Empty
    when neither applies, which is how a correctly-drawn document stays quiet.
    """
    parts: list[str] = []
    if attempts > 1:
        parts.append(f"a failed attempt is run again, up to {attempts} attempts in all")
    if cyclic:
        parts.append("an edge leads back to it, so the loop runs it again")
    return ", and ".join(parts)
