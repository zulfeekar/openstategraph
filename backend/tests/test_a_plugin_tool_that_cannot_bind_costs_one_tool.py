"""production-ready/93: one tool that will not bind costs one capability.

`production-ready/87` closed the *listing* side of a malformed tool inside a
package's own `tools/` folder. The same one-takes-all shape survived a layer
down, on the path an **entry-point plugin** takes:

- `extensions._discover_tools` checked `inspect.isabstract` and caught a
  raising constructor, but never checked `Args` — so a plugin class written
  with `args_schema = NoArgs` instantiated cleanly and entered the process-wide
  registry;
- `plugin_capabilities` already degrades per tool, so the card appeared in the
  palette and the node was placeable;
- `validate` resolved the binding through that registry and printed it as
  fine;
- and then `NodeRuntime._bind_tools` called `as_langchain_tools()` with no
  `try`, so `args_schema=self.Args` raised `AttributeError` **out of the
  compile**, taking every other tool wired to that agent with it.

Reproduced before anything was touched, through the loader rather than around
it: a fake entry point shipping one healthy tool and one broken one in a single
`load()` result, then `_bind_tools` on a planned document. It raised, and the
healthy sibling was lost with it.

Two guards, and the first is the general one. `_bind_tools` wraps each tool, so
*whatever* a stranger's `as_langchain_tools` does, the agent loses one
capability and hears why. `_discover_tools` then applies 87's own `Args` check
with 87's own sentence, so the broken plugin never reaches the registry and the
three doors say one thing: absent.

The load-bearing assertion in every class below is that the **healthy tools are
still there**. A test that only asserts "an exception was caught" would stay
green against a guard that returned an empty list.
"""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
from typing import Any

import pytest

from openstategraph.abc import BaseTool, NoArgs, ToolResult
from openstategraph import extensions
from openstategraph.compile.diagnostics import Finding
from openstategraph.compile.node_runtime import NodeRuntime, RuntimeServices
from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.extensions import TOOLS_GROUP, entry_point_tools, reset_entry_point_cache


# --------------------------------------------------------------------------
# The tools a third party's distribution would ship: one healthy, one with the
# 87 slip, in one `load()` result. They travel together on purpose — a fix that
# only isolates *entry points* from each other passes a two-plugin fixture and
# still loses this one.
# --------------------------------------------------------------------------


class AcmeGood(BaseTool):
    name = "acme_good"
    description = "A perfectly good tool from the same distribution."
    node_type = "tool.acme-good"
    Args = NoArgs

    def _execute(self, args: Any) -> ToolResult:
        return ToolResult(content="good")


class AcmeAlsoGood(BaseTool):
    name = "acme_also_good"
    description = "A second healthy tool, wired to the same agent."
    node_type = "tool.acme-also-good"
    Args = NoArgs

    def _execute(self, args: Any) -> ToolResult:
        return ToolResult(content="also good")


class AcmeBespoke(BaseTool):
    """`args_schema` is the name on the *other* side of the seam."""

    name = "acme_bespoke"
    description = "Wrote args_schema instead of Args."
    node_type = "tool.acme-bespoke"
    args_schema = NoArgs

    def _execute(self, args: Any) -> ToolResult:
        return ToolResult(content="bespoke")


class AcmeAbstractBase(BaseTool):
    """Abstract for the ordinary reason, and with no `Args` either.

    Its diagnosis must stay the *abstract* one: the Args check must not
    overtake a fault that is already named better.
    """

    name = "acme_base"
    description = "Shared config for a family."
    node_type = "tool.acme-base"


class AcmeMean(BaseTool):
    """Binds by raising. Nothing to do with `Args` — the general case."""

    name = "acme_mean"
    description = "Its as_langchain_tools raises."
    node_type = "tool.acme-mean"
    Args = NoArgs

    def _execute(self, args: Any) -> ToolResult:  # pragma: no cover - never reached
        return ToolResult(content="mean")

    def as_langchain_tools(self, warnings: list[str] | None = None) -> list[Any]:
        raise RuntimeError("the MCP handshake exploded")


