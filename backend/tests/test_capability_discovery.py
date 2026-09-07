"""Capability discovery (ticket 18): `tools/`/`functions/` -> the editor.

Every test writes real `.py` files into a `tmp_path` workflow directory and
imports them for real — the whole point being proven is that a developer's
own file, on disk, becomes a discoverable capability, not a fixture standing
in for one.
"""

from __future__ import annotations

import sys
from pathlib import Path

from openstategraph.abc.tool import BaseTool
from openstategraph.api.capability_discovery import (
    discover_functions,
    discover_tool_instances,
    discover_tools,
)


TOOL_SOURCE = '''\
from openstategraph.abc.tool import BaseTool, ToolResult
from pydantic import BaseModel


class GreetArgs(BaseModel):
    name: str


class GreetTool(BaseTool):
    name = "greet"
    description = "Greets someone by name."
    Args = GreetArgs

    def _execute(self, args: GreetArgs) -> ToolResult:
        return ToolResult(content=f"Hello, {args.name}!")
'''


def write(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)


class TestDiscoverTools:
    def test_finds_a_basetool_subclass_and_reads_its_schema(self, tmp_path: Path) -> None:
        write(tmp_path / "tools" / "greet.py", TOOL_SOURCE)

        found = discover_tools(tmp_path, slug="my-flow")

        assert len(found) == 1
        tool = found[0]
        assert tool.id == "my-flow/tools.GreetTool"
        assert tool.name == "greet"
        assert tool.description == "Greets someone by name."
        assert "name" in tool.args_schema["properties"]

    def test_an_empty_or_missing_tools_folder_returns_nothing(self, tmp_path: Path) -> None:
        assert discover_tools(tmp_path, slug="x") == []
        (tmp_path / "tools").mkdir()
        assert discover_tools(tmp_path, slug="x") == []

    def test_a_leading_underscore_file_is_skipped(self, tmp_path: Path) -> None:
        write(tmp_path / "tools" / "_helper.py", TOOL_SOURCE)
        assert discover_tools(tmp_path, slug="x") == []

    def test_a_syntax_error_in_one_file_does_not_blank_the_others(self, tmp_path: Path) -> None:
        write(tmp_path / "tools" / "broken.py", "this is not python (((")
        write(tmp_path / "tools" / "greet.py", TOOL_SOURCE)

        found = discover_tools(tmp_path, slug="x")
        assert [t.name for t in found] == ["greet"]

    def test_a_reexport_through_init_is_not_double_counted(self, tmp_path: Path) -> None:
        write(tmp_path / "tools" / "greet.py", TOOL_SOURCE)
        write(
            tmp_path / "tools" / "__init__.py",
            "from .greet import GreetTool\n",
        )

        found = discover_tools(tmp_path, slug="x")
        # __init__.py itself is scanned too (it is not underscore-*prefixed*
        # in the sense that matters — glob("*.py") includes it), but the
        # class it re-exports is only ever counted once, from the module it
        # was actually *defined* in.
        assert len([t for t in found if t.name == "greet"]) == 1

    def test_two_workflows_with_an_identically_named_file_do_not_collide(
        self, tmp_path: Path
    ) -> None:
        first = tmp_path / "first"
        second = tmp_path / "second"
        write(first / "tools" / "greet.py", TOOL_SOURCE)
        write(second / "tools" / "greet.py", TOOL_SOURCE)

        found_first = discover_tools(first, slug="first")
        found_second = discover_tools(second, slug="second")

        assert found_first[0].id == "first/tools.GreetTool"
        assert found_second[0].id == "second/tools.GreetTool"

    def test_the_abstract_base_itself_is_never_discovered(self, tmp_path: Path) -> None:
        write(
            tmp_path / "tools" / "abstract_only.py",
            "from openstategraph.abc.tool import BaseTool\n",
        )
        assert discover_tools(tmp_path, slug="x") == []


class TestDiscoverFunctions:
    def test_finds_a_top_level_function_with_its_signature_and_docstring(
        self, tmp_path: Path
    ) -> None:
        write(
            tmp_path / "functions" / "share.py",
            'def share_of_total(part: float, total: float) -> float:\n'
            '    """The fraction `part` is of `total`."""\n'
            "    return part / total\n",
        )

        found = discover_functions(tmp_path, slug="my-flow")

        assert len(found) == 1
        fn = found[0]
        assert fn.id == "my-flow/functions.share_of_total"
        assert fn.docstring == "The fraction `part` is of `total`."
        assert "part" in fn.signature

    def test_a_private_helper_function_is_not_discovered(self, tmp_path: Path) -> None:
        write(
            tmp_path / "functions" / "helpers.py",
            "def _internal_helper():\n    pass\n\n\ndef public_one():\n    pass\n",
        )
        found = discover_functions(tmp_path, slug="x")
        assert [f.name for f in found] == ["public_one"]

    def test_an_imported_function_is_not_rediscovered_as_local(self, tmp_path: Path) -> None:
        write(tmp_path / "functions" / "real.py", "def real_fn():\n    pass\n")
        write(
            tmp_path / "functions" / "reexport.py",
            "from .real import real_fn\n",
        )
        found = discover_functions(tmp_path, slug="x")
        assert len([f for f in found if f.name == "real_fn"]) == 1


