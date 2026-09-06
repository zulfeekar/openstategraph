"""`async-first/05`, second family: the grader ladder gets an async door.

Same three substitutability statements as the router's file, asserted the same
way, plus the one thing that is the grader's own: the **deterministic checks
run before either door reaches a model**, so a grader that can answer without a
model must not be made to await anything at all. A cheap check that started
costing a thread hop would be a regression this map does not claim.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from openstategraph.abc.grader import BaseGrader, Grader, IGrader, Verdict


class _Reply:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeModel:
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
    """`compile/node_runtime.py`'s `_DeepAgentAsChatModel` shape, and this is
    the family that actually receives one — it is built per grading call."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.thread: threading.Thread | None = None

    def invoke(self, messages: list) -> _Reply:
        self.thread = threading.current_thread()
        return _Reply(self.answer)


class TestTheDoorItself:
    @pytest.mark.asyncio
    async def test_agrade_awaits_the_model(self) -> None:
        model = FakeModel("PASS\nthe figures are all from the data")
        verdict = await Grader(model=model).agrade("42 albums", question="how many?")

        assert verdict.passed is True
        assert verdict.reason == "the figures are all from the data"
        assert model.async_calls == 1
        assert model.sync_calls == 0

    @pytest.mark.asyncio
    async def test_a_rejection_reads_the_same_on_both_doors(self) -> None:
        model = FakeModel("FAIL\nname the album, not the artist")
        verdict = await Grader(model=model).agrade("some answer")

        assert verdict.passed is False
        assert verdict.feedback == "name the album, not the artist"

    @pytest.mark.asyncio
    async def test_a_deterministic_rejection_never_reaches_the_model(self) -> None:
        model = FakeModel("PASS")
        verdict = await Grader(model=model).agrade("   ")

        assert verdict.passed is False
        assert verdict.failed_check == "empty"
        assert model.async_calls == 0
        assert model.sync_calls == 0

    @pytest.mark.asyncio
    async def test_no_model_passes_on_the_async_path_too(self) -> None:
        verdict = await Grader().agrade("a real answer")

        assert verdict.passed is True
        assert verdict.reason == "No grading model configured"

    @pytest.mark.asyncio
    async def test_a_model_without_ainvoke_is_run_in_a_thread(self) -> None:
        model = SyncOnlyModel("PASS")
        here = threading.current_thread()

        verdict = await Grader(model=model).agrade("an answer")

        assert verdict.passed is True
        assert model.thread is not None
        assert model.thread is not here

    def test_grade_is_untouched(self) -> None:
        model = FakeModel("PASS")
        assert Grader(model=model).grade("an answer").passed is True
        assert model.sync_calls == 1
        assert model.async_calls == 0