class _Dist:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeEntryPoint:
    """Only what the loader is allowed to touch: name, group, dist, load()."""

    def __init__(self, name: str, group: str, dist: str, result: Any) -> None:
        self.name = name
        self.group = group
        self.dist = _Dist(dist)
        self._result = result

    def load(self) -> Any:
        return self._result


def install(monkeypatch: pytest.MonkeyPatch, *entry_points: FakeEntryPoint) -> None:
    def fake(*, group: str | None = None, **_: Any) -> list[FakeEntryPoint]:
        return [ep for ep in entry_points if group in (None, ep.group)]

    monkeypatch.setattr(importlib.metadata, "entry_points", fake)
    reset_entry_point_cache()


@pytest.fixture(autouse=True)
def _clean_cache() -> Any:
    reset_entry_point_cache()
    yield
    reset_entry_point_cache()


# --------------------------------------------------------------------------
# The document, and the runtime the canvas would build for it.
# --------------------------------------------------------------------------


def _document(*tool_types: str) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {"id": "in1", "type": "io.input", "data": {}},
        {"id": "agent1", "type": "agent.llm", "data": {"tier": "react"}},
        {"id": "out1", "type": "io.output", "data": {}},
    ]
    edges: list[dict[str, Any]] = [
        {"source": {"nodeId": "in1", "portId": "text"},
         "target": {"nodeId": "agent1", "portId": "prompt"}},
        {"source": {"nodeId": "agent1", "portId": "result"},
         "target": {"nodeId": "out1", "portId": "text"}},
    ]
    for index, tool_type in enumerate(tool_types):
        node_id = f"tool{index}"
        nodes.append({"id": node_id, "type": tool_type, "data": {}})
        edges.append(
            {"source": {"nodeId": node_id, "portId": "tool"},
             "target": {"nodeId": "agent1", "portId": "tools"}}
        )
    return {"version": 1, "name": "plugin repro", "nodes": nodes, "edges": edges}


def _bind(document: dict[str, Any], registry: dict[str, Any]) -> tuple[list[Any], NodeRuntime]:
    """`_bind_tools` for the one agent, exactly as the compiler reaches it."""
    plan = WorkflowCompiler().plan(document)
    runtime = NodeRuntime(services=RuntimeServices(model=None, tools=registry))  # type: ignore[arg-type]
    runtime._types = {n["id"]: n["type"] for n in document["nodes"]}
    runtime._nodes = {n["id"]: n for n in document["nodes"]}
    return runtime._bind_tools("agent1", plan), runtime


class TestOneToolThatRaisesWhileBindingCostsOneTool:
    """The general guard: whatever the cause, the other tools survive."""

    def _registry(self) -> dict[str, Any]:
        return {
            "tool.acme-good": AcmeGood(),
            "tool.acme-also-good": AcmeAlsoGood(),
            "tool.acme-mean": AcmeMean(),
        }

    def test_the_healthy_tools_are_still_bound(self) -> None:
        # The assertion the whole ticket is about. Before the guard this line
        # never ran: `_bind_tools` raised out of the compile.
        bound, _ = _bind(
            _document("tool.acme-good", "tool.acme-mean", "tool.acme-also-good"),
            self._registry(),
        )
        assert sorted(t.name for t in bound) == ["acme_also_good", "acme_good"]

    def test_the_broken_one_is_named_on_the_capability_channel(self) -> None:
        _, runtime = _bind(
            _document("tool.acme-good", "tool.acme-mean"), self._registry()
        )
        recorded = runtime.diagnostics.warnings()
        assert any("tool1" in w and "tool.acme-mean" in w for w in recorded), recorded

    def test_the_sentence_carries_the_exception(self) -> None:
        _, runtime = _bind(_document("tool.acme-mean"), self._registry())
        recorded = " ".join(runtime.diagnostics.warnings())
        assert "RuntimeError" in recorded
        assert "the MCP handshake exploded" in recorded

    def test_it_travels_the_same_channel_every_lost_capability_uses(self) -> None:
        _, runtime = _bind(_document("tool.acme-mean"), self._registry())
        assert runtime.diagnostics.any(Finding.CAPABILITY_FAILED)


