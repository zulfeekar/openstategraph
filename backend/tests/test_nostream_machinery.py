"""Machinery tokens are stopped at the source, not withheld at the fold (21).

A router classifies and a grader judges; neither is talking to the customer.
Both of their model invocations nonetheless streamed onto `stream_mode=
"messages"`, and `AnswerChannel`/`machinery_nodes` then emptied the frames on
the way out. That works — `test_customer_token_stream.py` proves it — but it
is a curtain in front of a door: the bytes are produced, streamed, folded and
only then blanked, and a developer audience still receives them all.

LangGraph publishes the door. `langgraph.constants.TAG_NOSTREAM` (`"nostream"`,
present in the installed 1.2.10) is checked in `pregel/_messages.py`:

    if metadata and (not tags or (TAG_NOSTREAM not in tags)):

— i.e. an invocation carrying the tag is omitted from `messages` mode
entirely. The doc says the same: "Invocations tagged with `nostream` still run
and produce output; their tokens are simply not emitted in `messages` mode."

**Not a replacement for the fold**, and this file does not delete a single one
of the fold's tests. The fold also guards mounted children, tool payloads and
node kinds this tag cannot reach, and a model that is not a LangChain runnable
cannot be tagged at all. This is the cheaper first line.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openstategraph.compile.node_runtime import NOSTREAM_TAG, silence_tokens  # noqa: E402


class _Runnable:
    """The `with_config` half of a LangChain runnable, and nothing else."""

    def __init__(self, tags: tuple[str, ...] = ()) -> None:
        self.tags = tags

    def with_config(self, **config: Any) -> "_Runnable":
        return _Runnable(tuple(config.get("tags") or ()))


class _BareModel:
    """A hand-rolled stand-in, of which this codebase passes around several."""

    def invoke(self, _messages: Any) -> Any:  # pragma: no cover - never called
        raise AssertionError


class TestTheTagIsTheLibrarysOwn:
    def test_it_is_read_from_langgraph_rather_than_retyped(self) -> None:
        from langgraph.constants import TAG_NOSTREAM

        assert NOSTREAM_TAG == TAG_NOSTREAM


class TestSilencingAModel:
    def test_a_runnable_comes_back_tagged(self) -> None:
        assert silence_tokens(_Runnable()).tags == (NOSTREAM_TAG,)

    def test_an_existing_tag_is_kept(self) -> None:
        # `with_config(tags=...)` replaces rather than merges, so a model that
        # already carried tags would lose them to a careless implementation.
        assert set(silence_tokens(_Runnable(("mine",))).tags) == {"mine", NOSTREAM_TAG}

    def test_tagging_twice_does_not_double_it(self) -> None:
        assert silence_tokens(silence_tokens(_Runnable())).tags == (NOSTREAM_TAG,)

    def test_a_real_runnables_existing_tags_survive(self) -> None:
        """The reason the merge is hand-rolled, against the real library.

        Measured on langchain-core 1.5.3: `with_config(tags=...)` on a
        `RunnableBinding` **replaces** the list rather than merging it, and
        reasoning effort already binds these very models — so the naive
        spelling would drop a caller's tags on exactly the nodes this touches.
        """
        from langchain_core.runnables import RunnableLambda

        already_tagged = RunnableLambda(lambda x: x).with_config(tags=["mine"])

        assert set(silence_tokens(already_tagged).config["tags"]) == {"mine", NOSTREAM_TAG}

    def test_a_model_that_cannot_be_tagged_is_returned_untouched(self) -> None:
        # Every degradation here is "behave exactly as before". A stand-in with
        # no `with_config` is still a working model for the fold's own tests.
        bare = _BareModel()

        assert silence_tokens(bare) is bare

    def test_an_unconfigured_provider_is_not_detonated(self) -> None:
        """The regression this ticket actually introduced, before it shipped.

        `UnconfiguredProvider` raises from `__getattr__` so that *"a provider
        is required at the moment a model is used, not at the moment one is
        built"* — a workflow whose router never runs must still compile with
        no credentials. A bare `getattr(model, "with_config", None)` does not
        return `None` against it; it raises `MissingProviderKey` at COMPILE
        time. `test_behind_the_scenes.py` caught it; this states it.
        """
        from openstategraph.chat_model import UnconfiguredProvider

        sentinel = UnconfiguredProvider("no key here")

        # Silencing must be a no-op, and must not raise on the way to being one.
        assert silence_tokens(sentinel) is sentinel

        # And the sentinel is still armed for the moment it is genuinely used.
        from openstategraph.errors import MissingProviderKey

        try:
            sentinel.invoke([])
        except MissingProviderKey:
            pass
        else:  # pragma: no cover
            raise AssertionError("the sentinel stopped reporting its own gap")

    def test_nothing_is_returned_for_nothing(self) -> None:
        # `_resolve_model` returns `None` when no model is configured, and both
        # call sites already branch on it.
        assert silence_tokens(None) is None


def _plan() -> Any:
    """An empty *real* plan, not a namespace shaped like one.

    This was a `SimpleNamespace` carrying the four fields `_grader` happened
    to read, with a comment warning that a stub omitting a field the
    production plan always has is a stub that drifts. It drifted:
    `organisms-first-class` 59 taught `_grader` to walk `plan.fan_out` too,
    and this test broke on a change it has no opinion about. `CompiledPlan`
    is a dataclass with a default for every field, so the empty one costs
    nothing and cannot drift again."""
    from openstategraph.compile.workflow_compiler import CompiledPlan

    return CompiledPlan()


def _runtime(model: Any) -> Any:
    from openstategraph.compile.node_runtime import NodeRuntime

    return NodeRuntime(model=model)


class TestTheMachineryNodesUseIt:
    """The two call sites, driven through the real builders.

    Both build their classifying/judging model **eagerly**, in the builder
    body rather than in the returned `run` closure, so the model a node would
    call is inspectable without calling one. Asserted on that model rather
    than on a call count, because what regresses is a refactor that resolves
    the model somewhere new and forgets to silence it.
    """

    def test_a_router_classifies_with_a_silenced_model(self) -> None:
        router = _runtime(_Runnable())._router(
            "r1", {"data": {"branches": [{"id": "b1", "name": "one"}]}}, _plan()
        )

        assert NOSTREAM_TAG in _model_of(router).tags

    def test_a_grader_judges_with_a_silenced_model(self) -> None:
        grader = _runtime(_Runnable())._grader("g1", {"data": {"criteria": "right"}}, _plan())

        assert NOSTREAM_TAG in _model_of(grader).tags

    def test_an_agents_own_prose_is_left_alone(self) -> None:
        """The boundary of the ticket, stated rather than implied.

        An agent's tokens ARE the reply, and watching them appear is the only
        thing that makes a 70-second run bearable. `MACHINERY_NODE_TYPES`
        already records why `agent.llm`, `orchestrate.*` and
        `output.formatted` are absent from the machinery set; this keeps a
        future "silence everything" tidy-up from quietly including them.
        """
        model = _Runnable()

        assert _runtime(model)._resolve_model({}) is model


class TestTheDeepTierIsSilencedToo:
    """`tier: "deep"` reaches the tag by a different route, on purpose.

    `create_deep_agent` does not accept a `RunnableBinding` as its `model` —
    a non-`BaseChatModel` is treated as a model *identifier* and the failure
    is `AttributeError: 'RespondingModel' object has no attribute 'count'`,
    which names neither the call nor the binding that caused it. So the deep
    tier keeps an unbound model and carries the tag on the **invocation**,
    where LangChain propagates it down to the child LLM run.
    """

    def test_a_deep_router_invokes_with_the_tag(self) -> None:
        assert _deep_invocation_config("router")["tags"] == [NOSTREAM_TAG]

    def test_a_deep_grader_invokes_with_the_tag(self) -> None:
        assert _deep_invocation_config("grader")["tags"] == [NOSTREAM_TAG]

    def test_the_model_itself_reaches_the_deep_agent_unbound(self) -> None:
        # The constraint above, stated as a test so a later "just silence it
        # everywhere" edit fails here rather than in a stranger's run.
        from openstategraph.compile.node_runtime import _DeepAgentAsChatModel

        model = _Runnable()
        adapter = _DeepAgentAsChatModel(model, name="x", tags=(NOSTREAM_TAG,))

        assert adapter._model is model


def _deep_invocation_config(which: str) -> dict[str, Any]:
    """Runs one deep-tier machinery node against a stubbed `create_deep_agent`."""
    import deepagents
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    from openstategraph.compile.node_runtime import _DeepAgentAsChatModel

    seen: list[Any] = []

    class _StubDeepAgent:
        def invoke(self, _payload: Any, config: Any = None) -> Any:
            seen.append(config)
            return {"messages": [AIMessage(content="PASS")]}

    original = deepagents.create_deep_agent
    try:
        deepagents.create_deep_agent = lambda **_kwargs: _StubDeepAgent()
        _DeepAgentAsChatModel(_Runnable(), name=which, tags=(NOSTREAM_TAG,)).invoke(
            [SystemMessage(content="judge"), HumanMessage(content="candidate")]
        )
    finally:
        deepagents.create_deep_agent = original

    assert seen, "the deep agent was never invoked"
    return seen[0]


class TestTheTagActuallySuppressesTokens:
    """End to end against a real `StateGraph`, not against our own belief.

    Everything above asserts that we attach a string. This asserts the string
    does the thing — that LangGraph omits a tagged invocation from
    `stream_mode="messages"` — because the failure mode of the whole ticket is
    a tag that is spelled right, attached correctly, and read by nobody.
    """

    def _tokens_from(self, model: Any) -> list[str]:
        from typing import TypedDict

        from langgraph.graph import END, START, StateGraph

        class _State(TypedDict):
            said: str

        def talk(_state: _State) -> dict[str, str]:
            return {"said": model.invoke("hello").content}

        graph = StateGraph(_State)
        graph.add_node("talk", talk)
        graph.add_edge(START, "talk")
        graph.add_edge("talk", END)
        compiled = graph.compile()

        return [
            str(part["data"][0].content)
            for part in compiled.stream(
                {"said": ""}, stream_mode=["messages"], subgraphs=True, version="v2"
            )
            if part["type"] == "messages"
        ]

    def _model(self) -> Any:
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

        return GenericFakeChatModel(messages=iter(["one two three"] * 10))

    def test_an_untagged_model_streams(self) -> None:
        # The control. Without it the test below passes against a graph that
        # never streamed anything in the first place.
        assert "".join(self._tokens_from(self._model())) == "one two three"

    def test_a_silenced_model_does_not(self) -> None:
        assert self._tokens_from(silence_tokens(self._model())) == []


def _model_of(builder: Any) -> Any:
    """The model a built node closed over, whatever it named the variable."""
    for cell in builder.__closure__ or ():
        contents = cell.cell_contents
        if isinstance(contents, _Runnable):
            return contents
        # The router/grader hold theirs one level down, in the per-skill
        # factory that `run` calls.
        for inner in getattr(contents, "__closure__", None) or ():
            if isinstance(inner.cell_contents, _Runnable):
                return inner.cell_contents
    raise AssertionError("the built node closed over no model at all")
