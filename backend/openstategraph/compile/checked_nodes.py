"""Whose streamed reply a grader will judge before the run ends.

## The finding

`every-workflow-green/45`. A grader-checked workflow puts its first attempt on
screen the moment the model types it, and nothing on that text says it is a
draft. The observed run answered a money question with **$96,699.19** — forty
times the total revenue the database holds — and thirteen seconds later the
grader rejected it, the revision loop ran, and the settled answer was
**$826.65**. The machinery worked; what the reader was shown while it worked
did not distinguish the two.

The agent cannot help here, and must not be asked to: its locked preamble
forbids it from referring to an earlier attempt at all, precisely so a model
never narrates its own retries. So marking which attempt a piece of text
belongs to is the surface's job, and this module is the fact the surface
needs.

## Why the compiler owns it

Two clients render that text — the editor's Ask panel and `/chat` — and
neither can work this out for itself. The editor holds the document, so it
could see a grader in *this* graph; `/chat` holds a diagram and a slug. And
**both** are blind to the case that produced the ticket's own recording: a
mount compiles a second document whose grader neither client has ever heard
of, and the reply streams from inside it. The one thing that has read every
document in the composition is the compiler, which is the same argument
`machinery_nodes` makes one field along, for the same clients.

## What "checked" means, exactly

A node is checked when a grader node is **reachable from it** — not when the
document merely contains one. The distinction is the whole value of the field:
`chinook-assistant` routes to a graded SQL branch and to an ungrounded web
branch with no grader anywhere downstream (ticket 44). A boolean per run would
mark the web branch's answer *"not checked yet"* and then never check it,
which is a worse lie than saying nothing — and it is what makes a one-attempt
run on an ungraded workflow gain no label at all rather than a flicker.

Reachability is read off the plan rather than off the raw edges, for the
reason `_closes_a_loop_impl` gives: `conditional` is where a grader's
destinations become a fact, and asking the compiler means this answer cannot
disagree with what the graph does.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from openstategraph.compile.workflow_compiler import CompiledPlan

#: The node type whose verdict is the check. One spelling, taken from the
#: registration in `NodeRuntime.factory` rather than retyped at each reader.
GRADER_NODE_TYPE = "route.grader"


def _successors(plan: "CompiledPlan") -> dict[str, set[str]]:
    """Every way control can move, from all three of the plan's edge shapes.

    `fan_out` counts: an orchestrator's `Send` dispatch is how control reaches
    a worker, and a worker whose result a grader judges is as much a draft as
    an agent's.
    """
    out: dict[str, set[str]] = {}
    for src, dst in plan.edges:
        out.setdefault(str(src), set()).add(str(dst))
    for src, branches in plan.conditional.items():
        out.setdefault(str(src), set()).update(str(d) for d in branches.values())
    for src, workers in plan.fan_out.items():
        out.setdefault(str(src), set()).update(str(w) for w in workers)
    return out


def nodes_a_grader_checks(
    plan: "CompiledPlan", types: Mapping[str, str]
) -> set[str]:
    """Node ids — and their graph-name spellings — a grader sits downstream of.

    Both spellings, for the reason `machinery_nodes` records: a `token` frame
    is reported under whichever of the canvas id and its `safe_name` the fold
    could resolve, and a node id legally carries characters a LangGraph node
    name may not.

    An empty result is the honest answer for a document with no grader in it,
    and it is the common case — nothing is marked, so nothing flickers.
    """
    from openstategraph.compile.workflow_compiler import safe_name

    graders = {node for node, kind in types.items() if kind == GRADER_NODE_TYPE}
    if not graders:
        return set()

    predecessors: dict[str, set[str]] = {}
    for src, destinations in _successors(plan).items():
        for dst in destinations:
            predecessors.setdefault(dst, set()).add(src)

    seen: set[str] = set()
    queue: deque[str] = deque(graders)
    while queue:
        node = queue.popleft()
        for src in predecessors.get(node, ()):
            if src not in seen:
                seen.add(src)
                queue.append(src)

    spelled: set[str] = set()
    for node in seen:
        spelled.add(node)
        spelled.add(safe_name(node))
    return spelled


__all__ = ["GRADER_NODE_TYPE", "nodes_a_grader_checks"]
