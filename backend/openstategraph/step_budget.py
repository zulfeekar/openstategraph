"""How many supersteps one run may spend, and where that number comes from.

**Supersteps, not iterations.** LangGraph's `recursion_limit` counts
supersteps across the whole graph, so one lap of a loop that fans out costs
several — `examples/fanout-in-a-loop` spends four per lap. CLAUDE.md
therefore forbids the label "max iterations" anywhere a user reads, and the
settled user-facing word is **step budget**. This module is named for that
word so the vocabulary has one home rather than a convention.

**Why it is its own module.** The number is decided in three places that do
not share a layer — the HTTP doors in `api/routes/runs.py`, and
`CompiledWorkflow.ask` in `loader.py`, which is what `openstategraph run`
calls. `workflow_default_model` lives in `api/model_resolution` because only
the API resolves a model; the budget is also the CLI's, and `loader` must
not import the API to get it. It is also deliberately import-cheap: nothing
here pulls langgraph in, which `import openstategraph` is asserted on.

**What happens when it runs out** (`organisms-first-class` 56). Not a crash.
`_grader` reads LangGraph's managed `remaining_steps` and, with barely any
left, stops asking for another lap: the run takes the wired `pass` edge, the
answer it had is published, and `run_health` reports a budget stop on the
silent channel. Before that, `GraphRecursionError` came out of every door and
the answer the workflow had already produced was thrown away — with
LangGraph's own advice to raise the number, which is the opposite of what this
module's callers tell a user.

**A mount runs on this number too, and may only ask for less**
(`organisms-first-class` 60 and 61). A mounted child is a separate `invoke`
with a fresh superstep counter and the *run's* ceiling, inherited through the
ambient runnable config — so the ceiling is the **run's**, settled by 60. What
61 added is `mount_step_budget` below: the child's own saved
`settings.recursionLimit` is consulted at the mount boundary and can *lower*
that ceiling for the child, never raise it. Below the slack the
guard above needs, the child cannot stop itself and the exhaustion arrives at
the mount boundary, where `node_runtime._subgraph` translates it into
`StepBudgetExhausted` rather than letting LangGraph's advice to raise the
number reach a caller. That one *is* a failed step: unlike the loop door there
is no candidate to publish.

**Why it exists at all** (`workflow-gallery` 26). `settings.recursionLimit`
was held by the editor's model, serialised by `RuntimeClient`, accepted by
`RunRequest` and consumed by the graph config — and read out of a saved
document by nothing. A developer set it, it round-tripped faithfully through
`workflow.json`, and every run took 50 regardless. A declared field that
reaches nothing looks supported, which is the defect class
`test_data_key_contract.py` was written for.
"""

from __future__ import annotations

from typing import Any

#: Supersteps, not iterations. Matches the editor's own default so a
#: workflow behaves the same run from a script as from the canvas.
DEFAULT_STEP_BUDGET = 50

#: The same window `RunRequest.recursion_limit` validates against. A
#: document is *not* validated by Pydantic, so a saved number outside it
#: arrives here rather than being rejected at the door.
MIN_STEP_BUDGET = 10
MAX_STEP_BUDGET = 1000


def workflow_step_budget(document: Any) -> int | None:
    """The budget this document saved, or `None` if it saved none.

    Tolerant in reading, strict in trusting — CLAUDE.md's rule, applied to a
    document rather than to a model's reply. The editor writes
    `recursionLimit`; a hand-written package or a script is at least as
    likely to write `recursion_limit`, and both mean the one thing, so both
    are read. Everything else is *not* interpreted: a string, a float, a
    `bool` (which is an `int` in Python and is never a step budget) and a
    non-dict `settings` all return `None` and inherit the default. Nothing
    here raises — a saved number is not worth killing a run over.

    Out of range is **clamped, not obeyed and not refused**. Refusing would
    mean a document that opens fine in the editor cannot run; obeying would
    put a value past the door's own contract into the config.
    """
    settings = document.get("settings") if isinstance(document, dict) else None
    if not isinstance(settings, dict):
        return None
    for key in ("recursionLimit", "recursion_limit"):
        value = settings.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return max(MIN_STEP_BUDGET, min(MAX_STEP_BUDGET, value))
    return None


def resolve_step_budget(explicit: int | None, document: Any) -> int:
    """The budget one run gets: the caller's, else the document's, else 50.

    Precedence mirrors `resolve_model(request.model or
    workflow_default_model(document))` exactly, and for the same reason: a
    caller who names a number means it, and a workflow that names one runs
    the same wherever it is opened.
    """
    if explicit is not None:
        return explicit
    return workflow_step_budget(document) or DEFAULT_STEP_BUDGET


def mount_step_budget(inherited: int, document: Any) -> int:
    """The ceiling a *mounted* child runs under: the smaller of two numbers.

    `organisms-first-class` 61. `resolve_step_budget` above answers "what does
    this run get"; this answers "how much of it may this mount spend", and the
    two differ because the caller is different. A caller of a run *names* a
    number and means it, higher or lower. The caller of a mount is the run
    itself, and its number is a **ceiling** — a mount is one isolated step of
    it. So a child package's saved `settings.recursionLimit` is honoured in
    exactly one direction:

        min(what the run allows, what the child saved)

    A child asking for **less** gets less, and stops itself gracefully through
    `56`'s guard instead of spending a caller's budget it declared it did not
    need. A child asking for **more** gets the run's number, because the
    alternative — a mounted package saving 1000 inside a `recursion_limit=10`
    run — is an unbounded run, which is the one thing a step budget exists to
    prevent. That case is not silent: `node_runtime._subgraph` names both
    numbers when such a child then runs out.

    Reading the child's number as the *winner* was priced and rejected for
    that reason; ignoring it entirely was rejected because the downward
    direction costs a caller nothing. Before this, neither direction had any
    effect at any depth — a grandchild saving 200 under a mid saving 300 ran
    on the run's number and neither saved number was consulted.
    """
    requested = workflow_step_budget(document)
    if requested is None:
        return inherited
    return min(inherited, requested)
