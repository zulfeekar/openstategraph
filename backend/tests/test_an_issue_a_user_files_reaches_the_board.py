"""An issue a user files reaches the board — `team-board-and-gap-reports/05`.

Six workflows, none of them on `issues`, so a platform gap reached a
maintainer only through a notification email and closing it taught the board
nothing. This test holds the three pieces that fix that, and it holds each one
against something that can move on its own rather than against a list written
here:

* **the template's fields against the report schema** — `docs/gap-report.schema.json`
  is generated from the Pydantic model (`07`), so a field added to the model
  and missing from the template is a red test rather than a report that quietly
  drops it;
* **the workflow's posture against the file** — no checkout, read-only at the
  top, `issues: write` only on the job that writes back, and no issue text
  interpolated into a shell;
* **the bridge against recorded payloads** — the real GitHub is never touched
  here. `apply_event` is pure over a payload and a store, which is the whole
  reason it can be tested at all.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from openstategraph import github_issue_bridge as bridge
from openstategraph.kanban_sqlite import SqliteKanbanStore
from openstategraph.kanban_store import Stage

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / ".github" / "ISSUE_TEMPLATE" / "platform-gap.yml"
WORKFLOW = REPO / ".github" / "workflows" / "issues-to-board.yml"
SCHEMA = REPO / "docs" / "gap-report.schema.json"
CHECKLIST = REPO / "docs" / "maintainers" / "public-repository-settings.md"


def schema() -> dict[str, Any]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def template() -> dict[str, Any]:
    return yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))


def workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def fields() -> list[dict[str, Any]]:
    """Every input the template collects — `markdown` blocks are prose, not
    fields, and carry no id."""
    return [item for item in template()["body"] if item["type"] != "markdown"]


# -- the template is the schema's fields, and nothing else -----------------


def test_the_template_and_the_schema_both_exist() -> None:
    """A subset assertion over an empty set passes, so prove both ends first."""
    assert TEMPLATE.is_file(), "the platform-gap template is gone"
    assert SCHEMA.is_file(), "the generated report schema is gone"
    assert len(fields()) >= 8, "the template collects almost nothing; this test measures nothing"


def test_the_templates_fields_are_the_report_schemas_properties() -> None:
    """Exactly the allowlist — the computed dedup key excepted, which no
    person types and no door hands in."""
    computed = {
        name
        for name, spec in schema()["properties"].items()
        if spec.get("readOnly") is True
    }
    assert computed, "the schema has no computed field; this exclusion is measuring nothing"
    assert {field["id"] for field in fields()} == set(schema()["properties"]) - computed


def test_a_dropdown_offers_exactly_the_schemas_enum() -> None:
    """`kind` and `door` are closed vocabularies in the model, so a template
    offering a seventh option would collect a value the model refuses."""
    definitions = schema()["$defs"]
    properties = schema()["properties"]
    checked = 0
    for field in fields():
        if field["type"] != "dropdown":
            continue
        reference = properties[field["id"]].get("$ref", "")
        assert reference, f"{field['id']} is a dropdown over a field with no enum"
        enum = definitions[reference.rsplit("/", 1)[-1]]["enum"]
        assert field["attributes"]["options"] == enum, field["id"]
        checked += 1
    assert checked == 2, "kind and door are the two closed vocabularies"


def test_the_bridge_reads_the_labels_the_template_writes() -> None:
    """The rendered issue body is headed by each field's **label**, and the
    bridge has no checkout to read the template from — so the two spellings are
    pinned against each other here rather than trusted."""
    assert {field["id"]: field["attributes"]["label"] for field in fields()} == dict(
        bridge.FIELD_LABELS
    )


# -- the workflow's posture ------------------------------------------------


def test_the_workflow_fires_on_the_events_the_ticket_names() -> None:
    triggers = workflow()[True] if True in workflow() else workflow()["on"]
    assert set(triggers["issues"]["types"]) == {"opened", "edited", "closed", "reopened"}
    assert triggers["issue_comment"]["types"] == ["created"]


def test_the_workflow_is_read_only_at_the_top_and_writes_only_to_issues() -> None:
    document = workflow()
    assert document["permissions"] == {"contents": "read"}
    granted = {
        name: job.get("permissions", {}) for name, job in document["jobs"].items()
    }
    assert granted, "the workflow has no jobs"
    for name, permissions in granted.items():
        assert set(permissions) <= {"contents", "issues"}, name
        assert permissions.get("contents", "read") == "read", name


def test_no_workflow_on_issues_checks_anything_out() -> None:
    """An issue's title and body are attacker-controlled text. This workflow
    reads none of the repository, so it needs no copy of it — and a checkout is
    the first half of every workflow that later grows a build step."""
    for path in sorted((REPO / ".github" / "workflows").glob("*.yml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        triggers = document[True] if True in document else document["on"]
        if not isinstance(triggers, dict) or "issues" not in triggers:
            continue
        for job in document["jobs"].values():
            for step in job.get("steps", ()):
                assert not str(step.get("uses", "")).startswith("actions/checkout"), path.name
                assert "git clone" not in str(step.get("run", "")), path.name


def test_no_issue_text_is_interpolated_into_the_workflow() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for expression in re.findall(r"\$\{\{([^}]*)\}\}", text):
        assert "github.event.issue.title" not in expression, expression
        assert "github.event.issue.body" not in expression, expression
        assert "github.event.comment" not in expression, expression


def test_the_secret_the_workflow_reads_is_named_on_the_checklist() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets.OPENSTATEGRAPH_KANBAN_URL" in text
    assert "OPENSTATEGRAPH_KANBAN_URL" in CHECKLIST.read_text(encoding="utf-8")


# -- the bridge, over recorded payloads ------------------------------------


BODY = """### Version

