"""Which capabilities answer from outside the run, and where no gate stands.

`launch-readiness/151`, and the rule it makes checkable:

> **A model may supply a *word*. It may never supply a *number*.**

A guess about **language** — *"you probably mean Middle East Gulf"* — is safe,
because the store re-resolves it and it either matches something real or is
reported as not covered. A guess about a **quantity** — `1664`, `4031`,
*"81 ports"* — is unfalsifiable at the moment it is made and indistinguishable
from a fact. Measured on this project: three identical runs of one question
gave a correct answer, a correct refusal, and an **invented 81-port country
set** (`launch-readiness/126`, `127`).

This module is the compile-time half. It answers one structural question —
*can a model-supplied quantity reach an Output without passing a gate?* — and
`Finding.UNDECLARED_FALLBACK` says so at build time, naming the node.

**A leaf module on purpose**, the same way `side_effects.py` is: it imports
nothing from `compile/`, and reads the plan structurally (`.edges`,
`.conditional`) rather than by importing `CompiledPlan`.
"""

from __future__ import annotations

from typing import Any, Mapping


def answers_from_outside_the_run(tool: Any) -> bool:
    """Whether this tool's results are open-world text rather than records.

    **The default is the quiet side, and that is the difference from
    `acts_outside_the_run` next door.** `launch-readiness/121` defaults
    `side_effecting` to `True` because an undeclared tool must land on the
    *safe* side, and there the safe side is also the rare side — a mail sender
    is unusual, so the noise falls where it belongs. Here the relationship is
    inverted: nearly every tool in a quantitative workflow *is* the store, so
    a conservative default would fire this finding on every graph holding an
    agent and a tool, and the ticket names that as the failure that makes a
    finding worthless ("a finding that fires on every graph is a finding
    nobody reads").

    The two flags also carry different costs for being wrong. A false negative
    on `side_effecting` sends a duplicate mail; a false negative here is a
    missing sentence about a hazard the run-time gate can still catch. So the
    declaration burden sits on the unusual case — the tool that reaches past
    the run's own data — and `tool.web-search` / `tool.web-fetch` declare it.

    `getattr` rather than an attribute access, because `ITool` is a `Protocol`
    and a registry may hold something that never inherited from `BaseTool`.
    """
    return bool(getattr(tool, "open_world", False))


def _predecessors(plan: Any) -> dict[str, set[str]]:
    """Every drawn hop, static and conditional, read backwards.

    Both kinds, for `_guarded_upstream`'s reason: a grader's `pass` and a
    guardrail's `blocked` are **conditional** edges, and they are the ones
    that reach an Output in every guarded document in this repository.
    """
    backward: dict[str, set[str]] = {}
    for src, dst in plan.edges:
        backward.setdefault(dst, set()).add(src)
    for src, branches in (plan.conditional or {}).items():
        for dst in (branches or {}).values():
            backward.setdefault(dst, set()).add(src)
    return backward


def reaches_without_passing(node_id: str, plan: Any, blockers: Any) -> set[str]:
    """Every node a drawn path reaches `node_id` from without meeting a blocker.

    A blocker is not *reported* and is not *walked through* — the walk stops
    there, which is what "a gate stands between them" means structurally. It
    is `node_runtime._guarded_upstream` generalised: that one asks whether a
    producer survives the walk, this one hands back the survivors so the
    caller can ask a question about each.

    Cycle-safe. Never contains `node_id` unless a path genuinely leaves it and
    returns.
    """
    stopped = set(blockers)
    backward = _predecessors(plan)
    found: set[str] = set()
    stack = list(backward.get(node_id, ()))
    while stack:
        current = stack.pop()
        if current in found or current in stopped:
            continue
        found.add(current)
        stack.extend(backward.get(current, ()))
    return found


def gated_by(plan: Any, types: Mapping[str, str], gate_type: str) -> set[str]:
    """The nodes of `gate_type` in this document, as blockers for the walk.

    Deliberately keyed by *type* and not by what the gate checks. This finding
    reports the **absence** of a gate, never the adequacy of one — and
    `launch-readiness/133` is the record of why: a check that accepted
    `SELECT DISTINCT k, a, b` as a dedup reported success on a wrong query,
    which is worse than no check, because it turned "unverified" into
    "verified". Judging a gate's contents from the compiler would be the same
    move. What a placed gate actually verifies is the run-time half's job.
    """
    return {node_id for node_id in plan.nodes if types.get(node_id, "") == gate_type}