class TestTheBrokenPluginNeverReachesTheRegistry:
    """87's `Args` check, applied on the plugin path with 87's own sentence."""

    def _discovered(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        install(
            monkeypatch,
            FakeEntryPoint(
                "acme", TOOLS_GROUP, "acme-tools", [AcmeGood, AcmeBespoke, AcmeAlsoGood]
            ),
        )
        return entry_point_tools()

    def test_the_healthy_siblings_still_register(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # One `load()` result, three classes. Losing the two good ones is the
        # defect; this is the line that catches a guard that drops too much.
        discovered = self._discovered(monkeypatch)
        assert sorted(discovered.values) == ["tool.acme-also-good", "tool.acme-good"]

    def test_the_broken_one_is_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert "tool.acme-bespoke" not in self._discovered(monkeypatch).values

    def test_the_warning_names_the_class_and_the_distribution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        warnings = self._discovered(monkeypatch).warnings
        assert len(warnings) == 1, warnings
        assert "AcmeBespoke" in warnings[0]
        assert "acme-tools" in warnings[0]

    def test_it_says_what_87_says_about_the_same_mistake(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # One mistake, one wording — the reason `_missing_args_message` lives
        # in the diagnoses block rather than at either call site.
        warning = self._discovered(monkeypatch).warnings[0]
        assert "Args = NoArgs" in warning
        assert "args_schema" in warning


class TestRealFaultsAreStillRealFaults:
    """The Args check must not overtake a fault already named better, and must
    not become a blanket that buries a distribution that will not import."""

    def test_an_abstract_class_keeps_its_abstract_diagnosis(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install(
            monkeypatch,
            FakeEntryPoint("acme", TOOLS_GROUP, "acme-tools", [AcmeAbstractBase, AcmeGood]),
        )
        discovered = entry_point_tools()
        assert list(discovered.values) == ["tool.acme-good"]
        assert len(discovered.warnings) == 1, discovered.warnings
        assert "_execute" in discovered.warnings[0]

    def test_a_distribution_that_will_not_import_still_says_so(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry_point = FakeEntryPoint("acme", TOOLS_GROUP, "acme-tools", None)
        entry_point.load = lambda: (_ for _ in ()).throw(ImportError("no such module"))  # type: ignore[method-assign]
        install(monkeypatch, entry_point)
        warnings = entry_point_tools().warnings
        assert any("ImportError" in w and "no such module" in w for w in warnings), warnings


class TestTheThreeDoorsAgree:
    """Palette, `validate`, run — one class, one answer: absent."""

    @pytest.fixture(autouse=True)
    def _installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        install(
            monkeypatch,
            FakeEntryPoint("acme", TOOLS_GROUP, "acme-tools", [AcmeGood, AcmeBespoke]),
        )

    def test_the_palette_does_not_offer_a_card_that_cannot_bind(self) -> None:
        from openstategraph.api.plugin_capabilities import plugin_tool_capabilities

        capabilities, warnings = plugin_tool_capabilities()
        assert [c.id for c in capabilities] == ["tool.acme-good"]
        assert any("AcmeBespoke" in w for w in warnings), warnings

    def test_validate_names_the_node_instead_of_calling_it_resolved(
        self, tmp_path: Path
    ) -> None:
        from openstategraph.validation import unresolved_tool_bindings

        package = tmp_path / "acme-flow"
        package.mkdir()
        findings = unresolved_tool_bindings(
            _document("tool.acme-good", "tool.acme-bespoke"), package
        )
        assert len(findings) == 1, findings
        assert "tool.acme-bespoke" in findings[0]
        assert "tool.acme-good" not in findings[0]

    def test_the_run_binds_the_good_one_and_reports_the_other(self) -> None:
        from openstategraph.api.registries import build_tool_registry

        registry = build_tool_registry(None, None)
        bound, runtime = _bind(
            _document("tool.acme-good", "tool.acme-bespoke"), registry
        )
        assert [t.name for t in bound] == ["acme_good"]
        assert any("tool.acme-bespoke" in w for w in runtime.diagnostics.warnings())
