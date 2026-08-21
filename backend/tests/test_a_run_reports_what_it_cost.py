"""A finished run can say how many tokens it spent, without a tracer.

`workflow-gallery` 35. The owner's acceptance test for the flagship names four
things and the fourth is *"total tokens/cost recorded"*. `RunResult` could not
answer it, so every eval scorecard printed `NO_COST_SIGNAL` in its cost row and
the catalogue wrote *"cannot be measured"* into its estimate column — twenty
examples budgeted against a number nothing measured.

**LangChain already counted it.** `get_usage_metadata_callback` aggregates
`AIMessage.usage_metadata` per model, in-process, with no tracer and no
account (`langchain-core` 1.5.3; the docs page is
`/oss/python/langchain/models.mdx`, Token usage). This is that callback wrapped
around the one `invoke()` the library door already makes — not a new accounting
layer, which `CLAUDE.md` forbids in as many words.

**Driven through the real compiled graph and read at the door**, not off the
callback: a test that asserts on `cb.usage_metadata` stays green against an
`ask()` that never wraps anything.

**No live model run was possible** — this environment has no provider
credential — so every figure here is a scripted model that reports usage the
way a real provider does. The live half of the ticket (re-basing the
catalogue's estimates on measured figures) is unverified and is
`workflow-gallery/73`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from conftest import RespondingModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from openstategraph.evaluation.runner import NO_USAGE_REPORTED, evaluate, package_asker
from openstategraph.evaluation.dataset import EvalCase, EvalDataset
from openstategraph.loader import load_workflow
from openstategraph.results import RunResult

EXAMPLES = Path(__file__).resolve().parent.parent / "openstategraph" / "examples"


class Metered(RespondingModel):
    """A scripted model that reports usage the way a provider does.

    Both halves are required by `UsageMetadataCallbackHandler` and neither is
    obvious: it reads `usage_metadata` off the `AIMessage` **and**
    `response_metadata["model_name"]`, and drops the row entirely when either
    is missing. That is the shape of the "unknown, not zero" case below.
    """

    def __init__(
        self,
        name: str,
        rules: Any = None,
        default: str = "PASS",
        inp: int = 100,
        out: int = 10,
        *,
        report: bool = True,
    ) -> None:
        super().__init__(rules or [], default)
        object.__setattr__(self, "mname", name)
        object.__setattr__(self, "inp", inp)
        object.__setattr__(self, "out", out)
        object.__setattr__(self, "report", report)

    def _reply(self, text: str):  # noqa: ANN001, ANN202
        extra: dict[str, Any] = {}
        if self.report:
            extra = {
                "usage_metadata": {
                    "input_tokens": self.inp,
                    "output_tokens": self.out,
                    "total_tokens": self.inp + self.out,
                },
                "response_metadata": {"model_name": self.mname},
            }
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text, **extra))])


class TwoModels(Metered):
    """One graph, two models — the grader bills to a different name.

    The ticket's own measured figures had two providers on one run, and per-model
    is the whole reason the aggregate is a mapping rather than an integer.
    """

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        content = "\n".join(str(m.content) for m in messages)
        self.calls.append(content)
        if "You are a grader" in content:
            saved = (self.mname, self.inp, self.out)
            object.__setattr__(self, "mname", "scripted-grader")
            object.__setattr__(self, "inp", 40)
            object.__setattr__(self, "out", 4)
            try:
                return self._reply("PASS")
            finally:
                object.__setattr__(self, "mname", saved[0])
                object.__setattr__(self, "inp", saved[1])
                object.__setattr__(self, "out", saved[2])
        return self._reply("A short summary of the release notes.")


def _package(tmp_path: Path, name: str) -> Path:
    destination = tmp_path / name
    shutil.copytree(EXAMPLES / name, destination)
    return destination


def _ask(tmp_path: Path, model: Any, name: str = "chained-summarizer") -> RunResult:
    return load_workflow(_package(tmp_path, name), model=model).ask("Summarise the release notes.")


class TestTheLibraryDoorCarriesWhatTheRunSpent:
    """The door the ticket names first, and the one every other door reads."""

    def test_a_run_reports_tokens_per_model(self, tmp_path: Path) -> None:
        result = _ask(tmp_path, Metered("scripted-model-a", inp=100, out=10))
        assert result.usage == {
            "scripted-model-a": {"input_tokens": 200, "output_tokens": 20, "total_tokens": 220}
        }

    def test_the_total_is_a_whole_number_across_every_model(self, tmp_path: Path) -> None:
        result = _ask(tmp_path, Metered("scripted-model-a", inp=100, out=10))
        assert result.total_tokens == 220

    def test_two_models_on_one_run_stay_apart(self, tmp_path: Path) -> None:
        """Per-model, never one summed integer: the paid step is the one a
        reader wants named, and a total cannot name it."""
        result = _ask(tmp_path, TwoModels("scripted-model-a", inp=100, out=10), "evaluator-optimizer")
        assert set(result.usage) == {"scripted-model-a", "scripted-grader"}
        assert result.usage["scripted-grader"]["input_tokens"] == 40
        assert result.total_tokens == sum(
            row["total_tokens"] for row in result.usage.values()
        )


class TestSilenceIsUnknownAndNeverZero:
    """`CLAUDE.md`: never put a non-finite number in a serialisable field, and
    `int | None` with `None` meaning unbounded/unknown. `0` is a claim that a
    run was free; a provider that reports nothing has made no such claim."""

    def test_a_model_that_reports_nothing_leaves_usage_empty(self, tmp_path: Path) -> None:
        result = _ask(tmp_path, Metered("quiet-model", report=False))
        assert result.usage == {}

    def test_and_the_total_is_none_rather_than_zero(self, tmp_path: Path) -> None:
        result = _ask(tmp_path, Metered("quiet-model", report=False))
        assert result.total_tokens is None
        assert result.total_tokens != 0

    def test_a_hand_built_run_result_defaults_to_unknown(self) -> None:
        assert RunResult("hello").usage == {}
        assert RunResult("hello").total_tokens is None

    def test_a_zero_that_a_provider_actually_reported_is_kept(self) -> None:
        """The inverse of the rule, and it must not be swallowed: a provider
        that genuinely reports `0` has said something, and `0` is that."""
        result = RunResult("hi", usage={"m": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}})
        assert result.total_tokens == 0


class TestUsageSurvivesThePickleTheRestOfTheRunSurvives:
    def test_a_round_trip_keeps_the_figures(self, tmp_path: Path) -> None:
        import pickle

        result = _ask(tmp_path, Metered("scripted-model-a", inp=100, out=10))
        assert pickle.loads(pickle.dumps(result)).usage == result.usage

    def test_an_older_five_field_pickle_still_loads(self) -> None:
        """`_rebuild`'s trailing arguments are optional so a `RunResult`
        pickled before this field still unpickles — as unknown, not as zero."""
        from openstategraph.results import _rebuild

        old = _rebuild("hi", {}, {}, [], 0)
        assert old.usage == {}
        assert old.total_tokens is None


class TestNothingAboutCostMovesAnExitCode:
    """`bc58fc1`'s lesson. Tokens are a report, never a verdict: `failures` is
    the only channel `cli.run_exit_code` reads, and spending is not failing."""

    def test_a_metered_run_still_exits_zero(self, tmp_path: Path) -> None:
        from openstategraph.cli import run_exit_code

        result = _ask(tmp_path, Metered("scripted-model-a", inp=999999, out=999999))
        assert result.failures == []
        assert run_exit_code(result) == 0

    def test_usage_is_not_a_warning(self, tmp_path: Path) -> None:
        result = _ask(tmp_path, Metered("scripted-model-a"))
        assert not any("token" in w.lower() for w in result.warnings)


class TestTheCliJsonDoorPrintsIt:
    def test_run_json_carries_the_usage_block(
        self, tmp_path: Path, capsys: Any, monkeypatch: Any
    ) -> None:
        from openstategraph import cli

        package = _package(tmp_path, "chained-summarizer")
        model = Metered("scripted-model-a", inp=100, out=10)
        monkeypatch.setattr(cli, "_load", lambda args, **kw: load_workflow(package, model=model))
        code = cli.main(["run", str(package), "Summarise the release notes.", "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["usage"] == {
            "scripted-model-a": {"input_tokens": 200, "output_tokens": 20, "total_tokens": 220}
        }
        assert payload["total_tokens"] == 220

    def test_a_quiet_provider_prints_null_not_zero(
        self, tmp_path: Path, capsys: Any, monkeypatch: Any
    ) -> None:
        from openstategraph import cli

        package = _package(tmp_path, "chained-summarizer")
        model = Metered("quiet-model", report=False)
        monkeypatch.setattr(cli, "_load", lambda args, **kw: load_workflow(package, model=model))
        cli.main(["run", str(package), "Summarise the release notes.", "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["usage"] == {}
        assert payload["total_tokens"] is None


def _dataset() -> EvalDataset:
    return EvalDataset(
        name="two-questions",
        database="chinook.db",
        # Refusal cases, so grading never opens a database: this suite is
        # about the cost row, and a missing fixture file must not be able to
        # make it fail for an unrelated reason.
        cases=[
            EvalCase(id="q1", question="one?", expects="refusal"),
            EvalCase(id="q2", question="two?", expects="refusal"),
        ],
    )


class TestTheScorecardsCostRowReportsMeasuredTokens:
    """`NO_COST_SIGNAL` retires. What replaces it is narrower and true: tokens
    are measured; a dollar figure still is not, because prices live in no file
    this repository owns."""

    def _card(self, usage: Any) -> Any:
        from openstategraph.evaluation.runner import AskOutcome

        def ask(case: EvalCase) -> AskOutcome:
            return AskOutcome(answer="I cannot answer that.", outputs={}, usage=dict(usage))

        return evaluate(_dataset(), ask, database=Path("chinook.db"))

    def test_tokens_are_summed_across_the_dataset_per_model(self) -> None:
        card = self._card({"m1": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}})
        assert card.cost["tokens"] == {
            "m1": {"input_tokens": 20, "output_tokens": 4, "total_tokens": 24}
        }
        assert card.cost["total_tokens"] == 24

    def test_the_rendered_cost_row_prints_the_number(self) -> None:
        card = self._card({"m1": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}})
        row = next(line for line in card.render().splitlines() if line.startswith("cost"))
        assert "24" in row
        assert "not available" not in row

    def test_no_dollar_figure_is_invented(self) -> None:
        card = self._card({"m1": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}})
        assert card.cost["usd"] is None

    def test_a_dataset_no_model_metered_still_says_so(self) -> None:
        card = self._card({})
        assert card.cost["tokens"] == {}
        assert card.cost["total_tokens"] is None
        assert card.cost["note"] == NO_USAGE_REPORTED

    def test_the_live_asker_carries_usage_off_the_run(self, tmp_path: Path) -> None:
        """The seam that makes the row real: `package_asker` reads the door."""
        workflow = load_workflow(
            _package(tmp_path, "chained-summarizer"),
            model=Metered("scripted-model-a", inp=100, out=10),
        )
        outcome = package_asker(workflow)(_dataset().cases[0])
        assert outcome.usage == {
            "scripted-model-a": {"input_tokens": 200, "output_tokens": 20, "total_tokens": 220}
        }