class TestTheInvalidationPolicy:
    """The recorded answer to "cache or not" (gap PF-01, ticket 10).

    The policy is **no cache: every call re-executes the module**, and these
    tests pin the three properties that make that the right answer rather
    than merely the current one. They are written so that adding a cache
    fails here loudly, in the place the decision is recorded, instead of
    silently trading a property for milliseconds.

    See `_import_module`'s docstring for the reasoning and the measurement.
    """

    def test_an_edited_tool_takes_effect_on_the_very_next_call(self, tmp_path: Path) -> None:
        """The property a cache would cost, stated as a test.

        A workflow package is *files on disk*. A developer who edits one and
        reloads the capabilities panel expects to see the edit — that is the
        whole loop. Any cache keyed on anything coarser than the file's
        content turns this green test red, which is the point of writing it.

        **The two replacement strings are the same byte length on purpose**,
        and the two writes land in the same second. That is precisely the
        edit CPython's own `__pycache__` used to serve stale, because a
        `.pyc` is validated against `(source mtime in whole seconds, source
        size)` and this edit changes neither. It is written this way so the
        test fails against the bug it was found by, rather than against a
        length change any cache would have noticed.
        """
        write(tmp_path / "tools" / "greet.py", TOOL_SOURCE)
        assert discover_tools(tmp_path, slug="x")[0].description == "Greets someone by name."

        write(
            tmp_path / "tools" / "greet.py",
            TOOL_SOURCE.replace("Greets someone by name.", "Greets someone, warmly."),
        )
        assert discover_tools(tmp_path, slug="x")[0].description == "Greets someone, warmly."

    def test_a_discovered_tool_is_always_an_instance_of_the_shared_base(
        self, tmp_path: Path
    ) -> None:
        """The invariant the `isinstance` hazard is actually about.

        Re-executing a *workflow* module is safe because the module's
        `from openstategraph.abc.tool import BaseTool` resolves through
        `sys.modules` to the one base object, however many times the leaf is
        executed. The hazard in `_import_module`'s docstring belongs to
        `importlib.reload` of the **base**, which nothing here does and
        nothing here may start doing — caching the leaf never fixes it and
        not caching the leaf never causes it.
        """
        write(tmp_path / "tools" / "greet.py", TOOL_SOURCE)

        first = discover_tool_instances(tmp_path, slug="x")
        second = discover_tool_instances(tmp_path, slug="x")

        assert first and second
        for _, instance in first + second:
            assert isinstance(instance, BaseTool)

        # And the identity a cache would be "protecting" is already gone: two
        # calls yield two distinct class objects today. So nothing in the
        # codebase can be relying on cross-call class identity — anything that
        # did would already be broken, not broken by this decision.
        assert type(first[0][1]) is not type(second[0][1])

    def test_discovery_never_registers_a_workflow_module_in_sys_modules(
        self, tmp_path: Path
    ) -> None:
        """Why re-execution stays bounded rather than accumulating.

        `module_from_spec` + `exec_module` without a `sys.modules` entry means
        each execution is self-contained and collectable, and two workflows
        that both ship `tools/db.py` can never shadow one another. A cache is
        not needed to stop a leak, because there is no leak to stop.
        """
        write(tmp_path / "tools" / "greet.py", TOOL_SOURCE)
        before = set(sys.modules)

        discover_tools(tmp_path, slug="leaky-flow")

        assert not [name for name in set(sys.modules) - before if "leaky-flow" in name]

    def test_discovery_leaves_no_pycache_in_the_workflow_package(self, tmp_path: Path) -> None:
        """The visible half of the same decision.

        Compiling the source here instead of handing it to the loader means a
        developer's `tools/` folder never grows a `__pycache__` it did not ask
        for — the stale bytecode simply has nowhere to live.
        """
        write(tmp_path / "tools" / "greet.py", TOOL_SOURCE)

        discover_tools(tmp_path, slug="x")

        assert not list(tmp_path.rglob("__pycache__"))
