"""launch-readiness 167 — a guard that runs out of attempts publishes what it refused.

Measured live on 2026-08-28 (an MCP package, the owner's question,
`maxAttempts: 2`):

```
lap 1  guard1  pass
lap 2  guard1  "The answer reports 8,715 tracks. That figure came from a
                bare COUNT(*) over main.PlaylistTrack..."     -> EXHAUSTED
       out1    "...there are 8,715 tracks."
```

The verdict was recorded and the branch was `pass`, so the answer shipped **with
the check's own objection to it sitting in the run's state, unread by the
reader.** That is worse than having no guard: the reader sees a normal answer,
and the system knew it was wrong.

**The pass is correct and is not changed here.** `_grader`'s argument holds and
holds harder for a guard, whose laps are cheap: a loop that cannot finish is
worse than a mediocre answer, and refusing to publish turns a ceiling into a
dead run — `Grader.normalise`'s warning. Raising `maxAttempts` is not a fix
either; exhaustion is a ceiling, not an accident, and every ceiling is
reachable. Only the silence was the defect.

## What `103` transferred, and what it did not

`launch-readiness/103` (`e170dfb`) forced a grader to `pass` and put
`CAPABILITY_UNAVAILABLE_ANSWER` **in the answer slot**, from the run's own
record, with no prompt rule and no matching on *"I cannot"*.

- **Transferred:** the trigger is entirely the run's own record — a branch of
  `pass` while `passed` is false — and no model is asked anything.
- **Did not transfer:** `103` *replaces* the answer, and here it must not.
  `103`'s fact says the producer had nothing to produce from, so its prose was
  never an answer. A guard's objection is a **judgement about** an answer the
  workflow really did produce, and `_grader`'s own rule covers that case
  explicitly: *a candidate the grader merely disliked is still the answer the
  workflow produced.* So the doubt is appended, not substituted.

The rail is `abc/tool_notes` (`8caaf38`), which renders facts whether or not the
model mentions them — the same mechanism `103` used and the reason `127` built
it: a model asked to disclose discloses most of the time.
"""

from __future__ import annotations

from typing import Any

from openstategraph.abc.tool_notes import UnverifiedAnswer, notes_for_reader

OBJECTION = "The answer reports 1,454,449 vessels, and that figure counts rows."
DRAFT = "There are 1,454,449 dark vessels."


def _wire(source: str, port: str, target: str, target_port: str) -> dict:
    return {
        "source": {"nodeId": source, "portId": port},
        "target": {"nodeId": target, "portId": target_port},
    }


def _document(*, cap: int = 2, check: str = "always_objects") -> dict:
    return {
        "nodes": [
            {"id": "a1", "type": "agent.llm", "data": {}},
            {
                "id": "guard1",
                "type": "guard.check",
                "data": {"check": check, "maxAttempts": cap},
            },
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            _wire("a1", "result", "guard1", "candidate"),
            _wire("guard1", "revise", "a1", "feedback"),
            _wire("guard1", "pass", "out1", "result"),
        ],
    }


def _run(
    *, cap: int = 2, reason: str = OBJECTION, thread: str = "167", limit: int = 40
) -> dict[str, Any]:
    """One whole run of the drawing above, through the compiled graph.

    At the layer the defect lives: the ceiling, the branch, the output node and
    the reader rail are four different objects and the defect was in the gap
    between the third and the fourth.
    """
    from openstategraph.compile.node_runtime import NodeRuntime, RunState
    from openstategraph.compile.workflow_compiler import WorkflowCompiler

    from conftest import RespondingModel

    document = _document(cap=cap)
    runtime = NodeRuntime(
        model=RespondingModel([], default=DRAFT),
        functions={"function.always_objects": lambda text: reason},
    )
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    return dict(
        graph.invoke(
            {"question": "How many dark vessels?", "attempts": 0, "decisions": {}, "outputs": {}},
            {"recursion_limit": limit, "configurable": {"thread_id": thread}},
        )
    )


# ------------------------------------------------------------------ #
# The defect
# ------------------------------------------------------------------ #


