"""The sentence channel promised what nothing on the other side can deliver.

`the-agent-asks-for-what-it-cannot-get` 04, sharpened by the owner from their
own transcript:

> "If the capability — in that case a function or tool — does not exist, the
> chat offers a tool/function asking HITL, but it doesn't write or code using
> the skill flow."

`advisor_context` speaks over **two channels and validates one.** The fenced
block is constrained to node types that exist — the catalogue is literally a
list of them, and `applicableSuggestion` drops anything else. The *sentence*
before it was constrained by nothing at all, and a model told to explain in
plain words what it cannot do will offer to fix it, because that is what a
helpful assistant does.

A developer answers "yes", and there is nothing on the other side of yes: no
tool here writes a file, and the agent has no capability to create a
capability. `CLAUDE.md` states the law twice — *do not promise which is not
possible* — and this was that law broken at the model layer, by an instruction
we wrote.

So the prohibition belongs where the offer is invited: in the base's own
context block, beside the requirement that produced the sentence. Same shape as
`branch_context`'s "never offer a capability no branch above provides", which
is this repository's precedent for constraining prose the parser cannot police.

The half NOT fixed here is the structured one — an unregistered `nodeType`
still resolves to `null` and no second card is offered. The ticket stays
`partially` for it.
"""

from __future__ import annotations

import openstategraph.abc.agent as agent_module
from openstategraph.abc.agent import ReactAgentNode
from openstategraph.compile.node_runtime import NodeRuntime, RunState, RuntimeServices, advisor_context
from openstategraph.compile.workflow_compiler import CompiledPlan
from openstategraph.developer_channel import split_suggestion

from conftest import any_chat_model

CATALOG = "- tool.web-search — searches the web"


class _RecordingAgent(ReactAgentNode):
    built: list["_RecordingAgent"] = []

    def build(self):
        _RecordingAgent.built.append(self)
        return None


class _RecordingWorker:
    """`_worker` invokes what `build` returns, so it needs a stub agent back."""

    built: list["_RecordingWorker"] = []

    def __init__(self, **kwargs: object) -> None:
        self._kwargs = kwargs

    def resolve_prompt(self) -> str:
        parts = [self._kwargs.get("context") or "", self._kwargs.get("default_rules") or ""]
        return "\n\n".join(str(p) for p in parts if p)

    def build(self):
        _RecordingWorker.built.append(self)
        return _StubAgent()


class _StubAgent:
    def invoke(self, _payload):
        from langchain_core.messages import AIMessage

        return {"messages": [AIMessage(content="done")]}


def _agent_prompt(**services_kwargs: object) -> str:
    _RecordingAgent.built.clear()
    runtime = NodeRuntime(services=RuntimeServices(model=any_chat_model(), **services_kwargs))  # type: ignore[arg-type]
    node = {"id": "agent-analyst", "type": "agent.llm", "data": {"systemPrompt": "Be terse."}}
    run = runtime._agent("agent-analyst", node, CompiledPlan())
    run(RunState(question="q"))  # type: ignore[typeddict-item]
    (built,) = _RecordingAgent.built
    return built.resolve_prompt() or ""


def _worker_prompt(**services_kwargs: object) -> str:
    _RecordingWorker.built.clear()
    runtime = NodeRuntime(services=RuntimeServices(model=any_chat_model(), **services_kwargs))  # type: ignore[arg-type]
    node = {
        "id": "worker-research",
        "type": "orchestrate.worker",
        "title": "Researcher",
        "data": {"role": "Gathers and states the facts."},
    }
    run = runtime._worker("worker-research", node, CompiledPlan())
    run(RunState(task_id="task-1", task_instruction="Find best practices"))  # type: ignore[typeddict-item]
    (built,) = _RecordingWorker.built
    return built.resolve_prompt() or ""


#: The clause, quoted once. Every assertion below reads it from here so a
#: reword is one edit rather than six — and so no test can pass by restating a
#: sentence the prompt does not actually carry.
FORBIDS_OFFERING = "never offer to build, write, add or wire anything yourself"
NAMES_THE_REAL_ROUTE = "a developer applies"