0.3.0rc15

### Kind

no-backend

### Node or tool type ids

tool.QueryTool

### Door

api

### What refused

No implementation for tool "tool.QueryTool"

### Check id

_No response_

### First traceback line

_No response_

### Operating system

Darwin 25.6.0

### Python

3.13.1

### Project hash

_No response_
"""


def payload(
    action: str = "opened",
    *,
    number: int = 41,
    labels: tuple[str, ...] = ("bug",),
    body: str = BODY,
    event: str = "issues",
) -> dict[str, Any]:
    issue = {
        "number": number,
        "title": "The Query tool has no implementation on this install",
        "body": body,
        "labels": [{"name": name} for name in labels],
        "html_url": f"https://github.com/o/osg/issues/{number}",
        "user": {"login": "a-reporter"},
        "state": "open" if action != "closed" else "closed",
    }
    document: dict[str, Any] = {"action": action, "issue": issue}
    if event == "issue_comment":
        document["comment"] = {"body": "any news?", "user": {"login": "a-reporter"}}
    return document


@pytest.fixture()
def store(tmp_path: Path) -> SqliteKanbanStore:
    return SqliteKanbanStore(tmp_path / "kanban.sqlite")


def test_an_opened_issue_becomes_a_card_on_the_github_board(store: SqliteKanbanStore) -> None:
    outcome = bridge.apply_event(payload(), store)

    assert outcome.action == "filed"
    card = store.read_card("github:issue-41")
    assert card.board == "github"
    assert card.kind == "bug"
    assert card.title == "The Query tool has no implementation on this install"
    assert "tool.QueryTool" in card.story
    assert "api" in card.story
    assert card.done_when.strip()
    assert "41" in card.priority_reason


def test_the_same_issue_twice_is_one_card(store: SqliteKanbanStore) -> None:
    bridge.apply_event(payload(), store)
    again = bridge.apply_event(payload("edited"), store)

    assert again.action == "already-filed"
    assert len(store.list_cards()) == 1


def test_a_reopened_issue_with_no_card_gets_one(store: SqliteKanbanStore) -> None:
    assert bridge.apply_event(payload("reopened"), store).action == "filed"


def test_a_pull_request_comment_writes_nothing(store: SqliteKanbanStore) -> None:
    """`issue_comment` fires for pull requests too, and a pull request is not
    a gap report."""
    document = payload("created", event="issue_comment")
    document["issue"]["pull_request"] = {"url": "https://api.github.com/…/pulls/41"}

    outcome = bridge.apply_event(document, store)

    assert outcome.action == "skipped"
    assert store.list_cards() == []


def test_an_unknown_label_falls_to_a_known_kind(store: SqliteKanbanStore) -> None:
    """Tolerant in reading, strict in trusting: a label nobody registered does
    not become a card kind the board has no column for."""
    bridge.apply_event(payload(labels=("needs-triage", "wontfix")), store)

    assert store.read_card("github:issue-41").kind in {"task", "bug", "grilling"}


def test_a_closed_issue_with_a_finished_card_comments_the_resolution(
    store: SqliteKanbanStore,
) -> None:
    bridge.apply_event(payload(), store)
    task_id = "github:issue-41"
    store.set_stage(task_id, Stage.ATTENDED, actor="a-maintainer")
    store.set_stage(task_id, Stage.RED, actor="a-maintainer", test_id="tests/test_x.py::test_y", reason="the tool resolved to nothing")
    store.set_stage(task_id, Stage.GREEN, actor="a-maintainer", test_id="tests/test_x.py::test_y")
    store.set_stage(task_id, Stage.FINISHED, actor="a-maintainer", commit="abc1234", reason="the tool now resolves and says which distribution ran")

    outcome = bridge.apply_event(payload("closed"), store)

    assert outcome.action == "closed-with-resolution"
    assert "abc1234" in outcome.comment
    assert "the tool now resolves" in outcome.comment


def test_a_closed_issue_with_an_unfinished_card_says_so(store: SqliteKanbanStore) -> None:
    """Closing an issue is not the evidence the board's gate asks for, so the
    card is not moved — and the issue is told that rather than left to imply a
    resolution nobody recorded."""
    bridge.apply_event(payload(), store)

    outcome = bridge.apply_event(payload("closed"), store)

    assert outcome.action == "closed-unresolved"
    assert "unattended" in outcome.comment
    assert store.read_card("github:issue-41").stage is Stage.UNATTENDED


def test_a_closed_issue_with_no_card_files_one_first(store: SqliteKanbanStore) -> None:
    outcome = bridge.apply_event(payload("closed"), store)

    assert outcome.action == "closed-unresolved"
    assert store.read_card("github:issue-41").board == "github"


def test_an_issue_with_no_template_fields_still_becomes_a_card(
    store: SqliteKanbanStore,
) -> None:
    outcome = bridge.apply_event(payload(body="it broke, no idea why"), store)

    assert outcome.action == "filed"
    assert "it broke" in store.read_card("github:issue-41").story


# -- the entry point -------------------------------------------------------


def test_the_entry_point_names_the_missing_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`openwiki-update.yml`'s failure mode, not repeated: a run that dies for
    an unset secret says which one."""
    event = tmp_path / "event.json"
    event.write_text(json.dumps(payload()), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.delenv("OPENSTATEGRAPH_KANBAN_URL", raising=False)

    assert bridge.main([]) == 1
    assert "OPENSTATEGRAPH_KANBAN_URL" in capsys.readouterr().err


def test_the_entry_point_writes_the_comment_it_wants_posted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = tmp_path / "event.json"
    event.write_text(json.dumps(payload("closed")), encoding="utf-8")
    comment = tmp_path / "comment.md"
    output = tmp_path / "output.txt"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("OPENSTATEGRAPH_KANBAN_URL", f"sqlite:///{tmp_path / 'k.sqlite'}")
    monkeypatch.setenv("OPENSTATEGRAPH_BRIDGE_COMMENT_FILE", str(comment))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    assert bridge.main([]) == 0
    assert "unattended" in comment.read_text(encoding="utf-8")
    assert "comment=written" in output.read_text(encoding="utf-8")
