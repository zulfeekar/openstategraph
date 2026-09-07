"""One store, one socket, and a history a person can actually read.

`memory-and-replay/43` and `launch-readiness/99`.

**The finding this suite is built on: capture was never the gap.** The
checkpointer already holds every question and answer keyed by `thread_id`,
`api/threads.py` already reads it back as a query *and* as JSON, and
`loader._append_trace` has been writing one JSON line per run since
`workflow-gallery` 35. What did not exist was a **socket** — a way for the
person installing this to say where those rows also go — and what that
hardcoded trace file proved is that we had already answered the question once,
for one destination, with no way to answer it again.

So the tests below are about the seam, not about a new recording. In order:

1. the Protocol is satisfied without inheriting from us, and its surface is
   **pinned**, because widening a `runtime_checkable` Protocol later
   un-satisfies every third-party sink at the next `isinstance`;
2. the registry behaves the way the other six extension points here behave —
   duplicate throws, `upsert` is how you say you meant it, `list()`
   enumerates, and a fresh one is constructible;
3. **the default reaches no network**, and no sink that could is registered
   without somebody naming it;
4. a sink cannot bypass the developer/customer seam, and cannot carry a
   credential, because of what the record is built from;
5. one broken sink never costs the run that fed it.
"""

from __future__ import annotations

import ast
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from openstategraph import run_sinks
from openstategraph.run_identity import RUN_IDENTITY_KEYS
from openstategraph.run_sinks import (
    IRunSink,
    JsonlRunSink,
    RunRecord,
    RunSinkRegistry,
    SqliteRunSink,
    default_run_sink_registry,
    publish,
    read_runs,
)


def a_record(**overrides: Any) -> RunRecord:
    """A finished turn, with every identity field populated."""
    fields: dict[str, Any] = {
        "workflow_slug": "chinook-assistant",
        "thread_id": "run-abc123",
        "session_id": "browser-tab-9",
        "user_email": "someone@example.com",
        "question": "how many invoices in 2009?",
        "answer": "83.",
        "seconds": 1.25,
        "attempts": 1,
        "decisions": {"grade": "pass"},
        "usage": {"gpt-oss:120b-cloud": {"input_tokens": 900, "output_tokens": 40}},
    }
    fields.update(overrides)
    return RunRecord(**fields)


class CountingSink:
    """A third-party sink: it inherits nothing from us and satisfies the Protocol."""

    def __init__(self) -> None:
        self.seen: list[RunRecord] = []
        self.closed = False

    def record(self, record: RunRecord) -> None:
        self.seen.append(record)

    def close(self) -> None:
        self.closed = True


class ExplodingSink:
    def record(self, record: RunRecord) -> None:
        raise RuntimeError("the collector is down")

    def close(self) -> None:
        raise RuntimeError("still down")


# --------------------------------------------------------------------------
# 1. The Protocol
# --------------------------------------------------------------------------


def test_a_stranger_s_class_satisfies_the_socket_without_inheriting_from_us():
    """The owner's ask, literally: *an instance of a class our core recognises*.

    A `Protocol` rather than an ABC for the reason `ITool` and `IRouter` both
    record: requiring inheritance to participate is what makes a hierarchy
    closed for extension.
    """
    assert isinstance(CountingSink(), IRunSink)
    assert not isinstance(object(), IRunSink)


def test_the_sink_protocol_is_complete_at_birth_and_this_test_says_why():
    """**Adding a member here is a breaking change wearing an addition's clothes.**

    `runtime_checkable` checks member *presence*, so a seventh member added in
    six months un-satisfies every sink anybody shipped against this release, at
    the next `isinstance`, in their install rather than ours. `ITool`,
    `IRouter`, `IGrader`, `IOrchestrator` and `IAgent` were each left untouched
    for exactly this reason, and this suite exists so the same discipline is
    not merely intended here.

    Two members, and the second is not decoration: a sink that batches — which
    every network sink does — needs a moment to flush, and a sink that holds a
    sqlite handle needs one to release it.

    **What makes two members enough forever is that the extension point is the
    record, not the method set.** A new kind of observation (a human's thumbs
    up/down, `launch-readiness/142`) arrives as a new `kind` on `RunRecord`,
    which is an addition every existing sink survives, rather than as a
    `feedback()` method, which is one none of them do.
    """
    members = {
        name
        for name in dir(IRunSink)
        if not name.startswith("_") and callable(getattr(IRunSink, name, None))
    }
    assert members == {"record", "close"}


