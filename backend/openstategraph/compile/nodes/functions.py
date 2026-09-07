"""The `function.` namespace: the built-in one, and the package's own.

Two builders, one reason to change — **what a `function.*` node is allowed to
be.** `_format_report_function` is the built-in, registered by exact type;
`_discovered_function` serves the whole `function.` namespace and loses to it
by the registry's exact-beats-namespace rule, so a package's own
`format_report` can never shadow the built-in by accident. That precedence is
the fact this module owns, and keeping the two apart would leave it stated in
neither.

`compile/nodes/__init__.py` carries the argument for the package and the
binding mechanism.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openstategraph.compile.workflow_compiler import CompiledPlan
from openstategraph.compile.state import RunState
from openstategraph.compile.diagnostics import Finding
from openstategraph.compile.state import _silent_member_note, _upstream_text
from openstategraph.compile.upstream import upstream_sources

if TYPE_CHECKING:
    # The class these functions are methods of. Type-only: the import that
    # matters runs the other way, once, when `NodeRuntime`'s class body binds
    # them. See this package's `__init__.py` for why that is the seam.
    from openstategraph.compile.node_runtime import NodeRuntime


def _format_report_function(
    self: "NodeRuntime", node_id: str, node: dict[str, Any], plan: CompiledPlan
) -> Any:
    """A deterministic **function** node — distinct from a *tool*.

    The distinction the cookbook (ticket 27) drew and this makes concrete: a
    *tool* is model-callable, chosen by an agent mid-loop; a *function* is a
    graph step the compiler always runs, with no model in the decision. This
    one has nothing to decide — it joins whatever worker results exist into
    one report, in task-id order, with no LLM call and therefore no
    variance. Determinism here is a feature: the same worker results always
    produce the same report text, which is what makes the graph-engineering
    proof below assertable byte-for-byte.
    """
    # The TS field schema (`FormatReportNode.ts`) calls this key
    # `reportTitle`, not `title` — found via a TS-schema-vs-Python-factory
    # diff, not live: a canvas-authored document could never have reached
    # this field at all, since every real document produces `reportTitle`
    # and this read silently fell through to the "Report" default every
    # time.
    title = (node.get("data") or {}).get("reportTitle") or "Report"
    #: Static edges and conditional branches alike, resolved once: the
    #: document's wiring does not change during a run.
    sources = upstream_sources(plan, node_id)

    def run(state: RunState) -> dict[str, Any]:
        results = state.get("worker_results") or {}
        # Scoped to ids the *current* plan(s) declared, not every id ever
        # written across every past attempt. `subtasks[orchestrator_id]` is
        # overwritten (not accumulated) on each replan, so this discards
        # stale results from a rejected attempt rather than silently
        # blending them into a report about the latest one.
        current_ids = {
            task["id"]
            for plan_list in (state.get("subtasks") or {}).values()
            for task in plan_list
        }
        scoped = {k: v for k, v in results.items() if k in current_ids}
        # No worker fan-out reached this join — so gather what its own
        # upstream nodes produced instead (`every-workflow-green` 27). Both
        # edge tables, through the one reader: a source arriving on a
        # guard's `pass` is in `plan.conditional` and not in `plan.edges`,
        # so reading only the latter answered "nothing was dispatched to
        # this join" about a wired, drawn graph (`osg-agent-experience` 51).
        #
        # This is the shape the `empty` message below has always described
        # and refused: "an edge into `candidate` from anything else
        # sequences this step without carrying data". It is now the shape a
        # classifier in `matchMode: "all"` produces on every compound
        # question, so refusing it would mean two desks running in parallel
        # and one of them being thrown away by `answer`'s LATEST_NONEMPTY —
        # the same silent loss the mode exists to end, moved one node
        # along.
        #
        # A fallback rather than a merge, and preferred in that order: an
        # orchestrator fan-out and a classifier fan-out do not share a join
        # in practice, and reading `worker_results` first keeps every
        # shipped report byte-identical.
        if not scoped:
            outputs = state.get("outputs") or {}
            scoped = {
                src: str(outputs[src])
                for src in sources
                if str(outputs.get(src) or "").strip()
            }
        # A task that died (retries exhausted → error handler wrote to
        # outputs, which carries no task identity) must appear as a
        # named gap, not vanish from the join (ticket 61 residual #2).
        for missing in sorted(current_ids - scoped.keys()):
            scoped[missing] = "_(this task failed before reporting a result)_" 
        body = "\n\n".join(
            # An empty member result renders as an explicit gap — a blank
            # section reads like formatting, and the grader (and the
            # human) must see the miss to act on it (ticket 61).
            f"### {task_id}\n{text or _silent_member_note(task_id, state)}"
            for task_id, text in sorted(scoped.items())
        )
        # An empty body means the *plan* was empty, not that the workers
        # were quiet: a dispatched task that died is filled in above as a
        # named gap. So the only way to get here is that nothing ever
        # dispatched to this join — the shape `docs/patterns.md` §4 warns
        # about, where agents are wired straight into `candidate` and the
        # edges sequence the join without carrying anything. Saying which
        # of the two happened is the difference between a debuggable run
        # and a shrug (production-ready ticket 31).
        empty = (
            "_No results — nothing was dispatched to this join. It reports the "
            "worker results of a supervisor's fan-out; an edge into `candidate` "
            "from anything else sequences this step without carrying data "
            "(docs/patterns.md §4)._"
        )
        report = f"# {title}\n\n{body}" if body else f"# {title}\n\n{empty}"
        return {"outputs": {node_id: report}, "answer": report}

    return run


def _discovered_function(self: "NodeRuntime", node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
    """A workflow-discovered function as a deterministic graph step.

    The signature contract is `fn(text: str) -> str` — a transform of the
    node's upstream text, no model, no state access (ticket 35: code is
    referenced by name, never given the raw state to hide control flow
    in). A raised exception becomes readable output — the same
    errors-are-data rule `BaseTool.run` applies: retrying a deterministic
    function reproduces the same failure, so the useful move is to carry
    the message downstream where a grader or a person can read it.
    """
    node_type = str(node.get("type", ""))
    fn = self.services.functions.get(node_type)
    if fn is None:
        self.diagnostics.record(Finding.UNRESOLVED_FUNCTION, node_type)
        return self._passthrough(node_id, node, plan)

    # A function node fed by a grader's `pass` (or a guard's `pass`, or an
    # approval's `approved`) arrives over a *conditional* edge, which
    # `plan.edges` does not carry — `_agent`, `_output`, `_guardrail` and
    # `_subgraph` already close this gap; this handler was the one left
    # open (`launch-readiness` 66). Without it, a function node placed
    # behind a routed edge silently read the turn's original question
    # instead of its wired upstream — found live, with `execute_sql`
    # reading a natural-language question where SQL should have been, and
    # nothing reporting it.
    sources = upstream_sources(plan, node_id)

    def run(state: RunState) -> dict[str, Any]:
        text = _upstream_text(state, sources) or state.get("question", "")
        try:
            result = fn(text)
        except Exception as exc:
            return {"outputs": {node_id: f"[{node_id} failed: {type(exc).__name__}: {exc}]"}}
        output = result if isinstance(result, str) else str(result)
        return {"outputs": {node_id: output}, "answer": output}

    return run
