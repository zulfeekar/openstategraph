"""`route.grader` — the node that judges an answer and routes on the verdict.

A grader's verdict is an **edge**, never a score: `pass` or `revise`, consumed
by the graph. Grading a *dataset* is a different clock and a different
consumer and is deliberately not a node at all — `docs/evaluation.md` carries
that distinction and `CLAUDE.md` states it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
from openstategraph.abc.grader import Grader, Verdict
from openstategraph.abc.tool_notes import (
    notes_for_grader,
    peek_notes,
)
from openstategraph.compile.diagnostics import (
    Finding,
)
from openstategraph.compile.workflow_compiler import (
    CAPABILITY_UNAVAILABLE_ANSWER,
    CompiledPlan,
    step_budget_floor_for,
    unbound_capability_claim,
    unrun_query_claim,
)
from openstategraph.compile.context import (
    _text,
)
from openstategraph.compile.state import (
    RunState,
    _upstream_text,
    _wired_skill,
)
from openstategraph.compile.token_stream import (
    NOSTREAM_TAG,
    silence_tokens,
)
from openstategraph.compile.deep_tier import _DeepAgentAsChatModel
from openstategraph.compile.fields import _replaces_rules
from openstategraph.compile.reporting import (
    _values_never_sent,
)

if TYPE_CHECKING:
    # The class these functions are methods of. Type-only: the import that
    # matters runs the other way, once, when `NodeRuntime`'s class body binds
    # them. See this package's `__init__.py` for why that is the seam.
    from openstategraph.compile.node_runtime import NodeRuntime


def _grader(self: "NodeRuntime", node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
    """Judges, and chooses `pass` or `revise`.

    The card's `tier` field (react/deep/custom) previously did nothing on
    this side — `Grader.grade()` always made one bare chat-model call
    regardless of what a developer picked. `tier: "deep"` now actually
    builds a `create_deep_agent` for the judgement, via
    `_DeepAgentAsChatModel` rather than by teaching `BaseGrader` about
    deep agents.
    """
    data = node.get("data") or {}
    base_model = self._resolve_model(data, node_id)
    # See the router's line: a grader streams `FAIL Include the SQL SELECT
    # statement…` onto the end of a finished answer.
    grading_model = silence_tokens(base_model)
    if _text(data, "tier") == "deep" and base_model is not None:
        grading_model = _DeepAgentAsChatModel(
            base_model, name=f"grader_{node_id}", tags=(NOSTREAM_TAG,)
        )
    raw_rubric = data.get("rubric")
    rubric_rows = [
        {"criterion": str(row.get("criterion") or row.get("name") or ""),
         "required": bool(row.get("required", True))}
        for row in raw_rubric
    ] if isinstance(raw_rubric, list) else []
    cap = int(data.get("maxAttempts") or self.services.max_attempts)
    # Both sources, because a **conditional** upstream is not in
    # `plan.edges` (`launch-readiness` 165). A `guard.check`'s `pass` and
    # another grader's `pass` are conditional edges, so a grader reading
    # only `plan.edges` sees no candidate at all and rejects with "The
    # answer is empty" — without a model call, so nothing in the trace
    # says why. Found by wiring 165's gate into an MCP package and running it:
    # four live runs, four empty answers, the full draft sitting in
    # `outputs[guard1]` the whole time.
    #
    # `_guard_check` was written after this and already reads both. That
    # is the asymmetry, not a difference between the two node kinds:
    # `diagnostics.py` tells people to put a guard between a step and the
    # output, and every graph that has a grader on that path — the
    # ordinary NL2SQL shape — silently emptied its answer for following
    # the advice.
    upstream = [src for src, dst in plan.edges if dst == node_id]
    upstream += [
        src
        for src, dests in plan.conditional.items()
        if node_id in dests.values() and src not in upstream
    ]
    skills = plan.skill_bindings.get(node_id, [])
    # Whether this grader can actually send anything back
    # (`workflow-gallery` 31). Read from the plan at build time, which is
    # the only place both the node id and the drawn destinations are known
    # — `_router_for` sees the destinations and cannot write state, and the
    # node sees the state and would otherwise not know what was drawn.
    #
    # Reported and not refused: a grader used as a recorder is a legal
    # graph, and `support-triage` ships exactly that on purpose because
    # `agent.feedback` is `maxConnections: 1` and a revise edge behind a
    # three-way classifier would have to pick one desk.
    revise_wired = "revise" in (plan.conditional.get(node_id) or {})
    if not revise_wired:
        self.diagnostics.record(Finding.UNWIRED_REVISE, node_id)
    # How few supersteps this grader may see and still stop safely — one
    # more lap, then the whole `pass` tail (`organisms-first-class` 59).
    # Read from the plan here, at build time, for the same reason
    # `revise_wired` is: the drawn destinations are known here and the
    # state is known inside `run`, and neither place knows both.
    floor = step_budget_floor_for(plan, node_id)

    def grader_for(skill: str, run_ctx: str = "") -> Grader:
        """A grader is cheap to build, so it is built per skill value.

        The skill text arrives through *state* (the port's upstream node
        writes it), so it cannot be known at compile time — the same
        reason `_agent` rebuilds. With nothing wired this is one
        construction per invocation of a plain dataclass-ish object, and
        with something wired it is the only correct order of events.

        **Per call, with no cache behind it** — the answer to
        `launch-readiness/182`'s fourth question for this family. The agent
        family's memo was keyed on the rendered run-context block and
        outlived every run, which made it an unbounded dict of built
        agents; nothing here is kept between invocations, so the 3.2
        KiB/run that sweep measured is construction that is collected
        again, not accumulation.
        """
        return Grader(
            criteria=_text(data, "criteria"),
            rubric=rubric_rows,
            skill=skill,
            replace_defaults=_replaces_rules(data),
            model=grading_model,
            context=run_ctx,
        )

    async def run(state: RunState) -> dict[str, Any]:
        """`async def` since `async-first/14`, awaiting `agrade`.

        The same measurement as `_router` above, and this is the family it
        matters most for: **a grader runs every lap of a revision loop**,
        so "short" describes one call and never a run. Before this, a
        cancelled run left the judgement's model call in flight and paid
        for it.

        The deterministic prelude is untouched and still answers first —
        `BaseGrader._verdict_without_a_model` is shared by both doors on
        purpose, so an empty candidate is rejected here with no model
        consulted through either.
        """
        # The best candidate *this* grader has already seen, when the
        # producer has just gone quiet (`one-chinook-honest` 25).
        #
        # A revise lap can return less than the lap before it — the traced
        # run refused honestly on attempt one and returned `""` on two and
        # three — and an empty candidate at the cap would publish nothing
        # over an answer the workflow genuinely produced.
        #
        # `outputs[node_id]` is this node's own last outcome, so the text
        # kept is the one this grader judged, on the branch that reached
        # it, this turn — `_input` resets `outputs` at the turn boundary
        # with every other per-run channel.
        #
        # **Not `state["answer"]`, which is what this line used to read.**
        # That saved the traced run only by accident of shape: the
        # document has one agent, so the graph-wide answer happened to be
        # that agent's own attempt one. `_agent` already refuses the same
        # key a few hundred lines up, and names why — in a multi-agent
        # document it "may belong to somebody else". Measured, it does: a
        # chain whose *second* agent returned nothing had this grader
        # judge, force-pass and publish the **first** agent's text as the
        # second's answer, with `outputs[a2]` still empty beside it.
        previous = str((state.get("outputs") or {}).get(node_id) or "")
        candidate = _upstream_text(state, upstream) or previous
        # `launch-readiness/154`. This grader judges the producing node's
        # raw text, and `127`'s disclosure is appended after it by
        # `_output` — so a criterion like *"say which sense you used"* was
        # judged against a document that did not contain the sentence the
        # reader would actually get, and could burn a whole revise lap to
        # obtain it.
        #
        # **Peeked, never taken.** `take_notes` drains, and a grader that
        # drained the rail would delete the reader's disclosure — `154`'s
        # fix causing `127`'s defect. And it rides in the generated
        # *Context* layer, never in the candidate: what this node publishes
        # is still exactly what the producer wrote.
        seen = peek_notes()
        sections = (
            self._run_context_section(),
            notes_for_grader(seen, unsent_values=_values_never_sent(state, seen)),
        )
        grader = grader_for(
            _wired_skill(state, skills, self.static_sources),
            "\n\n".join(part for part in sections if part),
        )

        # A deterministic check the *grader* cannot make, because it needs
        # the run and a `BaseGrader` sees only the candidate
        # (`production-ready` 95). "The answer shows a SELECT and nothing
        # ever sent one" is a fact about `tool_use`, so it is answered here
        # and dressed as an ordinary `Verdict.reject` — which is what makes
        # it print like every other rule-based rejection, `check` and all.
        #
        # It belongs beside `deterministic_checks` in spirit and cannot
        # live there in code: putting state on `BaseGrader.grade` would
        # teach the grader ladder about `tool_use`, and a grader is a
        # judgement over a text.
        unrun = unrun_query_claim(candidate, state.get("tool_use"), upstream)
        # The second fact of the same kind, and the one this node used to
        # be blind to (`launch-readiness` 103). An agent whose drawn
        # capabilities all resolved to nothing did not answer the question;
        # it reported its own brokenness in the answer slot, and a refusal
        # is trivially grounded, so both criteria passed it and a broken
        # run shipped with the confidence of a working one.
        #
        # It is read before the model for the reason the whole
        # deterministic prelude is: this is a fact, and paying a judgement
        # to notice it would be slower, costlier and less reliable — and a
        # model can be talked out of a fact.
        blocked = unbound_capability_claim(state.get("tool_use"), upstream)
        # Spelled as a statement rather than the conditional expression it
        # was: `await` is legal in a ternary and reads as though both arms
        # might be awaited, and the whole point of the `unrun` arm is that
        # no model is asked.
        if blocked:
            verdict = Verdict.reject(blocked, check="unbound_capability")
        elif unrun:
            verdict = Verdict.reject(unrun, check="unrun_query")
        else:
            verdict = await grader.agrade(
                candidate, question=state.get("question", "")
            )

        # Budget check before routing: a grader that keeps rejecting must
        # still let the run finish with an honest answer rather than spin.
        #
        # Counted **per grader**, against this node's own row in
        # `revisions`, and incremented here rather than at every agent
        # (`workflow-gallery` 21). `judged` includes the candidate in hand,
        # so `maxAttempts: 1` means the first candidate is also the last —
        # which is what the graph-wide check happened to do for the single
        # -agent loop, and the shape every other graph did not get.
        judged = int((state.get("revisions") or {}).get(node_id, 0)) + 1

        # The *other* budget, and the one that used to end the run with an
        # exception rather than an answer (`organisms-first-class` 56).
        #
        # `maxAttempts` above is this grader's own lap count; the **step
        # budget** (`recursion_limit`) is the workflow's ceiling on
        # supersteps, and a lap costs one per node on the cycle — so a cap
        # the step budget cannot pay for is an ordinary drawing, not an
        # exotic one. Before this, that graph raised
        # `GraphRecursionError` and every door lost the answer the
        # workflow had already produced.
        #
        # Read off `remaining_steps`, which LangGraph populates; the docs
        # call this proactive read the recommended approach over catching
        # the error outside, because the graph completes normally. `None`
        # when a caller invoked the compiled graph without the managed key
        # in play, and then this changes nothing.
        remaining = state.get("remaining_steps")
        starved = isinstance(remaining, int) and remaining <= floor
        exhausted = judged >= cap or starved
        # `blocked` forces the `pass` branch and the ticket says why: a
        # retry with the same missing capability produces the same refusal
        # and burns the budget. The branch is the *edge*, not the verdict —
        # what travels along it is replaced below.
        branch = "pass" if verdict.passed or exhausted or blocked else "revise"

        # The ceiling reports itself when it has nothing to hand on.
        #
        # Forcing `pass` at the cap is right — a loop that cannot finish is
        # worse than a mediocre answer — but when the last attempt produced
        # *nothing*, passing an empty string makes every surface downstream
        # claim success and show a blank. Found live in the editor: a
        # mounted analyst exhausted three attempts and the chat panel said
        # "No answer was produced" directly above "3 attempts before the
        # grader passed it", which is two contradictory sentences and no way
        # to act on either.
        #
        # Only when the candidate is empty. A candidate the grader merely
        # disliked is still the answer the workflow produced, and replacing
        # it with our commentary would be worse than passing it on.
        outcome = candidate
        if blocked:
            # **Not the model's prose.** The refusal was correct and it is
            # still not an answer — and it named internal tool ids on a
            # customer surface to say so, which is the platform's job and
            # not a model's. `CAPABILITY_UNAVAILABLE_ANSWER` says the one
            # thing the refusal could not say honestly about itself: this
            # is not an answer to the question that was asked.
            #
            # This is the one case that replaces a *non-empty* candidate.
            # The rule below — a candidate the grader merely disliked is
            # still what the workflow produced — holds against a judgement.
            # It cannot hold against a fact that says the producer had
            # nothing to produce from.
            outcome = CAPABILITY_UNAVAILABLE_ANSWER
        elif branch == "pass" and not candidate.strip() and not verdict.passed:
            # Which ceiling was hit changes what a reader can do about it:
            # a cap is a number on this card, the step budget is a number
            # on the workflow. Saying "after 500 attempts" for a run that
            # made four laps would be a false sentence.
            outcome = (
                "I could not produce an answer before the workflow's step "
                "budget ran out. The last review said: "
                f"{verdict.feedback or 'no reason given'}"
            ) if starved else (
                f"I could not produce an answer after {cap} "
                f"{'attempt' if cap == 1 else 'attempts'}. "
                f"The last review said: {verdict.feedback or 'no reason given'}"
            )

        # A pass the budget forced, not one the grader gave. `feedback`
        # is cleared on a pass, so without this the rejection is discarded
        # here and no surface can ever report it (`every-workflow-green`
        # 09). What is published does not change.
        update: dict[str, Any] = {
            "decisions": {node_id: branch},
            "revisions": {node_id: judged},
            "feedback": "" if branch == "pass" else verdict.feedback,
            "outputs": {node_id: outcome},
            # The judgement itself, beside the branch it produced. Written
            # unconditionally — unlike `forced` and `unrouted`, whose
            # presence is the signal — because a downstream reader asking
            # "what did the machine think of this text" needs an answer for
            # an ordinary pass too (`workflow-gallery` 32).
            #
            # `reason` first, `feedback` as the fallback: `Verdict` splits
            # them deliberately (the reason explains the verdict to a human,
            # the feedback is written for the agent that must retry), and a
            # deterministic rejection fills only one of the two.
            # `check` names *which* deterministic check rejected the
            # candidate, and is empty for every model judgement — which is
            # what makes the grader's two paths distinguishable downstream
            # (`production-ready` 92). `Verdict.failed_check` had named it
            # since the field was added and it was dropped here, so a
            # rejection costing 0.021 ms and one costing two seconds
            # produced byte-identical frames and ticket 84 spent a session
            # plus a live model run establishing which had happened.
            #
            # The marker travels beside the reason rather than instead of
            # it: the check name is an internal token an open set of
            # subclasses may extend (`test_grader.py`'s stricter grader
            # adds `no_figure`; this node adds `unrun_query`), so no
            # reader may map it to a sentence — the sentence is `reason`,
            # and `check` is only the fact that no model was asked.
            "verdicts": {
                node_id: {
                    "verdict": "pass" if verdict.passed else "revise",
                    "reason": verdict.reason or verdict.feedback,
                    "check": verdict.failed_check,
                }
            },
        }
        if blocked:
            # Deliberately neither `forced` nor `budget_stops`: both name a
            # ceiling that was hit, and no ceiling was hit here. The
            # developer-facing sentence for this is
            # `Finding.CAPABILITY_FAILED`, recorded by `_bind_tools` at
            # compile time — which is earlier, more specific, and already
            # reaches the run response, the CLI and `CompiledWorkflow`.
            pass
        elif branch == "pass" and not verdict.passed:
            # A budget stop is a force-pass too, and the *publication* is
            # identical — so it stays out of `forced`, whose sentence
            # names the attempts cap. Two ceilings, two sentences, one
            # channel (`workflow_compiler.step_budget_warnings`).
            if starved:
                update["budget_stops"] = {node_id: remaining}
            else:
                update["forced"] = {node_id: verdict.feedback or ""}
        # A verdict with nowhere to go. `_router_for` will fall back to the
        # first declared destination — correct, and it must not be the only
        # thing that happens. Only on `revise`: at the cap the branch is
        # `pass`, the answer really was published, and `forced` above is
        # already the sentence for that (gallery ticket 22's case, which is
        # a different mechanism and stays a different key).
        if branch == "revise" and not revise_wired:
            update["unrouted"] = {node_id: branch}
        return update

    return run

