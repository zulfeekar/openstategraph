"""PK-06: a tool an installed distribution ships must reach the *palette*.

Ticket 05 made a third party's tool **bindable** — `pip install` and the
runtime resolves `tool.acme-ping`. Nothing put it in the editor, so a user
could not wire the thing they had just installed. Authoring an atom is a
two-place job (a Python tool the runtime binds, a node definition the editor
renders) and doing half of it produced no error anywhere.

Three properties, one class each:

- **the same registry** — the palette is fed from `_process_tool_layer`, the
  object `build_tool_registry` itself layers, so the editor can never claim a
  tool the runtime lacks;
- **precedence, spoken aloud** — a plugin may replace a built-in (that is what
  installing one is *for*), and the payload says so rather than letting a card
  change identity silently;
- **half-authored is loud** — a Python tool with no editor card is named, with
  the two ways to give it one.

Entry points are faked, exactly as `test_extensions.py` fakes them: what is
under test is our handling of what `importlib.metadata` returns.
"""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openstategraph.abc import BaseTool, NoArgs, ToolResult
from openstategraph.abc.tool import ToolField
from openstategraph.api.main import create_app
from openstategraph.api.plugin_capabilities import (
    plugin_tool_capabilities,
    unrenderable_tool_warning,
)
from openstategraph.extensions import DISABLE_PLUGINS_ENV, TOOLS_GROUP


class AcmePingTool(BaseTool):
    """What a third-party distribution ships."""

    name = "acme_ping"
    description = "Answers with a pong."
    node_type = "tool.acme-ping"
    Args = NoArgs
    node_fields = (
        ToolField(
            key="endpoint",
            label="Endpoint",
            kind="text",
            placeholder="https://acme.example/ping",
            hint="Where the ping goes.",
        ),
    )

    def _execute(self, args: Any) -> ToolResult:
        return ToolResult(content="pong")


class AcmeWebSearchTool(BaseTool):
    """A plugin that claims a node type the framework already ships."""

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
    def __init__(self, name: str, group: str, dist: str, result: Any = None) -> None:
        self.name = name
        self.group = group
        self.dist = _FakeDist(dist)
        self._result = result

    def load(self) -> Any:
        return self._result


def install(monkeypatch: pytest.MonkeyPatch, *entry_points: FakeEntryPoint) -> None:
    """Pretend these entry points are installed in this environment."""

    def fake_entry_points(*, group: str = "") -> list[FakeEntryPoint]:
        return [ep for ep in entry_points if ep.group == group]

    monkeypatch.delenv(DISABLE_PLUGINS_ENV, raising=False)
    monkeypatch.setattr(importlib.metadata, "entry_points", fake_entry_points)


def _saved_workflow(tmp_path: Path) -> TestClient:
    client = TestClient(create_app(workflows_root=tmp_path))
    client.put(
        "/api/workflows/my-flow",
        json={"name": "My Flow", "document": {"nodes": [], "edges": []}},
    )
    return client


class TestAnInstalledPluginReachesThePalette:
    def test_it_is_reported_as_an_app_scoped_capability(self, monkeypatch, tmp_path) -> None:
        install(monkeypatch, FakeEntryPoint("acme", TOOLS_GROUP, "osg-acme", [AcmePingTool]))
        client = _saved_workflow(tmp_path)

        body = client.get("/api/workflows/my-flow/capabilities").json()

        [tool] = [t for t in body["plugin_tools"] if t["node_type"] == "tool.acme-ping"]
        assert tool["id"] == "tool.acme-ping"
        assert tool["name"] == "acme_ping"
        assert tool["description"] == "Answers with a pong."
        assert tool["distribution"] == "osg-acme"
        assert "properties" in tool["args_schema"]

    def test_declared_fields_travel_with_it(self, monkeypatch, tmp_path) -> None:
        """A plugin's card is configurable without a hand-written TS file: the
        fields it declares are the ones the editor renders."""
        install(monkeypatch, FakeEntryPoint("acme", TOOLS_GROUP, "osg-acme", [AcmePingTool]))
        client = _saved_workflow(tmp_path)

        body = client.get("/api/workflows/my-flow/capabilities").json()
        [tool] = [t for t in body["plugin_tools"] if t["node_type"] == "tool.acme-ping"]

        assert tool["fields"] == [
            {
                "key": "endpoint",
                "label": "Endpoint",
                "kind": "text",
                "default_value": "",
                "placeholder": "https://acme.example/ping",
                "hint": "Where the ping goes.",
                "options": [],
            }
        ]

    def test_it_is_the_registry_the_runtime_binds(self, monkeypatch, tmp_path) -> None:
        """The palette cannot claim a tool the runtime lacks: both read
        `_process_tool_layer`, so one list is impossible without the other."""
        install(monkeypatch, FakeEntryPoint("acme", TOOLS_GROUP, "osg-acme", [AcmePingTool]))
        from openstategraph.api.registries import build_tool_registry
        from openstategraph.api.workflow_store import WorkflowStore

        capabilities, _ = plugin_tool_capabilities()
        registry = build_tool_registry(WorkflowStore(root=tmp_path), None)

        assert {c.node_type for c in capabilities} <= set(registry)
        assert "tool.acme-ping" in {c.node_type for c in capabilities}

    def test_a_broken_distribution_is_named_not_swallowed(self, monkeypatch, tmp_path) -> None:
        class Unplaceable(BaseTool):
            name = "unplaceable"
            description = "Declares no node_type."
            Args = NoArgs

            def _execute(self, args: Any) -> ToolResult:
                return ToolResult(content="")

        install(monkeypatch, FakeEntryPoint("acme", TOOLS_GROUP, "osg-acme", [Unplaceable]))
        client = _saved_workflow(tmp_path)

        body = client.get("/api/workflows/my-flow/capabilities").json()

        assert body["plugin_tools"] == []
        assert any("osg-acme" in w and "node_type" in w for w in body["warnings"])

    def test_plugins_can_be_switched_off_entirely(self, monkeypatch, tmp_path) -> None:
        install(monkeypatch, FakeEntryPoint("acme", TOOLS_GROUP, "osg-acme", [AcmePingTool]))
        monkeypatch.setenv(DISABLE_PLUGINS_ENV, "1")
        client = _saved_workflow(tmp_path)

        assert client.get("/api/workflows/my-flow/capabilities").json()["plugin_tools"] == []


