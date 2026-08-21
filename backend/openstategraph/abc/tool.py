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
from dataclasses import dataclass
from typing import Any, Callable, ClassVar, Protocol, runtime_checkable

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


#: Every `ToolField.kind` the editor renders as the control it names.
#:
#: The closed set a plugin author writes against, and the **owner** of that
#: vocabulary — `src/app/pluginNodes.ts` re-declares the same four and
#: `backend/tests/test_the_second_consumer_is_pinned.py` fails if the two
#: disagree. Before framework-packaging ticket 11 the set was a sentence in a
#: docstring, and the sentence and the renderer had different memberships.
#:
#: Narrower than `src/core/model/contracts/fields.ts`, deliberately: that is
#: the editor's own field vocabulary, nine kinds wide, and several of them
#: (`repeatable-group`, `file`, `readonly`) mean nothing coming from a tool
#: that has one flat `data` record and no upload seam. A plugin gets the four
#: that survive the wire.
PLUGIN_FIELD_KINDS: tuple[str, ...] = ("text", "textarea", "select", "toggle")


@dataclass(frozen=True)
class ToolField:
    """One control on the tool's editor card, declared by the tool itself.

    **The two-place authoring problem this exists to remove** (register PK-06).
    A tool is bindable the moment its Python class installs, but a tool the
    editor cannot *render* is a capability nobody can wire — and a third party
    cannot add a TypeScript file to this repo. So a distribution declares its
    card's fields here, in the same class the runtime binds, and the editor
    builds the card from the capabilities payload. One declaration, two
    consumers, no hand-mirrored type across the boundary.

    The value a user types lands in the node's `data` under `key`, and reaches
    the tool through `BaseTool.configure(data)` — the mechanism that already
    exists for a bundled tool's own config (the email tool's recipient). A tool
    that declares fields but never overrides `configure` gets a card whose
    values it ignores, which is why `configure` is where the docs point.

    `kind` names an editor control, deliberately from a small closed set —
    `PLUGIN_FIELD_KINDS`, above. An unknown kind renders as text rather than
    failing the whole card: a plugin built against a newer editor must
    degrade, not disappear. It also earns a capability warning, because
    degrading silently is how the wrong control looks like the right one.

    **`number` was in this sentence and in no renderer** (framework-packaging
    ticket 11). It was documented here and in `docs/building-an-atom.md` as a
    member of the closed set, `src/app/pluginNodes.ts` had no branch for it,
    and `src/core/model/contracts/fields.ts` — the editor's authoritative
    field vocabulary — has no such kind at all. A plugin author following the
    documented set got a text box and no signal. The set is now what the
    renderer implements, and a test says so in both directions.
    """

    #: Key within the node's `data` record — what `configure()` reads.
    key: str
    #: Micro-label above the control. Defaults to the key.
    label: str = ""
    kind: str = "text"
    #: JSON-representable only: this crosses the wire. Never `Infinity`/`NaN`.
    default_value: Any = ""
    placeholder: str = ""
    hint: str = ""
    #: `select` only, `(value, label)` pairs — or bare strings, used for both.
    options: tuple[Any, ...] = ()


