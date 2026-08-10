"""The agent ladder: ``IAgent`` → ``AbstractAgentNode`` → ``Base/React/Deep/Custom``.

This mirrors the library's own layering (CLAUDE.md's three-tier table):

| Tier        | Construct                       | Class here        |
| ----------- | ------------------------------- | ----------------- |
| LangGraph   | hand-written ``StateGraph``     | ``CustomGraphNode`` |
| LangChain   | ``create_agent`` (ReAct)        | ``ReactAgentNode``  |
| Deep Agents | ``create_deep_agent``           | ``DeepAgentNode``   |

Two rules the shape enforces:

- **The base holds the minimum.** ``AbstractAgentNode`` owns the three
  resolvers — ``resolve_model`` / ``resolve_prompt`` / ``resolve_middleware``
  — and the one template method that sequences them. A concrete supplies only
  what makes it that tier: which constructor it calls and which middleware
  slots it presets. Nothing else may accrete here; a new shared concern is a
  collaborator (like ``SystemPrompt``), not a new base member.

- **``DeepAgentNode`` is a sibling of ``ReactAgentNode``, never a subclass.**
  ``create_deep_agent`` is ``create_agent`` plus a fixed middleware slot
  assembly — the relationship is *data*, so it is expressed as a preset, not
  as inheritance. (An earlier draft had ``DeepAgentNode extends
  ReactAgentNode``; CLAUDE.md records why that was wrong.)

Retry, timeout and caching are **not** here, and must never be: they are
graph-assembly parameters (``add_node`` / ``set_node_defaults``), applied by
the compiler to every node family alike.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Protocol, runtime_checkable

from openstategraph.abc.middleware import MiddlewareSlotTable
from openstategraph.abc.prompt import SystemPrompt


@runtime_checkable
class IAgent(Protocol):
    """The contract consumers depend on: a name, and a build to a Runnable."""

    name: str

    def build(self) -> Any: ...


class AbstractAgentNode(ABC):
    """Shared *capability*, never shared *composition*.

    Everything every agent tier needs exactly once: config in, and the three
    resolution steps that turn config into a model, a prompt and a middleware
    list. The composition itself — which constructor, which slot preset —
    belongs to the concrete tier.
    """

    #: The canonical slot order the base owns. Contributors name a slot; they
    #: never say "position 3". Slots the base does not know about flatten
    #: after these, in first-set order.
    SLOT_ORDER: ClassVar[tuple[str, ...]] = (
        "skills",
        "filesystem",
        "subagents",
        "summarization",
        "limits",
        "patch-tool-calls",
    )

    #: Locked prompt machinery. Empty by default — an agent, unlike a router,
    #: legitimately answers free-form, so the base imposes no contract. A tier
    #: or a node type overrides these when it *does* own machinery.
    PREAMBLE: ClassVar[str] = ""
    OUTPUT_CONTRACT: ClassVar[str] = ""

    def __init__(
        self,
        *,
        name: str,
        model: Any = None,
        tools: Any = (),
        rules: str = "",
        context: str = "",
        middleware: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.tools = list(tools)
        #: The developer's system-prompt rules (the editable part).
        self.rules = rules
        #: Machine-supplied situational text — e.g. the ``skill`` port's
        #: upstream value. Rides above the rules, per SystemPrompt's ordering.
        self.context = context
        #: Named slot contributions from config; replacement is by slot name.
        self._middleware_contributions = dict(middleware or {})

    # -- the three resolvers: the single places config becomes a thing ----- #

    def resolve_model(self) -> Any:
        return self.model

    def system_prompt(self) -> SystemPrompt:
        """The assembled prompt, as a structure — inspectable without a run."""
        return (
            SystemPrompt(preamble=self.PREAMBLE, output_contract=self.OUTPUT_CONTRACT)
            .with_context(self.context)
            .with_rules(self.rules)
        )

    def resolve_prompt(self) -> str | None:
        """The string the model sees, or ``None`` when nothing is configured.

        ``None`` matters: passing ``system_prompt=""`` to ``create_agent``
        would still *override* the library's own default, which is not what an
        unconfigured node means.
        """
        rendered = self.system_prompt().render()
        return rendered or None

    def resolve_middleware(self) -> MiddlewareSlotTable:
        """Preset slots first, then config contributions, replacement by name."""
        table = MiddlewareSlotTable(order=self.SLOT_ORDER)
        table.merge(self.middleware_preset())
        table.merge(self._middleware_contributions)
        return table

    # -- what a concrete tier supplies ------------------------------------ #

    def middleware_preset(self) -> dict[str, Any]:
        """The slots this tier fills before config gets a say. Empty by default."""
        return {}

    @abstractmethod
    def build_agent(
        self, *, model: Any, tools: list[Any], system_prompt: str | None, middleware: list[Any]
    ) -> Any:
        """Calls this tier's constructor. The only abstract member."""

    # -- the template method ---------------------------------------------- #

    def build(self) -> Any:
        """Resolve everything, then let the tier construct. Never overridden
        to change *sequence* — only ``build_agent`` varies."""
        return self.build_agent(
            model=self.resolve_model(),
            tools=self.tools,
            system_prompt=self.resolve_prompt(),
            middleware=self.resolve_middleware().flatten(),
        )