class TestTheInstructionConstrainsTheSentenceChannel:
    def test_it_forbids_offering_to_build_the_missing_capability(self) -> None:
        assert FORBIDS_OFFERING in advisor_context("agent-1", CATALOG)

    def test_it_says_what_the_agent_may_truthfully_say_instead(self) -> None:
        """A prohibition with no substitute is a leading question — the same
        failure `every-workflow-green` 29 recorded about a catalogue with no
        way to decline. So the clause names the real next step: the block is a
        suggestion, and a developer is the one who applies it."""
        assert NAMES_THE_REAL_ROUTE in advisor_context("agent-1", CATALOG)

    def test_it_says_the_agent_cannot_create_a_capability(self) -> None:
        """The reason, not just the rule. A model that is told only 'do not
        offer' can still imply it is coming."""
        assert "cannot create a capability" in advisor_context("agent-1", CATALOG)

    def test_it_never_asks_the_user_to_confirm_a_build(self) -> None:
        """The observed shape was a question — 'shall I add it?' — and a
        question is an offer with a second turn attached."""
        assert "never ask whether you should" in advisor_context("agent-1", CATALOG)


class TestItReachesEveryBlockedNodeType:
    """The trap this repo has paid for: `advisor_context` was once composed
    into `_agent` and not `_worker`, and both tests stayed green because
    neither asked a node anything (`every-workflow-green` 19). A clause added
    to the string proves nothing about what a blocked node was told."""

    def test_a_blocked_agent_is_told(self, monkeypatch) -> None:
        monkeypatch.setattr(agent_module, "agent_node_for_tier", lambda tier: _RecordingAgent)
        assert FORBIDS_OFFERING in _agent_prompt(advisor_catalog=CATALOG)

    def test_a_blocked_worker_is_told(self, monkeypatch) -> None:
        monkeypatch.setattr(agent_module, "ReactAgentNode", _RecordingWorker)
        assert FORBIDS_OFFERING in _worker_prompt(advisor_catalog=CATALOG)

    def test_it_rides_context_above_the_developers_rules(self, monkeypatch) -> None:
        """`SystemPrompt` renders context, then rules, then the locked output
        contract. The prohibition is machinery, so it sits with the machinery —
        never in a field a developer could clear."""
        monkeypatch.setattr(agent_module, "agent_node_for_tier", lambda tier: _RecordingAgent)
        prompt = _agent_prompt(advisor_catalog=CATALOG)
        assert prompt.index(FORBIDS_OFFERING) < prompt.index("Be terse.")


class TestAnUnblockedAgentIsUnaffected:
    """The inverse, and it is load-bearing: an ordinary run has no catalogue,
    so it must carry none of this — not the fence, and not the prohibition."""

    def test_no_catalogue_composes_nothing_at_all(self) -> None:
        assert advisor_context("agent-1", "") == ""

    def test_an_ordinary_agent_prompt_is_untouched(self, monkeypatch) -> None:
        monkeypatch.setattr(agent_module, "agent_node_for_tier", lambda tier: _RecordingAgent)
        prompt = _agent_prompt()
        assert FORBIDS_OFFERING not in prompt
        assert "```suggestion" not in prompt
        assert "Be terse." in prompt


class TestTheSuggestionFenceStillWorksExactlyAsBefore:
    """The narrowness is the safety and it is the part that regresses. Nothing
    here widens a parser, but a prompt change that broke the taught format
    would be `every-workflow-green` 17 again — so the shape the parser reads is
    asserted against the shape the prompt still teaches."""

    def test_the_prompt_still_teaches_the_fence_the_parser_reads(self) -> None:
        text = advisor_context("agent-1", CATALOG)
        assert "```suggestion" in text
        assert '"attachTo": "agent-1"' in text
        assert '"none"' in text
        assert "never the block alone" in text

    def test_a_real_suggestion_still_splits_out_of_the_answer(self) -> None:
        answer = (
            "I can't look that up — nothing here reaches the web.\n\n"
            '```suggestion\n{"nodeType": "tool.web-search", "attachTo": "agent-1", '
            '"port": "tools", "label": "Web", "reason": "live data"}\n```'
        )
        prose, suggestion = split_suggestion(answer)
        assert suggestion is not None
        assert suggestion["nodeType"] == "tool.web-search"
        assert "nodeType" not in prose

    def test_ordinary_prose_is_still_left_alone(self) -> None:
        """No matcher over prose was added — this is the test that would catch
        one being added later."""
        answer = "I could build you a summary of the three rows above."
        prose, suggestion = split_suggestion(answer)
        assert suggestion is None
        assert prose == answer
