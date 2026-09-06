"""`team-board-and-gap-reports/08`. The door a refusal can point at.

A user places a card the editor offers, presses run, and is told this runtime
has no implementation for it. That refusal already knows the type id — it is
exactly the report we want — and until this ticket the next step it offered was
nothing: open a browser, find the repository, find the form, and retype from
memory what the terminal already had in its hand.

The owner's decision (`OWNER-DECISIONS.md`) is that **GitHub is the user's
door**, filed under the user's own `gh` login, opt-in per send, with the exact
payload shown first. So the three properties this file holds open are:

- **Nothing is sent that a person did not confirm in the same run.** A run
  without `--yes` reaches no subprocess at all, and the fake `gh` on `PATH`
  records every argv it is handed, so "it did not send" is measured rather
  than asserted.
- **No credential of ours is anywhere near it.** The door reads no `.env`, no
  `OPENSTATEGRAPH_*` key, and hands `gh` nothing but the issue the user just
  read. `gh` brings the user's own credentials; we bring none.
- **A refusal names a next step.** No `gh`, or a `gh` nobody has logged in,
  prints the report and says how to file it by hand — never a traceback, which
  is `docs-onramp/09`'s rule at the door it was written for.

The fake `gh` matters for a fourth reason: a real one on the runner would file
a real issue on a public repository the first time this suite ran.
"""

from __future__ import annotations

import ast
import contextlib
import io
import stat
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from openstategraph import cli
from openstategraph.config_file import render_config_file, reset_active_config
from openstategraph.document_checks import FindingClass
from openstategraph.gap_report import GapDoor, GapKind, GapReport, hashed_project_id
from openstategraph.gap_report_door import (
    DoorClosed,
    LABEL,
    UnreportableSubject,
    build_report,
    file_issue,
    issue_body,
    issue_title,
    repository,
)
from openstategraph.github_issue_bridge import FIELD_LABELS, parse_issue_form
from openstategraph.kanban_store import kanban_store_path

PACKAGE = Path(__file__).resolve().parents[1] / "openstategraph"

A_TYPE = "tool.reddit-search"
A_PROJECT = "11111111-2222-3333-4444-555555555555"


def a_report(**overrides: object) -> GapReport:
    return build_report(
        str(overrides.pop("subject", A_TYPE)),
        project_hash=hashed_project_id(A_PROJECT),
        **overrides,  # type: ignore[arg-type]
    )


@pytest.fixture
def fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A `gh` that records its argv and answers like a logged-in one.

    On `PATH` and nowhere else: `shutil.which` finds this and never the real
    binary, which on a maintainer's laptop is logged in to a real account.
    """
    return _install_gh(tmp_path, monkeypatch, script=_RECORDING)


@pytest.fixture
def a_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    config = tmp_path / "openstategraph.yaml"
    config.write_text(render_config_file(project_id=A_PROJECT))
    monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(config))
    reset_active_config()
    yield tmp_path
    reset_active_config()


_RECORDING = """#!{python}
import json, os, sys
with open(os.environ["GH_ARGV_LOG"], "a") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:2] == ["auth"]:
    sys.exit(0)
print("https://github.com/owner/repo/issues/1")
"""

_LOGGED_OUT = """#!{python}
import json, os, sys
with open(os.environ["GH_ARGV_LOG"], "a") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
sys.stderr.write("You are not logged into any GitHub hosts.\\n")
sys.exit(1)
"""


def _install_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, script: str) -> Path:
    home = tmp_path / "fake-bin"
    home.mkdir(exist_ok=True)
    executable = home / "gh"
    # The shebang names this interpreter by absolute path: `PATH` below
    # holds nothing but this directory, so `/usr/bin/env python3` would
    # find no python — and an unrunnable fake is a `gh` that refuses for
    # a reason no test meant to arrange.
    executable.write_text(script.format(python=sys.executable))
    executable.chmod(executable.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    log = tmp_path / "gh-argv.jsonl"
    monkeypatch.setenv("GH_ARGV_LOG", str(log))
    monkeypatch.setenv("PATH", str(home))
    return log


def _calls(log: Path) -> list[list[str]]:
    import json

    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


# --------------------------------------------------------------------------
# What a report is built from


class TestTheSubjectIsATypeId:
    """The archetypal platform gap, and the one thing a refusal already
    carries: the type id this runtime has no implementation for."""

    def test_it_builds_a_no_backend_report(self) -> None:
        report = a_report()
        assert report.kind is GapKind.NO_BACKEND
        assert report.type_ids == (A_TYPE,)
        assert report.check == FindingClass.NO_BACKEND.value
        assert A_TYPE in report.refusal.text

    def test_the_door_is_where_the_user_was_standing(self) -> None:
        assert a_report(door=GapDoor.EDITOR).door is GapDoor.EDITOR
        assert a_report().door is GapDoor.CLI

    def test_a_question_is_not_a_subject(self) -> None:
        """The model refuses it, and it must reach the model to be refused —
        this door adds no second gate that could disagree with the first."""
        with pytest.raises(ValidationError):
            a_report(subject="which artist sold the most?")

    def test_a_patrol_card_says_why_it_cannot_be_sent(self) -> None:
        """A card records a driver's sentence or a node's own failure, and the
        report allowlist has no field for either. Refused by name, with the
        by-hand path — never a half-built report with somebody's prose in it."""
        with pytest.raises(UnreportableSubject) as raised:
            a_report(subject=f"{A_PROJECT}:thread-7")
        said = str(raised.value)
        assert "type id" in said
        assert repository() in said


