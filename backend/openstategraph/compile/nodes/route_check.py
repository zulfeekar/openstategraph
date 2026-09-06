"""`route.check` — the fork a package function decides.

`osg-agent-experience/42`. The owner's rule is that a question naming no date
range is asked back rather than answered on an assumed window, and the fact was
already in the run for free: `resolve.vocabulary` reports the range as
uncovered without calling anybody. Nothing could turn that fact into a route to
an output. `guard.check` routes `pass`/`revise`, but `revise` is a `feedback`
port and an `output.formatted` takes `result`; `route.classifier` can name an
`ask_back` branch, but a **model** picks it, and on the first live run
(2026-09-05, *"How much crude did Norway export?"*) it picked `sm_shipments`
and never asked. A deterministic fact was demoted to a model's judgement
because no node carried it.

## What it is, in one sentence

`route.classifier`'s shape with `guard.check`'s means: the same
`add_conditional_edges` construct, one label per branch, decided by a named
package function instead of by a model.

## Why it is not a flag on either of them

- Not a mode of `route.classifier`, because that node's whole substance is a
  composed prompt — a preamble, the branch list as Context, the developer's
  rules, a locked output contract. A "no model" switch would make every one of
  those fields dead configuration on half the instances, which is the
  Interface-Segregation failure `CLAUDE.md` names.
- Not a mode of `guard.check`, because its outputs would change **kind** with
  configuration: two ports typed `result`/`feedback` on one setting and n ports
  typed `result` on another. Cardinality belongs to the port; *type* does not
  vary at runtime at all.

So it is a sibling, and what the two checks share is a collaborator rather than
an ancestor — `named_check.call_check`, the lookup-and-call that turns a raised
exception into data. The rest is different because the questions are different.

## Every out-port is `result`-typed, and that is the ticket

A grader's and a guard's `revise` is `feedback`, which only a node declaring a
`feedback` input accepts — an agent, a router. That is right for a loop and it
is exactly what an ask-back could not use, because the thing an ask-back wants
downstream is an **output**. Here every way out carries the same `result` a
function or an agent emits, so an output, an agent or another fork may hang off
any branch.

## Termination

No lap budget and no `maxAttempts`, deliberately — unlike `guard.check`. This
node does not close a cycle: its branches go forward. A document that draws one
back into a cycle is caught by the machinery that already catches every other
one (`always_taken_cycles` needs a conditional step on the loop, and this *is*
a conditional step), so a lap counter here would be a second answer to a
question already answered.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openstategraph.compile.context import _text
from openstategraph.compile.fields import branch_ids_by_spelling as _branch_ids
from openstategraph.compile.diagnostics import Finding
from openstategraph.compile.nodes.named_check import call_check
from openstategraph.compile.upstream import upstream_sources
from openstategraph.compile.state import (
    RunState,
    _upstream_text,
)
from openstategraph.compile.workflow_compiler import (
    ROUTE_CHECK_FALLBACK_BRANCH,
    CompiledPlan,
    unrouted_record,
)

if TYPE_CHECKING:
    # The class these functions are methods of. Type-only: the import that
    # matters runs the other way, once, when `NodeRuntime`'s class body binds
    # them. See this package's `__init__.py` for why that is the seam.
    from openstategraph.compile.node_runtime import NodeRuntime

#: The way out for a name the function did not give, or gave and nothing
#: declares. A **static** port rather than one of the configured rows, which is
#: the one place this node's branch table differs from a classifier's.
#:
#: A classifier's `fallback` is a *field naming one of its own branches*,
#: because the fallback is something the model has to be told about in the
#: prompt — it is a sentence in `_describe_branches`. There is no prompt here
#: and nothing to tell, so the honest shape is a port that always exists: a
#: developer can see on the canvas where an unrecognised answer goes, instead
#: of discovering it in `_router_for`'s first-destination default.
FALLBACK_BRANCH = ROUTE_CHECK_FALLBACK_BRANCH


def _route_check(self: "NodeRuntime", node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
    """Names the branch for the conditional edge to read. No model.

    The split is the one `_router`'s module docstring describes and this is
    the other half of: the node writes `decisions[node_id]`, and the
    compiler's `path` function (`_router_for`) dispatches on it. Neither has
    to know how the other works.

    The function contract is the same `fn(text: str) -> str` every
    `function.*` node already uses (`_discovered_function`) — no new registry
    and no widened signature. What differs is only how the return is read: a
    `guard.check` reads it as a complaint, this reads it as a destination.
    """
    data = node.get("data") or {}
    check_name = _text(data, "check").strip()
    fn = self.services.functions.get(f"function.{check_name}") if check_name else None
    if fn is None:
        # At build time, not on the first lap: which function a document names
        # is a document fact, and a run that discovers it has no decider ought
        # to have been told before it started.
        self.diagnostics.record(Finding.UNRESOLVED_FUNCTION, f"route.check:{check_name}")
    branches = _branch_ids(data.get("branches"))
    # A fork placed after a grader, a guard, a classifier or another fork
    # arrives over a *conditional* edge, which `plan.edges` does not carry —
    # the same situation `_output`, `_subgraph` and `_guard_check` handle.
    sources = upstream_sources(plan, node_id)
    wired = set(plan.conditional.get(node_id) or {})

    def run(state: RunState) -> dict[str, Any]:
        candidate = _upstream_text(state, sources) or state.get("question", "")
        if fn is None:
            answered, reason = "", f'no function named "{check_name}" is discovered here'
        else:
            answered, reason = call_check(fn, candidate)

        branch = branches.get(answered.strip().casefold()) if answered else None
        if branch is None:
            branch = FALLBACK_BRANCH
            if not reason:
                reason = (
                    f'the check returned "{answered}", which no branch declares'
                    if answered
                    else "the check returned nothing"
                )

        update: dict[str, Any] = {
            "decisions": {node_id: branch},
            # A fork forwards; it does not transform. Written so a node
            # downstream of any branch reads the candidate rather than the
            # empty string — `_upstream_text` resolves through `outputs`.
            "outputs": {node_id: candidate},
            "verdicts": {
                node_id: {"verdict": branch, "reason": reason, "check": check_name}
            },
        }
        # A decision the node understands with nowhere to go. It was reported
        # here and dispatched wrongly there: `_router_for` fell through to the
        # first declared destination, so a fork published a branch its own
        # verdict had not named (`osg-agent-experience/80`). The dispatch is
        # fixed at the compiler seam; what this writes is the record of it,
        # and it now carries *which* of the two things happened, because a
        # fallback taken and a run stopped read very differently to whoever
        # is looking for their answer.
        if branch not in wired:
            update["unrouted"] = {
                node_id: unrouted_record(branch, stopped=not plan.unrouted_route.get(node_id))
            }
        return update

    return run
