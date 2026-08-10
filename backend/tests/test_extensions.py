"""Extension without forking: a third party's distribution registers on install.

Ticket 05. The three properties the design demands, one class each:

- **honest** — a failing entry point logs a WARNING naming the distribution and
  is skipped; it never takes the registry down with it, exactly as the bundled
  Chinook guard already behaves;
- **ordered** — built-in < third-party < workflow-local, preserving the
  local-shadows-global rule `build_tool_registry` already documents;
- **cheap and controllable** — nothing is imported until a registry is built,
  and a reproducible run can switch the whole mechanism off.

Entry points are faked rather than installed: a real fake distribution would
mean a `pip install` inside the test suite, and what is under test is our
*handling* of what `importlib.metadata` returns, not `importlib.metadata`.
"""

from __future__ import annotations

import importlib.metadata
import logging
from pathlib import Path
from typing import Any

import pytest

from openstategraph.abc import BaseTool, NoArgs, ToolResult
from openstategraph.extensions import (
    DISABLE_PLUGINS_ENV,
    ENTRY_POINT_GROUPS,
    KNOWLEDGE_BUILDERS_GROUP,
    TOOLS_GROUP,
    entry_point_knowledge_builders,
    entry_point_tools,
)


class AcmeTool(BaseTool):
    """The tool a third-party distribution would ship."""

    name = "acme_ping"
    description = "Answers with a pong."
    node_type = "tool.acme-ping"
    Args = NoArgs

    def _execute(self, args: Any) -> ToolResult:
        return ToolResult(content="pong")


class ShadowingWebSearch(BaseTool):
    """A plugin tool that claims a node type the framework already ships."""

    name = "acme_web_search"
    description = "A third party's take on web search."
    node_type = "tool.web-search"
    Args = NoArgs

    def _execute(self, args: Any) -> ToolResult:
        return ToolResult(content="acme")


class _FakeDist:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeEntryPoint:
    """Only what our loader is allowed to touch: name, group, dist, load()."""

    def __init__(self, name: str, group: str, dist: str, result: Any = None,
                 error: Exception | None = None) -> None:
        self.name = name
        self.group = group
        self.dist = _FakeDist(dist)
        self._result = result
        self._error = error

    def load(self) -> Any:
        if self._error is not None:
            raise self._error
        return self._result


def install(monkeypatch: pytest.MonkeyPatch, *entry_points: FakeEntryPoint) -> None:
    """Pretend these entry points are installed in the environment."""

    def fake_entry_points(*, group: str = "") -> list[FakeEntryPoint]:
        return [ep for ep in entry_points if ep.group == group]

    monkeypatch.delenv(DISABLE_PLUGINS_ENV, raising=False)
    monkeypatch.setattr(importlib.metadata, "entry_points", fake_entry_points)


class TestTheGroupNamesAreTheContract:
    def test_they_are_the_three_we_published(self) -> None:
        """A third party writes these strings into their own pyproject.toml, so
        renaming one silently un-registers every plugin that ever shipped."""
        from openstategraph.extensions import PROVIDERS_GROUP

        assert TOOLS_GROUP == "openstategraph.tools"
        assert KNOWLEDGE_BUILDERS_GROUP == "openstategraph.knowledge_builders"
        assert PROVIDERS_GROUP == "openstategraph.providers"
        assert ENTRY_POINT_GROUPS == (TOOLS_GROUP, KNOWLEDGE_BUILDERS_GROUP, PROVIDERS_GROUP)


class TestAToolFromAnInstalledDistribution:
    def test_it_reaches_the_registry_a_run_is_given(self, monkeypatch, tmp_path) -> None:
        install(monkeypatch, FakeEntryPoint("acme", TOOLS_GROUP, "openstategraph-acme", [AcmeTool]))
        from openstategraph.api.registries import build_tool_registry
        from openstategraph.api.workflow_store import WorkflowStore

        registry = build_tool_registry(WorkflowStore(root=tmp_path), None)

        assert "tool.acme-ping" in registry
        assert registry["tool.acme-ping"].run().content == "pong"

    def test_an_instance_works_as_well_as_a_class(self, monkeypatch) -> None:
        """`= AcmeTool` and `= TOOLS` (a list of instances) are both natural
        spellings, and a plugin author should not have to guess which we take."""
        install(monkeypatch, FakeEntryPoint("acme", TOOLS_GROUP, "acme", AcmeTool()))

        assert "tool.acme-ping" in entry_point_tools().values

    def test_a_bare_class_needs_no_iterable_wrapper(self, monkeypatch) -> None:
        install(monkeypatch, FakeEntryPoint("acme", TOOLS_GROUP, "acme", AcmeTool))

        assert "tool.acme-ping" in entry_point_tools().values

    def test_a_tool_declaring_no_node_type_is_reported_not_registered(self, monkeypatch) -> None:
        """`node_type` is the wiring identity. Without one there is nothing a
        document could bind, so silence would leave the author guessing."""

        class Unplaceable(BaseTool):
            name = "unplaceable"
            description = "No node type."
            Args = NoArgs

            def _execute(self, args: Any) -> ToolResult:
                return ToolResult(content="")

        install(monkeypatch, FakeEntryPoint("acme", TOOLS_GROUP, "acme-tools", Unplaceable))
        found = entry_point_tools()

        assert found.values == {}
        assert any("acme-tools" in w and "node_type" in w for w in found.warnings)


