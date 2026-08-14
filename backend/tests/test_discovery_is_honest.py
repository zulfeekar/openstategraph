"""Ticket 07 / register RC-04: a capability that fails to load says so.

The bug this file exists to keep fixed: `BaseTool._execute` is abstract, and
`ITool` publicly advertises `run(**kwargs)`. A third party who implemented the
advertised method shipped a tool that installed, validated, ran — and was
simply *absent*, because `discover_tool_instances` skipped abstract classes
without a word. Entry-point plugins aimed that failure shape outward.

Every test below asserts on the **user-visible** text, not on a log record:
a developer who never opens a server log still has to see it, so discovery
findings ride the same channel unresolved tools already use
(`runtime_warnings()` -> the run response -> `CompiledWorkflow.warnings` ->
the CLI). The log line is kept as well, and a couple of tests pin that too.
"""

from __future__ import annotations

import importlib.metadata
import logging
from pathlib import Path
from typing import Any

import pytest

from types import SimpleNamespace

from openstategraph.compile.diagnostics import CompileDiagnostics, Finding
from openstategraph.abc import BaseTool, NoArgs, ToolResult
from openstategraph.api.capability_discovery import (
    discover_tool_instances,
    discover_tool_registry,
)


GOOD_TOOL = '''\
from openstategraph.abc import BaseTool, NoArgs, ToolResult


class GoodTool(BaseTool):
    name = "good"
    description = "Implements _execute, like the docs say."
    node_type = "tool.good"
    Args = NoArgs

    def _execute(self, args) -> ToolResult:
        return ToolResult(content="good")
'''


def write(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)


def discover(workflow_dir: Path, slug: str = "my-flow") -> tuple[list[Any], list[str]]:
    warnings: list[str] = []
    found = discover_tool_instances(workflow_dir, slug, warnings=warnings)
    return found, warnings


class TestTheRunOverrideTrap:
    """The specific case RC-04 names, and the one that must never be
    diagnosed generically: "skipped an abstract class" leaves the reader
    exactly as stuck as silence did."""

    SOURCE = '''\
from openstategraph.abc import BaseTool, NoArgs, ToolResult


class AcmePing(BaseTool):
    name = "acme_ping"
    description = "Overrides the method ITool advertises."
    node_type = "tool.acme-ping"
    Args = NoArgs

    def run(self, **kwargs) -> ToolResult:
        return ToolResult(content="pong")
'''

    def test_defining_such_a_class_fails_at_import(self) -> None:
        """The earliest honest moment. Such a class is *already* unusable —
        it is abstract, so it can never be instantiated — so refusing it at
        definition time cannot break anything that works today."""
        namespace: dict[str, Any] = {}
        with pytest.raises(TypeError) as excinfo:
            exec(self.SOURCE, namespace)

        message = str(excinfo.value)
        assert "AcmePing" in message
        assert "_execute(self, args)" in message
        assert "run()" in message

    def test_discovery_names_the_class_the_method_and_the_fix(self, tmp_path: Path) -> None:
        write(tmp_path / "tools" / "acme.py", self.SOURCE)

        found, warnings = discover(tmp_path)

        assert found == []
        assert len(warnings) == 1
        assert "AcmePing" in warnings[0]
        assert "_execute(self, args)" in warnings[0]
        assert "acme.py" in warnings[0]

    def test_an_intermediate_base_may_still_wrap_run(self, tmp_path: Path) -> None:
        """The escape hatch, and the reason the definition-time check is not a
        blanket ban: re-declaring `_execute` as abstract says "I know what I am
        doing, my subclasses supply the work"."""
        write(
            tmp_path / "tools" / "logged.py",
            "from abc import abstractmethod\n"
            "from openstategraph.abc import BaseTool, NoArgs, ToolResult\n"
            "\n"
            "class LoggingTool(BaseTool):\n"
            "    name = 'logging'\n"
            "    description = 'Wraps run for its subclasses.'\n"
            "    Args = NoArgs\n"
            "    def run(self, **kwargs):\n"
            "        return super().run(**kwargs)\n"
            "    @abstractmethod\n"
            "    def _execute(self, args): ...\n"
            "\n"
            "class RealTool(LoggingTool):\n"
            "    name = 'real'\n"
            "    description = 'The concrete one.'\n"
            "    node_type = 'tool.real'\n"
            "    def _execute(self, args):\n"
            "        return ToolResult(content='real')\n",
        )

        found, warnings = discover(tmp_path)

        assert [name for name, _ in found] == ["my-flow/tools.RealTool"]
        assert warnings == []


