"""What a package's `functions/` folder can and cannot bind — `export-and-eject/11`.

A discovered **tool**'s node type is slug-qualified (`<slug>/tools.QueryTool`).
A discovered **function**'s is not: `discover_function_callables` keys its
registry `function.<name>` and `NodeRuntime.builder_for` dispatches on that
prefix, so a document names `function.shout` with nothing in it saying whose.

Ticket 11 asked two questions about the consequence and this file answers both
by running it:

* **Mounts.** Measured, not assumed — a child's own function wins over a
  parent's of the same name, so the flat namespace does not cross a mount
  boundary in the case that matters.
* **Built-ins.** `function.format_report` is a built-in occupying the same flat
  namespace. A package defining `def format_report` is shadowed at both ends,
  which is the right answer and used to be a silent one.

Qualifying the runtime key was priced and rejected — see the ticket. It would
change the shape of a value already written into every document that names a
function, and buys nothing the two facts below do not already give.
"""

from __future__ import annotations

from pathlib import Path

from openstategraph.api.capability_discovery import (
    discover_function_callables,
    discover_functions,
)
from openstategraph.api.registries import runtime_warnings
from openstategraph.compile.node_runtime import NodeRuntime, PackageAssets, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler


def _package(root: Path, slug: str, source: str) -> Path:
    directory = root / slug
    (directory / "functions").mkdir(parents=True)
    (directory / "functions" / "f.py").write_text(source)
    return directory


