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

**And when the child stops itself instead** (`organisms-first-class` 62), the
overrule travels up inside the `budget_stops` value rather than through a
channel of its own — `record_overruled_mount` at the boundary,
`read_budget_stop` in `workflow_compiler.step_budget_warnings`. Said once per
package however many times it is mounted, and only when the ceiling actually
bit: a child that asked for less, or asked for more and never ran low, is told
nothing, because a warning nobody can act on is the same defect as a promise
nobody can keep.

**Why it exists at all** (`workflow-gallery` 26). `settings.recursionLimit`
was held by the editor's model, serialised by `RuntimeClient`, accepted by
`RunRequest` and consumed by the graph config — and read out of a saved
document by nothing. A developer set it, it round-tripped faithfully through
`workflow.json`, and every run took 50 regardless. A declared field that
reaches nothing looks supported, which is the defect class
`test_data_key_contract.py` was written for.
"""

from __future__ import annotations

from typing import Any, Mapping

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
    return cap_step_budget(inherited, workflow_step_budget(document))


def cap_step_budget(inherited: int, requested: int | None) -> int:
    """`mount_step_budget`'s one decision, without a document to read it from.

    Split out for `composition_step_budget` below, which walks the mount tree
    the compiler recorded rather than the documents it was built from — the
    tree carries the saved number, not the document. Two callers, one rule, so
    the arithmetic of a *bound* cannot drift from the arithmetic of a *run*.
    """
    return inherited if requested is None else min(inherited, requested)


def composition_step_budget(ceiling: int, mounts: Mapping[str, Any]) -> int:
    """The most supersteps a whole composition may spend, top graph included.

    `organisms-first-class` 63, whose title said the total was *unbounded in
    depth*. Measured, it is not, and both halves of that matter:

    - **Depth on its own costs nothing.** A loop package mounted three levels
      down spends exactly what it spends one level down; a composition's cost
      tracks the number of mount *instances in the expansion*, which is drawn.
      Depth multiplies only where the drawing branches, which is the same
      sentence as "eight loops run eight loops".
    - **The expansion is finite, and finite at build time.**
      `NodeRuntime._subgraph` compiles every child eagerly and refuses a mount
      cycle there (`_ancestry`), so by the time a graph exists every mount it
      will ever make has been compiled and recorded. There is therefore a
      worst case, and it can be reported before the run starts.

    So the answer taken for 63 is **reporting**, not preventing. The two
    preventions were priced and rejected, and are pinned against in
    `test_a_compositions_total_spend_is_bounded_by_its_drawing.py`:

    - **One shared, decrementing allowance** across the composition is what
      "bound the total" would mean, and it makes a mount's cost depend on what
      ran before it. `CLAUDE.md` defines a mount as *"another workflow run as
      one isolated step — task in, answer out"*; a package that behaves
      differently in the second position than in the first is not that, and
      the innermost loop — the one a developer can least predict — is the one
      that would starve.
    - **A depth-scaled ceiling**, each level taking a fraction, is bounded and
      position-independent and silently starves deep compositions, which is
      `61`'s stated cost multiplied. It would also break `59`'s computed floor
      for any level below it.

    The sum, not a product: the top graph's ceiling plus, for each mount, the
    ceiling *it* runs under (`61`'s downward-only cap, applied at every edge
    and inherited past it) plus everything below it. `mounts` is the map
    `NodeRuntime` recorded — `MountedGraph.saved_step_budget` and
    `MountedGraph.mounts` are the only two fields read.

    It is a **ceiling, not an estimate**. A real run reaches it only if every
    loop in every document exhausts its own budget, which is what
    `56`'s guard exists to stop happening quietly.
    """
    total = ceiling
    for mount in mounts.values():
        branch = cap_step_budget(ceiling, getattr(mount, "saved_step_budget", None))
        total += composition_step_budget(branch, getattr(mount, "mounts", None) or {})
    return total


def read_budget_stop(value: Any) -> tuple[Any, list[dict[str, Any]]]:
    """A `budget_stops` value, read tolerantly: how much was left, and why.

    `organisms-first-class` 62. The key's value was a bare `remaining` count
    written by `_grader`, which is all a grader knows. A mount knows one more
    thing — whether the ceiling the child ran under was smaller than the one
    the child's own document asked for — and that fact has no other way to
    reach a reader: it is minted at the boundary, while the sentence is minted
    in `workflow_compiler.step_budget_warnings` out of this key.

    So the value widens rather than a fifth key being invented: the four keys
    this boundary carries (`outputs`, `forced`, `unrouted`, `budget_stops`)
    have already been lost there three times, and the streaming door folds
    these values through verbatim, so widening the *value* keeps both doors
    agreeing for free.

    Both shapes are read and neither is trusted further than its keys:

    - `3` — a grader that stopped itself under a ceiling nobody overruled.
    - `{"remaining": 3, "overruled": [{...}]}` — the same, plus one record per
      mount boundary that could not honour a saved step budget.
    """
    if isinstance(value, dict):
        overruled = value.get("overruled")
        return value.get("remaining"), [
            record for record in overruled if isinstance(record, dict)
        ] if isinstance(overruled, list) else []
    return value, []


def record_overruled_mount(
    value: Any, workflow: str, requested: int, allowed: int
) -> dict[str, Any]:
    """Add this mount's overruled request to one `budget_stops` value.

    Appended rather than replacing, because a grandchild's overrule and its
    parent's are two different facts about two different documents and both
    are true — `nested_record` prefixes the *key* through every mount, and
    this does the same job for the value. Idempotent on the record, so a
    boundary crossed twice cannot double it.
    """
    remaining, overruled = read_budget_stop(value)
    record = {"workflow": workflow, "requested": requested, "allowed": allowed}
    if record not in overruled:
        overruled = [*overruled, record]
    return {"remaining": remaining, "overruled": overruled}
