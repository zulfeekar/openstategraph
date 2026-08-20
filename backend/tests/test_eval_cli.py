"""`openstategraph eval`, and the harness end to end with a scripted model.

The live eval calls a model, costs money and flakes; it is documented in
`docs/evaluation.md` and deliberately absent from the default test run. What is
tested here is everything around the model: the real `load_workflow` path, the
real SQL execution, the real scorecard, the real exit codes — with
`RespondingModel` standing in for the provider. That is the difference between
a harness that is tested and a harness that is merely run.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from conftest import RespondingModel  # shared test double
from openstategraph.cli import main
from openstategraph.evaluation import Scorecard, default_dataset_path, evaluate_package


def _node(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "data": data, "position": {"x": 0, "y": 0}}


def _edge(src: str, src_port: str, dst: str, dst_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": src_port},
        "target": {"nodeId": dst, "portId": dst_port},
    }


DOCUMENT = {
    "version": 1,
    "name": "tiny-sql",
    "nodes": [
        _node("in1", "input.text"),
        _node("ag1", "agent.llm", systemPrompt="Answer from the database."),
        _node("out1", "output.formatted"),
    ],
    "edges": [_edge("in1", "text", "ag1", "prompt"), _edge("ag1", "result", "out1", "result")],
}


@pytest.fixture()
def package(tmp_path: Path) -> Path:
    """A real workflow package with a real database and a real dataset beside it."""
    directory = tmp_path / "tiny-sql"
    (directory / "evals").mkdir(parents=True)
    (directory / "data").mkdir()
    (directory / "workflow.json").write_text(
        json.dumps({"version": 1, "name": "tiny-sql", "savedAt": "", "document": DOCUMENT})
    )

    db = directory / "data" / "tiny.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE genre (id INTEGER, name TEXT)")
    conn.executemany("INSERT INTO genre VALUES (?, ?)", [(1, "Rock"), (2, "Latin"), (3, "Metal")])
    conn.commit()
    conn.close()

    (directory / "evals" / "tiny.eval.json").write_text(
        json.dumps(
            {
                "name": "tiny",
                "database": "../data/tiny.sqlite",
                "cases": [
                    {
                        "id": "e01",
                        "question": "How many genres are there?",
                        "difficulty": "easy",
                        "gold_sql": "SELECT COUNT(*) AS n FROM genre",
                        "expected": {"columns": ["n"], "rows": [[3]], "row_count": 1},
                    },
                    {
                        "id": "u01",
                        "question": "What is the weather in Berlin?",
                        "difficulty": "easy",
                        "expects": "refusal",
                        "forbidden_patterns": ["degrees"],
                    },
                ],
            }
        )
    )
    return directory


@pytest.fixture()
def scripted() -> RespondingModel:
    return RespondingModel(
        rules=[(lambda context: "genres" in context, "```sql\nSELECT COUNT(id) FROM genre\n```\nThree.")],
        default="I only answer questions about this music store.",
    )


def test_a_package_is_graded_end_to_end_without_a_network(
    package: Path, scripted: RespondingModel
) -> None:
    """The real `load_workflow` seam, the real database, a scripted provider.

    Note what is being proved: the model answered with SQL that does not match
    the gold *string* (`COUNT(id)` vs `COUNT(*)`) and still scores 1.0, because
    the metric is what the query returns.
    """
    scorecard = evaluate_package(package, model=scripted)

    assert scorecard.execution_accuracy == 1.0
    assert scorecard.refusal_accuracy == 1.0
    assert scorecard.overall_accuracy == 1.0
    assert [item.verdict for item in scorecard.items] == ["correct", "refused_correctly"]
    # A real run through the compiler: the agent node counted one attempt.
    assert scorecard.items[0].attempts >= 1


def test_the_dataset_is_found_by_convention(package: Path) -> None:
    assert default_dataset_path(package).name == "tiny.eval.json"


def test_two_datasets_are_not_resolved_by_guessing(package: Path) -> None:
    (package / "evals" / "other.eval.json").write_text("{}")
    with pytest.raises(ValueError, match="--dataset"):
        default_dataset_path(package)


def test_a_package_with_no_dataset_says_so(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="eval.json"):
        default_dataset_path(tmp_path)


def test_the_cli_reports_a_missing_dataset_without_the_exception_class_name(
    package: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`cmd_eval` lets `evaluate_package`'s `FileNotFoundError` reach `main`'s
    catch-all uncaught. The message it prints names the path and the fix
    (ticket 83) — it must not also open with the Python exception's class
    name, which is what happened before that ticket."""
    for dataset in (package / "evals").glob("*.eval.json"):
        dataset.unlink()

    code = main(["eval", str(package)])

    assert code == 1
    err = capsys.readouterr().err
    assert "eval.json" in err
    assert not err.startswith("FileNotFoundError")


