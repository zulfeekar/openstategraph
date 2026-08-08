"""Tool resolution by canvas node type — ticket 33's seam, pinned.

Three parts that previously each failed a different silent way:

- A tool declares its own `node_type` (the canvas type id) in its manifest,
  so the wiring identity has one source of truth — the tool. A WIP attempt
  keyed a registry by lowercased class name (`tool.querydatatool`), which can
  never match a canvas type (`tool.tabular-query`).
- `configure(data)` is how one bound node's own field values reach its tool
  instance — replacing a compiler special-case that knew about exactly one
  Chinook field and left every other tool's config inert.
- Discovery builds a per-workflow registry keyed by node_type, loading the
  workflow's `tools/` under a synthetic module name (a hyphenated slug can
  never be imported as a package).
"""

from __future__ import annotations

from pathlib import Path

from openstategraph.api.capability_discovery import discover_tool_registry, discover_tools
from openstategraph.compile.node_runtime import NodeRuntime
from openstategraph.abc.tool import BaseTool, NoArgs, ToolResult

REPO = Path(__file__).resolve().parent.parent.parent
TABULAR = REPO / "workflows" / "tabular-analytics"


class ARecordingTool(BaseTool):
    name = "recorder"
    description = "records configure calls"
    node_type = "tool.recorder"
    Args = NoArgs

    def _execute(self, args) -> ToolResult:
        return ToolResult(content="ok")


class TestBaseToolContract:
    def test_manifest_carries_the_node_type(self) -> None:
        assert ARecordingTool().manifest()["node_type"] == "tool.recorder"

    def test_configure_defaults_to_the_same_instance(self) -> None:
        tool = ARecordingTool()
        assert tool.configure({"anything": 1}) is tool


class TestBoundToolConfiguration:
    @staticmethod
    def _runtime_with(tool: BaseTool, node_data: dict) -> NodeRuntime:
        runtime = NodeRuntime(tools={tool.node_type: tool})
        runtime._types["t1"] = tool.node_type
        runtime._nodes["t1"] = {"id": "t1", "type": tool.node_type, "data": node_data}
        return runtime

    def test_every_tool_receives_its_nodes_data_not_just_chinook(self) -> None:
        seen: list[dict] = []

        class ConfigAware(ARecordingTool):
            def configure(self, data):
                seen.append(dict(data))
                return self

        runtime = self._runtime_with(ConfigAware(), {"maxRows": 7})
        assert runtime._bound_tool("t1") is not None
        assert seen == [{"maxRows": 7}]

    def test_a_missing_implementation_stays_a_loud_warning(self) -> None:
        runtime = NodeRuntime(tools={})
        runtime._types["t1"] = "tool.ghost"
        assert runtime._bound_tool("t1") is None
        assert "tool.ghost" in runtime.unresolved_tools

    def test_chinook_row_cap_still_configures_through_the_generic_hook(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "openstategraph_test_chinook_tools",
            REPO / "workflows" / "chinook-nl-to-sql" / "tools" / "chinook.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        tool = module.ExecuteSqlTool()
        configured = tool.configure({"maxRows": 3})
        assert configured.row_cap == 3
        # The shared registry instance must never be mutated in place.
        assert tool.row_cap != 3 or configured is not tool


class TestWorkflowToolDiscovery:
    def test_registry_is_keyed_by_canvas_node_type(self) -> None:
        registry = discover_tool_registry(TABULAR, slug="tabular-analytics")
        assert set(registry) == {
            "tool.tabular-list-files",
            "tool.tabular-get-schema",
            "tool.tabular-query",
            "tool.tabular-sample",
        }
        for node_type, tool in registry.items():
            assert isinstance(tool, BaseTool)
            assert tool.node_type == node_type

    def test_capabilities_expose_the_node_type_too(self) -> None:
        capabilities = discover_tools(TABULAR, slug="tabular-analytics")
        by_name = {c.name: c for c in capabilities}
        assert by_name["tabular_query_data"].node_type == "tool.tabular-query"

    def test_a_workflow_without_tools_discovers_an_empty_registry(self) -> None:
        registry = discover_tool_registry(
            REPO / "workflows" / "intent-routed-demo", slug="intent-routed-demo"
        )
        assert registry == {}