class TestAForcedPassIsNotSilent:
    def test_the_run_still_publishes_the_candidate(self) -> None:
        """The pass is correct and is not changed. This is the anti-vacuity half:
        a fix that suppressed the answer would pass every other test here."""
        final = _run()
        assert DRAFT in str(final.get("answer") or "")

    def test_the_reader_is_told_it_did_not_pass(self) -> None:
        answer = str(_run(thread="167-a").get("answer") or "")
        assert "did not pass this workflow's own check on it" in answer
        assert "unverified" in answer

    def test_the_objection_itself_never_reaches_the_reader(self) -> None:
        """`143`'s sentence-shape rule. The guard's `reason` is developer text
        written for a model to act on — it names tables and statements."""
        answer = str(_run(thread="167-b").get("answer") or "")
        assert OBJECTION not in answer
        assert "COUNT" not in answer.upper()

    def test_the_developer_channel_gets_the_ceiling_it_never_had(self) -> None:
        final = _run(thread="167-c")
        assert final.get("forced") == {"guard1": OBJECTION}

    def test_the_verdict_is_still_recorded_beside_it(self) -> None:
        final = _run(thread="167-d")
        assert (final.get("verdicts") or {})["guard1"]["verdict"] == "revise"
        assert (final.get("decisions") or {})["guard1"] == "pass"


class TestTheOtherDirection:
    """`133`: a check that fires on correct work teaches people to bypass it."""

    def test_a_guard_that_passes_adds_nothing_at_all(self) -> None:
        final = _run(reason="", thread="167-e")
        assert str(final.get("answer") or "").strip() == DRAFT
        assert "forced" not in final or not final.get("forced")

    def test_a_guard_satisfied_on_a_later_lap_adds_nothing(self) -> None:
        """The objection stood and then stopped standing — nothing was forced."""
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        from conftest import RespondingModel

        laps: list[int] = []

        def relents(text: str) -> str:
            laps.append(1)
            return OBJECTION if len(laps) == 1 else ""

        document = _document(cap=4)
        runtime = NodeRuntime(
            model=RespondingModel([], default=DRAFT),
            functions={"function.always_objects": relents},
        )
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        final = graph.invoke(
            {"question": "q", "attempts": 0, "decisions": {}, "outputs": {}},
            {"recursion_limit": 40, "configurable": {"thread_id": "167-f"}},
        )
        assert len(laps) >= 2, "the guard never got a second candidate"
        assert str(final.get("answer") or "").strip() == DRAFT
        assert not final.get("forced")


class TestTheTwoCeilingsStayTwoSentences:
    """A `maxAttempts` cap is a number on this card; the step budget is a number
    on the workflow. A reader's next move differs, so one sentence for both
    would be false about one of them."""

    def test_the_step_budget_is_its_own_key(self) -> None:
        final = _run(cap=50, thread="167-g", limit=8)
        assert "budget_stops" in final and final["budget_stops"], final.keys()
        assert not final.get("forced")

    def test_and_its_own_reader_sentence(self) -> None:
        capped = notes_for_reader([UnverifiedAnswer(check="c", starved=False)])
        starved = notes_for_reader([UnverifiedAnswer(check="c", starved=True)])
        assert "ran out of attempts" in capped
        assert "ran out of steps" in starved
        assert capped != starved

    def test_neither_sentence_names_the_check(self) -> None:
        for note in (UnverifiedAnswer(check="row_counts_in_prose"), UnverifiedAnswer(starved=True)):
            assert "row_counts_in_prose" not in notes_for_reader([note])


class TestTheWarningNoLongerCallsAGuardAGrader:
    """`forced` and `budget_stops` now carry two node families, so the sentence
    that reads them may name neither. It said `Grader "guard1"`, which was false
    every time a guard reached the ceiling — the identical shape of defect this
    map is about."""

    def test_the_forced_pass_sentence(self) -> None:
        from openstategraph.compile.workflow_compiler import forced_pass_warnings

        line = forced_pass_warnings({"guard1": OBJECTION})[0]
        assert line.startswith('The review at "guard1"')
        assert "Grader" not in line
        assert OBJECTION in line, "the developer channel keeps the reason verbatim"

    def test_the_step_budget_sentence(self) -> None:
        from openstategraph.compile.workflow_compiler import step_budget_warnings

        line = step_budget_warnings({"guard1": 2})[0]
        assert line.startswith('The review at "guard1"')
        assert "supersteps" in line and "iterations" not in line