def _document(name: str, fn_type: str) -> dict:
    return {
        "version": 2,
        "name": name,
        "nodes": [
            {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "f1", "type": fn_type, "position": {"x": 200, "y": 0}, "data": {}},
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


def _mount_document(slug: str) -> dict:
    return {
        "version": 2,
        "name": "parent",
        "nodes": [
            {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
            {
                "id": "m1",
                "type": "workflow.subgraph",
                "position": {"x": 200, "y": 0},
                "data": {"workflow": slug},
            },
            {"id": "out1", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "m1", "portId": "candidate"},
            },
            {
                "source": {"nodeId": "m1", "portId": "report"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    }


def _answer(document: dict, runtime: NodeRuntime) -> str:
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    final = graph.invoke({"question": "hi", "attempts": 0, "decisions": {}, "outputs": {}})
    return str(final["answer"])


class TestTheIdsDiscoveryMints:
    """The asymmetry itself, measured rather than read off the source."""

    def test_a_capability_id_is_slug_qualified_and_a_registry_key_is_not(
        self, tmp_path: Path
    ) -> None:
        directory = _package(tmp_path, "pkg-a", "def shout(text: str) -> str:\n    return text\n")

        assert [c.id for c in discover_functions(directory, "pkg-a")] == ["pkg-a/functions.shout"]
        assert set(discover_function_callables(directory, "pkg-a")) == {"function.shout"}

    def test_a_document_naming_what_the_registry_keys_reaches_that_package_code(
        self, tmp_path: Path
    ) -> None:
        directory = _package(
            tmp_path, "pkg-a", 'def shout(text: str) -> str:\n    return text + " [A]"\n'
        )
        runtime = NodeRuntime(functions=discover_function_callables(directory, "pkg-a"))

        assert _answer(_document("a", "function.shout"), runtime) == "hi [A]"
        assert runtime_warnings(runtime) == []


class TestTwoPackagesWithTheSameFunctionName:
    def test_each_package_binds_its_own(self, tmp_path: Path) -> None:
        a = _package(tmp_path, "pkg-a", 'def shout(text: str) -> str:\n    return text + " [A]"\n')
        b = _package(tmp_path, "pkg-b", 'def shout(text: str) -> str:\n    return text + " [B]"\n')

        assert (
            _answer(
                _document("a", "function.shout"),
                NodeRuntime(functions=discover_function_callables(a, "pkg-a")),
            )
            == "hi [A]"
        )
        assert (
            _answer(
                _document("b", "function.shout"),
                NodeRuntime(functions=discover_function_callables(b, "pkg-b")),
            )
            == "hi [B]"
        )

    def test_a_mounted_child_binds_its_own_over_the_parents(self, tmp_path: Path) -> None:
        """The ticket's "probably already safe", measured.

        The flat key is shared, but a child runtime is built with
        `{**parent.functions, **child.functions}` — the child's own last and
        therefore highest — so a mount does not hand the parent's `shout` to a
        child that ships its own.
        """
        parent = _package(
            tmp_path, "parent", 'def shout(text: str) -> str:\n    return text + " [PARENT]"\n'
        )
        child = _package(
            tmp_path, "child", 'def shout(text: str) -> str:\n    return text + " [CHILD]"\n'
        )
        child_document = _document("child", "function.shout")

        runtime = NodeRuntime(
            functions=discover_function_callables(parent, "parent"),
            document_loader=lambda slug: child_document,
            package_loader=lambda slug: PackageAssets(
                tools={},
                functions=discover_function_callables(child, "child"),
                skills_context="",
                workflow_middleware={},
                knowledge_dir=None,
            ),
        )

        assert _answer(_mount_document("child"), runtime) == "hi [CHILD]"


class TestAFunctionShadowedByABuiltIn:
    """`function.format_report` is a built-in; a package's is never called."""

    def test_the_package_function_is_reported_rather_than_vanishing(
        self, tmp_path: Path
    ) -> None:
        directory = _package(
            tmp_path,
            "pkg-a",
            'def format_report(text: str) -> str:\n    return "PKG " + text\n'
            'def shout(text: str) -> str:\n    return text\n',
        )
        runtime = NodeRuntime(functions=discover_function_callables(directory, "pkg-a"))

        warnings = [w for w in runtime_warnings(runtime) if "format_report" in w]
        assert len(warnings) == 1, runtime_warnings(runtime)
        assert "function.format_report" in warnings[0]
        assert "never" in warnings[0]
        # The function that does not collide is not reported.
        assert not [w for w in runtime_warnings(runtime) if "shout" in w]

    def test_the_built_in_still_wins_and_the_package_code_does_not_run(
        self, tmp_path: Path
    ) -> None:
        directory = _package(
            tmp_path,
            "pkg-a",
            'def format_report(text: str) -> str:\n    return "PKG " + text\n',
        )
        runtime = NodeRuntime(functions=discover_function_callables(directory, "pkg-a"))
        document = _document("a", "function.format_report")
        document["nodes"][1]["data"] = {"reportTitle": "Answer"}

        assert "PKG " not in _answer(document, runtime)
        assert runtime.builder_for("function.format_report").__name__ != "_discovered_function"

    def test_a_runtime_with_no_package_functions_reports_nothing(self) -> None:
        assert runtime_warnings(NodeRuntime(model=None)) == []


class TestAChildBindingAFunctionItsOwnPackageDoesNotShip:
    """`export-and-eject/13` — the gap the merge leaves, and it was silent.

    The merge above (`{**parent.functions, **child.functions}`) settles a
    *collision*: two packages shipping `shout` do not cross. It says nothing
    about a name only one side ships. `function.` is flat and the parent's
    registry is the base of the child's, so a child naming a function its own
    package does not ship falls through to whatever the parent happens to
    have — and the same document answers differently depending on who mounted
    it, which is exactly the condition `runtime_warnings()` exists for.

    Whether the inheritance should exist at all is `export-and-eject/14`.
    What is settled here is that it cannot happen quietly.
    """

    @staticmethod
    def _parent_and_empty_child(tmp_path: Path) -> tuple[Path, Path, dict]:
        parent = _package(
            tmp_path,
            "parent",
            'def parent_only(text: str) -> str:\n    return text + " [PARENT-LEAKED]"\n',
        )
        child = tmp_path / "child"
        (child / "functions").mkdir(parents=True)
        return parent, child, _document("child", "function.parent_only")

    @staticmethod
    def _runtime(parent: Path, child: Path, child_document: dict) -> NodeRuntime:
        return NodeRuntime(
            functions=discover_function_callables(parent, "parent"),
            document_loader=lambda slug: child_document,
            package_loader=lambda slug: PackageAssets(
                tools={},
                functions=discover_function_callables(child, "child"),
                skills_context="",
                workflow_middleware={},
                knowledge_dir=None,
            ),
        )

    def test_the_same_document_answers_differently_depending_on_who_mounted_it(
        self, tmp_path: Path
    ) -> None:
        """The leak itself, kept as the measurement the ticket was filed on."""
        parent, child, child_document = self._parent_and_empty_child(tmp_path)

        mounted = self._runtime(parent, child, child_document)
        assert _answer(_mount_document("child"), mounted) == "hi [PARENT-LEAKED]"

        alone = NodeRuntime(functions=discover_function_callables(child, "child"))
        assert _answer(child_document, alone) == "hi"

    def test_the_developer_is_told_which_function_reached_outside_the_package(
        self, tmp_path: Path
    ) -> None:
        parent, child, child_document = self._parent_and_empty_child(tmp_path)
        runtime = self._runtime(parent, child, child_document)

        _answer(_mount_document("child"), runtime)

        leaked = [w for w in runtime_warnings(runtime) if "parent_only" in w]
        assert len(leaked) == 1, runtime_warnings(runtime)
        assert "function.parent_only" in leaked[0]
        assert "child" in leaked[0]

    def test_a_child_binding_its_own_function_stays_silent(self, tmp_path: Path) -> None:
        """The inverse that makes the report worth having."""
        parent = _package(
            tmp_path, "parent", 'def shout(text: str) -> str:\n    return text + " [PARENT]"\n'
        )
        child = _package(
            tmp_path, "child", 'def shout(text: str) -> str:\n    return text + " [CHILD]"\n'
        )
        child_document = _document("child", "function.shout")
        runtime = self._runtime(parent, child, child_document)

        assert _answer(_mount_document("child"), runtime) == "hi [CHILD]"
        assert runtime_warnings(runtime) == []

    def test_a_built_in_named_by_a_child_is_not_a_leak(self, tmp_path: Path) -> None:
        """`function.format_report` is nobody's package, so nothing leaked."""
        parent = _package(
            tmp_path, "parent", "def unrelated(text: str) -> str:\n    return text\n"
        )
        child = tmp_path / "child"
        (child / "functions").mkdir(parents=True)
        child_document = _document("child", "function.format_report")
        child_document["nodes"][1]["data"] = {"reportTitle": "Answer"}
        runtime = self._runtime(parent, child, child_document)

        _answer(_mount_document("child"), runtime)
        assert runtime_warnings(runtime) == []

    def test_the_parents_own_function_node_is_unaffected(self, tmp_path: Path) -> None:
        """A parent binding its own function is not a mount question at all."""
        parent = _package(
            tmp_path, "parent", 'def shout(text: str) -> str:\n    return text + " [PARENT]"\n'
        )
        runtime = NodeRuntime(functions=discover_function_callables(parent, "parent"))

        assert _answer(_document("parent", "function.shout"), runtime) == "hi [PARENT]"
        assert runtime_warnings(runtime) == []

    def test_the_built_in_shadow_finding_is_a_different_sentence(self, tmp_path: Path) -> None:
        """`997337a`'s finding must still fire, and must not read as this one.

        Both are `CAPABILITY_FAILED` and both name a function, so the thing
        that separates them is the sentence. One says a package's code will
        never be called; the other says a child called somebody else's.
        """
        directory = _package(
            tmp_path,
            "pkg-a",
            'def format_report(text: str) -> str:\n    return "PKG " + text\n',
        )
        runtime = NodeRuntime(functions=discover_function_callables(directory, "pkg-a"))

        warnings = runtime_warnings(runtime)
        assert len(warnings) == 1, warnings
        assert "never be called" in warnings[0]
        assert "mounted" not in warnings[0]

    def test_a_child_falling_back_to_the_parents_assets_wholesale_is_not_reported(
        self, tmp_path: Path
    ) -> None:
        """No `package_loader` is the documented honest fallback, not a leak.

        When the loader is absent the child is built from the parent's own
        assets deliberately — there is no child registry to have reached
        outside of, so there is nothing here a developer could act on.
        """
        parent = _package(
            tmp_path,
            "parent",
            'def parent_only(text: str) -> str:\n    return text + " [PARENT-LEAKED]"\n',
        )
        child_document = _document("child", "function.parent_only")
        runtime = NodeRuntime(
            functions=discover_function_callables(parent, "parent"),
            document_loader=lambda slug: child_document,
        )

        assert _answer(_mount_document("child"), runtime) == "hi [PARENT-LEAKED]"
        assert runtime_warnings(runtime) == []