def test_a_new_kind_of_row_needs_no_protocol_change():
    """`142`'s thumbs up/down can feed this store without breaking a sink.

    This is the claim that makes `43`, `99`, `142` and `guardrails/07` one
    feature rather than four: they want the same rows. `kind` is a plain
    string, documented rather than enumerated, so a consumer that does not know
    a kind ignores it instead of failing to parse it.
    """
    before = {
        name
        for name in dir(IRunSink)
        if not name.startswith("_") and callable(getattr(IRunSink, name, None))
    }
    thumbs = a_record(kind="feedback", answer="")
    sink = CountingSink()
    publish(thumbs, registry=_only(sink))
    assert sink.seen[0].kind == "feedback"
    # The sink took a kind it has never heard of, and the seam it is reached
    # through did not move. **The field 142 still owes is a rating**; this
    # ticket deliberately does not invent one, because a column whose meaning
    # is decided by a feature nobody has built yet is a guess that would ship
    # with a schema.
    assert before == {"record", "close"}


# --------------------------------------------------------------------------
# 2. The registry — the seventh extension point of this kind
# --------------------------------------------------------------------------


def test_two_claims_on_one_name_is_ambiguity_not_precedence():
    registry = RunSinkRegistry()
    registry.register("jsonl", CountingSink())
    with pytest.raises(ValueError) as caught:
        registry.register("jsonl", CountingSink())
    assert "upsert" in str(caught.value)


def test_upsert_is_how_you_say_you_meant_to_replace_it():
    registry = RunSinkRegistry()
    first, second = CountingSink(), CountingSink()
    registry.register("jsonl", first)
    registry.upsert("jsonl", second)
    assert registry.get("jsonl") is second
    assert registry.list() == (("jsonl", second),)


def test_list_enumerates_in_registration_order():
    registry = RunSinkRegistry()
    a, b = CountingSink(), CountingSink()
    registry.register("a", a)
    registry.register("b", b)
    assert [name for name, _ in registry.list()] == ["a", "b"]


def test_a_fresh_registry_is_constructible_so_registrations_do_not_leak():
    """The property that keeps one test's sink out of the next test's run."""
    assert default_run_sink_registry() is not default_run_sink_registry()
    registry = default_run_sink_registry()
    registry.register("mine", CountingSink())
    assert default_run_sink_registry().get("mine") is None


# --------------------------------------------------------------------------
# 3. Privacy — the default goes nowhere
# --------------------------------------------------------------------------


def test_the_default_registry_holds_exactly_one_sink_and_it_is_local():
    """`CLAUDE.md`: *never send a user's graph to a third party.*

    The rule that makes `draw_mermaid()` the only drawing call in this
    repository decides this default too. A telemetry pipe enabled on install is
    the same breach with a different content type, so the shipped registry
    holds one sink, it writes a file on the machine that ran the workflow, and
    every other destination is an explicit act by the person installing.
    """
    registry = default_run_sink_registry()
    assert [name for name, _ in registry.list()] == ["sqlite"]
    assert isinstance(registry.get("sqlite"), SqliteRunSink)


