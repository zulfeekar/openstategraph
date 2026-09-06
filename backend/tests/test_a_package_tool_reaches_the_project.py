"""A package `tools/` module that imports the host project's own code.

`launch-readiness/195`. This is the adopted-codebase case, not an exotic one:
`docs/building-an-atom.md` recommends `tools/` for exactly the capability that
reaches something the project already owns, and anything a project already
owns is imported by module name — `from myapp.inventory import stock_level`.

Measured before it was ruled on. The same package, from the same directory:

| Invocation | Answer |
| --- | --- |
| `python -c "load_workflow(...)"` at the project root | no warnings |
| `openstategraph validate workflows/stock-agent` | exit 1, three problems |
| `PYTHONPATH=. openstategraph validate …` | `VALID`, exit 0 |

The mechanism is ordinary: `python script.py` and `python -c` put the
invocation directory on `sys.path`; a console script installed into a
virtualenv does not. So the pre-flight check and the run disagreed about one
package, which is the single thing `validate` exists to prevent.

## Two things are pinned here, and only one of them is a behaviour change

**The message.** The remedy printed was *"Copy the package's `tools/` folder
next to workflow.json"* — and the folder was already there; that is how
discovery found the module it then failed to import. A reader who follows that
advice literally moves a directory to where it already is, sees no change, and
concludes the tool system is broken. `CLAUDE.md`'s standing rule is that an id
that resolves to nothing is reported **by name**; this message named the wrong
noun entirely. It is wrong regardless of how the second question is answered,
so it is fixed first and separately.

**The path.** Whether the CLI makes the project root importable. The answer
taken, and the prior art it rests on, is argued in
`docs/decisions/importing-the-projects-own-code.md`; the short form is that
nothing is injected implicitly — pytest's own rule is that *"rootdir is NOT
used to modify sys.path/PYTHONPATH or influence how modules are imported"* —
and the opt-in is a key in the committed config file, which is Alembic's
`prepend_sys_path` verbatim, for the defect its own changelog describes in our
words: *"running the alembic command line would not place the local '.' path
in sys.path, meaning an application locally present in '.' and importable
through normal channels, e.g. python interpreter, pytest, etc. would not be
located"*.

The two properties that make the opt-in defensible rather than a hidden hack
are each a test below: it is **committed** (it lives in a file under version
control, so `grep` finds it and review sees it), and it is **process-level**
(`console_main` applies it, `main` does not — the same boundary `.env` already
observes one line up, for the same reason: a function anyone can call must not
rewrite the interpreter under the caller).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from openstategraph import cli, config_file
from openstategraph.api.capability_discovery import discover_tool_instances
from openstategraph.validation import unresolved_tool_bindings

#: What the package's tool needs and this interpreter has never heard of.
HOST_MODULE = "myapp_195_host"

#: The sentence this ticket exists to delete from the wrong case.
COPY_THE_FOLDER = "Copy the package's tools/ folder next to workflow.json"


def _document(tool_type: str = "tool.stock-level") -> dict[str, Any]:
    return {
        "version": 1,
        "name": "stock-agent",
        "settings": {},
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 0, "y": 0}},
            {"id": "a1", "type": "agent.llm", "data": {}, "position": {"x": 4, "y": 0}},
            {"id": "t1", "type": tool_type, "data": {}, "position": {"x": 4, "y": 6}},
            {"id": "out1", "type": "output.formatted", "data": {}, "position": {"x": 9, "y": 0}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "a1", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "t1", "portId": "tool"},
                "target": {"nodeId": "a1", "portId": "tools"},
            },
            {
                "source": {"nodeId": "a1", "portId": "result"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    }


TOOL_SOURCE = f"""\
from {HOST_MODULE}.inventory import stock_level

from openstategraph.abc.tool import BaseTool, NoArgs, ToolResult


class StockLevelTool(BaseTool):
    name = 'stock_level'
    description = 'How many units of a SKU are in stock.'
    node_type = 'tool.stock-level'
    Args = NoArgs

    def _execute(self, args):
        return ToolResult(content=str(stock_level('widget')))
"""


def _project(root: Path, *, with_host: bool = False, with_tools: bool = True) -> Path:
    """A project directory holding one package whose tool imports the project."""
    package = root / "workflows" / "stock-agent"
    package.mkdir(parents=True)
    (package / "workflow.json").write_text(
        json.dumps(
            {"version": 1, "name": "stock-agent", "savedAt": "", "document": _document()}
        )
    )
    if with_tools:
        tools = package / "tools"
        tools.mkdir()
        (tools / "stock.py").write_text(TOOL_SOURCE)
    if with_host:
        host = root / HOST_MODULE
        host.mkdir()
        (host / "__init__.py").write_text("")
        (host / "inventory.py").write_text("def stock_level(sku):\n    return 42\n")
    return package


class TestTheMessageNamesTheRealCause:
    """The half that is wrong however the path question is answered."""

    def test_the_import_failure_names_the_module_that_was_missing(
        self, tmp_path: Path
    ) -> None:
        package = _project(tmp_path)
        warnings: list[str] = []

        discover_tool_instances(package, "stock-agent", warnings=warnings)

        assert warnings, "a tool module that will not import must be surfaced"
        assert HOST_MODULE in warnings[0], (
            "the exception said `No module named 'myapp'` and the warning must too — "
            f"got {warnings[0]!r}"
        )

    def test_the_import_failure_says_it_is_not_a_file_placement_problem(
        self, tmp_path: Path
    ) -> None:
        package = _project(tmp_path)
        warnings: list[str] = []

        discover_tool_instances(package, "stock-agent", warnings=warnings)

        # The reader's next move is a path/install question. Say so, in the
        # sentence, rather than leaving them to infer it from a traceback.
        assert "sys.path" in warnings[0] or "importable" in warnings[0]
        assert "pip install -e" in warnings[0]

    def test_the_binding_finding_does_not_send_the_reader_to_move_a_folder(
        self, tmp_path: Path
    ) -> None:
        """The ticket's own `Done when`."""
        package = _project(tmp_path)

        findings = unresolved_tool_bindings(_document(), package)

        assert findings, "the tool still has no implementation, so it is still a finding"
        assert COPY_THE_FOLDER not in findings[0], (
            "the folder IS next to workflow.json — that is how discovery found the "
            f"module it then failed to import. Got: {findings[0]!r}"
        )

    def test_a_package_with_no_tools_folder_still_gets_the_copy_advice(
        self, tmp_path: Path
    ) -> None:
        """The other half: that remedy is right when nothing was found at all.

        Deleting it outright would trade one misdirection for another — this
        is the case the sentence was written for, and it stays.
        """
        package = _project(tmp_path, with_tools=False)

        findings = unresolved_tool_bindings(_document(), package)

        assert findings and COPY_THE_FOLDER in findings[0]


