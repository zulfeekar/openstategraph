"""The tool ladder: ``ITool`` → ``BaseTool`` → concrete tool.

Generic, so it lives in the shared backend package rather than under a workflow.
Concrete tools bound to one domain live in ``workflows/<slug>/tools/``.

Two rules from CLAUDE.md are load-bearing here and easy to break later:

**Pydantic is the single source of truth.** A tool's arguments are a Pydantic
model, and the TypeScript types are *generated* from it. Never hand-mirror an
argument schema across the boundary.

**Wrap LangChain, never subclass it.** ``BaseTool`` below is *ours*. It exposes
``as_langchain_tool()``, which adapts to a ``StructuredTool`` at the seam. If we
subclassed ``langchain_core.tools.BaseTool`` instead, every upstream change to
its internals would reach into our whole tool catalogue, and the compile seam
would stop being one-directional.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """What every tool returns.

    Errors are *data*, not exceptions. A model writing SQL will get it wrong,
    and the useful response is to hand the error back so it can read and retry —
    raising would abort the graph node instead of letting the agent recover.
    """

    ok: bool = True
    content: str = ""
    error: str | None = None

    @classmethod
    def failure(cls, message: str) -> ToolResult:
        return cls(ok=False, content="", error=message)


@runtime_checkable
class ITool(Protocol):
    """The contract consumers depend on.

    A ``Protocol`` rather than an ABC so that a plain callable or a third-party
    object can satisfy it without inheriting from us — the interface describes a
    shape, and requiring inheritance to participate is what makes a hierarchy
    closed for extension.
    """

    name: str
    description: str

    def run(self, **kwargs: Any) -> ToolResult: ...


class BaseTool(ABC):
    """Usable default implementation.

    Subclasses declare ``name``, ``description`` and ``Args``, then implement
    ``_execute``. Everything shared — argument validation, turning a raised
    exception into a ``ToolResult``, and the LangChain adaptation — is declared
    **once** here and never repeated per tool. That is the anti-duplication rule,
    and it is why a new tool is a few lines rather than a copied file.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    #: The canvas node type this tool answers to (`tool.tabular-query`).
    #: The tool declares its own wiring identity — ticket 33 — so the
    #: runtime registry, the discovery endpoint and the (eventually
    #: generated) TypeScript node definition all key off one declaration.
    #: Empty means "not placeable on a canvas", which is legitimate for a
    #: tool only ever handed to an agent programmatically.
    node_type: ClassVar[str] = ""
    #: Pydantic model describing the arguments. The source of truth for the
    #: generated TypeScript, and for the schema the LLM is shown.
    Args: ClassVar[type[BaseModel]]

    @abstractmethod
    def _execute(self, args: BaseModel) -> ToolResult:
        """Do the work. Arguments are already validated."""

    def configure(self, data: dict[str, Any]) -> "BaseTool":
        """One bound node's own field values, delivered to its tool.

        Returns the instance to use — **a fresh one when config matters**,
        never a mutation of the shared registry instance: two nodes of the
        same tool type with different config in one document would otherwise
        clobber each other. The default ignores config entirely, which is
        correct for a stateless tool; a tool with a configurable field
        overrides this and reads exactly the keys it declared.
        """
        return self

    def run(self, **kwargs: Any) -> ToolResult:
        """Validate, execute, and convert failure into data.

        The single place a tool's exceptions become a readable result, so no
        concrete tool needs its own try/except.
        """
        try:
            args = self.Args(**kwargs)
        except Exception as exc:  # pydantic.ValidationError and friends
            return ToolResult.failure(f"Invalid arguments: {exc}")

        try:
            return self._execute(args)
        except Exception as exc:
            return ToolResult.failure(f"{type(exc).__name__}: {exc}")

    def as_langchain_tool(self) -> Any:
        """Adapt to a LangChain ``StructuredTool`` at the boundary.

        Imported lazily so the tool catalogue stays importable — and unit
        testable — without LangChain present.
        """
        from langchain_core.tools import StructuredTool

        def _call(**kwargs: Any) -> str:
            result = self.run(**kwargs)
            return result.content if result.ok else f"Error: {result.error}"

        return StructuredTool.from_function(
            func=_call,
            name=self.name,
            description=self.description,
            args_schema=self.Args,
        )

    def manifest(self) -> dict[str, Any]:
        """What the editor needs to render this tool as a node.

        The frontend consumes this; it never imports the implementation. This is
        the one-directional compile seam: description flows out, nothing flows
        back in.
        """
        return {
            "name": self.name,
            "description": self.description,
            "node_type": self.node_type,
            "args_schema": self.Args.model_json_schema(),
        }


class NoArgs(BaseModel):
    """For tools that take nothing — still a model, so codegen stays uniform."""

    model_config = {"extra": "forbid"}


__all__ = ["BaseTool", "ITool", "NoArgs", "ToolResult", "Field"]