class TestABrokenPluginIsSkipped:
    def test_it_logs_a_warning_naming_the_distribution(self, monkeypatch, caplog) -> None:
        install(
            monkeypatch,
            FakeEntryPoint("broken", TOOLS_GROUP, "openstategraph-broken",
                           error=ImportError("no module named 'nope'")),
        )

        with caplog.at_level(logging.WARNING):
            found = entry_point_tools()

        assert found.values == {}
        assert "openstategraph-broken" in caplog.text
        assert any("openstategraph-broken" in w for w in found.warnings)

    def test_the_other_plugins_still_register(self, monkeypatch) -> None:
        """One bad distribution in a venv must not cost an adopter every other
        capability in it — the same rule the bundled Chinook guard follows."""
        install(
            monkeypatch,
            FakeEntryPoint("broken", TOOLS_GROUP, "broken-dist", error=RuntimeError("boom")),
            FakeEntryPoint("acme", TOOLS_GROUP, "acme-dist", [AcmeTool]),
        )

        assert "tool.acme-ping" in entry_point_tools().values

    def test_a_registry_build_survives_it_entirely(self, monkeypatch, tmp_path) -> None:
        install(
            monkeypatch,
            FakeEntryPoint("broken", TOOLS_GROUP, "broken-dist", error=RuntimeError("boom")),
        )
        from openstategraph.api.registries import build_tool_registry
        from openstategraph.api.workflow_store import WorkflowStore

        registry = build_tool_registry(WorkflowStore(root=tmp_path), None)

        assert "tool.web-search" in registry  # the built-ins are untouched

    def test_a_constructor_that_raises_is_the_same_case(self, monkeypatch) -> None:
        class Exploding(BaseTool):
            name = "exploding"
            description = "Fails to construct."
            node_type = "tool.exploding"
            Args = NoArgs

            def __init__(self) -> None:
                raise RuntimeError("no credentials")

            def _execute(self, args: Any) -> ToolResult:
                return ToolResult(content="")

        install(monkeypatch, FakeEntryPoint("acme", TOOLS_GROUP, "acme-dist", Exploding))
        found = entry_point_tools()

        assert found.values == {}
        assert any("acme-dist" in w for w in found.warnings)

    def test_a_metadata_layer_that_itself_fails_is_survivable(self, monkeypatch) -> None:
        """Some environments ship a broken `.dist-info`. Enumeration failing is
        not a reason for `load_workflow` to fail."""

        def exploding_entry_points(**kwargs: Any) -> list[Any]:
            raise ValueError("a distribution's metadata is unreadable")

        monkeypatch.delenv(DISABLE_PLUGINS_ENV, raising=False)
        monkeypatch.setattr(importlib.metadata, "entry_points", exploding_entry_points)
        found = entry_point_tools()

        assert found.values == {}
        assert found.warnings


class TestPrecedence:
    """built-in < third-party < workflow-local. Pinned, because each boundary
    is a different person's expectation: a plugin author expects to be able to
    replace a bundled default, and a package author expects their own `tools/`
    to win over whatever else happens to be installed in the venv."""

    def _package_with_its_own_web_search(self, tmp_path: Path) -> Any:
        from openstategraph.api.workflow_store import WorkflowStore

        package = tmp_path / "my-flow"
        (package / "tools").mkdir(parents=True)
        (package / "workflow.json").write_text('{"document": {"nodes": [], "edges": []}}')
        (package / "tools" / "local.py").write_text(
            "from openstategraph.abc import BaseTool, NoArgs, ToolResult\n"
            "\n"
            "class LocalWebSearch(BaseTool):\n"
            "    name = 'local_web_search'\n"
            "    description = 'The package its own.'\n"
            "    node_type = 'tool.web-search'\n"
            "    Args = NoArgs\n"
            "    def _execute(self, args):\n"
            "        return ToolResult(content='local')\n"
        )
        return WorkflowStore(root=tmp_path)

    def test_a_plugin_layers_over_a_built_in(self, monkeypatch, tmp_path) -> None:
        install(monkeypatch, FakeEntryPoint("acme", TOOLS_GROUP, "acme", [ShadowingWebSearch]))
        from openstategraph.api.registries import build_tool_registry
        from openstategraph.api.workflow_store import WorkflowStore

        registry = build_tool_registry(WorkflowStore(root=tmp_path), None)

        assert registry["tool.web-search"].run().content == "acme"

    def test_but_the_workflows_own_tool_still_wins(self, monkeypatch, tmp_path) -> None:
        install(monkeypatch, FakeEntryPoint("acme", TOOLS_GROUP, "acme", [ShadowingWebSearch]))
        from openstategraph.api.registries import build_tool_registry

        store = self._package_with_its_own_web_search(tmp_path)
        registry = build_tool_registry(store, "my-flow")

        assert registry["tool.web-search"].run().content == "local"


