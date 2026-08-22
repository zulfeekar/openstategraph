"""Every tool in the catalogue can be adapted the way its base promises.

`BaseTool.as_langchain_tool(on_call=...)` grew its optional hook in
`production-ready` 12, so a caller handing out tools it does not own can learn
which of them were *actually run* rather than which were offered. That is the
difference between the knowledge explorer's provenance footer being evidence
and being a claim about availability.

`McpTool` overrode the method **before** the hook existed and was never
updated, so the override reads `as_langchain_tool(self)` — no `on_call`. mypy
reported it as `[override] incompatible with supertype`
(`organisms-first-class` 48), and the Liskov clause CLAUDE.md calls
non-negotiable is not a typing formality here: `knowledge_explorer` line 436
calls `bound.as_langchain_tool(on_call=called.add)` over every `tool.*` node in
a document, and `tool.mcp` is not on `EXPLORER_DENY_PREFIXES`. A document with
an MCP server node on it took a `TypeError` out of a registry lookup.

The ladder was not bent — `BaseTool` is the right base and `McpTool` is the
right leaf. The override existed only to carry a docstring explaining the
refusal, and it silently dropped a parameter it was never taught about. So the
fix is the override's signature, and the pin is this census: the promise is
made by the *base*, so it is checked against every leaf rather than the one
that happened to break.
"""

from __future__ import annotations

import inspect
from typing import Any

from openstategraph.abc.tool import BaseTool


def _catalogue() -> dict[str, Any]:
    from openstategraph.api.registries import build_tool_registry

    return build_tool_registry(None, None)


class TestOnCallSurvivesEveryOverride:
    def test_the_catalogue_is_not_empty(self) -> None:
        """A census that enumerates nothing passes for the wrong reason."""
        assert len(_catalogue()) >= 5

    def test_every_tool_accepts_the_hook_its_base_promises(self) -> None:
        base = inspect.signature(BaseTool.as_langchain_tool)

        broken = {
            node_type: str(inspect.signature(type(tool).as_langchain_tool))
            for node_type, tool in _catalogue().items()
            if isinstance(tool, BaseTool)
            and inspect.signature(type(tool).as_langchain_tool) != base
        }

        assert broken == {}, (
            f"these tools are not substitutable for BaseTool{base}; a caller "
            f"passing on_call gets a TypeError: {broken}"
        )

    def test_the_mcp_tool_reports_its_own_call(self) -> None:
        """The behaviour, not the signature: the hook must actually fire.

        A signature widened to `**kwargs` would pass the census above and still
        drop the name on the floor.
        """
        from openstategraph.prebuilt_mcp import McpTool

        called: set[str] = set()
        refusing = McpTool().as_langchain_tool(on_call=called.add)

        answer = refusing.func()

        assert "as_langchain_tools" in answer or "contributes" in answer
        assert called == {McpTool().name}


class TestTheExplorerPathThatBroke:
    def test_binding_a_document_with_an_mcp_node_does_not_raise(self) -> None:
        """The call site, exercised: `knowledge_explorer` line 436's shape."""
        from openstategraph.prebuilt_mcp import McpTool

        called: set[str] = set()
        bound = McpTool().configure({})

        assert bound.as_langchain_tool(on_call=called.add) is not None
