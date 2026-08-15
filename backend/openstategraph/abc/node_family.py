"""The ladder a third party subclasses to contribute a **node family**.

CLAUDE.md's open/closed rule: "extend by **registering**, never by editing the
engine. Every extension point is a `Registry<T>`: node types, executors,
providers … A new capability must not require touching `core/`." The editor
half of that held — a brand-new node type reaches the palette, the serializer,
the executor lookup and the connection rules by registration alone, walked in
`src/core/extendability.test.ts`. The compiler half did not: `NodeRuntime`'s
builder table was a private dict literal, so a node family the engine had never
heard of resolved to the passthrough builder. It compiled, it ran, and it did
nothing.

This is the missing seam. A family declares the node type it serves and how to
build that node's step; `openstategraph.node_families` is the entry-point group
that installs one (see `openstategraph.extensions`).

    # in the THIRD PARTY's pyproject.toml
    [project.entry-points."openstategraph.node_families"]
    sentiment = "acme_osg:SentimentFamily"

    # acme_osg.py
    from openstategraph.abc import BaseNodeFamily, NodeBuildContext

    class SentimentFamily(BaseNodeFamily):
        node_type = "analyse.sentiment"

        def respond(self, text: str, context: NodeBuildContext) -> str:
            return "positive" if ":)" in text else "negative"

**What a family may see is `NodeBuildContext`, not the runtime.** The runtime
is a 2,000-line compiler internal with no stability guarantee; the context is
the narrow, named set of things building a node legitimately needs — this
node's own id and document entry, the compiled plan, the runtime's
collaborators, the diagnostics channel, and two callables (`upstream_text`,
`resolve_model`) that would otherwise each be a reimplementation of compiler
behaviour in every plugin.

**Built-ins are un-shadowable.** `NodeRuntime.builder_for` consults its own
table first and reports a family that tried, naming the distribution. A
plugin's node type also may not begin `function.` — a `function.<name>` node
binds a callable named in the *document*, and `extensions`' own docstring
records why a distribution must not be able to change what one resolves to.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Mapping, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - types only, as `loader.py` established
    from openstategraph.compile.diagnostics import CompileDiagnostics
    from openstategraph.compile.workflow_compiler import CompiledPlan


@dataclass(frozen=True)
class NodeBuildContext:
    """Everything a node family may see of the runtime that is building it.

    A parameter object rather than eight arguments, for the reason
    `RuntimeServices` is one: this is a **published** signature, so every
    capability a later version hands a family would otherwise widen the
    `build` of every family ever shipped.
    """

    #: This node's canvas id — the key its output is written under.
    node_id: str
    #: This node's raw document entry. `data` below is the part families want.
    node: dict[str, Any]
    #: What the compiler decided about the graph before it was built: nodes,
    #: edges, conditional routes, fan-out. Read-only in every honest use.
    plan: 'CompiledPlan'
    #: The runtime's collaborators — model, tools, functions, memory settings,
    #: the memory store. Typed `Any` here only to keep this module out of the
    #: compiler's import graph; it is a `compile.node_runtime.RuntimeServices`.
    services: Any = None
    #: Where a family reports what it could not do. Use
    #: `Finding.CAPABILITY_FAILED` for "I was asked for something I could not
    #: supply"; raising from `build` is reported for you, but as our sentence
    #: rather than yours.
    diagnostics: 'CompileDiagnostics | None' = None
    #: The text this node's upstream nodes produced, given the run state —
    #: the compiler's own `_upstream_text` over this node's incoming edges,
    #: handed over rather than re-derived, because "what did the node before
    #: me say" has one right answer and a second implementation of it in every
    #: plugin is a second answer.
    upstream_text: Callable[[Mapping[str, Any]], str] = field(
        default=lambda _state: ""
    )
    #: This node's own model, falling back to the graph's shared default —
    #: including the provider/model spelling, the per-node override and
    #: reasoning effort, none of which a plugin should have to know about.
    resolve_model: Callable[[dict[str, Any]], Any] = field(default=lambda _data: None)

    @property
    def data(self) -> dict[str, Any]:
        """This node's configuration, as the editor saved it. Never `None`."""
        return dict(self.node.get("data") or {})


@runtime_checkable
class INodeFamily(Protocol):
    """The contract `NodeRuntime.builder_for` depends on.

    A `Protocol`, for the reason `IRouter` is one: a family assembled some
    other way — a closure, a dataclass, an adapter over somebody else's
    framework — satisfies this without inheriting from us.
    """

    #: The document `type` this family serves, e.g. `"analyse.sentiment"`.
    node_type: str

    def build(self, context: NodeBuildContext) -> Callable[..., Any]:
        """The step function this node runs: `state -> state update`."""
        ...


class BaseNodeFamily(ABC):
    """A usable default: text in, text out, state plumbing already written.

    A family that only transforms the text its upstream node produced —
    which is most of them — implements `respond` and inherits everything
    else: reading upstream output, writing `outputs[node_id]`, and turning an
    exception at run time into a failure marker rather than a 500.

    Two state keys are written, matching `_discovered_function`, the built-in
    this ladder generalises: `outputs[node_id]` so a downstream node can read
    it, and `answer` so a family that happens to be the last node before the
    exit still answers. Both carry named reducers in `RunState` — which is
    what makes it safe for two node types to write `answer`, and is the rule
    CLAUDE.md states after an `InvalidUpdateError` found live.

    A family needing more than one string in and one out — fan-out, a
    conditional edge, its own subgraph — overrides `build` instead and talks
    to the plan directly.
    """

    #: The document `type` this family serves. Required, and namespaced by
    #: convention (`<verb>.<thing>`), because it is what a document names.
    node_type: ClassVar[str] = ""

    def build(self, context: NodeBuildContext) -> Callable[..., Any]:
        """The step function. Override for anything `respond` cannot express."""
        from openstategraph.compile.workflow_compiler import failure_marker

        node_id = context.node_id

        def run(state: Mapping[str, Any]) -> dict[str, Any]:
            try:
                answer = self.respond(context.upstream_text(state), context)
            except Exception as exc:
                # The same shape `_discovered_function` uses for a callable
                # that raised: the run continues and says what happened,
                # rather than failing the whole graph on one plugin's bug.
                return {
                    "outputs": {
                        node_id: failure_marker(
                            node_id,
                            f"{type(self).__name__} failed: {type(exc).__name__}: {exc}",
                        )
                    }
                }
            return {"outputs": {node_id: answer}, "answer": answer}

        return run

    @abstractmethod
    def respond(self, text: str, context: NodeBuildContext) -> str:
        """What this node produces, given what the node before it produced."""


__all__ = ["BaseNodeFamily", "INodeFamily", "NodeBuildContext"]
