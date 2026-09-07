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
node's own id and document entry, the compiled plan, the diagnostics channel,
two callables (`upstream_text`, `resolve_model`) that would otherwise each be
a reimplementation of compiler behaviour in every plugin, and
`NodeCapabilities`, which is that same sentence applied to the collaborators.

That last one was the exception until framework-packaging ticket 09: the field
read `services: Any` and carried the whole `RuntimeServices`, so the paragraph
above was true of six fields out of seven. `NodeCapabilities` names three.

**Built-ins are un-shadowable.** `NodeRuntime.builder_for` consults its own
table first and reports a family that tried, naming the distribution. A
plugin's node type also may not begin `function.` — a `function.<name>` node
binds a callable named in the *document*, and `extensions`' own docstring
records why a distribution must not be able to change what one resolves to.
"""

from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Mapping, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - types only, as `loader.py` established
    from openstategraph.compile.diagnostics import CompileDiagnostics
    from openstategraph.compile.workflow_compiler import CompiledPlan


@dataclass(frozen=True)
class NodeCapabilities:
    """The runtime's collaborators a node family may reach — named, and only
    these.

    **Why this exists** (framework-packaging ticket 09). The field it replaces
    was `services: Any`, and what the compiler passed through it was the whole
    of `compile.node_runtime.RuntimeServices` — thirteen fields including
    `document_loader`, `package_loader`, `knowledge_dir_override` and
    `advisor_catalog`. That is the compiler internal this context exists to
    hide, published to every installed plugin through the one field on a
    stability-contract dataclass whose width nothing pinned. A field added to
    `RuntimeServices` next month widened the plugin seam, and the diff a
    reviewer saw was a line in the compiler — `public_api.txt` would not move,
    because the *name* `services` did not.

    The `Any` had a real reason and still does: `abc` must stay out of the
    compiler's import graph, so nothing here may name `RuntimeServices`. That
    is an argument for a façade, not for the object — this class is declared
    here, in `abc`, and the compiler fills it in.

    **Three fields, and the presumption is against a fourth.** They are what
    building a *step* legitimately needs and nothing more:

    - `tools` — the shared registry, keyed by node type, so a family can bind
      the capability a document's tool node names.
    - `functions` — the callables a package's `functions/` contributed, for the
      same reason.
    - `memory_store` — the long-term store, when the deployment has one.

    What is deliberately absent is everything that is the *compiler's* job
    rather than a step's: loading another document, resolving a package,
    finding a knowledge directory, the advisor catalogue, the middleware slot
    table. A family that finds itself needing one of those is describing a gap
    in this seam — the answer is a new named field here, argued and visible in
    the snapshot, not a widening nobody diffs.

    A model is not here either: `NodeBuildContext.resolve_model` already
    answers that question properly, including the per-node override and the
    provider spelling a plugin should not have to know.
    """

    #: Tool implementations, keyed by the node type a document names.
    tools: Mapping[str, Any] = field(default_factory=dict)
    #: Discovered callables, keyed by `function.<name>`.
    functions: Mapping[str, Any] = field(default_factory=dict)
    #: LangGraph's `BaseStore`, or `None` where the deployment has no memory.
    memory_store: Any = None


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
    #: What this family may reach of the runtime — see `NodeCapabilities`.
    #: Replaced `services: Any`, which was the whole `RuntimeServices`.
    capabilities: NodeCapabilities = field(default_factory=NodeCapabilities)
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

    @property
    def services(self) -> NodeCapabilities:
        """Deprecated spelling of `capabilities` (framework-packaging 09).

        The shim `docs/stability.md`'s deprecation policy requires, shipped in
        the same commit as the change rather than "before the release": a
        family written against the old name keeps working for the fields that
        survived, and hears about the new one.

        It returns the **façade**, not what `services` used to be. That is the
        change, not a shortcoming of the shim: the whole defect was that this
        name reached the compiler's own collaborators, so a plugin that read
        `context.services.document_loader` gets an `AttributeError` naming the
        attribute it should never have had. Loud, at the seam, rather than a
        `None` that behaves like a deployment without one.
        """
        warnings.warn(
            "NodeBuildContext.services is deprecated; use .capabilities, which "
            "names what a family may reach instead of handing over the compiler's "
            "RuntimeServices.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.capabilities


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
