"""One place a compiled graph becomes a picture, for whoever is reading it.

Drawing a workflow honestly takes two calls beyond `draw_mermaid()`, and
neither is optional:

- **the composition is spliced** from what the compiler recorded while it
  built each mount (`compile/composition.py`), because a mount compiles to a
  closure over the child's `invoke()` and LangGraph's `xray` cannot see
  through a function;
- **a customer's copy is relabelled** (`api/customer_graph.py`), because
  `__start__`, `__default_error_handler__` and `safe_name`d ids are the
  compiler's words, not the reader's.

`workflow-gallery` 56 taught the *preview* route both calls. Three **run**
surfaces — `RunResponse.mermaid`, the terminal SSE `done` frame, and MCP's
`run_workflow` — each drew their own and so made neither call, which is
`workflow-gallery` 62: a caller who had explicitly asked for the customer
channel received the compiler's vocabulary alongside its answer, and three
levels of `nested-mounts` as one box.

**So this is a seam rather than three repaired call sites.** Four surfaces
that must each remember two calls is a defect with a fifth instance waiting;
`tests/test_a_runs_diagram_opens_its_mounts.py` fails the day a new call site
draws its own.

**A run frame draws exactly what the preview draws.** The two answer different
questions — "what did the compiler build" against "what just ran" — but about
the same compiled graph, and two shapes for one workflow is a worse answer to
both. `xray=True` on every path for the same reason: it is what the preview
passes, it opens a genuine LangGraph subgraph should one ever be compiled, and
it changes nothing about what this compiler emits today.

Never `draw_mermaid_png()` from anywhere: it posts the user's graph to a
third-party API.
"""

from __future__ import annotations

from typing import Any, Mapping

from openstategraph.api.customer_graph import MountedDocument, customer_mermaid


def mounted_documents(mounts: Any, store: Any) -> dict[str, MountedDocument]:
    """The compiler's map of mounts, with each child's *document* beside it.

    The compiler records which package a mount runs; a package's document is
    the only thing that knows what its author called the nodes inside it. Both
    halves are needed to relabel an opened composition for a customer, and
    they live in different places, so they are joined here.

    A child that will not load is dropped rather than raised on: its subtree
    keeps the compiler's labels, which is worse than a title and much better
    than a 502 on a picture. A caller with no store at all — MCP's stateless
    `compile_workflow` — passes `None` and gets an empty map, which is the
    true answer there: nothing was mounted, because nothing could be.
    """
    resolved: dict[str, MountedDocument] = {}
    if store is None:
        return resolved
    for name, mounted in (mounts or {}).items():
        try:
            child = store.load(mounted.slug)
        except Exception:
            continue
        resolved[name] = MountedDocument(
            document=child, mounts=mounted_documents(mounted.mounts, store)
        )
    return resolved


def workflow_mermaid(
    graph: Any,
    document: Any,
    *,
    runtime: Any = None,
    audience: Any = None,
    store: Any = None,
) -> str:
    """Mermaid text for one compiled graph, in `audience`'s vocabulary.

    `runtime` is the `NodeRuntime` that built `graph` — the only object that
    knows which package each mount runs. Without it the composition cannot be
    opened, and a mount stays the one box LangGraph can see, which is the
    honest picture wherever no child was resolved.

    `audience` is `Audience.CUSTOMER`, `Audience.DEVELOPER`, or `None` for a
    caller with no audience at all (the SDK, MCP): the compiler's own names
    are kept unless a customer is explicitly named, deliberately, because
    those are the names a mount bug gets reported under.
    """
    from openstategraph.api.audience import Audience
    from openstategraph.compile.composition import expand_mounts

    drawable = graph.get_graph(xray=True)
    mounts: Mapping[str, Any] = dict(getattr(runtime, "mounted_graphs", None) or {})
    if mounts:
        drawable = expand_mounts(drawable, mounts)
    text: str = drawable.draw_mermaid()
    if audience is Audience.CUSTOMER:
        text = customer_mermaid(text, document, mounted_documents(mounts, store))
    return text