class TestEverySilentSkipHasAVoice:
    def test_an_unimportable_module_says_which_file_and_why(self, tmp_path: Path) -> None:
        write(tmp_path / "tools" / "broken.py", "this is not python (((")
        write(tmp_path / "tools" / "good.py", GOOD_TOOL)

        found, warnings = discover(tmp_path)

        assert [name for name, _ in found] == ["my-flow/tools.GoodTool"]
        assert len(warnings) == 1
        assert "broken.py" in warnings[0]
        assert "SyntaxError" in warnings[0]

    def test_abstract_for_another_reason_lists_what_is_missing(self, tmp_path: Path) -> None:
        write(
            tmp_path / "tools" / "half.py",
            "from abc import abstractmethod\n"
            "from openstategraph.abc import BaseTool, NoArgs, ToolResult\n"
            "\n"
            "class HalfDone(BaseTool):\n"
            "    name = 'half'\n"
            "    description = 'Forgot a hook of its own.'\n"
            "    node_type = 'tool.half'\n"
            "    Args = NoArgs\n"
            "    @abstractmethod\n"
            "    def connect(self): ...\n"
            "    def _execute(self, args):\n"
            "        return ToolResult(content='')\n",
        )

        found, warnings = discover(tmp_path)

        assert found == []
        assert len(warnings) == 1
        assert "HalfDone" in warnings[0]
        assert "connect" in warnings[0]
        # Distinct from the run-override diagnosis, not a shared generic line.
        assert "_execute(self, args)" not in warnings[0]

    def test_a_deliberate_shared_base_is_ignored_without_noise(self, tmp_path: Path) -> None:
        """`_Base`/`AbstractX`/`BaseX` is how this codebase already spells "not
        a tool, a parent of tools" (`_SqlExplorerBase`). Warning about it would
        train developers to ignore the channel."""
        write(
            tmp_path / "tools" / "family.py",
            "from openstategraph.abc import BaseTool, NoArgs, ToolResult\n"
            "\n"
            "class _AcmeBase(BaseTool):\n"
            "    description = 'Shared config for the acme family.'\n"
            "    Args = NoArgs\n"
            "\n"
            "class AcmeOne(_AcmeBase):\n"
            "    name = 'acme_one'\n"
            "    node_type = 'tool.acme-one'\n"
            "    def _execute(self, args):\n"
            "        return ToolResult(content='one')\n",
        )

        found, warnings = discover(tmp_path)

        assert [name for name, _ in found] == ["my-flow/tools.AcmeOne"]
        assert warnings == []

    def test_a_duplicate_node_type_names_both_classes_and_the_loser(
        self, tmp_path: Path
    ) -> None:
        write(tmp_path / "tools" / "a_first.py", GOOD_TOOL)
        write(tmp_path / "tools" / "b_second.py", GOOD_TOOL.replace("GoodTool", "RivalTool"))

        registry_warnings: list[str] = []
        registry = discover_tool_registry(tmp_path, "my-flow", warnings=registry_warnings)

        assert len(registry_warnings) == 1
        message = registry_warnings[0]
        assert "tool.good" in message
        assert "GoodTool" in message and "RivalTool" in message
        # The registry is a dict: the later declaration wins, so say so.
        assert registry["tool.good"].__class__.__name__ == "RivalTool"

    def test_a_constructor_that_raises_names_the_tool(self, tmp_path: Path) -> None:
        write(
            tmp_path / "tools" / "needy.py",
            "from openstategraph.abc import BaseTool, NoArgs, ToolResult\n"
            "\n"
            "class NeedyTool(BaseTool):\n"
            "    name = 'needy'\n"
            "    description = 'Wants credentials.'\n"
            "    node_type = 'tool.needy'\n"
            "    Args = NoArgs\n"
            "    def __init__(self):\n"
            "        raise RuntimeError('no credentials')\n"
            "    def _execute(self, args):\n"
            "        return ToolResult(content='')\n",
        )

        found, warnings = discover(tmp_path)

        assert found == []
        assert "NeedyTool" in warnings[0]
        assert "no credentials" in warnings[0]

    def test_a_tool_defined_in_an_unscanned_file_is_reported(self, tmp_path: Path) -> None:
        """`_helpers.py` is skipped by the leading-underscore convention. A
        class defined there and re-exported from a scanned module looks
        present in the source and is absent from every run."""
        write(
            tmp_path / "tools" / "_hidden.py",
            GOOD_TOOL.replace("GoodTool", "HiddenTool").replace("tool.good", "tool.hidden"),
        )
        write(
            tmp_path / "tools" / "exports.py",
            "import importlib.util, pathlib, sys\n"
            "_spec = importlib.util.spec_from_file_location(\n"
            "    'hidden_mod', pathlib.Path(__file__).with_name('_hidden.py'))\n"
            "_mod = importlib.util.module_from_spec(_spec)\n"
            "_spec.loader.exec_module(_mod)\n"
            "HiddenTool = _mod.HiddenTool\n",
        )

        found, warnings = discover(tmp_path)

        assert found == []
        assert len(warnings) == 1
        assert "HiddenTool" in warnings[0]
        assert "_hidden.py" in warnings[0]
        assert "exports.py" in warnings[0]

    def test_a_framework_tool_imported_for_reuse_is_not_reported(self, tmp_path: Path) -> None:
        """The `__module__` guard exists to stop double-counting re-exports.
        Only a class whose *own file lives in this tools/ folder* and never got
        scanned is a lost capability; an import from the framework is not."""
        write(
            tmp_path / "tools" / "reuse.py",
            "from openstategraph.prebuilt_web import WebSearchTool  # noqa: F401\n" + GOOD_TOOL,
        )

        found, warnings = discover(tmp_path)

        assert [name for name, _ in found] == ["my-flow/tools.GoodTool"]
        assert warnings == []

    def test_a_tool_with_no_node_type_is_listed_and_never_warned_about(
        self, tmp_path: Path
    ) -> None:
        """Documented-legitimate: `BaseTool.node_type` says empty means "not
        placeable on a canvas", which is correct for a tool only ever handed to
        an agent programmatically. It stays discoverable, just not bindable."""
        write(tmp_path / "tools" / "lib.py", GOOD_TOOL.replace('    node_type = "tool.good"\n', ""))

        found, warnings = discover(tmp_path)

        assert [name for name, _ in found] == ["my-flow/tools.GoodTool"]
        assert warnings == []
        assert discover_tool_registry(tmp_path, "my-flow") == {}


