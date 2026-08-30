"""A compiled workflow a host holds notices its own package changing.

`scale-and-adopt/14`, which is `scale-and-adopt/12`'s recorded cost turned into
a mechanism. Ticket 12 left this sentence in `docs/adoption.md`:

> if you cache the compiled object (and you should), an edit reaches your
> service when you drop that cache, and otherwise on restart

...and gave an adopter nothing to drop it *with*. The loop that leaves is
`edit -> restart -> look`, which is the difference between a workflow editor
and a workflow file editor.

**This is not the cache `launch-readiness/113` declined**, and the distinction
is the whole reason a second attempt is allowed. That decision measured our own
request path at 27 ms warm and refused to buy it with a staleness class
(`docs/decisions/per-request-compile-cost.md`); this repository's server still
compiles per request and this ticket does not change that. What ships here is
for the *host* that already holds a compiled object for the life of its
process, whether it wanted to or not — the 27 ms argument never applied to it,
because a host is not paying 27 ms, it is paying a restart.

The invalidation list that decision recorded is the specification, and the
mechanism has to cover all of it: the document, `tools/`, `functions/`,
`middlewares/`, `skills/`, `knowledge/`, a capability refresh, and every
mounted child transitively.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from openstategraph.live import LiveWorkflows


def _document(name: str) -> dict[str, Any]:
    """Three nodes, one package function, no model anywhere in it."""
    return {
        "version": 2,
        "name": name,
        "nodes": [
            {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "f1", "type": "function.shout", "position": {"x": 200, "y": 0}, "data": {}},
            {"id": "out1", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "f1", "portId": "candidate"},
            },
            {
                "source": {"nodeId": "f1", "portId": "report"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    }


def _package(root: Path, slug: str, *, suffix: str, name: str = "shouter") -> Path:
    directory = root / slug
    (directory / "functions").mkdir(parents=True, exist_ok=True)
    (directory / "functions" / "f.py").write_text(
        f'def shout(text: str) -> str:\n    return text + " {suffix}"\n'
    )
    (directory / "workflow.json").write_text(json.dumps(_document(name)))
    return directory


def _rename_the_function_node(directory: Path, function_type: str) -> None:
    """Edit the *document* only — the package's Python is untouched."""
    document = json.loads((directory / "workflow.json").read_text())
    for node in document["nodes"]:
        if node["id"] == "f1":
            node["type"] = function_type
    (directory / "workflow.json").write_text(json.dumps(document))


