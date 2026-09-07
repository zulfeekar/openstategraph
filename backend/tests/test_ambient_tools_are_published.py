"""Every agent gets tools nobody wired, and until now nothing said which.

**The defect** (`every-workflow-green` 05a). Running `workflow-2026`, the agent
called a tool it did not have and the runtime's own error listed what it *did*:

    Error: platform_list_workflows is not a valid tool, try one of
    [platform_describe_workflow, platform_ls, save_memory, search_memory,
    forget_memory]

**Five tools. The canvas wires two.** `save_memory`, `search_memory` and
`forget_memory` bind to every agent with no wiring at all — by design
(`node_runtime._bind_tools`: *"A store's presence turns on the prebuilt memory
tools for every agent — capability by configuration, no per-workflow wiring"*).

Bound-without-wiring is fine. **Unknowable is not.** A developer reading the
canvas could not enumerate what their agent can do, and the truth surfaced only
because a model hallucinated a tool name and provoked the runtime into listing
the real ones. Nothing *reported* it.

**Why a note on the card would have been a lie.** These are conditional on the
*environment*, not the document: the memory tools appear only when a store is
configured, so the same `workflow.json` has different agents on two
installations. A hardcoded "agents also get save_memory…" is false on a server
without a store — the unfalsifiable prose this repository keeps pinning.

So the truth is published, per server, from the same condition the runtime
actually branches on. `bindsWithoutWiring` is deliberately **not** reused: that
flag is for a node *placed but unwired* (the Knowledge atom), and these have no
node at all.
"""

from __future__ import annotations

from openstategraph.api.ambient_tools import ambient_tool_names


class TestItReportsWhatTheRuntimeWouldBind:
    def test_a_store_turns_the_memory_tools_on(self) -> None:
        names = ambient_tool_names(memory_store=object(), memory_settings=None)
        assert names == ["forget_memory", "save_memory", "search_memory"]

    def test_no_store_means_no_memory_tools(self) -> None:
        # The case that makes a hardcoded card note false. A server with no
        # store configured binds none of these, and must not claim otherwise.
        assert ambient_tool_names(memory_store=None, memory_settings=None) == []

    def test_the_names_are_sorted_so_the_payload_does_not_churn(self) -> None:
        # A list whose order varies re-renders every agent card for nothing.
        names = ambient_tool_names(memory_store=object(), memory_settings=None)
        assert names == sorted(names)


class TestItMatchesTheRuntime:
    def test_it_names_exactly_the_prebuilt_memory_tools(self) -> None:
        """Read from `memory_tools`, never a hand-kept list.

        Two spellings of one set agree on the day they are written and drift on
        the first tool added — the failure this codebase keeps finding. This
        asserts the published names come from the same function the runtime
        binds.
        """
        from openstategraph.memory import memory_tools

        # `memory_tools` takes *settings* and defaults them; the store is only
        # the switch. Conflating the two was this module's first bug, caught by
        # these tests before it shipped.
        runtime_names = sorted(t.name for t in memory_tools(None))
        assert ambient_tool_names(memory_store=object(), memory_settings=None) == runtime_names