class TestTheHappyPathStaysQuiet:
    def test_legitimate_tools_load_with_zero_warnings(self, tmp_path: Path) -> None:
        write(tmp_path / "tools" / "good.py", GOOD_TOOL)
        write(tmp_path / "tools" / "other.py", GOOD_TOOL.replace("Good", "Other").replace(
            "tool.good", "tool.other"))
        write(tmp_path / "tools" / "_private.py", "HELPER = 1\n")

        found, warnings = discover(tmp_path)

        assert sorted(name for name, _ in found) == [
            "my-flow/tools.GoodTool",
            "my-flow/tools.OtherTool",
        ]
        assert warnings == []

    def test_the_bundled_chinook_package_discovers_clean(self) -> None:
        """The repo's own example package is the regression canary: if the
        audit ever starts warning about legitimate code, this fails first."""
        package = Path(__file__).resolve().parents[2] / "workflows" / "chinook-assistant"
        if not (package / "tools").is_dir():  # pragma: no cover - checkout shape
            pytest.skip("bundled example package not present")

        found, warnings = discover(package, slug="chinook-assistant")

        assert found
        assert warnings == []

    def test_no_sink_no_crash(self, tmp_path: Path) -> None:
        """Every existing caller passes no `warnings` list. They must keep
        working, and still get the log line."""
        write(tmp_path / "tools" / "broken.py", "((((")

        assert discover_tool_instances(tmp_path, "my-flow") == []


