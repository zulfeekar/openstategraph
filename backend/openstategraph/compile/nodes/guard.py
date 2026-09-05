"""`guard.policy` and `guard.check` — the two nodes that stand in the way.

Siblings rather than one family with a flag, because they refuse different
things: a policy rewrites or blocks an outbound answer, a check asks a named
question of the evidence and routes on the answer. They share this module
because they share their subject — *what must be true before this leaves* —
and neither shares it with anything else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openstategraph.counted_rows import check_row_counts_in_prose
from openstategraph.grounded_numbers import check_numbers_in_prose
from openstategraph.table_coverage import check_zero_outside_coverage

#: Checks `guard.check` can name without a package function behind them
#: (`launch-readiness` 151).
#:
#: **One entry, and the registry exists because one entry could not fit the
#: existing contract.** `fn(text) -> str` is the narrow, serialisable seam
#: every `function.*` node uses, and it is right: a function with access to
#: raw graph state would be a second place for control flow to hide. But F3
#: asks *did anything this run retrieved contain this number*, which is a
#: question about the evidence, not about the text — so it is core's to
#: answer, with the wider signature, rather than a contract widened for
#: everybody. A package function of the same name still wins, so this is a
#: default and not a reservation.
#: A **second** entry (`launch-readiness` 165), on the same argument and a
#: different axis. `numbers_in_prose` asks where a number came from;
#: `row_counts_in_prose` asks what it counted — a bare `COUNT(*)` returns rows,
#: and the run that published *"1,454,449 dark vessels"* had retrieved that
#: number honestly, so 151's gate passed it correctly. Both need the evidence
#: rather than the text, which is what keeps them here.

_BUILT_IN_CHECKS: dict[str, Any] = {
    "numbers_in_prose": check_numbers_in_prose,
    "row_counts_in_prose": check_row_counts_in_prose,
    "zero_outside_coverage": check_zero_outside_coverage,
}

#: It came here from `compile/node_runtime.py` in the `docs-and-gaps/03`
#: split, unchanged, because `guard.check` is the only reader it has ever
#: had. That is the difference between what is genuinely shared and what
#: merely looked shared for being declared at the top of a long file.

if TYPE_CHECKING:
    # Types only — `from __future__ import annotations` keeps langgraph's
    # store out of this module's import graph, the pattern `loader.py`
    # established. The name is what matters here: `BaseStore` is the memory
    # store, never the filesystem `WorkflowStore` (ticket 12).

    # `mounted_graphs` is annotated with it below. The runtime import is
    # deliberately local to `builder_for` — `compile.composition` imports
    # back into this module — so the forward reference had nothing to
    # resolve against and both gates said so: ruff `F821` and mypy
    # `name-defined` (`organisms-first-class` 47).
    pass
from openstategraph.abc.tool_notes import (
    UnverifiedAnswer,
    record_notes,
)
from openstategraph.compile.diagnostics import (
    Finding,
)
from openstategraph.grounded_numbers import MODEL_AUTHORED
from openstategraph.run_summary import RunSummary, summarise_run
from openstategraph.compile.workflow_compiler import (
    CompiledPlan,
    failure_marker,
    step_budget_floor_for,
)
from openstategraph.compile.context import (
    _text,
)
from openstategraph.compile.upstream import upstream_sources
from openstategraph.compile.state import (
    RunState,
    _upstream_text,
)
from openstategraph.compile.grounding import _PRODUCES_CONTENT


def _wants_the_summary(fn: Any) -> bool:
    """Whether this check's function takes the run summary as well as the text.

    `osg-agent-experience/50`. The contract is still `fn(text) -> str` and a
    one-argument function is still the whole of it — the second parameter is
    an **opt-in**, read off the signature rather than announced by a flag,
    which is what makes every function anybody has already written keep
    working with no edit.

    Read once at build time, not per lap. Tolerant: a callable whose signature
    cannot be inspected at all (a C builtin, an exotic partial) is taken as
    the one-argument shape — the shape it has always had.

    Strict about what counts as room for a second argument: a keyword-only
    parameter is not it, and neither is `**kwargs`. `*args` is, because a
    function written `def check(*args)` genuinely accepts one.
    """
    import inspect

    try:
        parameters = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return False
    positional = [
        p
        for p in parameters
        if p.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in parameters):
        return True
    return len(positional) >= 2

if TYPE_CHECKING:
    # The class these functions are methods of. Type-only: the import that
    # matters runs the other way, once, when `NodeRuntime`'s class body binds
    # them. See this package's `__init__.py` for why that is the seam.
    from openstategraph.compile.node_runtime import NodeRuntime


def _guardrail(self: "NodeRuntime", node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
    """Applies a PII/content policy, and decides `allowed` or `blocked`.

    A **real state-transforming graph node**, not middleware and not a
    degenerate agent. Ticket 01 asked whether `PIIMiddleware`'s detection
    is separable, and it is: `RedactionRule` is public, its resolved form
    applies to a plain string, so `abc.guardrail` borrows every detector
    and every strategy from the library without importing an agent.

    ## Position is the scope, and this is where that stops being a slogan

    There is no `apply_to_input` / `apply_to_output` flag here, and there
    must never be one — the map settled that the canvas already says which
    direction an instance is, and a flag that can disagree with the wire
    is the `advisor`/`audience` defect again (`api/audience.py`). What
    makes an outbound instance behave differently is not configuration: it
    is that by the time it runs there is a settled `answer` and a
    populated `outputs` map for its policy to reach, and an inbound one
    has neither. One behaviour; the wire decides the consequence.

    ## Why it scrubs more than its own output

    `outputs` is not private state. `api/audience.py`'s table puts
    `decisions` / `outputs` on the **customer's** `done` frame — they are
    facts about their own turn — and every surface renders the map per
    node. So an outbound guard that rewrote only its own text would hand
    a customer a clean answer beside `outputs["agent-sql"]` carrying the
    59 real addresses `SELECT Email FROM Customer` returned. Scrubbing
    every entry it can see is not spooky action: it is this node doing
    exactly what its card says, at the confluence, which is the same
    argument `_output`'s never-blank floor makes.

    ## What it cannot reach, stated rather than implied

    `token` frames. The agent streams its prose while it is still typing
    and this node runs afterwards, so the live wire is already past. That
    is not a gap to paper over here — LangChain draws the identical line
    and answers the second half with `PIIMiddleware(apply_to_output=True)`,
    whose stream transformer sits *inside* the agent. Middleware on the
    agent base, never a node; see `.scratch/guardrails/map.md`.
    """
    from openstategraph.abc.guardrail import Guardrail

    data = node.get("data") or {}
    raw_policy = data.get("policy")
    policy = [row for row in raw_policy if isinstance(row, dict)] if isinstance(
        raw_policy, list
    ) else []
    guardrail = Guardrail(rules=policy, refusal=_text(data, "blockedMessage"))
    # Compile time, not run time (guardrails ticket 05). A `detector` is
    # the one regex a developer writes, and until this line nothing looked
    # at it until `screen()` did — so a missing `)` was an exception in the
    # middle of somebody's run rather than a sentence beside the card that
    # caused it. `problems()` parses the patterns and reads the strategies;
    # it compiles nothing of LangChain's and matches nothing, so a document
    # pays a parse per row for the whole class of "this row is not the
    # protection it looks like".
    for entity, problem in guardrail.problems():
        self.diagnostics.record(
            Finding.INVALID_GUARDRAIL_RULE, node_id, entity, problem
        )
    # A guard placed after another guard, a grader or an approval arrives
    # over a *conditional* edge, which `plan.edges` does not carry — the
    # same situation `_output` and `_subgraph` already handle, and which
    # `upstream_sources` now answers once for all of them.
    sources = upstream_sources(plan, node_id)
    #: The nodes whose `outputs` entry this guard may rewrite — see the
    #: scrub below. Resolved once, at build time, because the document's
    #: types do not change during a run.
    producers = {
        candidate
        for candidate, node_type in self._types.items()
        if node_type.startswith(_PRODUCES_CONTENT)
    }

    def run(state: RunState) -> dict[str, Any]:
        text = _upstream_text(state, sources) or state.get("question", "")
        try:
            screening = guardrail.screen(text)
        except ValueError as exc:
            # A table naming a strategy nobody implements, or a custom
            # entity with no pattern. Reported as this node's output
            # rather than raised: a card that claims a protection it
            # cannot deliver must be loud (`errors.py`), and taking the
            # whole run down would be a denial of service written by a
            # typo. It is deliberately NOT passed through — a guardrail
            # that fails open is the one failure mode worse than noisy.
            return {
                "decisions": {node_id: "blocked"},
                "outputs": {node_id: failure_marker(node_id, str(exc))},
            }

        update: dict[str, Any] = {
            "decisions": {node_id: "blocked" if screening.blocked else "allowed"},
            "outputs": {node_id: screening.text},
        }
        if screening.redactions:
            update["redactions"] = {
                node_id: [
                    {"entity": r.entity, "strategy": r.strategy, "count": r.count}
                    for r in screening.redactions
                ]
            }
        if not screening.changed:
            return update

        # A block scrubs exactly as a redaction does, and that was found
        # by a test rather than reasoned about: stopping at "the offending
        # text does not continue" left `outputs["in1"]` — the input node's
        # own echo — carrying the card number onto the customer's `done`
        # frame. Harmless when the customer typed it and a disclosure the
        # moment the blocked text is the *model's* answer, which is the
        # outbound instance of this very node. One rule, both outcomes.

        # What is already settled, brought into line with the policy.
        # Only the entries it actually changes are written, so a guard
        # finding nothing costs one key.
        #
        # **How far the scrub reaches depends on the verdict, and the
        # scope was found by a live run rather than reasoned about.**
        # Scrubbing every entry made an outbound guard rewrite
        # `outputs["in1"]` — the echo of the user's own question — to
        # `[REDACTED_EMAIL]`, in a document whose inbound card says
        # `email → pass`. That protects nobody (ticket 02's asymmetry:
        # inbound PII is the user's own, they typed it) and it destroys
        # the evidence that the machine ever received the true address,
        # which is the whole thing this design is for.
        #
        # So a transforming rule covers what was **produced** — an input
        # echoes, a router forwards, a guard rewrites; none of them
        # invent, and none is what an outbound policy exists to catch.
        # A **block** covers everything, because the two say different
        # things: `redact` means the reader must not see it, and `block`
        # means this workflow must not hold it at all — including in a
        # checkpointed trace that outlives the run.
        reach = (state.get("outputs") or {}).items()
        scrubbed = {
            key: screened
            for key, value in reach
            if (screening.blocked or key in producers)
            and isinstance(value, str)
            and (screened := guardrail.screen(value).text) != value
        }
        if scrubbed:
            update["outputs"] = {**scrubbed, **update["outputs"]}
        # Written **only** when there is already an answer to correct.
        # `answer` is `keep_latest_nonempty`, so writing it unconditionally
        # would make an inbound guard announce the user's own question as
        # the run's answer on any path where the agent produced nothing.
        settled = str(state.get("answer") or "")
        if settled:
            corrected = guardrail.screen(settled).text
            if corrected != settled:
                update["answer"] = corrected
        return update

    return run


def _guard_check(self: "NodeRuntime", node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
    """A grader's mechanical sibling (`launch-readiness` 65).

    Answers the same `pass`/`revise` question a grader does, over the
    same conditional-edge shape (`workflow_compiler.py` routes
    `GUARD_CHECK_TYPE` exactly where it routes `GRADER_TYPE`), but by
    calling a package function instead of a model — the decision was
    already made deterministically and for free by
    e.g. `function.validate_sql`, and this node hands its verdict back
    without paying for a model call to re-emit it.

    The function contract is the same `fn(text: str) -> str` every
    `function.*` node already uses (`_discovered_function`): an empty
    return is a pass, a non-empty return is both the `revise` reason and
    the feedback text sent upstream. No new contract, no new registry —
    `check` just names one of the same functions by its short name (the
    part after `function.`).

    Termination mirrors the grader's own two ceilings exactly, because a
    guard that always emitted `revise` would violate "a cycle must
    contain a conditional edge that can end it": `maxAttempts` (this
    node's own lap budget, forcing a pass once exhausted) and the step
    budget floor (`step_budget_floor_for`, forcing a pass before the
    graph's own recursion limit would raise). A mechanical lap is cheaper
    than a model lap, so a runaway is more likely here, not less — which
    is exactly why both ceilings apply here unweakened.
    """
    data = node.get("data") or {}
    check_name = _text(data, "check").strip()
    fn = self.services.functions.get(f"function.{check_name}") if check_name else None
    # `launch-readiness` 151. F3 — *every number in the prose appears in a
    # result row* — cannot be a package function, and that is why it sat
    # unwritten for three days: `fn(text) -> str` sees the candidate and
    # nothing else, and this check needs the **evidence** as well. So core
    # supplies it, with the wider signature, and a package function of the
    # same name still wins — an adopter overrides by writing one.
    built_in = _BUILT_IN_CHECKS.get(check_name) if fn is None else None
    #: Whether the package function asked for the run's record beside the
    #: candidate (`osg-agent-experience/50`). Resolved once, here, because a
    #: signature does not change during a run.
    summarised = fn is not None and _wants_the_summary(fn)
    model_authored = frozenset(
        candidate_id
        for candidate_id, candidate_type in self._types.items()
        if candidate_type.startswith(MODEL_AUTHORED)
    )
    sources = upstream_sources(plan, node_id)
    cap = int(data.get("maxAttempts") or self.services.max_attempts)
    revise_wired = "revise" in (plan.conditional.get(node_id) or {})
    if not revise_wired:
        self.diagnostics.record(Finding.UNWIRED_REVISE, node_id)
    floor = step_budget_floor_for(plan, node_id)

    def _summary(state: RunState) -> RunSummary:
        """The whole run, not this guard's upstream.

        A grader judges a named producer's output and narrows to it; a guard
        stands at the confluence and its candidate is whatever reached it, so
        the honest scope here is every node that called a tool.
        """
        return summarise_run(state.get("tool_use"))

    def run(state: RunState) -> dict[str, Any]:
        candidate = _upstream_text(state, sources) or state.get("question", "")
        if fn is None and built_in is None:
            self.diagnostics.record(Finding.UNRESOLVED_FUNCTION, f"guard.check:{check_name}")
            return {
                "decisions": {node_id: "pass"},
                "outputs": {node_id: candidate},
                "feedback": "",
            }

        try:
            if built_in is not None:
                reason = built_in(candidate, state, model_authored)
            elif fn is not None:
                # The second argument is the run's own record — which tools
                # this run reached, how many came back, and the last thing one
                # of them said. A check can then answer *"no evidence
                # arrived"* instead of arguing with the prose about units,
                # which is what the live Mongstad run's honesty check spent
                # two laps doing while three warehouse calls sat timed out in
                # state, unread.
                reason = fn(candidate, _summary(state)) if summarised else fn(candidate)
            else:  # pragma: no cover - the branch above returns first
                reason = ""
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
        reason = reason.strip() if isinstance(reason, str) else str(reason or "")

        judged = int((state.get("revisions") or {}).get(node_id, 0)) + 1
        remaining = state.get("remaining_steps")
        starved = isinstance(remaining, int) and remaining <= floor
        exhausted = judged >= cap or starved
        passed = not reason
        branch = "pass" if passed or exhausted else "revise"

        update: dict[str, Any] = {
            "decisions": {node_id: branch},
            "revisions": {node_id: judged},
            "feedback": "" if branch == "pass" else reason,
            "outputs": {node_id: candidate},
            "verdicts": {
                node_id: {
                    "verdict": "pass" if passed else "revise",
                    "reason": reason,
                    "check": check_name,
                }
            },
        }

        # `launch-readiness/167`. A ceiling that forces `pass` while the
        # objection still stands publishes **the very figure the check
        # refused**, and nothing anywhere says so: the verdict is recorded,
        # the branch is `pass`, and the customer meets an answer that reads
        # exactly like one that cleared the gate. Measured live on
        # 2026-08-28 — lap 2 rejected *"1,454,449 vessels"* and the output
        # node published it.
        #
        # **The pass is correct and is not changed.** `_grader` argues it
        # and the argument holds harder here, because a mechanical lap is
        # cheaper than a model lap and a runaway is more likely: a loop
        # that cannot finish is worse than a mediocre answer, and refusing
        # to publish turns a ceiling into a dead run, which is what
        # `Grader.normalise` warns against. Only the silence was the
        # defect, and it was silent on **both** channels.
        #
        # Two ceilings, two keys, exactly as on `_grader` — a `maxAttempts`
        # cap is a number on this card and the step budget is a number on
        # the workflow, so a reader's next move differs and one sentence
        # for both would be false about one of them.
        if branch == "pass" and not passed:
            if starved:
                update["budget_stops"] = {node_id: remaining}
            else:
                update["forced"] = {node_id: reason}
            # And the reader's own rail, because the developer channel is
            # not where the customer is. `record_notes` renders through
            # `_output` whether or not the model mentions it — the same
            # mechanism `127` built and `103` reused, and the reason both
            # exist: a model asked to disclose discloses most of the time.
            #
            # The check's `reason` is deliberately **not** carried. It is
            # developer text written for a model to act on and it names
            # tables and statements; `143`'s sentence-shape rule binds
            # anything reaching a customer. What travels is the one fact
            # the machinery can state honestly about itself.
            record_notes([UnverifiedAnswer(check=check_name, starved=bool(starved))])
        # A verdict with nowhere to go — the same fallback `_grader`
        # records, and only on `revise`: at the ceiling the branch is
        # `pass` and the two keys above are already the sentence for that.
        if branch == "revise" and not revise_wired:
            update["unrouted"] = {node_id: branch}
        return update

    return run

