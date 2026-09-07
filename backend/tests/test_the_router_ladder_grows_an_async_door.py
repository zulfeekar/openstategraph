"""`async-first/05`, first family: the router ladder gets an async door.

Same additive shape `async-first/04` settled one rung down on `BaseTool`, and
the same three substitutability statements, asserted directly rather than by
implication:

1. a router that overrides only `classify` works on the async path — **in a
   thread**, which this file asserts by identity rather than by hope, because a
   synchronous body on the event loop is strictly worse than the `def` it
   replaced;
2. a router that overrides only `aclassify` works on the synchronous path;
3. a router that overrides neither works on both.

Plus the two properties that are easy to assume and expensive to be wrong
about: a cancel is not swallowed, and a model that has no `ainvoke` is still
usable — `compile/node_runtime.py`'s `_DeepAgentAsChatModel` is exactly such a
model and it is in this tree today.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from openstategraph.abc.router import BaseRouter, Classification, IRouter, Router


class _Reply:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeModel:
    """Both doors, and it records which one was opened."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.sync_calls = 0
        self.async_calls = 0

    def invoke(self, messages: list) -> _Reply:
        self.sync_calls += 1
        return _Reply(self.answer)

    async def ainvoke(self, messages: list) -> _Reply:
        self.async_calls += 1
        return _Reply(self.answer)


class SyncOnlyModel:
    """The `_DeepAgentAsChatModel` shape: `invoke` and nothing else.

    Not a hypothetical — `compile/node_runtime.py` builds one per grading call
    and the grader ladder accepts it because `model` is deliberately typed
    `Any`. A ladder whose async door required `ainvoke` would refuse an object
    this repository already constructs.
    """

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.thread: threading.Thread | None = None

    def invoke(self, messages: list) -> _Reply:
        self.thread = threading.current_thread()
        return _Reply(self.answer)


def a_router(model: object = None, **kwargs: object) -> Router:
    return Router(["greeting", "dataquery"], model=model, **kwargs)  # type: ignore[arg-type]


class TestTheDoorItself:
    @pytest.mark.asyncio
    async def test_aclassify_awaits_the_model(self) -> None:
        model = FakeModel("dataquery")
        decision = await a_router(model).aclassify("how much revenue?")

        assert decision.branch == "dataquery"
        assert model.async_calls == 1
        assert model.sync_calls == 0

    def test_classify_is_untouched(self) -> None:
        model = FakeModel("greeting")
        decision = a_router(model).classify("hello")

        assert decision.branch == "greeting"
        assert model.sync_calls == 1
        assert model.async_calls == 0

    @pytest.mark.asyncio
    async def test_no_model_falls_back_on_the_async_path_too(self) -> None:
        decision = await a_router().aclassify("anything")

        assert decision.fell_back is True
        assert decision.branch == "dataquery"
        assert decision.reason == "No model configured"

    @pytest.mark.asyncio
    async def test_a_model_without_ainvoke_is_run_in_a_thread(self) -> None:
        model = SyncOnlyModel("greeting")
        here = threading.current_thread()

        decision = await a_router(model).aclassify("hi")

        assert decision.branch == "greeting"
        assert model.thread is not None
        assert model.thread is not here

    @pytest.mark.asyncio
    async def test_the_async_answer_is_normalised_the_same_way(self) -> None:
        """One parser, not two. `normalise` is where tolerance lives."""
        model = FakeModel("I think this is a dataquery, personally.")

        decision = await a_router(model).aclassify("q")

        assert decision.branch == "dataquery"
        assert decision.reason == "Found in a longer answer"


