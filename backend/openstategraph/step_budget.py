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