class BaseAgentNode(AbstractAgentNode):
    """The usable default: a plain ``create_agent`` loop.

    ``_constructor`` is an instance attribute so a test can record the call
    without patching the library, and so a subclass swaps constructors by
    assignment rather than by overriding ``build_agent`` again.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        from langchain.agents import create_agent

        self._constructor = create_agent

    def build_agent(
        self, *, model: Any, tools: list[Any], system_prompt: str | None, middleware: list[Any]
    ) -> Any:
        kwargs: dict[str, Any] = {"model": model, "tools": tools, "name": self.name}
        if system_prompt is not None:
            kwargs["system_prompt"] = system_prompt
        if middleware:
            kwargs["middleware"] = middleware
        return self._constructor(**kwargs)


class ReactAgentNode(BaseAgentNode):
    """The LangChain tier: ``create_agent``, no preset slots.

    Exists as a named tier (rather than using ``BaseAgentNode`` directly) so
    that "react" in a document maps to a class whose meaning cannot drift if
    the base ever grows a different default.
    """


class DeepAgentNode(BaseAgentNode):
    """The harness tier: ``create_deep_agent``.

    A sibling of ``ReactAgentNode`` — same base, different constructor and a
    ``subagents`` pass-through. The deepagents package pre-assembles its own
    middleware stack internally; slots contributed here ride after it via the
    library's ``middleware`` parameter.
    """

    def __init__(self, *, subagents: list[dict[str, Any]] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        from openstategraph._extras import require_extra

        deepagents = require_extra("deepagents", "deep", "tier='deep' agent nodes")

        self._constructor = deepagents.create_deep_agent
        self.subagents = list(subagents or [])

    def build_agent(
        self, *, model: Any, tools: list[Any], system_prompt: str | None, middleware: list[Any]
    ) -> Any:
        kwargs: dict[str, Any] = {"model": model, "tools": tools, "name": self.name}
        if system_prompt is not None:
            kwargs["system_prompt"] = system_prompt
        if middleware:
            kwargs["middleware"] = middleware
        if self.subagents:
            kwargs["subagents"] = self.subagents
        return self._constructor(**kwargs)


class CustomGraphNode(AbstractAgentNode):
    """The LangGraph tier: the developer already built the graph.

    Holds a user-authored Runnable (a compiled ``StateGraph``, or anything
    with ``invoke``) and returns it untouched — resolution has nothing to
    resolve, which is exactly why prompt machinery must never be forced onto
    this class (CLAUDE.md's argument against ``AbstractPromptedNode``).
    """

    def __init__(self, *, name: str, runnable: Any) -> None:
        super().__init__(name=name)
        self.runnable = runnable

    def build_agent(self, **_kwargs: Any) -> Any:  # pragma: no cover - via build()
        return self.runnable

    def build(self) -> Any:
        if self.runnable is None:
            raise ValueError(
                f"CustomGraphNode {self.name!r} has no runnable — a custom tier "
                "references code in the workflow's functions/, it cannot be blank"
            )
        return self.runnable


def agent_node_for_tier(tier: str) -> type[BaseAgentNode]:
    """The one place a document's ``tier`` string becomes a class.

    Unknown values fall back to ReAct rather than raising: a misconfigured
    tier should degrade to the plainest working agent, not abort a compile.
    ``custom`` also lands here deliberately — a custom graph needs a runnable
    no tier string can supply, so reaching it is a wiring step (the compiler
    resolves the referenced function), never a lookup.
    """
    # Annotated because an inferred dict of two ABCs joins to `ABCMeta`, which
    # is not the return type and would make every caller's `.tier` untyped.
    tiers: dict[str, type[BaseAgentNode]] = {"react": ReactAgentNode, "deep": DeepAgentNode}
    return tiers.get(tier, ReactAgentNode)


__all__ = [
    "IAgent",
    "AbstractAgentNode",
    "BaseAgentNode",
    "ReactAgentNode",
    "DeepAgentNode",
    "CustomGraphNode",
    "agent_node_for_tier",
]