def test_limit_stops_early(package: Path, scripted: RespondingModel) -> None:
    scorecard = evaluate_package(package, model=scripted, limit=1)
    assert len(scorecard.items) == 1


# --------------------------------------------------------------------------
# the command


def _stub(monkeypatch: pytest.MonkeyPatch, scorecard: Scorecard) -> dict[str, Any]:
    """Replace the one seam the command wraps, and record what it was passed."""
    seen: dict[str, Any] = {}

    def fake(package_dir: Any, **kwargs: Any) -> Scorecard:
        seen.update({"package": package_dir, **kwargs})
        return scorecard

    monkeypatch.setattr("openstategraph.evaluation.evaluate_package", fake)
    return seen


def _card(items: tuple[Any, ...] = ()) -> Scorecard:
    from openstategraph.evaluation import ItemVerdict

    return Scorecard(
        dataset="tiny",
        database="tiny.sqlite",
        model="scripted",
        items=items
        or (
            ItemVerdict(
                case_id="e01",
                question="How many genres are there?",
                difficulty="easy",
                expects="answer",
                verdict="correct",
                execution_match=True,
                exact_set_match=True,
                sql="SELECT 1",
                seconds=1.0,
                attempts=1,
            ),
            ItemVerdict(
                case_id="e02",
                question="How many tracks?",
                difficulty="easy",
                expects="answer",
                verdict="wrong_result",
                execution_match=False,
                exact_set_match=False,
                sql="SELECT 2",
                seconds=3.0,
                attempts=2,
            ),
        ),
        cost={"usd": None, "note": "not available"},
    )


def test_eval_prints_a_table_and_passes_without_a_threshold(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, _card())
    assert main(["eval", "./pkg"]) == 0
    assert "execution accuracy" in capsys.readouterr().out


def test_eval_exits_one_below_the_threshold(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CI gate. 50% overall against a 0.9 bar is a failed build."""
    _stub(monkeypatch, _card())
    assert main(["eval", "./pkg", "--threshold", "0.9"]) == 1
    assert main(["eval", "./pkg", "--threshold", "0.5"]) == 0


def test_eval_json_is_parseable_and_carries_the_caveats(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, _card())
    assert main(["eval", "./pkg", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["metrics"]["execution_accuracy"] == 0.5
    assert payload["not_measured"]
    assert [item["case_id"] for item in payload["items"]] == ["e01", "e02"]


def test_eval_forwards_its_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _stub(monkeypatch, _card())
    main(["eval", "./pkg", "--dataset", "d.json", "--limit", "3", "--model", "ollama:x"])
    assert seen["package"] == "./pkg"
    assert seen["dataset_path"] == "d.json"
    assert seen["limit"] == 3
    assert seen["model"] == "ollama:x"


def test_progress_goes_to_stderr_so_json_pipes_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = _stub(monkeypatch, _card())
    main(["eval", "./pkg"])
    assert seen["on_item"] is not None
    main(["eval", "./pkg", "--json"])
    assert seen["on_item"] is None
