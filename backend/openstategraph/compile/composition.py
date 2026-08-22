"""Drawing a composition, because LangGraph cannot draw this one.

`xray=True` expands a **LangGraph subgraph** — a compiled graph handed to
`add_node`. A mount is not that. `NodeRuntime._subgraph` compiles the child and
returns a **closure** that invokes it, so the parent's `StateGraph` holds an
ordinary Python function; LangGraph has no way to see through it and never
will. For as long as a preview was only `get_graph(xray=True).draw_mermaid()`,
`nested-mounts` — three documents, three levels, six nodes below the top —
rendered as three featureless boxes (`workflow-gallery` 28).

Two roads were open, and the commit that added this file prices both. This is
the second: **render the composition ourselves.** The first — make the child a
real subgraph node, which is what `xray` is *for* — would make the claim true
at the source, but the closure is load-bearing. It maps state across the
boundary, isolates the child from the parent's other keys, and gives the child
its own assets and memory namespace. Moving it is a compile-seam change to
behaviour several shipped things depend on, in service of a picture.

So the compiler says what it built, since it is the only thing that knows. The
splice below is deliberately the *same* one LangGraph performs for a genuine
subgraph (`langgraph/pregel/_draw.py`, "replace subgraphs"): trim the child's
`__start__`/`__end__`, `Graph.extend` it under the mount's name as a prefix,
and rewire the parent's edges onto the child's first and last nodes. Same
public drawable API, same `subgraph` blocks out of `draw_mermaid()` — so if a
node type ever *does* compile to a real subgraph, the two renderings agree
instead of competing.

Nothing here is on a run path. It is asked for only when something draws.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class MountedGraph:
    """One mount, as the compiler that built it can describe it.

    Recursive by construction: `mounts` is the *child's* map, so a grandchild
    costs no extra machinery. Written by `NodeRuntime._subgraph`, read only by
    `expand_mounts`.
    """

    #: The mounted package's slug — the child's identity, not the mount's.
    slug: str
    #: The compiled child. The same object the mount's closure invokes.
    graph: Any
    #: The child's own mounts, keyed by *its* graph node names.
    mounts: Mapping[str, "MountedGraph"] = field(default_factory=dict)
    #: What the child's document saved as `settings.recursionLimit`, already
    #: clamped by `workflow_step_budget`, or `None` if it saved none.
    #:
    #: `organisms-first-class` 63. The docstring above says this record is
    #: read only by `expand_mounts`; it now has a second reader,
    #: `step_budget.composition_step_budget`, which needs exactly the same
    #: thing a drawing needs — *what did the compiler actually build* — for a
    #: different question: what is the most this whole composition may spend.
    #: Recorded here rather than re-derived, because re-loading every child
    #: document to answer would be a second traversal that can disagree with
    #: the first, and the tree is already the compiler's own account.
    saved_step_budget: int | None = None


#: What the compiler adds around every document it builds. `__start__` and
#: `__end__` are the child's own entry and exit and must not survive a splice —
#: the parent already has its own. `__default_error_handler__` is the reason
#: this module cannot simply call LangGraph's `trim_first_node()`: it is an
#: **isolated** node, the target of no edge and the source of none, so
#: `Graph.first_node()` and `Graph.last_node()` each see two candidates and
#: answer `None`. LangGraph's own subgraph splice would decline to expand any
#: graph this compiler produces, for that reason and no other.
START = "__start__"
END = "__end__"


def _boundary(child: Any) -> tuple[str | None, str | None]:
    """The child's first and last real nodes, taken from its own `__start__`.

    Asked of the edges rather than of `Graph.first_node()`, which cannot
    answer here (see `START` above). A child whose entry or exit is not a
    single node is left unexpanded: the parent has exactly one edge in and one
    edge out of the mount, so there would be no honest place to attach them.
    """
    entries = {edge.target for edge in child.edges if edge.source == START}
    exits = {edge.source for edge in child.edges if edge.target == END}
    first = next(iter(entries)) if len(entries) == 1 else None
    last = next(iter(exits)) if len(exits) == 1 else None
    return first, last


def _trim_terminals(child: Any) -> None:
    """Drop the child's own `__start__`/`__end__` and every edge touching them."""
    for terminal in (START, END):
        child.nodes.pop(terminal, None)
    child.edges[:] = [
        edge
        for edge in child.edges
        if edge.source not in (START, END) and edge.target not in (START, END)
    ]


def expand_mounts(graph: Any, mounts: Mapping[str, MountedGraph]) -> Any:
    """Replace each mount node in `graph` with the child it runs, in place.

    `graph` is a drawable `langchain_core.runnables.graph.Graph` — what
    `compiled.get_graph()` returns — and it is returned for convenience rather
    than copied. A mount whose child could not be resolved, or whose child has
    no single entry and exit, is left as the one box it honestly is.
    """
    for name, mounted in mounts.items():
        if name not in graph.nodes:
            # A mount the compiler recorded but the drawing does not contain:
            # nothing to replace, and inventing a box would be the drift this
            # whole file exists to prevent.
            continue
        child = expand_mounts(mounted.graph.get_graph(), mounted.mounts)
        first_id, last_id = _boundary(child)
        if first_id is None or last_id is None:
            continue
        _trim_terminals(child)
        if not child.nodes:
            continue
        graph.nodes.pop(name)
        graph.extend(child, prefix=name)
        entry, exit_ = f"{name}:{first_id}", f"{name}:{last_id}"
        for index, edge in enumerate(graph.edges):
            if edge.source == name:
                edge = edge.copy(source=exit_)
            if edge.target == name:
                edge = edge.copy(target=entry)
            graph.edges[index] = edge
    return graph


__all__ = ["MountedGraph", "expand_mounts"]