def test_no_network_sink_ships_at_all():
    """Not merely disabled — **absent**.

    A disabled exporter is one environment variable from being enabled by
    somebody who has not read this paragraph, and an exporter we do not ship
    cannot be turned on by accident. `guardrails/07` is the only consumer with
    a concrete need today and it is a local one, so nothing here speculatively
    reaches a collector.
    """
    tree = ast.parse(Path(run_sinks.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    # Asserted over the **imports**, not over the text: this module's docstring
    # names the vendors on purpose, to say that they are the operator's choice
    # and not ours, and a test that failed on the paragraph explaining the rule
    # would be a test that punished documenting it.
    for vendor in ("langsmith", "opentelemetry", "httpx", "requests", "urllib"):
        assert vendor not in imported, f"{vendor} must not ship in the default sink module"


# --------------------------------------------------------------------------
# 4. The seam a sink must not bypass
# --------------------------------------------------------------------------


def test_a_record_carries_a_scrubbed_statement_and_never_the_argument_map():
    """`one-chinook-honest/30`'s rule, carried into the sink rather than re-derived.

    Two layers, both inherited by construction rather than reimplemented here:
    the record carries only what `statements_executed` published — the one
    argument recognised as a statement, never the argument map — so a tool's
    `connection_string` or `token` argument is *not recorded at all* rather
    than recorded and then scrubbed. A telemetry pipe is exactly how a
    redaction seam gets bypassed, and the way it is not bypassed here is that
    there is no second path to the data.
    """
    from openstategraph.executed_statements import statements_executed

    tool_use = {
        "agent-sql": {
            "queries": [
                {
                    # `sql` is what the *internal* record calls it; `statement`
                    # is what the published row calls it, because "what did
                    # this tool actually do" is not a SQL feature. Writing the
                    # published spelling here recorded nothing at all, which is
                    # the tolerant reader behaving correctly.
                    "tool": "mcp_execute_sql",
                    "sql": "SELECT 1 -- pwd=hunter2",
                    "arguments": {"connection_string": "postgres://u:s3cret@host/db"},
                    "result": "1",
                }
            ]
        }
    }
    published = statements_executed(tool_use)
    record = a_record(statements=published)
    row = record.statements[0]
    assert "hunter2" not in json.dumps(record.model_dump())
    assert "s3cret" not in json.dumps(record.model_dump())
    assert "arguments" not in row
    assert set(row) == {"node", "tool", "statement", "result", "truncated"}


def test_the_record_names_the_identity_keys_from_the_one_place_they_are_named():
    """No fifth spelling of who a run is for.

    `run_identity.RUN_IDENTITY_KEYS` is the single list; a store that invented
    its own would be the second chance to drift that module exists to remove.
    """
    for key in RUN_IDENTITY_KEYS:
        assert key in RunRecord.model_fields


# --------------------------------------------------------------------------
# 5. Isolation — diagnostics must never cost the run that produced them
# --------------------------------------------------------------------------


def test_a_broken_sink_never_kills_the_run_that_fed_it():
    """`_append_trace`'s rule, generalised: *losing a trace must never lose the run*.

    And the sinks after the broken one still get their row — a collector being
    down must not silently cost the local store too.
    """
    registry = RunSinkRegistry()
    good = CountingSink()
    registry.register("boom", ExplodingSink())
    registry.register("good", good)
    publish(a_record(), registry=registry)
    assert len(good.seen) == 1


# --------------------------------------------------------------------------
# 6. The read path — a query and JSON, the same rows
# --------------------------------------------------------------------------


def test_the_local_store_is_a_real_table_a_person_can_query(tmp_path: Path):
    """*"basically a query or JSON"* — and the query is not ours to invent.

    A developer or QA engineer at a terminal opens the file with `sqlite3` and
    writes SQL. That is why the sink writes columns rather than one JSON blob
    per run: a blob would make `guardrails/07`'s question — what has this
    workflow spent — a program rather than a query.
    """
    path = tmp_path / "runs.sqlite"
    sink = SqliteRunSink(path)
    sink.record(a_record())
    sink.record(a_record(thread_id="run-def456", workflow_slug="other"))
    sink.close()

    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            "SELECT thread_id, workflow_slug, question FROM runs ORDER BY thread_id"
        ).fetchall()
    finally:
        connection.close()
    assert [row[0] for row in rows] == ["run-abc123", "run-def456"]
    assert rows[0][1] == "chinook-assistant"


def test_the_same_rows_come_back_as_json_for_a_model_or_a_script(tmp_path: Path):
    """The other half of the owner's sentence, and it must be the *same* rows.

    Two readers over one table, never two stores — that is the whole design
    claim of `43`, and a JSON view assembled from somewhere else is how it
    would quietly stop being true.
    """
    path = tmp_path / "runs.sqlite"
    sink = SqliteRunSink(path)
    sink.record(a_record())
    sink.close()

    back = read_runs(path)
    assert len(back) == 1
    assert isinstance(back[0], RunRecord)
    assert back[0].question == "how many invoices in 2009?"
    assert back[0].usage["gpt-oss:120b-cloud"]["input_tokens"] == 900
    assert back[0].decisions == {"grade": "pass"}
    # A model reads this, so it must survive `json.dumps` with no coaxing.
    assert json.loads(json.dumps([row.model_dump() for row in back]))[0]["thread_id"] == (
        "run-abc123"
    )


def test_a_reader_can_narrow_to_one_workflow_or_one_thread(tmp_path: Path):
    """`(workflow_slug, thread_id)` is the key, and `149` chose the same one.

    Not a new identity: `session_id` already exists in checkpoint metadata as a
    listing-only grouping that spans threads, and `thread_id` is what LangGraph
    keys on and what `POST /api/runs/resume` demands back. Inventing a third
    would be the *loop*/*template*/*slug* collision again, deliberately.
    """
    path = tmp_path / "runs.sqlite"
    sink = SqliteRunSink(path)
    sink.record(a_record())
    sink.record(a_record(thread_id="run-def456", workflow_slug="other", session_id="tab-2"))
    sink.close()

    assert len(read_runs(path, workflow_slug="chinook-assistant")) == 1
    assert len(read_runs(path, thread_id="run-def456")) == 1
    assert len(read_runs(path, session_id="tab-2")) == 1
    assert len(read_runs(path)) == 2


def test_the_store_survives_being_written_twice_by_two_processes(tmp_path: Path):
    """Two servers on one machine share a state directory. Opening is not owning."""
    path = tmp_path / "runs.sqlite"
    one, two = SqliteRunSink(path), SqliteRunSink(path)
    one.record(a_record())
    two.record(a_record(thread_id="run-def456"))
    one.close()
    two.close()
    assert len(read_runs(path)) == 2


def test_reading_a_store_that_was_never_written_is_not_an_error(tmp_path: Path):
    """A fresh install has no runs, and *no runs* is an answer, not a failure."""
    assert read_runs(tmp_path / "absent.sqlite") == []


def test_a_state_directory_that_cannot_be_written_costs_the_row_and_not_the_run(
    tmp_path: Path,
):
    """A read-only mount is a supported install, per `state_dir`'s own docstring."""
    sink = SqliteRunSink(tmp_path / "no-such-dir" / "nested" / "deeper" / "runs.sqlite")
    # Whatever it does about the directory, it must not raise at the caller.
    sink.record(a_record())
    sink.close()


# --------------------------------------------------------------------------
# 7. The sink that already existed keeps its promise
# --------------------------------------------------------------------------


def test_the_trace_file_still_refuses_to_write_the_answer(tmp_path: Path):
    """`--trace-file` is now a registered sink rather than a hardcoded branch,
    and **its output is unchanged** — including the part that matters most.

    A trace file gets committed, emailed and pasted into issues, and the answer
    is the one field in a run that reliably contains a customer's data. The
    generalisation must not quietly widen it: the record carries the answer
    because the *local* store is the point, and this sink still writes only its
    length.
    """
    path = tmp_path / "trace.jsonl"
    sink = JsonlRunSink(path)
    sink.record(a_record())
    sink.close()

    line = json.loads(path.read_text(encoding="utf-8").strip())
    assert line["answer_chars"] == 3
    assert "answer" not in line
    assert line["question"] == "how many invoices in 2009?"
    assert line["usage"]["gpt-oss:120b-cloud"]["input_tokens"] == 900


def _only(sink: Any) -> RunSinkRegistry:
    registry = RunSinkRegistry()
    registry.register("test", sink)
    return registry


# --------------------------------------------------------------------------
# 8. The run door — the layer the defect would actually live at
# --------------------------------------------------------------------------
#
# Everything above tests the store and the socket in isolation, and every one
# of those tests would still pass if `ask()` never called `publish` at all.
# That is the failure shape this project has now recorded eight times in a
# month: a green suite, and the test sitting one layer up from the defect. So
# these drive a real workflow through the real door.


LINEAR = {
    "version": 2,
    "name": "Billing Analyst",
    "nodes": [
        {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 0, "y": 0}},
        {
            "id": "out1",
            "type": "output.formatted",
            "data": {},
            "position": {"x": 0, "y": 0},
        },
    ],
    "edges": [
        {
            "source": {"nodeId": "in1", "portId": "text"},
            "target": {"nodeId": "out1", "portId": "result"},
        }
    ],
}


