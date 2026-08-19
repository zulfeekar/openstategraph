"""Which tools this server binds to every agent without anybody wiring them.

**The gap this closes** (`every-workflow-green` 05a). An agent on a canvas with
two tools drawn actually had five. The extra three — `save_memory`,
`search_memory`, `forget_memory` — bind to *every* agent with no wiring, by
design: `node_runtime._bind_tools` says *"A store's presence turns on the
prebuilt memory tools for every agent — capability by configuration, no
per-workflow wiring, matching the minimum-viable-prebuilt rule."*

Bound-without-wiring is right. **Unknowable is not.** A developer reading the
canvas could not enumerate their own agent's capabilities, and the truth
surfaced only because a model hallucinated a tool name and made the runtime list
the real ones. Nothing reported it — which is exactly the blindspot question
this walk keeps asking.

**Why this is published rather than written on the card.** These tools are
conditional on the *environment*, not the document: no store, no memory tools.
So the same `workflow.json` has different agents on two installations, and a
hardcoded card note would be **false** on one of them — the unfalsifiable prose
this repository keeps finding and pinning. The card must be told, not taught.

**And why `bindsWithoutWiring` is not reused.** That flag belongs to a node that
is *placed but unwired* — the Knowledge atom, which you can see and choose not
to connect. These have no node at all; there is nothing on the canvas to carry a
flag.

**Scope, stated.** Server-level only. The knowledge lookup is the other ambient
binding and is *per package* (a non-empty `knowledge/`), so it is a different
question with a different answer and is deliberately not folded in here — one
list conflating two conditions would be wrong for whichever the reader cared
about.
"""

from __future__ import annotations

from typing import Any

# No `__all__` here on purpose: `openstategraph.api` is Tier 3 (internal), and
# a name exported from it reads as a promise this project has said it is not
# making — `docs/stability.md` names the package among the things deliberately
# not public. `test_public_api.py` fails on one.


def ambient_tool_names(*, memory_store: Any, memory_settings: Any = None) -> list[str]:
    """The tool names every agent on this server gets for free, sorted.

    **Two arguments, because the runtime uses two things.** `_bind_tools` gates
    on `services.memory_store is not None` and then builds from
    `memory_tools(services.memory)` — the *settings*, which decide which scopes
    are allowed. Collapsing them into one parameter was the first version of
    this, and the tests caught it: the store is the switch, the settings are the
    shape.

    Read from `memory_tools` rather than a hand-kept list: two spellings of one
    set agree on the day they are written and drift on the first tool added,
    which is the duplication-of-knowledge failure `CLAUDE.md` forbids outright.

    Sorted because an order that varies re-renders every agent card for nothing
    — the same reasoning `WorkflowCatalogue.set` records for its own comparison.
    """
    if memory_store is None:
        return []
    from openstategraph.memory import memory_tools

    return sorted(tool.name for tool in memory_tools(memory_settings))
