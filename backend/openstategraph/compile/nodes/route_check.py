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

from openstategraph.compile.context import (
    _branch_entries,
    _text,
)
from openstategraph.compile.diagnostics import Finding
from openstategraph.compile.nodes.named_check import call_check
from openstategraph.compile.state import (
    RunState,
    _upstream_text,
)
from openstategraph.compile.workflow_compiler import CompiledPlan

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
FALLBACK_BRANCH = "fallback"


def _branch_ids(raw: Any) -> dict[str, str]:
    """`{how it might be written: the branch id}` for one node's branch table.

    Tolerant in reading, strict in trusting (`CLAUDE.md`). A function may
    answer with the branch's **name**, which is what a developer writes and
    what the card shows, or with its stable **id**, which is what the port and
    the edge carry — both are in the document, so both are real spellings of
    the same branch and refusing one would be a trap rather than a rule.
    Case and surrounding whitespace are forgiven for the same reason.

    Nothing else is. A name outside this table resolves to no branch at all
    and the caller takes `FALLBACK_BRANCH`, which is the strict half: the
    tolerance widens how a *declared* branch may be spelled, never what counts
    as one.

    Declaration order decides a tie, so a table whose name and id collide
    across two rows resolves to the row a reader meets first.
    """
    table: dict[str, str] = {}
    for entry in _branch_entries(raw):
        if isinstance(entry, dict):
            branch_id = str(entry.get("id") or entry.get("name") or "")
            name = str(entry.get("name") or entry.get("id") or "")
        else:
            branch_id = name = str(entry)
        if not branch_id:
            continue
        table.setdefault(name.strip().casefold(), branch_id)
        table.setdefault(branch_id.strip().casefold(), branch_id)
    return table


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
    upstream = [src for src, dst in plan.edges if dst == node_id]
    # A fork placed after a grader, a guard, a classifier or another fork
    # arrives over a *conditional* edge, which `plan.edges` does not carry —
    # the same situation `_output`, `_subgraph` and `_guard_check` handle.
    conditional_upstream = [
        src for src, dests in plan.conditional.items() if node_id in dests.values()
    ]
    wired = set(plan.conditional.get(node_id) or {})

    def run(state: RunState) -> dict[str, Any]:
        candidate = _upstream_text(state, upstream + conditional_upstream) or state.get(
            "question", ""
        )
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
        # A decision the node understands with nowhere to go. `_router_for`
        # falls through to the first declared destination rather than hanging,
        # which is right and was silent — the same pair of facts, and the same
        # answer, as `_grader`'s `unrouted` (`workflow-gallery` 31).
        if branch not in wired:
            update["unrouted"] = {node_id: branch}
        return update

    return run
