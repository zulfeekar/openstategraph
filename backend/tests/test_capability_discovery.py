"""Capability discovery (ticket 18): `tools/`/`functions/` -> the editor.

Every test writes real `.py` files into a `tmp_path` workflow directory and
imports them for real — the whole point being proven is that a developer's
own file, on disk, becomes a discoverable capability, not a fixture standing
in for one.
"""

from __future__ import annotations

from pathlib import Path

from openstategraph.api.capability_discovery import discover_functions, discover_tools


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
