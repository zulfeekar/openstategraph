"""`route.classifier` — the node that decides which branch the run takes.

It writes its choice to `state["decisions"][node_id]`; the compiler's `path`
function reads it and the conditional edge dispatches. Two responsibilities,
two places, and neither has to know how the other works — which is the split
`node_runtime.py`'s own opening paragraph describes and this module is one
half of.
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
from openstategraph.abc.router import Router
from openstategraph.compile.workflow_compiler import (
    CompiledPlan,
    unrouted_record,
)
from openstategraph.compile.context import (
    _branch_entries,
    _text,
)
from openstategraph.compile.state import (
    RunState,
    _thread_question,
    _upstream_text,
    _wired_skill,
)
from openstategraph.compile.token_stream import (
    NOSTREAM_TAG,
    silence_tokens,
)
from openstategraph.compile.deep_tier import _DeepAgentAsChatModel
from openstategraph.compile.fields import _replaces_rules

if TYPE_CHECKING:
    # The class these functions are methods of. Type-only: the import that
    # matters runs the other way, once, when `NodeRuntime`'s class body binds
    # them. See this package's `__init__.py` for why that is the seam.
    from openstategraph.compile.node_runtime import NodeRuntime


def _router(self: "NodeRuntime", node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
    """Classifies, and writes the branch for the conditional edge to read.

    `tier` (react/deep/custom) was declared on `RouterNode.ts` but never
    read here — found by the same field diff that caught the grader's
    equivalent gap before this file's own `_DeepAgentAsChatModel` comment
    was written. `tier: "deep"` now does exactly what it already does
    for the grader: wraps the classifying model in a compiled deep agent
    rather than teaching `BaseRouter` about one.
    """
    data = node.get("data") or {}
    branches = _branch_entries(data.get("branches"))
    base_model = self._resolve_model(data, node_id)
    # A router streams the branch NAME it chose, which QA read glued to the
    # sentence beside it. The fold blanks it for a customer; `nostream`
    # stops it being produced at all (ticket 21). Two spellings because the
    # deep tier cannot take a bound model — see `_DeepAgentAsChatModel`.
    classifying_model = silence_tokens(base_model)
    if _text(data, "tier") == "deep" and base_model is not None:
        classifying_model = _DeepAgentAsChatModel(
            base_model, name=f"router_{node_id}", tags=(NOSTREAM_TAG,)
        )
    upstream = [src for src, dst in plan.edges if dst == node_id]
    skills = plan.skill_bindings.get(node_id, [])
    # `workflow-gallery` 48: a grader downstream of this router's branches
    # may send a `revise` verdict back here rather than onto a branch
    # agent directly (`docs/decisions/router-feedback-input.md` — "feedback
    # follows the branch"). This router is the direct target, so the
    # unwidened check is right: it does not need `_feedback_sources`'
    # router-relay case, only the same direct check every feedback-trusting
    # node has always made.
    feedback_sources = self._direct_feedback_sources(node_id, plan)
    # Which of this router's branches were actually drawn. A verdict naming
    # one that was not is `osg-agent-experience/80`'s live failure — the
    # classifier answered `unclear`, nobody had drawn that branch, and the
    # first branch that happened to be declared published an answer instead.
    # `route.check` and the grader have reported this since `60` and
    # `workflow-gallery/31`; the family the owner actually ran was the silent
    # one, so it says it too now.
    wired = set(plan.conditional.get(node_id) or {})
    stops_here = not plan.unrouted_route.get(node_id)

    def _lost(keys: list[str]) -> dict[str, Any]:
        return (
            {}
            if any(key in wired for key in keys)
            else {"unrouted": {node_id: unrouted_record(keys[0], stopped=stops_here)}}
        )

    def router_for(skill: str, run_ctx: str = "") -> Router:
        """Built per skill value, for the same reason `_agent` is: the
        wired text arrives through state, not through the document.

        The branch validation `Router.__init__` performs still happens at
        compile time via the construction below, so a router with no
        branches is rejected when the graph is built, not on first run.

        **There is no cache here, and that is the answer to
        `launch-readiness/182`'s fourth question.** That ticket found the
        agent family's memo keyed on the rendered run-context block — a
        per-run value inside a dict that outlives every run — and asked
        whether the other three prompted families carried the same defect.
        They do not: this constructs per call and `prebuilt` below is one
        object made at compile time for the case where nothing varies, so
        nothing accumulates. The 3.4 KiB/run that sweep measured here was
        per-call construction, collected each lap, not retention.
        """
        return Router(
            branches,
            fallback=_text(data, "fallback") or None,
            rules=_text(data, "rules"),
            skill=skill,
            replace_rules=_replaces_rules(data),
            model=classifying_model,
            match_mode=_text(data, "matchMode") or "best",
            context=run_ctx,
        )

    prebuilt = router_for("")

    async def run(state: RunState) -> dict[str, Any]:
        """`async def` since `async-first/14`, and the reason is the model
        call two levels down `aclassify`.

        Phase D (`async-first/06`) migrated the four *longest* families and
        left this one out as short. Measured rather than reasoned about,
        "short" turned out to be the wrong axis: under `astream` plus
        `task.cancel()` the stream stopped in under a millisecond and this
        node's five-second classification **ran to completion anyway** —
        `stop_when_client_leaves`' own "abandons rather than cancels",
        billed. The property that decides the win is whether the closure
        holds a model call at all, not how long that call takes; the seam
        document's node measurable in nothing is `_static_text`, which
        makes none.

        The replay below still asks no model, which is a call not made
        rather than a call awaited.
        """
        turn = _upstream_text(state, upstream) or state.get("question", "")
        # The conversation is what the classification needs (ticket 11) —
        # and *only* the classification. What this node produced is a
        # decision about `turn`; the history it read is not its work, and
        # publishing it made every earlier turn look like this turn's
        # evidence. Ticket 24, traced in-process: a turn that ran no SQL
        # at all had a previous turn's query recovered from this field,
        # which on an `expects: "refusal"` case scores
        # `should_have_refused` for a run that never touched the database.
        # The branch downstream reads `messages` for its history anyway,
        # so it loses nothing and stops being handed the transcript twice.
        # A trusted `revise` here does not reclassify: it re-dispatches to
        # whichever branch this router's own last decision named, which is
        # the whole mechanism (`workflow-gallery` 48). Skipping
        # `router.classify()` is not merely an optimisation — a fresh
        # classification could legally choose a *different* branch than
        # the one that wrote the rejected draft (the model is not
        # deterministic), which would hand the grader's correction to a
        # desk that never saw the question. The same trust rule every
        # feedback-consuming node already applies: only a source whose
        # revise/rejected edge names this node AND whose latest decision
        # still stands.
        decisions = state.get("decisions") or {}
        replaying = any(
            decisions.get(src) in ("revise", "rejected") for src in feedback_sources
        )
        replay_branch = decisions.get(node_id) if replaying else None
        if replay_branch:
            return {
                "decisions": {node_id: replay_branch},
                "outputs": {node_id: turn},
                **_lost([replay_branch]),
            }

        classified = (
            _thread_question(state) if turn == state.get("question", "") else turn
        )
        skill = _wired_skill(state, skills, self.static_sources)
        # `prebuilt` is the compile-time construction, kept for the common
        # case where nothing varies per run. A wired skill or a run-context
        # block does vary, so either one forces a rebuild.
        run_ctx = self._run_context_section()
        router = router_for(skill, run_ctx) if (skill or run_ctx) else prebuilt
        decision = await router.aclassify(classified)
        return {
            # The conditional edge dispatches on the *stable id* — the
            # `branch:<id>` port the canvas edge actually leaves from —
            # while the model classified by human-readable *name*.
            # `route_key` is the one place that mapping lives.
            "decisions": {node_id: router.route_key(decision.branch)},
            # Every branch it matched — **always**, one label or five
            # (`launch-readiness/175`, question 3). It used to be written
            # only when more than one matched, which made an absent row
            # mean either "this router took one branch" or "nothing here
            # reports branches", and a door publishing it could not tell
            # the two apart. One key per router that ran costs nothing and
            # removes the ambiguity. The compiler's dispatch is unmoved: a
            # one-item list has always been unwrapped back to a plain
            # label there, so the graph takes the identical path.
            "routes": {node_id: [router.route_key(b) for b in decision.branches]},
            "outputs": {node_id: turn},
            # Every branch it matched, not only the one it dispatches on: a
            # `matchMode: "all"` router that matched two desks and had one of
            # them wired went somewhere, and only a router that matched
            # nothing wired lost its verdict.
            **_lost(
                [router.route_key(decision.branch)]
                + [router.route_key(b) for b in decision.branches]
            ),
        }

    return run

