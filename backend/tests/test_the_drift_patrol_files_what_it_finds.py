"""The daily patrol turns a red library-contract test into a card.

**Why this exists, and why it is not the weekly docs-watch.** A scheduled job
already fingerprints the vendor's documentation pages and reports when one
changes. It could not have found the defect that created this map, and the
reason is the whole argument: **nothing changed**. LangGraph has refused a
timeout on a synchronous node since 1.2, the fact was already pinned in
`test_a_library_default_is_never_literalised.py`, and two other places in this
repository went on contradicting it for a release. A watcher pointed at the
vendor is blind to a contradiction that lives inside our own tree.

So this patrol asserts **our code against the installed library**, daily,
against a dependency resolve with no lockfile — which is what a new user's
install would give them. A version string moving is not a finding. A test going
red is.

**The corpus is a marker, not a directory.** A library fact belongs beside the
code that depends on it, so these tests are spread across the suite on purpose
and `-m library_contract` is the only thing that gathers them. That is "extend
by registering" one level down: the corpus grows by marking a test, never by
editing the runner. It also means a renamed marker would make the patrol
vacuously green, which is why the floor below is asserted separately.

`langchain-drift-watch` 05.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "library_drift_patrol.py"

JUNIT_ONE_FAILURE = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" errors="0" failures="1" skipped="0" tests="2">
    <testcase classname="backend.tests.test_x" name="test_that_passed" time="0.01"/>
    <testcase classname="backend.tests.test_x" name="test_that_failed" time="0.02">
      <failure message="AssertionError: the library moved">assert 1 == 2
        the second line is not the summary</failure>
    </testcase>
  </testsuite>
</testsuites>
"""


def _patrol():
    """The script, imported as a module rather than run as a subprocess."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("library_drift_patrol", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["library_drift_patrol"] = module
    spec.loader.exec_module(module)
    return module


def test_the_drift_corpus_is_not_empty() -> None:
    """A renamed marker must not make the patrol vacuously green.

    The floor is deliberately low and the assertion is on the *count*, not on
    the names: naming them here would be a second list to keep in step with the
    markers, which is the defect this whole map is about.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "backend/tests", "-m", "library_contract",
         "--collect-only", "-q", "-p", "no:randomly"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout[-2000:]
    collected = [
        line for line in result.stdout.splitlines() if "::" in line and "test" in line
    ]
    assert len(collected) >= 8, (
        f"only {len(collected)} tests carry the library_contract marker; the "
        "patrol gathers exactly these, so a dropped marker is a silent hole"
    )


def test_a_failure_becomes_one_card_with_a_stable_id(tmp_path: pathlib.Path) -> None:
    patrol = _patrol()
    report = tmp_path / "junit.xml"
    report.write_text(JUNIT_ONE_FAILURE, encoding="utf-8")

    versions = {"langgraph": "1.2.10", "langchain": "1.3.14"}
    cards = patrol.cards_for(report, versions=versions, sha="abc1234", project_id="p1")

    assert len(cards) == 1, "one failure, one card — the passing test is not news"
    card = cards[0]
    assert card["task_id"].startswith("p1:drift:")
    assert card["kind"] == "bug"
    assert card["priority"] == "high"
    # The versions are in the card, because "measured on the installed version"
    # is worthless without saying which.
    assert "1.2.10" in card["priority_reason"]
    assert "the library moved" in card["priority_reason"]
    assert "abc1234" in card["priority_reason"]
    # Ours, never a platform gap — the report door would refuse it by name.
    assert card["gap_evidence"] == ""

    again = patrol.cards_for(report, versions=versions, sha="abc1234", project_id="p1")
    assert again[0]["task_id"] == card["task_id"], "the id must survive a second run"


def test_a_green_run_files_nothing(tmp_path: pathlib.Path) -> None:
    patrol = _patrol()
    report = tmp_path / "junit.xml"
    report.write_text(
        JUNIT_ONE_FAILURE.replace(
            '<failure message="AssertionError: the library moved">assert 1 == 2\n'
            "        the second line is not the summary</failure>",
            "",
        ).replace('failures="1"', 'failures="0"'),
        encoding="utf-8",
    )

    assert patrol.cards_for(report, versions={}, sha="", project_id="p1") == []


def test_filing_twice_files_once(tmp_path: pathlib.Path) -> None:
    """`read_card` first, exactly as `patrol.run_patrol` does.

    A patrol that refiled every day would bury the board it is meant to inform.
    """
    patrol = _patrol()
    report = tmp_path / "junit.xml"
    report.write_text(JUNIT_ONE_FAILURE, encoding="utf-8")
    cards = patrol.cards_for(report, versions={}, sha="s", project_id="p1")

    class Store:
        def __init__(self) -> None:
            self.filed: list[str] = []

        def read_card(self, task_id: str):
            if task_id not in self.filed:
                raise KeyError(task_id)
            return object()

        def file_card(self, **kwargs) -> None:
            self.filed.append(kwargs["task_id"])

    store = Store()
    first = patrol.file_cards(store, cards)
    second = patrol.file_cards(store, cards)

    assert first == (1, 0), "the first run files it"
    assert second == (0, 1), "the second run skips it"
    assert len(store.filed) == 1