class TestSubstitutability:
    """CLAUDE.md's L, one statement per test and no `try` anywhere near them."""

    @pytest.mark.asyncio
    async def test_a_sync_only_override_works_on_the_async_path(self) -> None:
        class SyncOnlyRouter(Router):
            def __init__(self) -> None:
                super().__init__(["a", "b"])
                self.thread: threading.Thread | None = None

            def classify(self, question: str) -> Classification:
                self.thread = threading.current_thread()
                return Classification(branch="a", reason="mine")

        router = SyncOnlyRouter()
        here = threading.current_thread()

        decision = await router.aclassify("q")

        assert decision.branch == "a"
        assert decision.reason == "mine"
        assert router.thread is not None, "the override was bypassed entirely"
        assert router.thread is not here, (
            "a synchronous body ran on the event loop, which is strictly worse "
            "than the `def` the async door replaced"
        )

    def test_an_async_only_override_works_on_the_sync_path(self) -> None:
        class AsyncOnlyRouter(Router):
            def __init__(self) -> None:
                super().__init__(["a", "b"])

            async def aclassify(self, question: str) -> Classification:
                return Classification(branch="b", reason="mine")

        decision = AsyncOnlyRouter().classify("q")

        assert decision.branch == "b"
        assert decision.reason == "mine"

    @pytest.mark.asyncio
    async def test_an_async_only_override_is_reachable_from_a_running_loop(self) -> None:
        """The nesting case `asyncio.run` refuses, answered rather than shipped.

        A synchronous caller reached from inside a coroutine is ordinary here —
        the four sync doors `async-first/06` inventoried are all reachable that
        way — so the sync door has to work with a loop already running.
        """

        class AsyncOnlyRouter(Router):
            def __init__(self) -> None:
                super().__init__(["a", "b"])

            async def aclassify(self, question: str) -> Classification:
                # Deliberately *not* the fallback, so the assertion below
                # cannot pass by accident on a base that ignored the override.
                return Classification(branch="a", reason="mine")

        router = AsyncOnlyRouter()
        decision = await asyncio.to_thread(router.classify, "q")

        assert decision.branch == "a"
        assert decision.reason == "mine"

    @pytest.mark.asyncio
    async def test_a_router_that_overrides_neither_answers_both_doors(self) -> None:
        router = a_router(FakeModel("greeting"))

        assert router.classify("hi").branch == "greeting"
        assert (await router.aclassify("hi")).branch == "greeting"


class TestTheContractIsUnchanged:
    def test_irouter_still_has_one_member_and_a_plain_object_satisfies_it(self) -> None:
        """`IRouter` is `runtime_checkable`; a member added to it would
        un-satisfy every third-party classifier at the next `isinstance`, in
        their install, silently. So it is deliberately untouched — the same
        decision `async-first/04` made about `ITool`."""

        class HandWritten:
            branches = ["a"]
            fallback = "a"

            def classify(self, question: str) -> Classification:
                return Classification(branch="a")

        assert isinstance(HandWritten(), IRouter)

    def test_the_base_still_declares_exactly_one_abstract_method(self) -> None:
        assert BaseRouter.__abstractmethods__ == frozenset({"compile_path_map"})


class TestCancellation:
    @pytest.mark.asyncio
    async def test_a_cancel_is_not_turned_into_a_fallback(self) -> None:
        """`CancelledError` is a `BaseException`, and that is pinned rather
        than trusted: a cancelled classification must propagate as a cancel,
        never arrive downstream as "the model said nothing, take the
        fallback"."""

        class Hangs:
            async def ainvoke(self, messages: list) -> _Reply:
                await asyncio.sleep(3600)
                raise AssertionError("unreachable")

            def invoke(self, messages: list) -> _Reply:  # pragma: no cover
                raise AssertionError("unreachable")

        router = a_router(Hangs())
        task = asyncio.ensure_future(router.aclassify("q"))
        await asyncio.sleep(0)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_a_thread_bridged_classify_runs_to_completion_anyway(self) -> None:
        """What the default buys and what it does not.

        A thread cannot be interrupted, so the door a sync-only router gets is
        *availability*, not cancellation. Said out loud here so the default is
        never mistaken for this map's promise.
        """
        finished = threading.Event()

        class Slow(Router):
            def __init__(self) -> None:
                super().__init__(["a"])

            def classify(self, question: str) -> Classification:
                import time

                time.sleep(0.25)
                finished.set()
                return Classification(branch="a")

        task = asyncio.ensure_future(Slow().aclassify("q"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert finished.wait(2.0) is True