class TestACollisionWithABuiltIn:
    def test_the_plugin_wins_and_the_payload_says_so(self, monkeypatch, tmp_path) -> None:
        """Built-in < installed plugin < workflow-local. Replacing a bundled
        default is what installing a plugin is *for* — but a card that changes
        identity without a word is how a user stops trusting the palette."""
        install(monkeypatch, FakeEntryPoint("acme", TOOLS_GROUP, "osg-acme", [AcmeWebSearchTool]))
        client = _saved_workflow(tmp_path)

        body = client.get("/api/workflows/my-flow/capabilities").json()

        [tool] = [t for t in body["plugin_tools"] if t["node_type"] == "tool.web-search"]
        assert tool["distribution"] == "osg-acme"
        assert tool["replaces_builtin"] is True
        assert any("tool.web-search" in w and "osg-acme" in w for w in body["warnings"])

    def test_a_tool_claiming_nothing_bundled_replaces_nothing(self, monkeypatch, tmp_path) -> None:
        install(monkeypatch, FakeEntryPoint("acme", TOOLS_GROUP, "osg-acme", [AcmePingTool]))
        client = _saved_workflow(tmp_path)

        body = client.get("/api/workflows/my-flow/capabilities").json()
        [tool] = [t for t in body["plugin_tools"] if t["node_type"] == "tool.acme-ping"]

        assert tool["replaces_builtin"] is False
        assert not any("replaces" in w for w in body["warnings"])


class TestTheHalfAuthoredError:
    """A Python tool the editor cannot render must produce a message, not silence."""

    def test_it_names_the_type_and_both_ways_to_fix_it(self) -> None:
        warning = unrenderable_tool_warning(
            bindable=("tool.sql-query", "tool.web-search"),
            renderable=frozenset({"tool.web-search"}),
            declared=frozenset(),
        )

        assert warning is not None
        assert "tool.sql-query" in warning
        assert "tool.web-search" not in warning
        assert "src/nodes/tools/" in warning
        assert "docs/building-an-atom.md" in warning

    def test_a_declared_capability_is_not_half_authored(self) -> None:
        """A plugin-contributed or workflow-discovered tool arrives with its own
        descriptor, so the editor renders it generically — nothing is missing."""
        assert (
            unrenderable_tool_warning(
                bindable=("tool.acme-ping",),
                renderable=frozenset(),
                declared=frozenset({"tool.acme-ping"}),
            )
            is None
        )

    def test_a_fully_carded_registry_says_nothing(self) -> None:
        assert (
            unrenderable_tool_warning(
                bindable=("tool.web-search",),
                renderable=frozenset({"tool.web-search"}),
                declared=frozenset(),
            )
            is None
        )

    def test_the_live_endpoint_only_ever_names_genuinely_cardless_types(
        self, tmp_path
    ) -> None:
        """An invariant rather than a snapshot: adding a card must not need a
        test edit, but a warning naming a type that *has* one would be a lie."""
        from openstategraph.compile.node_catalogue import CATALOGUE

        client = _saved_workflow(tmp_path)
        body = client.get("/api/workflows/my-flow/capabilities").json()

        named = [w for w in body["warnings"] if "no editor card" in w]
        for node_type in CATALOGUE.node_types:
            assert not any(node_type in w for w in named)

    def test_a_workflow_tool_that_will_not_import_is_surfaced_too(self, tmp_path) -> None:
        """The same channel, for the other half-authoring: ticket 07's rule
        already collects these; before PK-06 the endpoint threw them away."""
        client = _saved_workflow(tmp_path)
        tools_dir = tmp_path / "my-flow" / "tools"
        tools_dir.mkdir()
        (tools_dir / "broken.py").write_text("import nope_not_a_module\n")

        body = client.get("/api/workflows/my-flow/capabilities").json()

        assert any("broken.py" in w for w in body["warnings"])
