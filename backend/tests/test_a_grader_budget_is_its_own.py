"""`maxAttempts` on a grader's card must be that grader's own budget.

`workflow-gallery` 21. `attempts` is one graph-wide integer that every
model-driven node increments once per invocation, and a grader's only budget
check was `state["attempts"] >= cap` — so the number on a card that reads
"Max revisions" was really a ceiling on *total model-node invocations in the
whole run*, and what it bought depended on the shape of the graph around it.

Three consequences, each reproduced below at the layer a caller stands on — a
real compiled graph over a shipped document, a scripted model, and `RunResult`:

1. a second grader inherits the first one's spend and force-passes the first
   candidate it is ever shown;
2. a lap costs one attempt *per model node on the path*, so a cycle holding two
   agents burns the budget twice as fast as one holding one;
3. nothing resets the count between stages, because there is only one key.

The inverses matter as much and are pinned too: a single-agent loop must keep
behaving exactly as it does today, and a turn boundary must still hand the next
turn a fresh budget.

**No live model run was possible** — this environment has no provider
credential — so every observation here is a scripted model through a real
`WorkflowCompiler` graph.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from conftest import RespondingModel
from openstategraph.loader import load_workflow

EXAMPLES = Path(__file__).resolve().parent.parent / "openstategraph" / "examples"

DRAFT = "- Fixed the export that silently produced an empty CSV."


def _package(tmp_path: Path, name: str, caps: dict[str, int]) -> Path:
    """A shipped example copied out and re-capped, so the test states the
    budget it is talking about instead of depending on the number the package
    happens to ship."""
    destination = tmp_path / name
    shutil.copytree(EXAMPLES / name, destination)
    payload = json.loads((destination / "workflow.json").read_text())
    for node in payload["document"]["nodes"]:
        if node["id"] in caps:
            node["data"]["maxAttempts"] = caps[node["id"]]
    (destination / "workflow.json").write_text(json.dumps(payload))
    return destination


class _RelentingGraders(RespondingModel):
    """Every grader rejects until it has personally seen `relent_on`
    candidates, then passes. Counted **per grader**, which is the whole point:
    a model that relents on its own second sight of an answer gives each loop
    exactly one revision, whatever else the graph is doing."""

    def __init__(self, relent_on: int = 2) -> None:
        super().__init__(rules=[])
        object.__setattr__(self, "relent_on", relent_on)
        object.__setattr__(self, "seen", {})

    def _which(self, context: str) -> str:
        return "second" if "two sentences" in context.lower() else "first"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        context = "\n".join(str(m.content) for m in messages)
        if "You are a grader" not in context:
            return self._reply(DRAFT)
        which = self._which(context)
        seen = dict(self.seen)
        seen[which] = seen.get(which, 0) + 1
        object.__setattr__(self, "seen", seen)
        if seen[which] >= self.relent_on:
            return self._reply("PASS")
        return self._reply(f"FAIL\nSay it better ({which}, lap {seen[which]}).")


def _ask(package: Path, model: Any, question: str = "Describe the export fix.") -> Any:
    return load_workflow(package, model=model).ask(question)


class TestASecondGraderDoesNotInheritTheFirstOnesSpend:
    """Consequence 1, and the reason the ticket exists.

    `two-stage-double-loop` ships `3` and `6` precisely to work around this.
    With the natural `2` on both cards, `grader2` used to see `attempts == 3`
    on the first candidate it was ever shown, force-pass it, and report
    `pass` — zero revisions, from a card promising two attempts.
    """

    @pytest.fixture(scope="class")
    def run(self, tmp_path_factory: pytest.TempPathFactory) -> Any:
        package = _package(
            tmp_path_factory.mktemp("two"),
            "two-stage-double-loop",
            {"grader1": 2, "grader2": 2},
        )
        model = _RelentingGraders(relent_on=2)
        return _ask(package, model), model

    def test_the_second_grader_judges_its_own_two_candidates(self, run: Any) -> None:
        _, model = run
        assert model.seen == {"first": 2, "second": 2}

    def test_neither_grader_was_forced(self, run: Any) -> None:
        """Both relented on their own second look, which `2` pays for. A
        forced-pass warning here is the defect wearing ticket 22's clothes."""
        result, _ = run
        assert [w for w in (result.warnings or []) if "ran out of attempts" in w] == []

    def test_both_stages_report_a_genuine_pass(self, run: Any) -> None:
        result, _ = run
        assert result.decisions.get("grader1") == "pass"
        assert result.decisions.get("grader2") == "pass"


class TestALapCostsOneAttemptWhateverElseIsOnThePath:
    """Consequence 2. `agentic-rag-rewrite`'s cycle is rewriter → retriever →
    grader, so under the graph-wide counter one lap cost **two** and
    `maxAttempts: 6` bought three laps. The number on the card had no fixed
    relationship to laps at all."""

    def test_two_agents_in_the_cycle_still_buy_two_looks(self, tmp_path: Path) -> None:
        package = _package(tmp_path, "agentic-rag-rewrite", {"grader1": 2})
        model = _RelentingGraders(relent_on=2)
        result = _ask(package, model, "What does the handbook say about refunds?")
        assert model.seen.get("first") == 2
        assert [w for w in (result.warnings or []) if "ran out of attempts" in w] == []


class TestTheBudgetStillStopsALoopThatCannotSucceed:
    """The inverse, and the behaviour no fix may move: a single-agent loop with
    a grader that never relents must exhaust at exactly its cap, force the
    pass, and report it (`workflow-gallery` 22)."""

    def test_a_never_satisfied_grader_stops_at_its_cap(self, tmp_path: Path) -> None:
        package = _package(tmp_path, "budget-exhaustion", {"grader1": 3})
        model = _RelentingGraders(relent_on=99)
        result = _ask(package, model, "Why is version control useful?")
        assert model.seen.get("first") == 3
        forced = [w for w in (result.warnings or []) if "ran out of attempts" in w]
        assert len(forced) == 1 and 'grader1' in forced[0]

    def test_a_cap_of_one_judges_once_and_never_revises(self, tmp_path: Path) -> None:
        """The boundary the old check also honoured: `1` means the first
        candidate is the last one."""
        package = _package(tmp_path, "budget-exhaustion", {"grader1": 1})
        model = _RelentingGraders(relent_on=99)
        result = _ask(package, model, "Why is version control useful?")
        assert model.seen.get("first") == 1
        assert result.decisions.get("grader1") == "pass"


class TestATurnBoundaryHandsBackAFullBudget:
    """Consequence 3's other face. A checkpointed thread carries state forward,
    which is right for the conversation and wrong for a spent budget — the
    comment on `RESET` in `node_runtime` records what a stale `attempts` cost
    when this was last got wrong. Whatever counts a grader's laps has to be
    cleared at the entry node too."""

    def test_the_second_turn_gets_its_own_laps(self, tmp_path: Path) -> None:
        package = _package(tmp_path, "budget-exhaustion", {"grader1": 2})
        model = _RelentingGraders(relent_on=99)
        workflow = load_workflow(package, model=model)
        workflow.ask("Why is version control useful?", thread_id="t-21")
        first_turn = dict(model.seen)
        workflow.ask("And why is review useful?", thread_id="t-21")
        assert first_turn.get("first") == 2
        assert model.seen.get("first") == 4