@pytest.fixture
def real_config_search(monkeypatch: pytest.MonkeyPatch) -> None:
    """`conftest` points `OPENSTATEGRAPH_CONFIG` at a file that is not there.

    Deliberately, so a developer's exported config cannot decide the suite —
    but it short-circuits `find_config_file` before the upward walk, and the
    walk is half of what these tests are about.
    """
    monkeypatch.delenv("OPENSTATEGRAPH_CONFIG", raising=False)


@pytest.mark.usefixtures("real_config_search")
class TestTheOptIn:
    """`prepend_sys_path:` — committed, explicit, and off unless asked for."""

    def test_nothing_is_prepended_by_default(self, tmp_path: Path) -> None:
        _project(tmp_path, with_host=True)
        (tmp_path / "openstategraph.yaml").write_text("version: 1\n")
        before = list(sys.path)

        added = config_file.apply_prepend_sys_path(tmp_path)

        assert added == []
        assert sys.path == before

    def test_a_declared_path_is_resolved_against_the_config_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Relative to the file, never to the directory you are standing in.

        The same rule `workflows_dir:` already follows, and for the same
        reason: the file is committed and shared, so its meaning cannot depend
        on which subdirectory a colleague ran the command from.
        """
        _project(tmp_path, with_host=True)
        (tmp_path / "openstategraph.yaml").write_text('version: 1\nprepend_sys_path: ["."]\n')
        monkeypatch.setattr(sys, "path", list(sys.path))

        added = config_file.apply_prepend_sys_path(tmp_path / "workflows" / "stock-agent")

        assert added == [tmp_path.resolve()]
        assert sys.path[0] == str(tmp_path.resolve())

    def test_it_is_what_makes_the_package_resolve(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The end-to-end claim, both directions, in one test."""
        package = _project(tmp_path, with_host=True)
        (tmp_path / "openstategraph.yaml").write_text('version: 1\nprepend_sys_path: ["."]\n')
        monkeypatch.setattr(sys, "path", list(sys.path))

        assert unresolved_tool_bindings(_document(), package), "unresolved before"
        config_file.apply_prepend_sys_path(tmp_path)
        assert unresolved_tool_bindings(_document(), package) == [], "resolved after"

    def test_a_directory_that_is_not_there_is_not_silently_added(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "openstategraph.yaml").write_text('version: 1\nprepend_sys_path: ["nope"]\n')
        monkeypatch.setattr(sys, "path", list(sys.path))

        assert config_file.apply_prepend_sys_path(tmp_path) == []


class TestItIsAProcessLevelAct:
    """`console_main` may rewrite `sys.path`; `main` may not.

    Exactly the boundary `console_main`'s own docstring already draws around
    `.env`: a **process** the user launched may reconfigure their interpreter
    from a file on disk; a **function** this project's tests call in-process
    may not, or every test that runs afterwards inherits it.
    """

    def test_main_does_not_touch_sys_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[object] = []
        monkeypatch.setattr(
            config_file, "apply_prepend_sys_path", lambda *a, **k: called.append(a) or []
        )

        cli.main(["env-example"])

        assert called == []

    def test_console_main_does(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[object] = []
        monkeypatch.setattr(
            config_file, "apply_prepend_sys_path", lambda *a, **k: called.append(a) or []
        )
        monkeypatch.setattr(cli, "main", lambda: 0)

        cli.console_main()

        assert called, "the installed command must apply the project's declared paths"


class TestTheGeneratedProjectDeclaresIt:
    """`init` writes the key, which is what makes the opt-in discoverable.

    Alembic's precedent exactly: *"the default value in newly generated
    alembic.ini files is `.`"*. A setting nobody knows about is not an opt-in,
    it is a footnote — and the whole argument for choosing a committed config
    key over an implicit injection is that a reader can see it.
    """

    def test_the_rendered_config_names_it(self) -> None:
        rendered = config_file.render_config_file()

        assert "prepend_sys_path" in rendered

    def test_the_rendered_config_still_parses(self, tmp_path: Path) -> None:
        path = tmp_path / "openstategraph.yaml"
        path.write_text(config_file.render_config_file())

        assert config_file.load_config(path).prepend_sys_path == ["."]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