@pytest.fixture()
def closed(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Every `CompiledWorkflow` somebody closed, in order.

    A spy rather than a member on `LiveWorkflows`: "what have you released" is
    a question only a test asks, and a public member that exists to answer it
    is a public member.
    """
    from openstategraph.loader import CompiledWorkflow

    seen: list[Any] = []
    original = CompiledWorkflow.close

    def recording(self: Any) -> None:
        seen.append(self)
        original(self)

    monkeypatch.setattr(CompiledWorkflow, "close", recording)
    return seen


@pytest.fixture()
def live(tmp_path: Path) -> Any:
    with LiveWorkflows(tmp_path) as held:
        yield held


class TestADocumentChange:
    def test_an_edit_on_disk_reaches_the_next_ask_with_no_restart(
        self, tmp_path: Path, live: LiveWorkflows
    ) -> None:
        _package(tmp_path, "shouter", suffix="[ONE]")
        (tmp_path / "shouter" / "functions" / "g.py").write_text(
            'def whisper(text: str) -> str:\n    return text + " [WHISPERED]"\n'
        )

        with live.use("shouter") as workflow:
            assert workflow.ask("hi").answer == "hi [ONE]"

        _rename_the_function_node(tmp_path / "shouter", "function.whisper")

        with live.use("shouter") as workflow:
            assert workflow.ask("hi").answer == "hi [WHISPERED]"

    def test_an_unchanged_package_is_the_same_object(
        self, tmp_path: Path, live: LiveWorkflows
    ) -> None:
        _package(tmp_path, "shouter", suffix="[ONE]")

        with live.use("shouter") as first:
            assert first.ask("hi").answer == "hi [ONE]"
        # A run writes checkpoints and memories, and none of it lands in the
        # package — `scale-and-adopt/03`. If any of it did, asking would
        # retire the graph that answered, and every request would recompile.
        with live.use("shouter") as second:
            assert second is first


class TestAPackageCodeChange:
    """The channel `workflow.json` cannot see, and the one 113's trap named."""

    def test_editing_the_packages_python_reaches_the_next_ask(
        self, tmp_path: Path, live: LiveWorkflows
    ) -> None:
        _package(tmp_path, "shouter", suffix="[ONE]")

        with live.use("shouter") as workflow:
            assert workflow.ask("hi").answer == "hi [ONE]"

        _package(tmp_path, "shouter", suffix="[TWO]")

        with live.use("shouter") as workflow:
            assert workflow.ask("hi").answer == "hi [TWO]"

    def test_an_edit_of_the_same_length_in_the_same_second_is_not_missed(
        self, tmp_path: Path, live: LiveWorkflows
    ) -> None:
        """The defect `capability_discovery._import_module` already refused.

        `(mtime in whole seconds, size)` is `__pycache__`'s key and it is blind
        to this edit. A stamp that used it would reintroduce the staleness that
        function exists to have removed, one layer up.
        """
        _package(tmp_path, "shouter", suffix="[ONE]")
        source = tmp_path / "shouter" / "functions" / "f.py"
        before = source.stat()
        with live.use("shouter") as workflow:
            assert workflow.ask("hi").answer == "hi [ONE]"

        _package(tmp_path, "shouter", suffix="[TWO]")
        # The same byte length, and now the same mtime to the nanosecond — so
        # the only thing that can tell these two files apart is their content.
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        assert source.stat().st_size == before.st_size
        assert source.stat().st_mtime_ns == before.st_mtime_ns

        with live.use("shouter") as workflow:
            assert workflow.ask("hi").answer == "hi [TWO]"


class TestAMountedChild:
    """A mount is by reference, so a child is an input to the parent's graph."""

    def _parent(self, root: Path, child_slug: str) -> None:
        directory = root / "parent"
        directory.mkdir(parents=True, exist_ok=True)
        directory.joinpath("workflow.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "name": "parent",
                    "nodes": [
                        {"id": "in1", "type": "input.text",
                         "position": {"x": 0, "y": 0}, "data": {}},
                        {"id": "m1", "type": "workflow.subgraph",
                         "position": {"x": 200, "y": 0},
                         "data": {"workflow": child_slug}},
                        {"id": "out1", "type": "output.formatted",
                         "position": {"x": 400, "y": 0}, "data": {}},
                    ],
                    "edges": [
                        {"source": {"nodeId": "in1", "portId": "text"},
                         "target": {"nodeId": "m1", "portId": "candidate"}},
                        {"source": {"nodeId": "m1", "portId": "report"},
                         "target": {"nodeId": "out1", "portId": "result"}},
                    ],
                }
            )
        )

    def test_editing_the_child_reaches_a_held_parent(
        self, tmp_path: Path, live: LiveWorkflows
    ) -> None:
        _package(tmp_path, "child", suffix="[CHILD ONE]", name="child")
        self._parent(tmp_path, "child")

        with live.use("parent") as workflow:
            assert "[CHILD ONE]" in workflow.ask("hi").answer

        _package(tmp_path, "child", suffix="[CHILD TWO]", name="child")

        with live.use("parent") as workflow:
            assert "[CHILD TWO]" in workflow.ask("hi").answer


class TestARunInFlight:
    """The defect that appears as a wrong answer rather than a crash."""

    def test_a_lease_taken_before_the_edit_keeps_the_graph_it_started_with(
        self, tmp_path: Path, live: LiveWorkflows
    ) -> None:
        _package(tmp_path, "shouter", suffix="[ONE]")

        with live.use("shouter") as in_flight:
            _package(tmp_path, "shouter", suffix="[TWO]")
            # A second asker gets the new graph...
            with live.use("shouter") as fresh:
                assert fresh is not in_flight
                assert fresh.ask("hi").answer == "hi [TWO]"
            # ...and the run that was already going is untouched and still
            # usable: nothing closed the graph under it.
            assert in_flight.ask("hi").answer == "hi [ONE]"

    def test_the_superseded_graph_is_released_when_its_last_lease_ends(
        self, tmp_path: Path, live: LiveWorkflows, closed: list[Any]
    ) -> None:
        """Released, and not one instant sooner.

        Closing a superseded workflow while a run is inside it closes the
        sqlite handles that run is checkpointing against — a failed run, or a
        half-written thread, rather than anything a happy-path test would see.
        """
        _package(tmp_path, "shouter", suffix="[ONE]")
        with live.use("shouter") as in_flight:
            _package(tmp_path, "shouter", suffix="[TWO]")
            with live.use("shouter"):
                pass
            assert closed == []
        assert closed == [in_flight]


