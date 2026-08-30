"""production-ready/87: a tool class that omits `Args` must cost one tool.

`BaseTool.Args` is a `ClassVar[type[BaseModel]]` with no default, and the
mistake that omits it is an ordinary one — `ToolCapability`'s own field is
spelled `args_schema`, and `to_langchain` passes `args_schema=self.Args`, so
`args_schema = NoArgs` in a tool body reads right and is wrong.

Before this file, such a class instantiated cleanly, entered the registry,
and then took `discover_tools`' single list comprehension down with an
`AttributeError` — a **500** from `GET /api/workflows/<slug>/capabilities`
that carried away every other tool in the package, the ambient tools, the
plugin tools and the `warnings` array that would have explained it.

The load-bearing assertion is not "the helper catches an exception". It is
**a healthy tool in the same module still arrives**, because that is the
difference between one lost capability and a lost palette.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openstategraph.api.capability_discovery import (
    discover_tool_instances,
    discover_tool_registry,
    discover_tools,
)

#: One module, two classes: the mistake and its healthy neighbour. They share
#: a file on purpose — a fix that only isolates *modules* from each other
#: passes a two-file fixture and still loses this one.
PAIR = '''\
from openstategraph.abc import BaseTool, NoArgs, ToolResult


class HealthyTool(BaseTool):
    name = "healthy"
    description = "A perfectly good tool, sharing a file with a broken one."
    node_type = "tool.healthy"
    Args = NoArgs

    def _execute(self, args) -> ToolResult:
        return ToolResult(content="healthy")


class BespokeTool(BaseTool):
    name = "bespoke"
    description = "Wrote args_schema, which is the name on the other side."
    node_type = "tool.bespoke"
    args_schema = NoArgs

    def _execute(self, args) -> ToolResult:
        return ToolResult(content="bespoke")
'''


def _package(root: Path, source: str = PAIR, name: str = "pair.py") -> Path:
    tools = root / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    (tools / name).write_text(source)
    return root


class TestTheHealthyNeighbourSurvives:
    """The severity, restated as an assertion."""

    def test_listing_still_describes_the_good_tool(self, tmp_path: Path) -> None:
        warnings: list[str] = []
        tools = discover_tools(_package(tmp_path), "my-flow", warnings=warnings)

        assert [t.node_type for t in tools] == ["tool.healthy"]
        assert tools[0].args_schema  # it was really described, not stubbed

    def test_the_registry_still_binds_the_good_tool(self, tmp_path: Path) -> None:
        registry = discover_tool_registry(_package(tmp_path), "my-flow")

        assert "tool.healthy" in registry
        # And the broken one is absent everywhere rather than present and
        # unbindable — `as_langchain_tool()` would raise the same
        # AttributeError, so `validate` and the runtime agree with this list.
        assert "tool.bespoke" not in registry


class TestTheSentence:
    """`BaseTool` already refuses the neighbouring mistake with a sentence
    that names the class and the fix. This one used to fall through."""

    def _warning(self, tmp_path: Path) -> str:
        warnings: list[str] = []
        discover_tool_instances(_package(tmp_path), "my-flow", warnings=warnings)
        assert len(warnings) == 1, warnings
        return warnings[0]

    def test_it_names_the_class(self, tmp_path: Path) -> None:
        assert "BespokeTool" in self._warning(tmp_path)

    def test_it_names_the_file(self, tmp_path: Path) -> None:
        assert "pair.py" in self._warning(tmp_path)

    def test_it_names_what_is_missing_and_how_to_write_it(self, tmp_path: Path) -> None:
        warning = self._warning(tmp_path)
        assert "Args" in warning
        assert "Args = NoArgs" in warning

    def test_it_names_the_lookalike_that_causes_the_mistake(self, tmp_path: Path) -> None:
        # The whole reason this is a plausible slip; a diagnosis that only
        # said "no Args" would leave a developer staring at `args_schema`.
        assert "args_schema" in self._warning(tmp_path)


class TestRealFaultsAreStillRealFaults:
    """Tolerance here must not become a blanket `except Exception` over
    discovery — a module that will not import is a different, worse thing
    and keeps its own louder sentence."""

    def test_an_unimportable_module_still_says_so(self, tmp_path: Path) -> None:
        warnings: list[str] = []
        _package(tmp_path, "import nosuchmodule_at_all\n", name="broken.py")
        discover_tool_instances(tmp_path, "my-flow", warnings=warnings)

        # The words moved in `launch-readiness/195` and the claim did not: a
        # `ModuleNotFoundError` for some *other* module now names that module
        # rather than saying only "could not be imported", because the remedy
        # differs. What this test is about is that the module is still named
        # and the consequence still stated.
        assert any(
            "broken.py" in w and "nosuchmodule_at_all" in w and "is missing from this run" in w
            for w in warnings
        ), warnings

    def test_a_deliberate_base_with_no_args_is_still_silent(self, tmp_path: Path) -> None:
        # `_SqlExplorerBase` is this pattern in the repository itself: a
        # `BaseTool` subclass holding shared config for a family, declaring
        # neither `_execute` nor `Args`. Warning about it would train
        # developers to ignore the channel.
        source = '''\
from openstategraph.abc import BaseTool, NoArgs, ToolResult


class _AcmeBase(BaseTool):
    name = "acme"
    description = "A family parent, not a tool."


class AcmePing(_AcmeBase):
    node_type = "tool.acme-ping"
    Args = NoArgs

    def _execute(self, args) -> ToolResult:
        return ToolResult(content="pong")
'''
        warnings: list[str] = []
        found: list[Any] = discover_tool_instances(
            _package(tmp_path, source, name="acme.py"), "my-flow", warnings=warnings
        )

        assert warnings == []
        assert [instance.node_type for _, instance in found] == ["tool.acme-ping"]


class TestTheEndpointCannotBeTakenDownByOneDescription:
    """The second half, and the one that holds whatever else goes wrong: the
    comprehension that died on the first exception is now a loop that reports
    one tool and keeps the rest."""

    def test_a_tool_whose_args_model_cannot_be_described_costs_only_itself(
        self, tmp_path: Path
    ) -> None:
        source = '''\
from openstategraph.abc import BaseTool, NoArgs, ToolResult


class GoodTool(BaseTool):
    name = "good"
    description = "Fine."
    node_type = "tool.good"
    Args = NoArgs

    def _execute(self, args) -> ToolResult:
        return ToolResult(content="good")


class Exploding:
    """Not a BaseModel; `model_json_schema()` blows up when called."""

    @staticmethod
    def model_json_schema():
        raise RuntimeError("boom")


class MeanTool(BaseTool):
    name = "mean"
    description = "Its Args is not describable."
    node_type = "tool.mean"
    Args = Exploding

    def _execute(self, args) -> ToolResult:
        return ToolResult(content="mean")
'''
        warnings: list[str] = []
        tools = discover_tools(
            _package(tmp_path, source, name="mean.py"), "my-flow", warnings=warnings
        )

        assert [t.node_type for t in tools] == ["tool.good"]
        assert any("MeanTool" in w and "mean.py" in w for w in warnings), warnings