def test_without_a_board_url_it_refuses_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """A patrol that cannot file what it finds should not run at all.

    This repository already has one scheduled job that fails silently every
    week and is mistaken for one that passes. The refusal names the variable so
    the fix is in the message rather than in somebody's memory.
    """
    patrol = _patrol()
    monkeypatch.delenv("OPENSTATEGRAPH_KANBAN_URL", raising=False)

    with pytest.raises(SystemExit) as raised:
        patrol.main(["--no-run"])

    assert raised.value.code == 2, "a patrol that could not file is not a pass"


def test_the_workflow_checks_its_credential_before_installing_anything() -> None:
    """The lesson from the scheduled job that fails every week.

    `openwiki-update.yml` fires on a schedule and has never once succeeded,
    because the secret it needs is not set. It discovers that *after* doing its
    work. This one refuses in its first step, so a misconfiguration costs
    seconds and says what to set.
    """
    workflow = REPO_ROOT / ".github" / "workflows" / "library-drift.yml"
    assert workflow.exists(), "the daily patrol has no workflow"

    text = workflow.read_text(encoding="utf-8")
    assert "schedule:" in text and "cron:" in text
    assert "workflow_dispatch:" in text, "a maintainer must be able to run it by hand"
    assert "contents: read" in text, "the patrol writes nothing to this repository"
    assert "OPENSTATEGRAPH_KANBAN_URL" in text

    # The *step*, not the string. An earlier version of this assertion matched
    # the first occurrence of the variable name, which is the `env:` line and
    # precedes everything — so deleting the whole check step left it green.
    # A test that cannot fail is worse than no test: it is a claim with a tick
    # beside it.
    steps = text.split("- name:")
    guard = [s for s in steps if "exit 1" in s and "OPENSTATEGRAPH_KANBAN_URL" in s]
    assert guard, "no step refuses when the board credential is absent"

    installs = [i for i, s in enumerate(steps) if "pip install" in s]
    guard_at = steps.index(guard[0])
    assert installs, "the workflow installs nothing"
    assert guard_at < min(installs), (
        "the credential is checked after installing — the openwiki failure mode"
    )


def test_the_resolve_is_deliberately_unlocked() -> None:
    """It must see what a *new* install sees, not what our lockfile pins.

    Reading the lock would answer a question nobody asked: whether the versions
    we recorded still pass. The question is whether the versions a user would
    get today still pass.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "library-drift.yml").read_text(
        encoding="utf-8"
    )

    # The *behaviour*, not the word: an earlier draft of this test banned the
    # string, and the comment in the workflow explaining why the lock is not
    # read duly failed it. A gate that forbids naming the thing it forbids
    # punishes the explanation and rewards silence.
    commands = [
        line for line in workflow.splitlines() if line.strip() and not line.strip().startswith("#")
    ]
    installs_from_the_lock = [
        line for line in commands if "uv.lock" in line or "uv sync" in line or "--locked" in line
    ]
    assert installs_from_the_lock == [], installs_from_the_lock
    assert any("pip install -e" in line for line in commands), "it installs nothing"


def test_an_empty_corpus_is_a_refusal_not_a_pass(tmp_path: pathlib.Path) -> None:
    """The hole a reviewer found: a renamed marker made the patrol green.

    pytest exits 5 for "nothing matched" and writes a report with `tests="0"`,
    which has no failures in it — so the patrol printed `0 failure(s)` and
    exited 0 while having checked nothing at all. That is the failure mode this
    repository already has one live example of: a scheduled job that reads in a
    run list exactly like one that passes.

    The floor test above cannot close it, because that runs in CI rather than
    inside the patrol.
    """
    patrol = _patrol()
    empty = tmp_path / "empty.xml"
    empty.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<testsuites><testsuite name="pytest" errors="0" failures="0" '
        'skipped="0" tests="0"/></testsuites>\n',
        encoding="utf-8",
    )

    # Either signal alone is enough: pytest's own code, or the report's count.
    assert patrol.ran_nothing(empty, 5) is True
    assert patrol.ran_nothing(empty, 0) is True

    populated = tmp_path / "junit.xml"
    populated.write_text(JUNIT_ONE_FAILURE, encoding="utf-8")
    assert patrol.ran_nothing(populated, 1) is False

    # And a report that was never written is not silently "nothing failed".
    assert patrol.ran_nothing(tmp_path / "absent.xml", 0) is True
