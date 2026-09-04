"""`get_engineering_rules` — the rules an agent reads before it composes.

`osg-agent-experience/25`, slice 1. The sheet's first instruction is *call
`get_engineering_rules` and `get_node_vocabulary` before composing anything*:
the vocabulary says what exists, the rules say what may be built out of it.
An adopter has no `CLAUDE.md`, so without this tool the second half of that
sentence has no door.

Thin over `engineering_rules.py`, like every other tool on this server — the
text has one home and this is a wrapper over it, not a second copy. The
version travels with the text because the rules are the *installed* package's
rules: an agent quoting a rule to a developer should be able to say which
release it came from.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from openstategraph import __version__
from openstategraph.api.services import WorkflowServices
from openstategraph.mcp_server import EXPOSED_TOOLS, build_mcp_server


@pytest.fixture()
def services(tmp_path: Path) -> WorkflowServices:
    root = tmp_path / "workflows"
    root.mkdir()
    return WorkflowServices(workflows_root=root)


def _call(server, name: str, args: dict):
    result = asyncio.run(server.call_tool(name, args))
    return result[1] if isinstance(result, tuple) else result


class TestExposedSurface:
    def test_the_rules_tool_is_on_the_reviewed_surface(self) -> None:
        assert "get_engineering_rules" in EXPOSED_TOOLS

    def test_it_is_registered_on_the_server(self, services: WorkflowServices) -> None:
        server = build_mcp_server(services)

        names = {tool.name for tool in asyncio.run(server.list_tools())}

        assert "get_engineering_rules" in names


class TestWhatItReturns:
    def test_it_carries_the_installed_version_beside_the_text(
        self, services: WorkflowServices
    ) -> None:
        server = build_mcp_server(services)

        result = _call(server, "get_engineering_rules", {})

        assert result["version"] == __version__
        assert result["rules"].startswith("#")

    def test_the_text_is_the_shipped_file_and_not_a_second_copy(
        self, services: WorkflowServices
    ) -> None:
        from openstategraph.engineering_rules import ENGINEERING_RULES

        server = build_mcp_server(services)

        result = _call(server, "get_engineering_rules", {})

        assert result["rules"] == ENGINEERING_RULES.read_text(encoding="utf-8")

    def test_it_answers_with_no_provider_and_no_workflows(
        self, services: WorkflowServices
    ) -> None:
        """Deterministic, like `get_node_vocabulary`: no model, no store, no
        credentials. A deployment with runs closed still serves the rules."""
        server = build_mcp_server(services, allow_runs=False)

        result = _call(server, "get_engineering_rules", {})

        assert "never invent a node type" in result["rules"].lower()