def _package(root: Path, slug: str = "linear-pkg") -> Path:
    directory = root / slug
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "workflow.json").write_text(
        json.dumps({"version": 1, "name": slug, "savedAt": "", "document": LINEAR})
    )
    return directory


def test_a_real_run_lands_in_the_local_store_and_reads_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`ask()` -> the default sink -> a queryable row, with no configuration.

    The suite opts the store out to `memory` the way it opts out the
    checkpointer, so this test points it at a real file to exercise the
    shipped default rather than the opt-out.
    """
    from openstategraph import load_workflow
    from openstategraph.run_sinks import reset_run_sink_registry

    store = tmp_path / "state" / "runs.sqlite"
    monkeypatch.setenv("OPENSTATEGRAPH_RUN_STORE_PATH", str(store))
    reset_run_sink_registry()

    workflow = load_workflow(_package(tmp_path))
    workflow.ask("swordfish", thread_id="t-1", session_id="tab-7")
    workflow.close()
    reset_run_sink_registry()  # close the handle so the row is on disk

    rows = read_runs(store)
    assert len(rows) == 1
    row = rows[0]
    assert row.kind == "run"
    assert row.question == "swordfish"
    assert row.answer == "swordfish"
    # The key, end to end: the conversation, and the grouping that spans them.
    assert row.thread_id == "t-1"
    assert row.session_id == "tab-7"
    assert row.workflow_slug == "linear-pkg"
    assert row.at  # a row nobody can order is a row nobody can read
    assert row.seconds >= 0


def test_two_turns_of_one_conversation_are_two_rows_under_one_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Replay needs the turns kept apart, and the conversation kept together.

    A store that collapsed a thread to its latest turn would answer *what was
    asked* with only the last question, which is the one thing a person
    diagnosing a wrong answer never wants.
    """
    from openstategraph import load_workflow
    from openstategraph.run_sinks import reset_run_sink_registry

    store = tmp_path / "state" / "runs.sqlite"
    monkeypatch.setenv("OPENSTATEGRAPH_RUN_STORE_PATH", str(store))
    reset_run_sink_registry()

    workflow = load_workflow(_package(tmp_path))
    workflow.ask("first", thread_id="t-1")
    workflow.ask("second", thread_id="t-1")
    workflow.close()
    reset_run_sink_registry()

    rows = read_runs(store, thread_id="t-1")
    assert sorted(row.question for row in rows) == ["first", "second"]


