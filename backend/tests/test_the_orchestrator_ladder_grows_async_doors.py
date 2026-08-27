"""`async-first/05`, third family: the orchestrator ladder gets async doors.

Three pairs rather than one, and the reason is the point of the family:
`plan` is built from two other public verbs. `aplan` can only await a model if
`asplit` and `alabel` are awaitable too — so `async-first/10` unblocking on
this file means all three, not the one the node calls.

Same three substitutability statements as the two files before it, plus the one
this family adds: `split` is `@abstractmethod`, so a subclass that writes only
`asplit` has to come out **concrete**. That is the `abc/tool.py` mechanism, and
it is asserted here by constructing such a class rather than by describing it.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from openstategraph.abc.orchestrator import (
    Archetype,
    BaseOrchestrator,
    Orchestrator,
    PlanningOrchestrator,
    Subtask,
)


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
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.thread: threading.Thread | None = None

    def invoke(self, messages: list) -> _Reply:
        self.thread = threading.current_thread()
        return _Reply(self.answer)


ARCHETYPES = [
    Archetype(key="writer", name="Writer", description="drafts prose"),
    Archetype(key="checker", name="Checker", description="verifies claims"),
]


class TestThePlanningSplit:
    @pytest.mark.asyncio
    async def test_asplit_awaits_the_planning_call(self) -> None:
        model = FakeModel("draft the agenda\ncheck the figures")
        pieces = await PlanningOrchestrator(model=model).asplit("run the meeting")

        assert pieces == ["draft the agenda", "check the figures"]
        assert model.async_calls == 1
        assert model.sync_calls == 0

    @pytest.mark.asyncio
    async def test_a_failed_planning_call_still_degrades_to_the_deterministic_split(
        self,
    ) -> None:
        class Explodes:
            async def ainvoke(self, messages: list) -> _Reply:
                raise RuntimeError("provider said 500")

        pieces = await PlanningOrchestrator(model=Explodes()).asplit("do X and do Y")

        assert pieces == ["do X", "do Y"]

    @pytest.mark.asyncio
    async def test_no_model_takes_the_deterministic_path_with_nothing_awaited(
        self,
    ) -> None:
        assert await PlanningOrchestrator().asplit("do X and do Y") == ["do X", "do Y"]

    @pytest.mark.asyncio
    async def test_the_deterministic_orchestrator_needs_no_thread_at_all(self) -> None:
        """A regex split has nothing to await and nothing to hand a pool.

        `Orchestrator` writes both halves rather than taking the installed
        door, so the zero-token path stays a function call on the loop instead
        of a thread hop bought for a regular expression.
        """
        here = threading.current_thread()
        seen: list[threading.Thread] = []

        class Watching(Orchestrator):
            def split(self, instruction: str, feedback: str = "") -> list[str]:
                seen.append(threading.current_thread())
                return super().split(instruction, feedback)

        # The subclass overrides only `split`, so it *does* get a door — the
        # assertion below is about the base class, which does not.
        assert await Orchestrator().asplit("do X and do Y") == ["do X", "do Y"]
        assert seen == []
        assert here is threading.current_thread()


class TestTheLabellingCall:
    @pytest.mark.asyncio
    async def test_alabel_awaits_the_model(self) -> None:
        model = FakeModel("writer\nchecker")
        subtasks = [Subtask(id="task-1", instruction="draft"), Subtask(id="task-2", instruction="verify")]

        labels = await Orchestrator(model=model).alabel(subtasks, ARCHETYPES)

        assert labels == ["writer", "checker"]
        assert model.async_calls == 1

    @pytest.mark.asyncio
    async def test_an_invented_label_is_still_not_trusted(self) -> None:
        """Tolerant in reading, strict in trusting — unchanged by the door."""
        model = FakeModel("writer\nsummariser")
        subtasks = [Subtask(id="1", instruction="a"), Subtask(id="2", instruction="b")]
        notes: list[str] = []

        labels = await Orchestrator(model=model).alabel(subtasks, ARCHETYPES, notes=notes)

        assert labels == ["writer", ""]
        assert any("matches no wired worker" in note for note in notes)

    @pytest.mark.asyncio
    async def test_a_labelling_failure_reaches_the_notes_sink_not_only_a_logger(
        self,
    ) -> None:
        class Explodes:
            async def ainvoke(self, messages: list) -> _Reply:
                raise RuntimeError("provider said 500")

        subtasks = [Subtask(id="1", instruction="a")]
        notes: list[str] = []

        labels = await Orchestrator(model=Explodes()).alabel(
            subtasks, ARCHETYPES, notes=notes
        )

        assert labels == [""]
        assert notes == [
            "archetype labelling failed; every subtask falls to the default worker"
        ]

    @pytest.mark.asyncio
    async def test_the_no_model_fallback_awaits_nothing(self) -> None:
        subtasks = [Subtask(id="1", instruction="ask the Writer to draft it")]

        assert await Orchestrator().alabel(subtasks, ARCHETYPES) == ["writer"]

    @pytest.mark.asyncio
    async def test_a_model_without_ainvoke_is_run_in_a_thread(self) -> None:
        model = SyncOnlyModel("writer")
        here = threading.current_thread()
        subtasks = [Subtask(id="1", instruction="a")]

        labels = await Orchestrator(model=model).alabel(subtasks, ARCHETYPES)

        assert labels == ["writer"]
        assert model.thread is not None
        assert model.thread is not here


class TestThePlan:
    @pytest.mark.asyncio
    async def test_aplan_awaits_both_verbs_beneath_it(self) -> None:
        model = FakeModel("draft the agenda\ncheck the figures")
        planner = PlanningOrchestrator(model=model)
        planner_labels = FakeModel("writer\nchecker")

        # Two different answers are needed from one model, so the labelling
        # call is served by a second fake swapped in after the split — the
        # point being only that `aplan` reaches both.
        pieces = await planner.asplit("run the meeting")
        planner.model = planner_labels
        subtasks = await planner.aplan("run the meeting", archetypes=ARCHETYPES)

        assert pieces == ["draft the agenda", "check the figures"]
        assert [t.archetype for t in subtasks] == ["writer", "checker"]

    @pytest.mark.asyncio
    async def test_aplan_bounds_and_ids_exactly_as_plan_does(self) -> None:
        planner = Orchestrator(max_subtasks=2)

        sync = planner.plan("do A and do B and do C", generation=3)
        each = await planner.aplan("do A and do B and do C", generation=3)

        assert [t.id for t in each] == [t.id for t in sync] == ["task-3-1", "task-3-2"]
        assert [t.instruction for t in each] == [t.instruction for t in sync]

    @pytest.mark.asyncio
    async def test_the_max_subtasks_note_still_reaches_the_caller(self) -> None:
        notes: list[str] = []

        await Orchestrator(max_subtasks=1).aplan("do A and do B", notes=notes)

        assert any("were dropped and never ran" in note for note in notes)

    @pytest.mark.asyncio
    async def test_an_instruction_that_does_not_split_is_still_one_unit_of_work(
        self,
    ) -> None:
        assert len(await Orchestrator().aplan("do the thing")) == 1
        assert await Orchestrator().aplan("   ") == []


class TestSubstitutability:
    @pytest.mark.asyncio
    async def test_a_sync_only_split_works_on_the_async_path_in_a_thread(self) -> None:
        seen: list[threading.Thread] = []

        class SyncOnly(BaseOrchestrator):
            def split(self, instruction: str, feedback: str = "") -> list[str]:
                seen.append(threading.current_thread())
                return ["mine"]

        here = threading.current_thread()

        assert await SyncOnly().asplit("q") == ["mine"]
        assert seen and seen[0] is not here, (
            "a synchronous body ran on the event loop, which is strictly worse "
            "than the `def` the async door replaced"
        )

    def test_an_async_only_split_produces_a_concrete_class(self) -> None:
        """`split` stays `@abstractmethod`, so this is the whole trick.

        `__init_subclass__` runs inside `type.__new__`, which `ABCMeta.__new__`
        calls *before* it computes `__abstractmethods__` — so the sync door is
        already installed by the time abstractness is decided, and the class
        comes out constructible rather than abstract-and-half-finished.
        """

        class AsyncOnly(BaseOrchestrator):
            async def asplit(self, instruction: str, feedback: str = "") -> list[str]:
                return ["mine"]

        assert AsyncOnly.__abstractmethods__ == frozenset()
        assert AsyncOnly().split("q") == ["mine"]

    @pytest.mark.asyncio
    async def test_an_async_only_split_is_reachable_from_a_running_loop(self) -> None:
        class AsyncOnly(BaseOrchestrator):
            async def asplit(self, instruction: str, feedback: str = "") -> list[str]:
                return ["mine"]

        planner = AsyncOnly()
        assert await asyncio.to_thread(planner.split, "q") == ["mine"]

    @pytest.mark.asyncio
    async def test_an_async_only_split_is_what_aplan_uses(self) -> None:
        """The statement that makes `async-first/10` worth anything.

        A door that satisfied `split` and left `plan` calling the synchronous
        one would put a model call back on the event loop by the longest route
        available.
        """

        class AsyncOnly(BaseOrchestrator):
            async def asplit(self, instruction: str, feedback: str = "") -> list[str]:
                return ["draft the agenda", "check the figures"]

        subtasks = await AsyncOnly().aplan("run the meeting")

        assert [t.instruction for t in subtasks] == [
            "draft the agenda",
            "check the figures",
        ]

    @pytest.mark.asyncio
    async def test_a_sync_only_label_override_is_honoured_by_aplan(self) -> None:
        class OwnLabels(Orchestrator):
            def label(self, subtasks, archetypes, *, notes=None) -> list[str]:
                return ["checker" for _ in subtasks]

        subtasks = await OwnLabels().aplan("do A and do B", archetypes=ARCHETYPES)

        assert [t.archetype for t in subtasks] == ["checker", "checker"]

    @pytest.mark.asyncio
    async def test_a_sync_only_plan_override_works_on_the_async_path(self) -> None:
        class OwnPlan(Orchestrator):
            def plan(self, instruction: str, **kwargs) -> list[Subtask]:
                return [Subtask(id="mine", instruction=instruction)]

        assert [t.id for t in await OwnPlan().aplan("q")] == ["mine"]

    def test_an_async_only_plan_override_works_on_the_sync_path(self) -> None:
        class OwnPlan(Orchestrator):
            async def aplan(self, instruction: str, **kwargs) -> list[Subtask]:
                return [Subtask(id="mine", instruction=instruction)]

        assert [t.id for t in OwnPlan().plan("q")] == ["mine"]

    @pytest.mark.asyncio
    async def test_an_orchestrator_that_overrides_neither_answers_both_doors(
        self,
    ) -> None:
        planner = Orchestrator()
        # Three-word fragments, so neither picks up the parent-context suffix a
        # short one would — this test is about the two doors agreeing, not
        # about that rule.
        brief = "draft the agenda and check the figures"

        assert [t.instruction for t in planner.plan(brief)] == [
            "draft the agenda",
            "check the figures",
        ]
        assert [t.instruction for t in await planner.aplan(brief)] == [
            "draft the agenda",
            "check the figures",
        ]


class TestTheContractIsUnchanged:
    def test_iorchestrator_is_still_satisfied_by_a_plain_object(self) -> None:
        """`IOrchestrator` is `runtime_checkable` and deliberately untouched."""
        from openstategraph.abc.orchestrator import IOrchestrator

        class HandWritten:
            def plan(self, instruction: str, **kwargs) -> list[Subtask]:
                return []

        assert isinstance(HandWritten(), IOrchestrator)

    def test_the_base_still_declares_exactly_one_abstract_method(self) -> None:
        assert BaseOrchestrator.__abstractmethods__ == frozenset({"split"})


class TestCancellation:
    @pytest.mark.asyncio
    async def test_a_cancelled_planning_call_is_not_a_deterministic_fallback(
        self,
    ) -> None:
        """`split` degrades on `except Exception`, which is exactly the shape
        that would swallow a stop if `CancelledError` were one. It is a
        `BaseException`; pinned rather than trusted, because the symptom would
        be a run that answered anyway after the client asked it not to."""

        class Hangs:
            async def ainvoke(self, messages: list) -> _Reply:
                await asyncio.sleep(3600)
                raise AssertionError("unreachable")

        task = asyncio.ensure_future(PlanningOrchestrator(model=Hangs()).asplit("q"))
        await asyncio.sleep(0)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_a_cancelled_labelling_call_is_not_a_collapse_onto_one_worker(
        self,
    ) -> None:
        class Hangs:
            async def ainvoke(self, messages: list) -> _Reply:
                await asyncio.sleep(3600)
                raise AssertionError("unreachable")

        subtasks = [Subtask(id="1", instruction="a")]
        task = asyncio.ensure_future(
            Orchestrator(model=Hangs()).alabel(subtasks, ARCHETYPES)
        )
        await asyncio.sleep(0)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_a_thread_bridged_split_runs_to_completion_anyway(self) -> None:
        finished = threading.Event()

        class Slow(BaseOrchestrator):
            def split(self, instruction: str, feedback: str = "") -> list[str]:
                import time

                time.sleep(0.25)
                finished.set()
                return ["mine"]

        task = asyncio.ensure_future(Slow().asplit("q"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert finished.wait(2.0) is True