# --------------------------------------------------------------------------
# The issue, and the one place its address comes from


class TestTheRepositoryIsDerivedOnce:
    def test_it_comes_from_the_packages_own_metadata(self) -> None:
        from importlib.metadata import metadata

        urls = dict(
            entry.split(", ", 1) for entry in metadata("openstategraph").get_all("Project-URL")
        )
        assert repository() == urls["Repository"].rsplit("github.com/", 1)[1]

    def test_the_module_hard_codes_no_second_copy(self) -> None:
        source = (PACKAGE / "gap_report_door.py").read_text(encoding="utf-8")
        # The bare name is also the *package* name (`stable-beta-public/34`
        # pointed `Homepage` at zulfeekar/openstategraph), so every import
        # line would match it; the second copy this guards against is the
        # slug, which no import ever spells.
        slug = repository()
        assert slug not in source and f"github.com/{slug}" not in source, (
            "the repository name is written down twice — derive it from the "
            "package metadata, which is generated from pyproject"
        )
        assert owner not in source


class TestTheIssueBodyIsTheReport:
    def test_every_field_is_under_the_templates_own_label(self) -> None:
        """The body is what a hand-filled form produces, so an issue this door
        files and an issue a user types land as the same card
        (`team-board-and-gap-reports/05`'s bridge parses both)."""
        report = a_report()
        parsed = parse_issue_form(issue_body(report))
        assert parsed["version"] == report.version
        assert parsed["kind"] == report.kind.value
        assert parsed["type_ids"] == A_TYPE
        assert parsed["door"] == report.door.value
        assert parsed["refusal"] == report.refusal.text
        assert parsed["project_hash"] == report.project_hash

    def test_it_carries_nothing_the_report_does_not(self) -> None:
        report = a_report()
        sent = report.model_dump(mode="json")
        allowed = {report.refusal.text, report.refusal.source.value} | {
            str(value) for value in sent.values() if isinstance(value, str)
        }
        allowed |= set(report.type_ids) | set(FIELD_LABELS.values())
        for line in issue_body(report).splitlines():
            stripped = line.strip().lstrip("#").strip()
            assert not stripped or stripped in allowed, stripped

    def test_the_title_says_what_refused(self) -> None:
        title = issue_title(a_report())
        assert title.startswith("[gap]: ")
        assert A_TYPE in title


# --------------------------------------------------------------------------
# The send, and the two ways it does not happen