class TestPluginsCanBeSwitchedOff:
    def test_the_environment_variable_excludes_everything(self, monkeypatch, tmp_path) -> None:
        """A reproducible run must be able to exclude whatever else is in the
        venv — otherwise a CI failure depends on a colleague's `pip install`."""
        install(monkeypatch, FakeEntryPoint("acme", TOOLS_GROUP, "acme", [AcmeTool]))
        monkeypatch.setenv(DISABLE_PLUGINS_ENV, "1")
        from openstategraph.api.registries import build_tool_registry
        from openstategraph.api.workflow_store import WorkflowStore

        registry = build_tool_registry(WorkflowStore(root=tmp_path), None)

        assert "tool.acme-ping" not in registry
        assert "tool.web-search" in registry


class TestKnowledgeBuilders:
    def test_a_third_party_builder_joins_the_ladder(self, monkeypatch) -> None:
        from openstategraph.knowledge_builders import BaseKnowledgeBuilder, Discovery

        class AcmeBuilder(BaseKnowledgeBuilder):
            source_kind = "acme"

            def discover(self, workflow_dir, document, workflows_root) -> Discovery:  # noqa: ANN001
                return Discovery(topics=[], warnings=[])

        install(monkeypatch, FakeEntryPoint("acme", KNOWLEDGE_BUILDERS_GROUP, "acme", AcmeBuilder))
        found = entry_point_knowledge_builders()

        assert [b.source_kind for b in found.values] == ["acme"]

    def test_run_build_sees_it_after_the_built_ins(self, monkeypatch, tmp_path) -> None:
        """Order is the escalation ladder: mechanical built-ins stamp ownership
        of their topics before anything installed alongside them can claim one."""
        from openstategraph.api.knowledge_build import run_build
        from openstategraph.knowledge_builders import BaseKnowledgeBuilder, Discovery

        seen: list[str] = []

        class AcmeBuilder(BaseKnowledgeBuilder):
            source_kind = "acme"

            def discover(self, workflow_dir, document, workflows_root) -> Discovery:  # noqa: ANN001
                seen.append("acme")
                return Discovery(topics=[], warnings=["acme found nothing"])

        install(monkeypatch, FakeEntryPoint("acme", KNOWLEDGE_BUILDERS_GROUP, "acme", AcmeBuilder))
        package = tmp_path / "my-flow"
        package.mkdir()
        report = run_build(package, {"nodes": [], "edges": []}, None, tmp_path, source="acme")

        assert seen == ["acme"]
        assert "acme found nothing" in report["warnings"]

    def test_a_broken_builder_entry_point_does_not_break_a_build(
        self, monkeypatch, tmp_path
    ) -> None:
        from openstategraph.api.knowledge_build import run_build

        install(
            monkeypatch,
            FakeEntryPoint("acme", KNOWLEDGE_BUILDERS_GROUP, "acme-kb",
                           error=ImportError("half-installed")),
        )
        package = tmp_path / "my-flow"
        package.mkdir()
        report = run_build(package, {"nodes": [], "edges": []}, None, tmp_path, source="root")

        assert any("acme-kb" in warning for warning in report["warnings"])


class TestNothingIsImportedUntilARegistryIsBuilt:
    def test_the_extensions_module_imports_no_metadata_at_module_scope(self) -> None:
        """`import openstategraph` must stay free of a `sys.path` scan: entry
        point enumeration is not free, and the top-level import is on every
        adopter's critical path."""
        import ast

        import openstategraph.extensions as extensions

        tree = ast.parse(Path(extensions.__file__).read_text())
        module_scope = [
            node.module
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("importlib")
        ] + [
            alias.name
            for node in tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
            if alias.name.startswith("importlib")
        ]

        assert module_scope == []