class TestTheFindingsReachAHumanWhoNeverReadsLogs:
    def test_they_land_on_runtime_warnings(self, tmp_path: Path) -> None:
        from openstategraph.api.registries import runtime_warnings

        # A real `CompileDiagnostics` rather than a fake with four fields.
        # The fake existed because `runtime_warnings` read seven attributes
        # off whatever it was handed, three of them defensively; there is one
        # collaborator to hold now, and it is a cheap value object
        # (reviews-2026-08-14 ticket 07).
        diagnostics = CompileDiagnostics()
        diagnostics.record(Finding.CAPABILITY_FAILED, "AcmePing overrides run()")

        assert "AcmePing overrides run()" in runtime_warnings(
            SimpleNamespace(diagnostics=diagnostics)
        )

    def test_a_runtime_built_for_a_broken_package_carries_them(self, tmp_path: Path) -> None:
        from openstategraph.api.services import WorkflowServices

        package = tmp_path / "my-flow"
        write(package / "tools" / "acme.py", TestTheRunOverrideTrap.SOURCE)
        (package / "workflow.json").write_text('{"document": {"nodes": [], "edges": []}}')

        services = WorkflowServices(tmp_path)
        runtime = services.runtime_for("my-flow", {"nodes": [], "edges": []}, None)

        assert any("AcmePing" in w for w in runtime.diagnostics.warnings())

    def test_load_workflow_reports_it_on_compiled_workflow_warnings(
        self, tmp_path: Path
    ) -> None:
        """The end of the chain, and the only part a consumer of the framework
        ever sees: `load_workflow(...).warnings` is what the CLI prints."""
        import json

        from conftest import RespondingModel

        from openstategraph import load_workflow

        package = tmp_path / "demo-pkg"
        write(package / "tools" / "acme.py", TestTheRunOverrideTrap.SOURCE)
        (package / "workflow.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "name": "demo-pkg",
                    "document": {
                        "version": 1,
                        "name": "demo",
                        "nodes": [
                            {"id": "in1", "type": "input.text", "data": {},
                             "position": {"x": 0, "y": 0}},
                            {"id": "out1", "type": "output.formatted", "data": {},
                             "position": {"x": 0, "y": 0}},
                        ],
                        "edges": [
                            {
                                "source": {"nodeId": "in1", "portId": "text"},
                                "target": {"nodeId": "out1", "portId": "result"},
                            }
                        ],
                    },
                }
            )
        )

        loaded = load_workflow(package, model=RespondingModel(rules=[], default="fine"))

        assert any("AcmePing" in w for w in loaded.warnings)
        # Reported once, not once per channel.
        assert len([w for w in loaded.warnings if "AcmePing" in w]) == 1

    def test_and_they_are_still_logged(self, tmp_path: Path, caplog) -> None:
        write(tmp_path / "tools" / "acme.py", TestTheRunOverrideTrap.SOURCE)

        with caplog.at_level(logging.WARNING):
            discover(tmp_path)

        assert "AcmePing" in caplog.text


class TestTheEntryPointPathGivesTheSameDiagnosis:
    """The outward-facing half: `openstategraph.tools` made third-party
    `BaseTool` subclasses a supported path, so the same footgun is aimed at
    strangers whose code we cannot read."""

    class _FakeDist:
        def __init__(self, name: str) -> None:
            self.name = name

    class FakeEntryPoint:
        def __init__(self, name: str, group: str, dist: str, result: Any) -> None:
            self.name = name
            self.group = group
            self.dist = TestTheEntryPointPathGivesTheSameDiagnosis._FakeDist(dist)
            self._result = result

        def load(self) -> Any:
            return self._result

    def install(self, monkeypatch: pytest.MonkeyPatch, *entry_points: Any) -> None:
        from openstategraph.extensions import DISABLE_PLUGINS_ENV

        monkeypatch.delenv(DISABLE_PLUGINS_ENV, raising=False)
        monkeypatch.setattr(
            importlib.metadata,
            "entry_points",
            lambda *, group="": [ep for ep in entry_points if ep.group == group],
        )

    def test_an_abstract_run_overriding_tool_is_diagnosed_not_generically(
        self, monkeypatch
    ) -> None:
        from abc import abstractmethod

        from openstategraph.extensions import TOOLS_GROUP, entry_point_tools

        class PluginPing(BaseTool):
            name = "plugin_ping"
            description = "Shipped by a stranger."
            node_type = "tool.plugin-ping"
            Args = NoArgs

            def run(self, **kwargs: Any) -> ToolResult:
                return ToolResult(content="pong")

            @abstractmethod
            def _execute(self, args: Any) -> ToolResult: ...

        self.install(monkeypatch, self.FakeEntryPoint("acme", TOOLS_GROUP, "acme", PluginPing))
        found = entry_point_tools()

        assert found.values == {}
        assert len(found.warnings) == 1
        message = found.warnings[0]
        assert "acme" in message
        assert "PluginPing" in message
        assert "_execute(self, args)" in message

    def test_two_plugins_claiming_one_node_type_is_reported(self, monkeypatch) -> None:
        from openstategraph.extensions import TOOLS_GROUP, entry_point_tools

        class First(BaseTool):
            name = "first"
            description = "First claim."
            node_type = "tool.contested"
            Args = NoArgs

            def _execute(self, args: Any) -> ToolResult:
                return ToolResult(content="first")

        class Second(BaseTool):
            name = "second"
            description = "Second claim."
            node_type = "tool.contested"
            Args = NoArgs

            def _execute(self, args: Any) -> ToolResult:
                return ToolResult(content="second")

        self.install(
            monkeypatch,
            self.FakeEntryPoint("a", TOOLS_GROUP, "dist-a", First),
            self.FakeEntryPoint("b", TOOLS_GROUP, "dist-b", Second),
        )
        found = entry_point_tools()

        assert found.values["tool.contested"].run().content == "second"
        assert len(found.warnings) == 1
        assert "tool.contested" in found.warnings[0]
        assert "dist-a" in found.warnings[0] and "dist-b" in found.warnings[0]