class TestNothingIsSentWithoutSaying(object):
    def test_a_plain_run_prints_the_report_and_reaches_no_subprocess(
        self, a_project: Path, fake_gh: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = cli.main(["report", A_TYPE])
        printed = capsys.readouterr().out
        assert code == cli.EXIT_OK
        assert "This is the whole report. Nothing else is sent." in printed
        assert A_TYPE in printed
        assert "--yes" in printed
        assert _calls(fake_gh) == []

    def test_the_report_is_printed_before_gh_is_reached(
        self, a_project: Path, fake_gh: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ordering, not just presence: *shown before sending* is the owner's
        decision, and a door that sends first and prints after would pass every
        assertion about what appears on the screen."""
        seen: list[str] = []
        page = io.StringIO()
        real = subprocess.run

        def watching(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            seen.append(page.getvalue())
            return real(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(subprocess, "run", watching)
        with contextlib.redirect_stdout(page):
            cli.main(["report", A_TYPE, "--yes"])
        assert seen, "gh was never called"
        assert "This is the whole report." in seen[0]

    def test_yes_files_the_issue_under_the_users_own_gh(
        self, a_project: Path, fake_gh: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = cli.main(["report", A_TYPE, "--yes"])
        printed = capsys.readouterr().out
        assert code == cli.EXIT_OK
        calls = _calls(fake_gh)
        assert calls[0][:2] == ["auth", "status"]
        create = calls[-1]
        assert create[:2] == ["issue", "create"]
        assert create[create.index("--repo") + 1] == repository()
        assert create[create.index("--label") + 1] == LABEL
        assert parse_issue_form(create[create.index("--body") + 1])["type_ids"] == A_TYPE
        assert "https://github.com/owner/repo/issues/1" in printed

    def test_nothing_of_ours_is_passed_to_gh(
        self, a_project: Path, fake_gh: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The argv is the report and the flags, and nothing else. A door that
        helpfully forwarded a key would pass every other test here."""
        monkeypatch.setenv("OPENSTATEGRAPH_KANBAN_URL", "postgresql://user:secret@host/db")
        cli.main(["report", A_TYPE, "--yes"])
        flat = " ".join(word for call in _calls(fake_gh) for word in call)
        assert "secret" not in flat
        assert "OPENSTATEGRAPH" not in flat

    def test_the_door_reads_no_credential_of_ours(self) -> None:
        """Structural: the module names no `.env`, no `OPENSTATEGRAPH_*` key
        and no dotenv reader, so there is no path by which one could travel."""
        source = (PACKAGE / "gap_report_door.py").read_text(encoding="utf-8")
        assert "OPENSTATEGRAPH_" not in source
        assert ".env" not in source
        tree = ast.parse(source)
        imported = {
            (node.module or "").split(".")[-1]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert "dotenv" not in imported
        reads = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv"}
        ]
        assert reads == []


class TestARefusalNamesTheNextStep:
    def test_no_gh_at_all(
        self, a_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        code = cli.main(["report", A_TYPE, "--yes"])
        printed = capsys.readouterr().out
        assert code == cli.EXIT_FAILURE
        assert "This is the whole report." in printed, "the report is still shown"
        assert "gh auth login" in printed
        assert f"github.com/{repository()}" in printed
        assert "Traceback" not in printed

    def test_a_gh_nobody_has_logged_in(
        self, a_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log = _install_gh(tmp_path, monkeypatch, script=_LOGGED_OUT)
        code = cli.main(["report", A_TYPE, "--yes"])
        printed = capsys.readouterr().out
        assert code == cli.EXIT_FAILURE
        assert "gh auth login" in printed
        assert [call[:2] for call in _calls(log)] == [["auth", "status"]], (
            "a logged-out gh must not be asked to create anything"
        )

    def test_the_second_door_is_named_as_what_it_is(self) -> None:
        """`09`'s keyless door exists and is off until an install names an
        endpoint. Naming it as available would be a promise the install in
        front of the user cannot keep; not naming it at all leaves somebody who
        will never have `gh` believing the form is the only other path."""
        with pytest.raises(DoorClosed) as raised:
            file_issue(a_report(), executable=None)
        said = str(raised.value)
        assert "keyless door" in said
        assert "off unless your install names an endpoint" in said

    def test_a_project_with_no_id_says_which_command_mints_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = tmp_path / "openstategraph.yaml"
        config.write_text("version: 1\nworkflows_dir: workflows\n")
        monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(config))
        reset_active_config()
        try:
            code = cli.main(["report", A_TYPE])
            captured = capsys.readouterr()
            printed = captured.out + captured.err
            assert code == cli.EXIT_FAILURE
            assert "openstategraph init" in printed
        finally:
            reset_active_config()


# --------------------------------------------------------------------------
# The sentence that offers the door, where the user actually is


def test_a_no_backend_refusal_names_the_command() -> None:
    """One copy owner (`document_checks.no_backend_implementation`), so every
    door that prints that finding offers the report without a second sentence
    to keep in step."""
    from openstategraph.document_checks import CheckContext, no_backend_implementation
    from openstategraph.compile.node_catalogue import CATALOGUE

    editor_only = sorted(CATALOGUE.editor_only)
    assert editor_only, "nothing is marked editor-only, so this check cannot fire"
    context = CheckContext(
        document={"nodes": {"n1": {"type": editor_only[0]}}},
        workflows_root=None,
        nodes={"n1": {"type": editor_only[0]}},
    )
    findings = list(no_backend_implementation(context))
    assert findings, "the check no longer fires on an editor-only card"
    assert "openstategraph report" in findings[0].message


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))


# --------------------------------------------------------------------------
# A patrol finding, as a report — `team-board-and-gap-reports/15`


class TestWhichOfTheTwoAnswersShipped:
    """`15` asked a judgement: is a run failure a platform gap at all?

    **Both, split by who wrote the sentence.** The gap is real and reportable —
    a tool type this install cannot reach is exactly the thing maintainers want
    to hear about — and the driver's own words are not, because
    `ToolResult.failure` carries whatever the tool was handed: an ODBC message,
    a vendor's prose, and (via `Invalid arguments: …`) the model's own
    arguments. So a finding is admitted as a **fourth refusal source** and the
    text it contributes is one of two shapes, both ours: this codebase's own
    sentence for that finding kind, or an exception line naming a class
    `openstategraph.errors` defines, which is what `Refusal.for_our_exception`
    already accepts from a live exception.

    `07`'s guarantee is therefore unwidened: there is still no way to put text
    a model or a vendor wrote into a `Refusal`.
    """

    def test_a_drivers_own_words_are_not_carried(self) -> None:
        from openstategraph.gap_report import Refusal, RefusalSource
        from openstategraph.run_findings import EVERY_TOOL_CALL_FAILED

        refusal = Refusal.for_finding(
            EVERY_TOOL_CALL_FAILED,
            "Error: ('HYT00', '[Microsoft][ODBC Driver 18]Login timeout expired')",
        )

        assert refusal.source is RefusalSource.FINDING
        assert "ODBC" not in refusal.text
        assert "HYT00" not in refusal.text
        assert "refused" in refusal.text

    def test_our_own_error_survives_as_itself(self) -> None:
        """The subset `15` named: a tool that raised one of *our* errors put a
        sentence we wrote on the finding, and that one is worth carrying."""
        from openstategraph.gap_report import Refusal, RefusalSource
        from openstategraph.run_findings import NODE_FAILURE

        refusal = Refusal.for_finding(
            NODE_FAILURE, "Error: MissingProviderKey: openai has no credential — set OPENAI_API_KEY"
        )

        assert refusal.source is RefusalSource.FINDING
        assert refusal.text.startswith("MissingProviderKey: ")
        assert "OPENAI_API_KEY" in refusal.text

    def test_a_foreign_exception_line_falls_back_to_our_sentence(self) -> None:
        """`OperationalError` is psycopg's, not ours, and its message is the
        statement it was given — which is the customer's SQL."""
        from openstategraph.gap_report import Refusal
        from openstategraph.run_findings import NODE_FAILURE

        refusal = Refusal.for_finding(
            NODE_FAILURE, "Error: OperationalError: SELECT name FROM customers"
        )

        assert "customers" not in refusal.text
        assert "SELECT" not in refusal.text

    def test_a_round_trip_cannot_widen_it(self) -> None:
        """The validator re-checks, so a stored evidence row someone edited by
        hand is refused rather than sent — which is the property that makes it
        safe for the card store to hold the finding's raw text."""
        from openstategraph.gap_report import Refusal, RefusalSource

        with pytest.raises(ValidationError):
            Refusal(source=RefusalSource.FINDING, text="Sure! Here is the table")  # type: ignore[call-arg]
        with pytest.raises(ValidationError):
            Refusal(  # type: ignore[call-arg]
                source=RefusalSource.FINDING,
                text="OperationalError: SELECT name FROM customers",
            )

    def test_an_unreportable_finding_is_refused_by_name(self) -> None:
        from openstategraph.gap_report import Refusal
        from openstategraph.run_findings import REDUNDANT_TOOL_CALL

        with pytest.raises(ValueError) as raised:
            Refusal.for_finding(REDUNDANT_TOOL_CALL, "Error: anything")
        assert REDUNDANT_TOOL_CALL in str(raised.value)


class TestACardThePatrolFiledCanBeReported:
    """The door `08` could not build, now that a card records the finding."""

    def _store(self, tmp_path: Path):
        from openstategraph.kanban_sqlite import SqliteKanbanStore

        return SqliteKanbanStore(tmp_path / "kanban.sqlite")

    def test_the_patrol_records_the_findings_type_ids_and_hash(self) -> None:
        import json

        from openstategraph.patrol import finding_evidence
        from openstategraph.run_findings import EVERY_TOOL_CALL_FAILED, RunFinding

        evidence = json.loads(
            finding_evidence(
                RunFinding(
                    name=EVERY_TOOL_CALL_FAILED,
                    tool="mssql_query",
                    arguments="Error: AADSTS7000222: the client secret is expired",
                    calls=3,
                ),
                project_hash=hashed_project_id(A_PROJECT),
            )
        )

        assert evidence["finding"] == EVERY_TOOL_CALL_FAILED
        assert evidence["type_ids"] == ["tool.mssql-query"]
        assert len(evidence["finding_hash"]) == 12

    def test_waste_records_nothing_because_it_is_not_a_gap(self) -> None:
        from openstategraph.patrol import finding_evidence
        from openstategraph.run_findings import REDUNDANT_TOOL_CALL, RunFinding

        assert (
            finding_evidence(
                RunFinding(name=REDUNDANT_TOOL_CALL, tool="mssql_query", calls=9),
                project_hash=hashed_project_id(A_PROJECT),
            )
            == ""
        )

    def test_a_card_with_a_finding_builds_a_report(self, tmp_path: Path) -> None:
        import json

        from openstategraph.gap_report_door import report_for_card
        from openstategraph.patrol import finding_evidence
        from openstategraph.run_findings import EVERY_TOOL_CALL_FAILED, RunFinding

        store = self._store(tmp_path)
        project_hash = hashed_project_id(A_PROJECT)
        evidence = finding_evidence(
            RunFinding(
                name=EVERY_TOOL_CALL_FAILED,
                tool="mssql_query",
                arguments="Error: Azure AD refused: AADSTS7000222: the secret is expired",
                calls=3,
            ),
            project_hash=project_hash,
        )
        store.file_card(
            task_id=f"{A_PROJECT}:refusal:abc123abc123",
            board="workflows",
            kind="bug",
            category="bug",
            title="Every mssql_query call in this run was refused the same way",
            gap_evidence=evidence,
        )

        report = report_for_card(
            store.read_card(f"{A_PROJECT}:refusal:abc123abc123"),
            project_hash=project_hash,
        )

        assert report.kind is GapKind.EVERY_TOOL_CALL_FAILED
        assert report.type_ids == ("tool.mssql-query",)
        assert report.check == EVERY_TOOL_CALL_FAILED
        assert report.aad_code == "AADSTS7000222"
        assert report.finding_hash == json.loads(evidence)["finding_hash"]

    def test_a_hand_filed_card_is_still_refused_by_name(self, tmp_path: Path) -> None:
        """`08`'s refusal, kept for the card it was always right about: a card
        somebody typed has a person's prose on it and no finding behind it."""
        from openstategraph.gap_report_door import report_for_card

        store = self._store(tmp_path)
        store.file_card(
            task_id=f"{A_PROJECT}:idea-a-nicer-palette",
            board="workflows",
            kind="task",
            category="gap",
            title="A nicer palette",
        )

        with pytest.raises(UnreportableSubject) as raised:
            report_for_card(
                store.read_card(f"{A_PROJECT}:idea-a-nicer-palette"),
                project_hash=hashed_project_id(A_PROJECT),
            )
        said = str(raised.value)
        assert f"{A_PROJECT}:idea-a-nicer-palette" in said
        assert repository() in said

    def test_an_older_store_gains_the_column(self, tmp_path: Path) -> None:
        """`kanban-patrol/26`'s repair loop, on the column this ticket adds."""
        import sqlite3

        store = self._store(tmp_path)
        store.file_card(
            task_id="proj:one", board="workflows", kind="bug", category="bug", title="One"
        )
        conn = sqlite3.connect(store.path)
        try:
            conn.execute("ALTER TABLE cards DROP COLUMN gap_evidence")
            conn.commit()
        finally:
            conn.close()

        assert store.read_card("proj:one").gap_evidence == ""

    def test_the_board_does_not_publish_the_evidence(self, tmp_path: Path) -> None:
        """`card_row` is what the two *board* doors publish, and a finding hash
        is not a thing a reader of a card reads. The report door reads the card
        itself, from the store it already opened."""
        from openstategraph.kanban_store import card_row

        store = self._store(tmp_path)
        store.file_card(
            task_id="proj:one", board="workflows", kind="bug", category="bug", title="One"
        )

        assert "gap_evidence" not in card_row(store.read_card("proj:one"), stale=False)


def test_the_cli_reports_a_card_and_sends_nothing(
    tmp_path: Path, a_project: Path, fake_gh: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The verb `08` shipped, on the subject `08` could not take."""
    from openstategraph.kanban_sqlite import SqliteKanbanStore
    from openstategraph.patrol import finding_evidence
    from openstategraph.run_findings import EVERY_TOOL_CALL_FAILED, RunFinding

    root = tmp_path / "workflows"
    root.mkdir()
    store = SqliteKanbanStore(kanban_store_path(root))
    task_id = f"{A_PROJECT}:refusal:0123456789ab"
    store.file_card(
        task_id=task_id,
        board="workflows",
        kind="bug",
        category="bug",
        title="Every mssql_query call in this run was refused the same way",
        gap_evidence=finding_evidence(
            RunFinding(
                name=EVERY_TOOL_CALL_FAILED,
                tool="mssql_query",
                arguments="Error: login timed out",
                calls=4,
            ),
            project_hash=hashed_project_id(A_PROJECT),
        ),
    )

    code = cli.main(["report", task_id, "--workflows-root", str(root)])

    printed = capsys.readouterr().out
    assert code == 0
    assert "tool.mssql-query" in printed
    assert _calls(fake_gh) == []


class _OneRefusedThread:
    """A checkpointer holding one conversation whose every tool call was
    refused the same way — `osg-agent-experience/74`'s shape, small enough to
    live beside the assertion that needs it.

    Written here rather than imported from the patrol's own suite because what
    is being pinned is the **wiring**: that `run_patrol` puts the finding on
    the card it files. Every other case in this file works on the seam
    directly, and a seam that nothing calls is the defect
    `team-board-and-gap-reports/15` was filed against.
    """

    REFUSAL = "Error: ('HYT00', 'Login timeout expired')"

    def __init__(self) -> None:
        from langchain_core.messages import AIMessage, ToolMessage

        messages: list[object] = []
        self._tuples: list[object] = []
        for index in range(2):
            call_id = f"c{index}"
            messages = [
                *messages,
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": call_id,
                            "name": "mssql_query",
                            "args": {"sql": f"SELECT {index}"},
                            "type": "tool_call",
                        }
                    ],
                ),
            ]
            self._tuples.append(self._stub(index * 2, messages))
            messages = [
                *messages,
                ToolMessage(content=self.REFUSAL, tool_call_id=call_id, name="mssql_query"),
            ]
            self._tuples.append(self._stub(index * 2 + 1, messages))
        self._tuples.reverse()

    def _stub(self, step: int, messages: list[object]) -> object:
        return type(
            "_Checkpoint",
            (),
            {
                "config": {"configurable": {"thread_id": "t-1", "checkpoint_ns": ""}},
                "checkpoint": {
                    "id": f"cp-{step}",
                    "ts": f"2026-09-06T09:{step:02d}:00+00:00",
                    "channel_values": {"messages": list(messages)},
                    "updated_channels": ["messages"],
                },
                "metadata": {"step": step, "source": "loop", "workflow_slug": "chinook"},
                "pending_writes": (),
            },
        )()

    def list(self, config: object, *, limit: int = 200) -> list[object]:
        return self._tuples[:limit]


def test_the_patrol_puts_the_finding_on_the_card_it_files(tmp_path: Path) -> None:
    """The wiring, end to end: a refused run becomes a card, and that card can
    be reported without anybody re-reading the run it came from."""
    from openstategraph.gap_report_door import report_for_card
    from openstategraph.kanban_store import open_kanban_store
    from openstategraph.patrol import run_patrol
    from openstategraph.run_sinks import RunRecord

    root = tmp_path / "workflows"
    root.mkdir()
    result = run_patrol(
        project_id=A_PROJECT,
        workflows_root=root,
        savers=[_OneRefusedThread()],
        records=[
            RunRecord(
                thread_id="t-1",
                workflow_slug="chinook",
                at="2026-09-06T09:00:00+00:00",
                seconds=1.0,
            )
        ],
    )

    assert result.filed, "the patrol filed nothing to report"
    card = open_kanban_store(root).read_card(result.filed[0])
    report = report_for_card(card, project_hash=hashed_project_id(A_PROJECT))
    assert report.kind is GapKind.EVERY_TOOL_CALL_FAILED
    assert report.type_ids == ("tool.mssql-query",)
    assert "HYT00" not in report.refusal.text