@runtime_checkable
class ITool(Protocol):
    """The contract consumers depend on.

    A ``Protocol`` rather than an ABC so that a plain callable or a third-party
    object can satisfy it without inheriting from us — the interface describes a
    shape, and requiring inheritance to participate is what makes a hierarchy
    closed for extension.

    **If you are subclassing ``BaseTool``, do not implement this method.**
    ``run`` is the *caller's* verb — what a consumer of any tool invokes — and
    ``BaseTool`` already implements it for you (validate, execute, turn an
    exception into data). The one method a ``BaseTool`` subclass implements is
    ``_execute(self, args)``. Implementing ``run`` instead leaves ``_execute``
    abstract, which makes the class uninstantiable and therefore invisible to
    discovery; ``BaseTool.__init_subclass__`` now refuses that at class
    definition time rather than letting it ship as a tool that does nothing.
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

    **``_execute`` is what you implement; ``run`` is what callers call.**
    ``ITool`` advertises ``run(**kwargs)`` because that is the shape a
    *consumer* depends on, and reading the interface first has led people to
    override ``run`` — which leaves ``_execute`` abstract, so the class cannot
    be instantiated and discovery finds nothing to register. That produced the
    worst failure shape this project has: a plugin that installs cleanly, type
    checks, and is simply absent. ``__init_subclass__`` below refuses it at
    class-definition time, naming the class and the fix. A genuinely
    intermediate base that wants to wrap ``run`` for its own subclasses opts
    out by re-declaring ``_execute`` as ``@abstractmethod`` — an explicit "I
    know, my subclasses supply the work".
    """

    name: ClassVar[str]
    description: ClassVar[str]
    #: The canvas node type this tool answers to (`tool.chinook-execute-sql`).
    #: The tool declares its own wiring identity — ticket 33 — so the
    #: runtime registry, the discovery endpoint and the (eventually
    #: generated) TypeScript node definition all key off one declaration.
    #: Empty means "not placeable on a canvas", which is legitimate for a
    #: tool only ever handed to an agent programmatically.
    node_type: ClassVar[str] = ""
    #: Pydantic model describing the arguments. The source of truth for the
    #: generated TypeScript, and for the schema the LLM is shown.
    Args: ClassVar[type[BaseModel]]
    #: Controls the editor puts on this tool's card, declared by the tool
    #: (register PK-06). Empty is the common case — a stateless tool needs no
    #: configuration — and a *bundled* tool declares its card in TypeScript
    #: instead, where the card can be as rich as it likes. This exists for the
    #: half of the world that cannot add a TypeScript file: an installed
    #: distribution. See `ToolField` and `configure`.
    node_fields: ClassVar[tuple[ToolField, ...]] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Fail at import, the earliest honest moment.

        Only one shape is refused: a subclass that defines ``run`` while no
        class in its ancestry (below ``BaseTool``) defines ``_execute`` at all.
        Such a class is *already* unusable — ``_execute`` stays abstract, so
        ``cls()`` raises — so refusing it here cannot break code that works
        today; it only moves an invisible failure (a tool absent from every
        registry) to a loud one, at the line that caused it.
        """
        super().__init_subclass__(**kwargs)
        if "run" not in cls.__dict__:
            return
        if any("_execute" in klass.__dict__ for klass in cls.__mro__ if klass is not BaseTool):
            return
        raise TypeError(_run_override_message(cls.__qualname__))

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

    def as_langchain_tool(self, on_call: Callable[[str], None] | None = None) -> Any:
        """Adapt to a LangChain ``StructuredTool`` at the boundary.

        Imported lazily so the tool catalogue stays importable — and unit
        testable — without LangChain present.

        ``on_call`` is told this tool's name **each time it actually runs**.
        It exists because a caller that hands out tools it does not own has no
        other way to learn which of them were used: the knowledge explorer
        writes a provenance footer, and that footer used to list every tool it
        had *offered* the agent, which is a claim about availability dressed up
        as a claim about evidence (`production-ready` 12). The codebase builder
        already records this way — its read tools note each file into a shared
        set — so this is the same mechanism for tools resolved out of a
        registry rather than constructed here.

        Optional, and the default is exactly the previous behaviour, so no
        existing caller changed.
        """
        from langchain_core.tools import StructuredTool

        def _call(**kwargs: Any) -> str:
            if on_call is not None:
                on_call(self.name)
            result = self.run(**kwargs)
            return result.content if result.ok else f"Error: {result.error}"

        return StructuredTool.from_function(
            func=_call,
            name=self.name,
            description=self.description,
            args_schema=self.Args,
        )

    def as_langchain_tools(self, warnings: list[str] | None = None) -> list[Any]:
        """A tool node contributes one tool. An MCP server contributes many.

        **This is the seam the canvas binds through**, and the default is
        exactly today's behaviour, so no concrete tool in this repository
        changed when it appeared. Liskov holds trivially: the singular case is
        the plural case with one element.

        It exists because `tool.mcp` breaks the one-node-one-tool assumption
        every other atom satisfies — one MCP server offers N tools, discovered
        at bind time. Expressing that by having the binding loop special-case a
        node type would have put knowledge of one atom into the compiler; a
        default method on the base puts it in the one class that needs it.

        `warnings` is the sink for anything that failed to *materialise*. A
        tool whose discovery needs the network (only `tool.mcp` does) appends a
        sentence here and returns fewer tools — or none — rather than raising,
        so a server that is down costs an agent one capability instead of
        costing the whole compile. `NodeRuntime._bind_tools` passes the list
        and records each sentence as a `CAPABILITY_FAILED` finding, which is
        the same channel every other lost capability already travels.
        """
        return [self.as_langchain_tool()]

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


# --------------------------------------------------------------------------
# Diagnoses, written once and reused everywhere a tool fails to materialise.
#
# Deliberately private (not in `__all__`): `openstategraph.abc` is Tier 1 and a
# name exported from it is a promise. These are internal wording, shared so
# that the definition-time TypeError, workflow-local discovery and entry-point
# loading say the *same* sentence — a developer who hits the trap through the
# plugin path and through their own `tools/` folder should not have to
# recognise two different descriptions of one mistake.
# --------------------------------------------------------------------------


def _run_override_message(class_name: str) -> str:
    """The RC-04 diagnosis: named class, named method, named fix."""
    return (
        f"{class_name} overrides run() but never implements _execute(), which leaves it "
        "abstract — it can never be instantiated, so no registry can ever hold it. "
        f"Implement `_execute(self, args)` on {class_name}; run() is the validated entry "
        "point BaseTool already provides (it builds Args, calls _execute, and turns an "
        "exception into a ToolResult), so leave it alone."
    )


def _missing_args_message(class_name: str) -> str:
    """The 87 diagnosis: named class, named ClassVar, named lookalike.

    Same voice as `_run_override_message` and for the same reason — a
    developer should learn what they forgot from a sentence, not from a
    traceback. It names `args_schema` explicitly because that is the spelling
    that *causes* the mistake: `ToolCapability`'s field and the
    `StructuredTool.from_function` keyword are both called `args_schema`, so
    writing it in a tool body reads right and leaves `Args` undeclared.
    """
    return (
        f"{class_name} declares no Args, so it can be neither described nor bound — "
        "BaseTool.Args is the Pydantic model run() validates against and "
        "as_langchain_tool() hands the model, and it has no default. Add "
        f"`Args = NoArgs` to {class_name} (or your own BaseModel). If you wrote "
        "`args_schema`, that is the name on the *other* side of the seam: the class "
        "attribute is `Args`."
    )


def _abstract_tool_diagnosis(cls: type) -> str:
    """Why this ``BaseTool`` subclass could not be instantiated.

    The ``run``-override case gets its own sentence. A generic "skipped an
    abstract class" would leave the reader exactly as stuck as the silence it
    replaced, which is the whole point of the ticket.
    """
    missing = tuple(sorted(getattr(cls, "__abstractmethods__", ()) or ()))
    overrides_run = any(
        "run" in klass.__dict__ for klass in cls.__mro__ if klass is not BaseTool
    )
    if "_execute" in missing and overrides_run:
        return _run_override_message(cls.__name__)
    if "_execute" in missing and len(missing) == 1:
        return (
            f"{cls.__name__} does not implement _execute(), so it is abstract and cannot be "
            "instantiated. Implement `_execute(self, args) -> ToolResult` — that is the one "
            "method a BaseTool subclass supplies."
        )
    listed = ", ".join(f"{name}()" for name in missing) or "at least one abstract method"
    return (
        f"{cls.__name__} is abstract — {listed} still unimplemented — so it cannot be "
        "instantiated. Implement it, or (if the class is a deliberate shared parent) name it "
        "with a leading underscore, `Abstract…` or `Base…` so discovery knows to pass over it."
    )


def _is_deliberate_base(cls: type) -> bool:
    """Two ways a class says "I am a parent of tools, not a tool".

    **Re-declaring ``_execute`` as ``@abstractmethod``** is the explicit one,
    and the same escape hatch ``__init_subclass__`` honours: a class that
    writes the abstract method out has stated its intent in code.

    **Its name** is the implicit one. `_SqlExplorerBase` in this very codebase
    is the pattern: a `BaseTool` subclass that exists only to hold shared
    configuration for a family and never declares `_execute` at all. There is
    no other signal available — every abstract class looks alike to `inspect` —
    and inventing a marker attribute would be a second spelling of something
    the name already says. Warning about these would train developers to
    ignore the channel, which costs more than the rare mis-named class it
    misses.
    """
    if getattr(cls.__dict__.get("_execute"), "__isabstractmethod__", False):
        return True
    name = cls.__name__
    return name.startswith(("_", "Abstract")) or (name.startswith("Base") and name != "Base")


class NoArgs(BaseModel):
    """For tools that take nothing — still a model, so codegen stays uniform."""

    model_config = {"extra": "forbid"}


__all__ = ["BaseTool", "ITool", "NoArgs", "ToolField", "ToolResult", "Field"]
