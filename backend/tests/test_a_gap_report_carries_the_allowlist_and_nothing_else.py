"""`team-board-and-gap-reports/07`. What a gap report may carry, as a type.

A user is asked to send a report about something their install refused to do.
The only honest way to ask that is to be able to say *exactly* what goes and
what does not — and "we only send anonymous diagnostics" is a sentence, not a
guarantee. This file is the guarantee: every forbidden class is named here and
asserted unrepresentable, so a door built later cannot invent a payload with a
document in it and pass review on the strength of a paragraph.

The three finding shapes already here are the internal vocabulary and none of
them is this. `RunFinding` carries `arguments` — normalised tool arguments,
which is user content. `DocumentFinding` carries `<node id>.<field>`, and a
node id is a name its author chose. A report is a **narrower projection**, and
the narrowing is the product.
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from openstategraph.compile.diagnostics import CompileDiagnostics, Finding
from openstategraph.document_checks import FindingClass
from openstategraph.gap_report import (
    CHECK_IDS,
    GAP_REPORT_SCHEMA_PATH,
    GapDoor,
    GapKind,
    GapReport,
    Refusal,
    RefusalSource,
    first_traceback_line,
    gap_report_schema,
    hashed_project_id,
)
from openstategraph.errors import PackageNotFound
from openstategraph.kanban_store import StageOrderError
from openstategraph.providers import builtin_specs

REPO = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parents[1] / "openstategraph"


def a_report(**overrides: object) -> GapReport:
    """The smallest report that is legal, so a test can change one thing."""
    fields: dict[str, object] = {
        "kind": GapKind.NO_BACKEND,
        "type_ids": ("tool.reddit-search",),
        "door": GapDoor.EDITOR,
        "refusal": Refusal.for_missing_implementation("tool.reddit-search"),
        "check": FindingClass.NO_BACKEND.value,
        "project_hash": hashed_project_id("11111111-2222-3333-4444-555555555555"),
    }
    fields.update(overrides)
    return GapReport(**fields)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# The allowlist is the whole model


def test_the_fields_are_exactly_the_owners_allowlist() -> None:
    """`OWNER-DECISIONS.md` § Report contents, plus the two hashes 01 and 09
    need. Written out by name rather than counted: a count would pass a swap."""
    assert set(GapReport.model_fields) == {
        "version",
        "kind",
        "type_ids",
        "door",
        "refusal",
        "check",
        "traceback_line",
        "os",
        "python",
        "project_hash",
        "aad_code",
    }
    assert set(GapReport.model_computed_fields) == {"finding_hash"}


#: The never-list, by name. Each is a real thing a door could reasonably reach
#: for while assembling a report, and each must fail rather than send.
FORBIDDEN = {
    "the document": {"document": {"nodes": {"in1": {"type": "input.text"}}}},
    "prompts": {"prompt": "You are a helpful assistant. Never mention…"},
    "field values": {"field_values": {"question": "how much did we invoice?"}},
    "table names": {"tables": ["Invoice", "Customer"]},
    "question text": {"question": "which artist sold the most?"},
    "file paths": {"path": "/Users/someone/work/workflows/x/workflow.json"},
    "environment values": {"env": {"OPENAI_API_KEY": "sk-live-abc"}},
}


@pytest.mark.parametrize("name", sorted(FORBIDDEN))
def test_the_forbidden_classes_are_unrepresentable(name: str) -> None:
    with pytest.raises(ValidationError) as raised:
        a_report(**FORBIDDEN[name])
    assert "extra" in str(raised.value).lower(), (
        f"{name} was accepted or refused for the wrong reason — the model must "
        "forbid extra fields, not ignore them"
    )


#: The same content, aimed at the fields that *do* exist. Extra-forbidden is
#: only half the guarantee: a door with a question in its hand will try the
#: nearest field that takes a string.
@pytest.mark.parametrize(
    "value",
    [
        pytest.param("which artist sold the most?", id="question text"),
        pytest.param("Invoice", id="a table name"),
        pytest.param("/Users/someone/workflows/x/workflow.json", id="an absolute path"),
        pytest.param("workflows/chinook/workflow.json", id="a relative path"),
        pytest.param("You are a helpful assistant.", id="a prompt"),
        pytest.param("sk-live-abcdefghijklmnop", id="a credential value"),
    ],
)
def test_a_type_id_field_takes_type_ids_and_not_content(value: str) -> None:
    with pytest.raises(ValidationError):
        a_report(type_ids=(value,))


def test_the_type_ids_that_are_real_are_accepted() -> None:
    """Type ids, never values — including the two ids that are not built in.

    A package-scoped tool (`<slug>/tools.QueryTool`) and a distribution's
    plugin type are both ids a document may legally hold (CLAUDE.md's four
    channels), and a report about one of them is exactly the report this map
    exists for.
    """
    report = a_report(
        type_ids=("tool.reddit-search", "chinook-assistant/tools.QueryTool", "tool.acme-ping")
    )
    assert len(report.type_ids) == 3


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("Invoice", id="a table name"),
        pytest.param("how much did we invoice in 2013?", id="question text"),
        pytest.param("route.check", id="a node type, which is not a check id"),
    ],
)
def test_a_check_id_must_be_one_this_codebase_publishes(value: str) -> None:
    with pytest.raises(ValidationError):
        a_report(check=value)


def test_the_check_vocabulary_is_derived_and_not_restated() -> None:
    """One vocabulary: the classes the document checks and the patrol already
    name. A second list here would be the drift this repository names by name."""
    assert {member.value for member in FindingClass} <= CHECK_IDS
    from openstategraph.run_findings import EVERY_TOOL_CALL_FAILED, NODE_FAILURE

    assert {NODE_FAILURE, EVERY_TOOL_CALL_FAILED} <= CHECK_IDS


# --------------------------------------------------------------------------
# The first traceback line, and nothing under it


def _raise_through_a_frame_with_a_path() -> None:
    def inner() -> None:
        raise StageOrderError("cannot move a card from done back to doing")

    inner()


def test_the_traceback_line_is_one_line_and_carries_no_path() -> None:
    try:
        _raise_through_a_frame_with_a_path()
    except StageOrderError as exc:
        line = first_traceback_line(exc)
    assert "\n" not in line
    assert __file__ not in line
    assert "/" not in line and "\\" not in line
    assert "StageOrderError" in line and "done back to doing" in line


def test_a_path_in_the_exceptions_own_message_does_not_survive() -> None:
    """The message is ours; the argument in it need not be."""
    line = first_traceback_line(
        FileNotFoundError("no such file: /Users/someone/.env")
    )
    assert "/Users/someone" not in line
    assert "<path>" in line


def test_a_hand_written_traceback_line_is_redacted_too() -> None:
    """The field, not only the helper — a door that assembles the string
    itself must not be a second route for a path."""
    report = a_report(traceback_line="ValueError: /Users/someone/x.py is missing")
    assert "/Users/someone" not in (report.traceback_line or "")


# --------------------------------------------------------------------------
# The refusal is ours, not theirs


def test_the_refusal_is_a_sentence_this_codebase_writes() -> None:
    missing = Refusal.for_missing_implementation("tool.reddit-search")
    assert missing.source is RefusalSource.RUNTIME
    assert missing.text == CompileDiagnostics.sentence_for(Finding.UNRESOLVED_TOOL).format(
        "tool.reddit-search"
    )

    spec = next(spec for spec in builtin_specs() if spec.env_vars)
    provider = Refusal.for_provider(spec)
    assert provider.source is RefusalSource.PROVIDER
    assert provider.text == spec.missing_key_message()

    # `team-board-and-gap-reports/16` narrowed this from *anything defined
    # under `openstategraph/`* to *anything `openstategraph.errors` defines*,
    # and this line used to read `StageOrderError` — `kanban_store`'s own
    # control-flow type. The class census is in
    # `test_every_error_we_define_can_be_a_refusal.py`; what belongs here is
    # that the seam produces a sentence of ours.
    refused = Refusal.for_our_exception(PackageNotFound("no workflow.json in that directory"))
    assert refused.source is RefusalSource.EXCEPTION
    assert refused.text == "PackageNotFound: no workflow.json in that directory"


def test_a_model_answer_cannot_become_a_refusal() -> None:
    """There is no constructor that takes a bare string, and the one that
    takes an exception takes only exceptions this package defines. A model's
    answer is a `str`; wrapping it in a `ValueError` does not make it ours."""
    with pytest.raises(TypeError):
        Refusal.for_our_exception(ValueError("Sure! Here is the customer table:"))
    with pytest.raises(ValidationError):
        Refusal(source=RefusalSource.RUNTIME, text="Sure! Here is the table")  # type: ignore[call-arg]


def _calls_named(module: Path, names: set[str]) -> list[str]:
    tree = ast.parse(module.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        label = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
        if label in names:
            found.append(f"{module.name}:{node.lineno} {label}(")
    return found


#: The modules that may build a report, each one a door and each one a
#: deliberate edit here. `gap_report_door.py` is the user's own `gh`
#: (`team-board-and-gap-reports/08`): it constructs exactly one report, from a
#: type id, and everything it then hands to a subprocess is that report's own
#: rendering. The second door (`09`) takes a report it is given and builds
#: none, which is why it is not on this list.
BUILDERS = {"gap_report.py", "gap_report_door.py"}


def test_nothing_else_in_the_package_builds_one() -> None:
    """Derived, not a list: every module under `openstategraph/` is parsed.

    The doors are named in `BUILDERS` above. This is the test that makes each
    of them a deliberate edit here rather than a payload invented in place.
    """
    offenders: list[str] = []
    for module in sorted(PACKAGE.rglob("*.py")):
        if module.name in BUILDERS:
            continue
        offenders += _calls_named(module, {"GapReport", "Refusal"})
    assert offenders == [], offenders


def test_the_module_cannot_send_anything() -> None:
    """Nothing about this is telemetry: no timer, no background sender, and no
    transport at all — so no call path can construct *and* dispatch."""
    source = (PACKAGE / "gap_report.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not imported & {"httpx", "requests", "urllib", "http", "socket", "smtplib"}
    functions = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not [name for name in functions if "send" in name or "post" in name]


# --------------------------------------------------------------------------
# The two hashes, and the text a user reads before any of it moves


def test_the_project_id_is_hashed_and_never_carried() -> None:
    project_id = "11111111-2222-3333-4444-555555555555"
    digest = hashed_project_id(project_id)
    assert digest == hashlib.sha256(project_id.encode("utf-8")).hexdigest()
    assert project_id not in digest
    with pytest.raises(ValidationError):
        a_report(project_hash=project_id)


def test_the_finding_hash_dedups_across_versions() -> None:
    """`09`'s dedup key. Derived from what the finding *is*, so the same gap
    reported from the same install after an upgrade is one card, not two."""
    first = a_report(version="0.3.0rc15")
    second = a_report(version="0.4.0")
    assert first.finding_hash == second.finding_hash
    assert a_report(type_ids=("tool.databricks-query",)).finding_hash != first.finding_hash
    assert first.finding_hash != first.project_hash


def test_render_shows_every_field_that_will_be_sent() -> None:
    """Derived from the model, so a field added later cannot be sent unseen."""
    report = a_report(aad_code="AADSTS7000222")
    rendered = report.render()
    for name, value in report.model_dump(mode="json").items():
        assert name in rendered, name
        if isinstance(value, str) and value:
            assert value in rendered, name


def test_render_says_what_is_never_sent() -> None:
    rendered = a_report().render()
    for phrase in ("document", "prompts", "field values", "table names", "file paths"):
        assert phrase in rendered


# --------------------------------------------------------------------------
# Published, and pinned to the publication


def test_the_committed_schema_matches_the_model() -> None:
    committed = json.loads(GAP_REPORT_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert committed == gap_report_schema(), (
        "docs/gap-report.schema.json is stale — run "
        "`python3 scripts/generate_gap_report_schema.py --write`"
    )


def test_the_script_checks_and_does_not_write_when_it_checks() -> None:
    before = GAP_REPORT_SCHEMA_PATH.read_bytes()
    done = subprocess.run(
        [sys.executable, "scripts/generate_gap_report_schema.py", "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert GAP_REPORT_SCHEMA_PATH.read_bytes() == before
