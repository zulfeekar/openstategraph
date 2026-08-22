"""One accessor reads the run's identity, and a fifth reader cannot forget.

`ac870f6` pinned a census of the doors that **write** `configurable`. Nothing
pinned the ones that **read** it, and there were four of them — `memory.py`
twice, `prebuilt_session._configurable`, `api/streaming.py` — each with its own
`or {}` and its own `str()`. `organisms-first-class/68` folds them into
`openstategraph.run_identity` and this file is the sibling census.

Two shapes, for the same reason the writer census has two.

**Behaviour**, because a helper returning a dict is not a reproduction: a
memory write has to land in the namespace the run's identity says, a thread
listing has to find the run it started, and the session-identity tool has to
tell a model who is asking. Those are the three consumers of the four keys, and
they are driven here rather than asserted about.

**A census**, because the recurring defect is never "this reader is wrong", it
is "a fifth reader appeared and hand-rolled it". `TestNoFifthReaderCanForget`
walks the package for the identity keys and fails on a module it has not been
told about, and fails again on any module but the accessor that reads one out
of the ambient run config.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any

import pytest

from openstategraph.run_identity import (
    RUN_IDENTITY_FIELDS,
    RUN_IDENTITY_KEYS,
    run_identity,
)


def _package_root() -> Path:
    import openstategraph

    return Path(openstategraph.__file__).parent


class TestTheAccessorItself:
    """Its whole contract: the four keys, strings, and `{}` for "we cannot say"."""

    def test_outside_a_run_it_is_empty(self) -> None:
        assert run_identity() == {}

    def test_a_run_config_yields_every_key_as_a_string(self) -> None:
        identity = run_identity(
            {"configurable": {"user_email": "a@x.com", "thread_id": 7}}
        )
        assert set(identity) == set(RUN_IDENTITY_KEYS)
        assert identity == {
            "user_email": "a@x.com",
            "session_id": "",
            "thread_id": "7",
            "workflow_slug": "",
        }

    def test_it_does_not_normalise(self) -> None:
        """The rule that keeps four callers from inheriting each other's rules.

        `memory.py` lowercases and substitutes periods for a Store namespace;
        `prebuilt_session` strips for a sentence a model reads. Folding either
        in here would apply it to both.
        """
        assert run_identity({"configurable": {"user_email": " A.B@X.com "}})[
            "user_email"
        ] == " A.B@X.com "

    def test_the_two_ways_of_knowing_nobody_stay_apart(self) -> None:
        """Ticket 07's distinction, now available to every reader.

        Config that never arrived is `{}`; config that arrived carrying nobody
        is a full dict of empty strings. Before this, only `memory.py` could
        tell them apart, and only because it wrote the `try` itself.
        """
        assert run_identity() == {}
        assert run_identity({"configurable": {}}) == {key: "" for key in RUN_IDENTITY_KEYS}

    def test_config_that_never_arrived_can_say_so_on_the_callers_logger(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        log = logging.getLogger("openstategraph.memory")
        with caplog.at_level(logging.DEBUG, logger="openstategraph.memory"):
            assert run_identity(log=log) == {}
        assert caplog.records, "the bug case must stay loggable where it was logged"

    def test_the_keys_and_labels_agree(self) -> None:
        assert RUN_IDENTITY_KEYS == tuple(key for key, _label in RUN_IDENTITY_FIELDS)


class TestTheReservedListIsStillOnePlace:
    """69 refuses a `settings.context` key that claims an identity key, and it
    may not carry its own copy of them to do it."""

    def test_the_refusal_reads_the_accessors_list(self) -> None:
        from openstategraph.compile.run_context import RESERVED_CONTEXT_KEYS

        assert RESERVED_CONTEXT_KEYS == RUN_IDENTITY_KEYS

    def test_prebuilt_session_reads_it_too_rather_than_restating_it(self) -> None:
        import openstategraph.prebuilt_session as prebuilt

        assert prebuilt.RUN_IDENTITY_FIELDS is RUN_IDENTITY_FIELDS


# ----------------------------------------------------- behaviour, at the doors


class TestEveryDoorStillBehaves:
    """The refactor is only a refactor if nothing downstream of it moved."""

    def test_a_memory_write_lands_in_the_namespace_the_identity_names(
        self, tmp_path: Path
    ) -> None:
        from openstategraph.api.services import WorkflowServices
        from openstategraph.mcp_server import WorkflowLibrary, WorkflowRuns
        from openstategraph.memory_segment import SEGMENT_ROOT

        root = tmp_path / "workflows"
        root.mkdir()
        services = WorkflowServices(workflows_root=root)
        WorkflowLibrary(services).save_draft("ledger-demo", "Ledger", _ledger_document())

        result = WorkflowRuns(services).run(slug="ledger-demo", question="the crossing")

        assert result["error"] is None
        assert {
            tuple(ns)
            for ns in services.memory_store.list_namespaces()
            if tuple(ns)[:1] == (SEGMENT_ROOT,)
        } == {(SEGMENT_ROOT, "ledger-demo", "crossings")}

    def test_a_run_with_no_identity_gains_none(self) -> None:
        """The inverse, and the one that matters: no fabricated person."""
        from openstategraph.memory import _user_namespace, _workflow_namespace

        assert _user_namespace() is None
        assert _workflow_namespace() is None

    def test_the_session_identity_tool_still_reads_the_run(self) -> None:
        from openstategraph.prebuilt_session import SessionIdentityTool

        tool = SessionIdentityTool()
        anonymous = tool._execute(tool.Args())
        assert "no identity" in anonymous.content


def _n(i: str, t: str, **d: Any) -> dict[str, Any]:
    return {"id": i, "type": t, "data": d, "position": {"x": 0, "y": 0}}


def _ledger_document() -> dict[str, Any]:
    return {
        "version": 2,
        "name": "Ledger",
        "nodes": [
            _n("in1", "input.text"),
            _n("seg1", "memory.segment", segment="crossings"),
            _n("out1", "output.formatted"),
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "seg1", "portId": "crossing"},
            },
            {
                "source": {"nodeId": "seg1", "portId": "onward"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    }


# ----------------------------------------------------- the census


#: Every module naming a run-identity key as a string literal, and what it is.
#:
#: `accessor` — the one module allowed to read an identity key out of a run's
#: config. `writer` — a door that *builds* `configurable`; the writer census in
#: `test_every_run_door_carries_identity.py` owns those and they are named here
#: only so this census stays complete. `transport` — a request, response or
#: CLI field carrying an identity across a wire, which is not a read of the
#: run. `checkpoint` — an identity read back off a *stored* checkpoint (its
#: config or its metadata), which is a lookup key for a run that has already
#: finished, not a claim about the run in progress.
IDENTITY_LITERAL_SITES: dict[str, str] = {
    "run_identity.py": "accessor",
    "loader.py": "writer",
    "mcp_server.py": "writer",
    "api/routes/runs.py": "writer",
    "compile/node_runtime.py": "writer",
    "memory.py": "accessor-caller",
    "api/streaming.py": "accessor-caller",
    "api/schemas.py": "transport",
    "cli.py": "transport",
    "api/threads.py": "checkpoint",
    "compile/paused_mount.py": "checkpoint",
}


#: Modules that read the run's identity, and must do it through the accessor.
#:
#: Separate from the table above because the goal is for a reader to stop
#: naming the keys at all: `prebuilt_session` iterates `RUN_IDENTITY_FIELDS`
#: and no longer contains one of the four strings anywhere, which is the end
#: state and not an omission.
ACCESSOR_CALLERS: tuple[str, ...] = (
    "memory.py",
    "api/streaming.py",
    "prebuilt_session.py",
)


def _identity_literals(tree: ast.AST) -> set[str]:
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value in set(RUN_IDENTITY_KEYS)
    }


def _string_literals(tree: ast.AST) -> set[str]:
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _reads_ambient_config(tree: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "get_config"
        for node in ast.walk(tree)
    )


def _modules() -> dict[str, ast.AST]:
    root = _package_root()
    return {
        path.relative_to(root).as_posix(): ast.parse(path.read_text(encoding="utf-8"))
        for path in root.rglob("*.py")
    }


class TestNoFifthReaderCanForget:
    """The sibling of `TestNoFifthDoorCanForget`, on the read side."""

    def test_every_module_naming_an_identity_key_is_classified(self) -> None:
        unknown = {
            module
            for module, tree in _modules().items()
            if _identity_literals(tree) and module not in IDENTITY_LITERAL_SITES
        }
        assert not unknown, (
            "a module names a run-identity key and nothing says why. If it "
            "reads one out of the run, call `openstategraph.run_identity."
            "run_identity()` instead of hand-rolling `configurable`; if it is a "
            f"wire field or a checkpoint lookup, classify it here: {sorted(unknown)}"
        )

    def test_no_classified_module_has_vanished(self) -> None:
        present = {module for module, tree in _modules().items() if _identity_literals(tree)}
        assert not set(IDENTITY_LITERAL_SITES) - present, (
            f"classified but no longer present: {sorted(set(IDENTITY_LITERAL_SITES) - present)}"
        )

    def test_only_the_accessor_reads_an_identity_key_out_of_the_run_config(self) -> None:
        """The drift `memory.py:135` and `:187` were: two readings, one fact."""
        offenders = sorted(
            module
            for module, tree in _modules().items()
            if module != "run_identity.py"
            and _identity_literals(tree)
            and _reads_ambient_config(tree)
        )
        assert not offenders, (
            "these modules pull a run-identity key straight out of `get_config()`. "
            "There is one accessor for that — `openstategraph.run_identity."
            f"run_identity()` — and it exists so these cannot disagree: {offenders}"
        )

    def test_only_the_accessor_spells_configurable_beside_an_identity_key(self) -> None:
        """The half `get_config()` alone misses.

        `api/streaming.py` reads a config it was *handed*, so it never called
        `get_config()` and the check above could not see it hand-roll the key.
        Naming `configurable` and an identity key in one module is the real
        signature of a reader, and only a door that builds the block, a
        checkpoint lookup, and the accessor itself may do it.
        """
        sanctioned = {
            module
            for module, kind in IDENTITY_LITERAL_SITES.items()
            if kind in {"accessor", "writer", "checkpoint"}
        }
        offenders = sorted(
            module
            for module, tree in _modules().items()
            if _identity_literals(tree)
            and "configurable" in _string_literals(tree)
            and module not in sanctioned
        )
        assert not offenders, (
            "these modules take a run-identity key out of a `configurable` "
            "mapping themselves. `openstategraph.run_identity.run_identity()` "
            f"is where that happens, once: {offenders}"
        )

    def test_every_accessor_caller_actually_calls_it(self) -> None:
        """The other half: classified as a caller, and it imports the thing."""
        modules = _modules()
        for module in ACCESSOR_CALLERS:
            imports = {
                node.module
                for node in ast.walk(modules[module])
                if isinstance(node, ast.ImportFrom)
            }
            assert "openstategraph.run_identity" in imports, (
                f"{module} is classified as reading identity through the accessor "
                "and does not import it"
            )