def test_the_store_is_off_when_the_operator_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`memory` is the opt-out, spelled exactly as the checkpointer's is.

    A deliberately stateless deployment gets the same sentence it already knows
    for the other two durable files, rather than a third convention.
    """
    from openstategraph import load_workflow
    from openstategraph.run_sinks import reset_run_sink_registry

    monkeypatch.setenv("OPENSTATEGRAPH_RUN_STORE_PATH", "memory")
    reset_run_sink_registry()

    workflow = load_workflow(_package(tmp_path))
    workflow.ask("swordfish")
    workflow.close()

    assert not (tmp_path / "runs.sqlite").exists()
    assert list(tmp_path.rglob("runs.sqlite")) == []


# --------------------------------------------------------------------------
# 9. The two readers, at the terminal
# --------------------------------------------------------------------------


def test_a_developer_at_a_terminal_gets_a_table_and_a_model_gets_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """*"a developer, a model, a QA engineer can all read it"* — and it is one store.

    Three readers, and the third needs no code of ours at all: the file is a
    real table with real columns, so `sqlite3` is the query surface for
    anything these two commands do not print.
    """
    from openstategraph.cli import main
    from openstategraph.run_sinks import SqliteRunSink

    store = tmp_path / "runs.sqlite"
    monkeypatch.setenv("OPENSTATEGRAPH_RUN_STORE_PATH", str(store))
    sink = SqliteRunSink(store)
    sink.record(a_record())
    sink.close()

    assert main(["runs", "list"]) == 0
    table = capsys.readouterr().out
    assert "run-abc123" in table
    assert "chinook-assistant" in table
    assert "how many invoices in 2009?" in table

    assert main(["runs", "list", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["thread_id"] == "run-abc123"
    assert rows[0]["usage"]["gpt-oss:120b-cloud"]["input_tokens"] == 900

    assert main(["runs", "path"]) == 0
    assert capsys.readouterr().out.strip() == str(store)


def test_the_listing_never_reports_an_unmeasured_run_as_a_free_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """*Absent is not zero* — the rule `RunResult.usage` already holds.

    A provider that reported nothing must not render as `0 tok`, because
    `guardrails/07` is going to argue a spending ceiling off these numbers and
    "this run was free" is the one wrong answer that would not look wrong.
    """
    from openstategraph.cli import main
    from openstategraph.run_sinks import SqliteRunSink

    store = tmp_path / "runs.sqlite"
    monkeypatch.setenv("OPENSTATEGRAPH_RUN_STORE_PATH", str(store))
    sink = SqliteRunSink(store)
    sink.record(a_record(usage={}))
    sink.close()

    assert main(["runs", "list"]) == 0
    assert "- tok" in capsys.readouterr().out.replace("       ", "")


def test_an_empty_store_says_so_rather_than_printing_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """A fresh install has no runs, and silence would read as a broken command."""
    from openstategraph.cli import main

    monkeypatch.setenv("OPENSTATEGRAPH_RUN_STORE_PATH", str(tmp_path / "runs.sqlite"))
    assert main(["runs", "list"]) == 0
    assert "no runs recorded yet" in capsys.readouterr().out


# --------------------------------------------------------------------------
# 10. Zero configuration, on every platform
# --------------------------------------------------------------------------
#
# The owner's bar, and it is higher than "a sink you can enable": *a user
# installs OSG and gets an offline store on the filesystem they can read and
# replay, without going through any configuration*, on Linux, macOS, Windows
# and WSL. These pin that claim rather than describing it.


def test_the_store_needs_no_configuration_at_all(monkeypatch: pytest.MonkeyPatch):
    """With **every** relevant variable unset, there is still a local store.

    The failure this guards against is subtle and would be invisible in a
    developer's shell: a default that quietly depends on an environment
    variable somebody exported once works perfectly for the person who wrote it
    and not at all for the stranger who installed it.
    """
    from openstategraph.run_sinks import SqliteRunSink, default_run_sink_registry

    monkeypatch.delenv("OPENSTATEGRAPH_RUN_STORE_PATH", raising=False)
    monkeypatch.delenv("OPENSTATEGRAPH_STATE_DIR", raising=False)

    registry = default_run_sink_registry()
    sink = registry.get("sqlite")
    assert isinstance(sink, SqliteRunSink)
    # A real path on this machine, not an in-memory fallback.
    assert sink.path is not None
    assert sink.path.name == "runs.sqlite"
    assert sink.path.is_absolute()


@pytest.mark.parametrize(
    "platform, home_var, expected",
    [
        ("linux", "XDG_STATE_HOME", ".local/state"),
        ("darwin", None, "Library/Application Support"),
        ("win32", "LOCALAPPDATA", None),
    ],
)
def test_the_store_lands_where_each_platform_says_it_should(
    platform: str,
    home_var: str | None,
    expected: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """One resolver, three platforms, and **no `platformdirs` dependency**.

    `state_dir` already carried the citations — XDG on Linux (so WSL falls out
    of the same branch), Application Support on macOS, `%LOCALAPPDATA%` on
    Windows, *Local* rather than *Roaming* because a sqlite file must not be
    synchronised between machines behind our back. The run store reuses it
    rather than resolving a path a second way, which is what stops the two
    files under `state_dir()` from ever disagreeing about where they live.
    """
    from openstategraph import state_dir as state_dir_module

    monkeypatch.delenv("OPENSTATEGRAPH_RUN_STORE_PATH", raising=False)
    monkeypatch.delenv("OPENSTATEGRAPH_STATE_DIR", raising=False)
    monkeypatch.setattr(state_dir_module.sys, "platform", platform)
    monkeypatch.setenv("HOME", str(tmp_path))
    if home_var:
        monkeypatch.setenv(home_var, str(tmp_path / "explicit"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    home = state_dir_module.user_state_home()
    assert home.is_absolute()
    if expected:
        assert expected in home.as_posix() or "explicit" in home.as_posix()


def test_the_run_store_resolves_through_state_dir_and_not_a_second_way():
    """A second path resolver is how two files under one directory drift apart."""
    tree = ast.parse(Path(run_sinks.__file__).read_text(encoding="utf-8"))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "openstategraph.state_dir" in imports
    assert "platformdirs" not in {name.split(".")[0] for name in imports}
    # Over the *literals*, not the text: this module's docstring names the three
    # platform conventions on purpose, to say they are `state_dir`'s answer and
    # not re-derived here. A test that failed on the paragraph explaining the
    # rule would punish documenting it — the same correction this suite already
    # made once, for the vendor-import check above.
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    for reinvention in ("XDG_STATE_HOME", "LOCALAPPDATA", "APPDATA"):
        assert reinvention not in literals, f"{reinvention} is state_dir's to answer"


# --------------------------------------------------------------------------
# 11. Unbounded on purpose, and an export rather than a silent sweep
# --------------------------------------------------------------------------


def test_nothing_in_the_store_drops_a_run_for_being_old(tmp_path: Path):
    """`96`'s rule: *age is only ever the second condition*, and there is no second.

    A conversation is the raw material for replay and for `99`'s verified
    patterns, so its value does not decay. The store therefore grows without
    bound **deliberately**, and the honest answer to a large file is an export
    and a truncation the operator performs — never a sweep they did not ask for
    and would discover by missing a run.
    """
    tree = ast.parse(Path(run_sinks.__file__).read_text(encoding="utf-8"))
    # Only what is actually **executed** — the arguments of `.execute(...)`.
    # Scanning every string literal instead scans the prose, and the prose
    # deliberately contains the word "delete": it is where a person is told how
    # to truncate the file themselves. Twice now this suite has caught its own
    # documentation; both times the fix was to assert over code.
    statements = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
        ):
            continue
        for argument in node.args:
            # f-strings too: every statement this module runs is assembled from
            # `_COLUMNS`, so a check that only understood plain constants would
            # be reading none of them and passing for that reason.
            for piece in ast.walk(argument):
                if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                    statements.add(piece.value.upper())
    assert statements, "found no executed SQL at all — this check would pass vacuously"
    for sweeper in ("DELETE", "DROP TABLE", "VACUUM"):
        assert not any(sweeper in sql for sql in statements), (
            f"the run store must not sweep ({sweeper})"
        )
    named = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    for sweeper in ("prune", "sweep", "expire", "purge", "truncate"):
        assert not any(sweeper in name.lower() for name in named), (
            f"the run store must not sweep ({sweeper})"
        )


def test_export_writes_the_same_rows_as_a_file_and_deletes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """The "or JSON" half: sqlite is the store, JSON is the export.

    And the export is what makes an unbounded default honest — a person can get
    every row out before truncating, so keeping everything by default never
    becomes a file they can only delete blind.
    """
    from openstategraph.cli import main
    from openstategraph.run_sinks import SqliteRunSink

    store = tmp_path / "runs.sqlite"
    monkeypatch.setenv("OPENSTATEGRAPH_RUN_STORE_PATH", str(store))
    sink = SqliteRunSink(store)
    sink.record(a_record())
    sink.close()

    out = tmp_path / "exported" / "runs.json"
    assert main(["runs", "export", "--to", str(out)]) == 0
    assert "wrote 1 run(s)" in capsys.readouterr().out

    exported = json.loads(out.read_text(encoding="utf-8"))
    assert exported[0]["thread_id"] == "run-abc123"
    assert exported[0]["answer"] == "83."
    # Exporting is a read. The store still holds the row.
    assert len(read_runs(store)) == 1