class TestSubstitutability:
    @pytest.mark.asyncio
    async def test_a_sync_only_override_works_on_the_async_path(self) -> None:
        class SyncOnlyGrader(Grader):
            def __init__(self) -> None:
                super().__init__()
                self.thread: threading.Thread | None = None

            def grade(self, candidate: str, *, question: str = "") -> Verdict:
                self.thread = threading.current_thread()
                return Verdict(passed=False, reason="mine", feedback="mine")

        grader = SyncOnlyGrader()
        here = threading.current_thread()

        verdict = await grader.agrade("an answer", question="q")

        assert verdict.reason == "mine"
        assert grader.thread is not None, "the override was bypassed entirely"
        assert grader.thread is not here, "a synchronous body ran on the event loop"

    def test_an_async_only_override_works_on_the_sync_path(self) -> None:
        class AsyncOnlyGrader(Grader):
            async def agrade(self, candidate: str, *, question: str = "") -> Verdict:
                return Verdict(passed=False, reason="mine", feedback="mine")

        verdict = AsyncOnlyGrader().grade("an answer")

        assert verdict.passed is False
        assert verdict.reason == "mine"

    @pytest.mark.asyncio
    async def test_an_async_only_override_is_reachable_from_a_running_loop(self) -> None:
        class AsyncOnlyGrader(Grader):
            async def agrade(self, candidate: str, *, question: str = "") -> Verdict:
                return Verdict(passed=False, reason="mine", feedback="mine")

        grader = AsyncOnlyGrader()
        verdict = await asyncio.to_thread(grader.grade, "an answer")

        assert verdict.reason == "mine"

    @pytest.mark.asyncio
    async def test_the_keyword_argument_survives_both_doors(self) -> None:
        """`question` is keyword-only, so a door that flattened its arguments
        would raise rather than misbehave — and would do it only for a subclass
        that overrode one half. Pinned in the direction that fails loudly."""
        seen: list[str] = []

        class SyncOnlyGrader(Grader):
            def grade(self, candidate: str, *, question: str = "") -> Verdict:
                seen.append(question)
                return Verdict(passed=True)

        await SyncOnlyGrader().agrade("an answer", question="the question")

        assert seen == ["the question"]

    @pytest.mark.asyncio
    async def test_a_grader_that_overrides_neither_answers_both_doors(self) -> None:
        grader = Grader(model=FakeModel("PASS"))

        assert grader.grade("an answer").passed is True
        assert (await grader.agrade("an answer")).passed is True

    @pytest.mark.asyncio
    async def test_a_deterministic_check_override_is_honoured_on_both_doors(self) -> None:
        """The family's real extension point, which is neither half of the pair.

        `deterministic_checks` is what a grader subclass usually writes, and it
        is called by both doors rather than by one — the shape that would break
        it is an async body that re-implemented the prelude instead of sharing
        it.
        """

        class NumericGrader(Grader):
            def deterministic_checks(self, candidate: str) -> Verdict | None:
                if not any(c.isdigit() for c in candidate):
                    return Verdict.reject("No figure in the answer.", check="numeric")
                return super().deterministic_checks(candidate)

        grader = NumericGrader(model=FakeModel("PASS"))

        assert grader.grade("no numbers here").failed_check == "numeric"
        assert (await grader.agrade("no numbers here")).failed_check == "numeric"


class TestTheContractIsUnchanged:
    def test_igrader_is_still_satisfied_by_a_plain_object(self) -> None:
        """`IGrader` is `runtime_checkable` and deliberately untouched — the
        same decision `async-first/04` made about `ITool`."""

        class HandWritten:
            def grade(self, candidate: str, *, question: str = "") -> Verdict:
                return Verdict(passed=True)

            def revise_payload(self, verdict: Verdict) -> dict:
                return {}

        assert isinstance(HandWritten(), IGrader)

    def test_the_base_still_declares_exactly_one_abstract_method(self) -> None:
        assert BaseGrader.__abstractmethods__ == frozenset({"revise_payload"})


class TestCancellation:
    @pytest.mark.asyncio
    async def test_a_cancel_is_not_turned_into_a_pass(self) -> None:
        """The dangerous direction for this family, and the reason the pin is
        worth writing. `normalise` **passes** whatever it cannot read — a
        deliberate choice, so a grader that cannot decide does not discard work
        — so a cancel converted into an error string would be laundered into an
        approval and the candidate would ship."""

        class Hangs:
            async def ainvoke(self, messages: list) -> _Reply:
                await asyncio.sleep(3600)
                raise AssertionError("unreachable")

        task = asyncio.ensure_future(Grader(model=Hangs()).agrade("an answer"))
        await asyncio.sleep(0)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_a_thread_bridged_grade_runs_to_completion_anyway(self) -> None:
        finished = threading.Event()

        class Slow(Grader):
            def grade(self, candidate: str, *, question: str = "") -> Verdict:
                import time

                time.sleep(0.25)
                finished.set()
                return Verdict(passed=True)

        task = asyncio.ensure_future(Slow().agrade("an answer"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert finished.wait(2.0) is True