class TestTwoRequestsDuringAnInvalidation:
    def test_they_compile_once_and_see_one_graph(
        self, tmp_path: Path, live: LiveWorkflows
    ) -> None:
        _package(tmp_path, "shouter", suffix="[ONE]")
        with live.use("shouter"):
            pass
        _package(tmp_path, "shouter", suffix="[TWO]")

        seen: list[Any] = []
        start = threading.Barrier(4)

        def ask() -> None:
            start.wait(timeout=10)
            with live.use("shouter") as workflow:
                seen.append(workflow)

        threads = [threading.Thread(target=ask) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert len(seen) == 4
        assert len({id(workflow) for workflow in seen}) == 1


class TestASecondProcess:
    """The arrangement an in-process event cannot cover."""

    def test_a_write_by_a_process_that_did_no_saving_is_still_noticed(
        self, tmp_path: Path, live: LiveWorkflows
    ) -> None:
        _package(tmp_path, "shouter", suffix="[ONE]")
        with live.use("shouter") as workflow:
            assert workflow.ask("hi").answer == "hi [ONE]"

        subprocess.run(
            [
                sys.executable,
                "-c",
                "import pathlib, sys;"
                "pathlib.Path(sys.argv[1]).write_text("
                "'def shout(text: str) -> str:\\n    return text + \" [BY ANOTHER PROCESS]\"\\n')",
                str(tmp_path / "shouter" / "functions" / "f.py"),
            ],
            check=True,
        )

        with live.use("shouter") as workflow:
            assert workflow.ask("hi").answer == "hi [BY ANOTHER PROCESS]"


class TestTheHostsOwnSignal:
    def test_invalidate_forces_one_recompile_and_never_keeps_a_stale_graph(
        self, tmp_path: Path, live: LiveWorkflows
    ) -> None:
        _package(tmp_path, "shouter", suffix="[ONE]")
        with live.use("shouter") as first:
            pass

        live.invalidate("shouter")

        with live.use("shouter") as second:
            assert second is not first
            assert second.ask("hi").answer == "hi [ONE]"


class TestTheLineBetweenAPackageAndTheCodeAroundIt:
    """Where "no restart" stops, measured rather than promised.

    A package's own `functions/f.py` is re-executed from its source bytes on
    every compile and never enters `sys.modules`, so editing it lands. A module
    that file *imports* is held by the interpreter for the life of the process,
    and `importlib.reload` on it is refused for the reason
    `capability_discovery._import_module` records — a reloaded base stops
    `isinstance`-matching the instances made from the old one. So the line runs
    at the package directory, and the product has to say so rather than let an
    adopter find it as a bug.
    """

    def test_a_module_the_package_imports_is_not_re_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        library = tmp_path / "lib"
        library.mkdir()
        (library / "house_rules.py").write_text('SUFFIX = "[FIRST]"\n')
        monkeypatch.syspath_prepend(str(library))
        monkeypatch.delitem(sys.modules, "house_rules", raising=False)

        packages = tmp_path / "workflows"
        _package(packages, "shouter", suffix="ignored")
        (packages / "shouter" / "functions" / "f.py").write_text(
            "import house_rules\n\n"
            "def shout(text: str) -> str:\n"
            "    return text + ' ' + house_rules.SUFFIX\n"
        )

        with LiveWorkflows(packages) as live:
            with live.use("shouter") as workflow:
                assert workflow.ask("hi").answer == "hi [FIRST]"

            (library / "house_rules.py").write_text('SUFFIX = "[SECOND]"\n')
            live.invalidate("shouter")

            with live.use("shouter") as workflow:
                # Recompiled — and still answering from the module the
                # interpreter loaded once. This is the restart case.
                assert workflow.ask("hi").answer == "hi [FIRST]"

    def test_the_documentation_draws_the_same_line(self) -> None:
        """The product says it, in the place an adopter is already reading."""
        adoption = (
            Path(__file__).resolve().parents[2] / "docs" / "adoption.md"
        ).read_text()

        assert "LiveWorkflows" in adoption
        section = adoption[adoption.index("LiveWorkflows") :]
        for claim in ("sys.modules", "restart", "pip install"):
            assert claim in section, claim
