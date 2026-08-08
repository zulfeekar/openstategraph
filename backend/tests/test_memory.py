"""The memory system (tickets 65+47): store, namespaces, prebuilt tools."""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.store.memory import InMemoryStore

from openstategraph.memory import USER_MEMORY_NAMESPACE, checkpointer_for, memory_tools


class S(TypedDict, total=False):
    out: str


def _run_in_graph(fn, *, store, config) -> dict[str, Any]:
    """Runs `fn` as a real graph node so `get_store`/`get_config` resolve —
    the tools are only ever called from inside a running graph."""
    builder = StateGraph(S)
    builder.add_node("n", fn)
    builder.add_edge(START, "n")
    builder.add_edge("n", END)
    return builder.compile(store=store).invoke({}, config)


class TestMemoryTools:
    def test_save_then_search_round_trips_through_the_user_namespace(self) -> None:
        store = InMemoryStore()
        save, search = memory_tools()
        config = {"configurable": {"user_email": "Me@Zulfeekar.com", "thread_id": "t1"}}

        _run_in_graph(lambda s: {"out": save.invoke({"fact": "favourite genre is Rock"})},
                      store=store, config=config)
        # Namespace is normalised (lowercased) — the same person is one key.
        items = store.search((USER_MEMORY_NAMESPACE, "me@zulfeekar_com"))
        assert [i.value["fact"] for i in items] == ["favourite genre is Rock"]

        result = _run_in_graph(lambda s: {"out": search.invoke({"query": "genre"})},
                               store=store, config=config)
        assert "Rock" in result["out"]

    def test_an_anonymous_user_gets_the_anonymous_namespace_not_an_error(self) -> None:
        store = InMemoryStore()
        save, _ = memory_tools()
        _run_in_graph(lambda s: {"out": save.invoke({"fact": "likes tables"})},
                      store=store, config={"configurable": {"thread_id": "t2"}})
        assert store.search((USER_MEMORY_NAMESPACE, "anonymous"))

    def test_users_never_see_each_others_memories(self) -> None:
        store = InMemoryStore()
        save, search = memory_tools()
        _run_in_graph(lambda s: {"out": save.invoke({"fact": "secret A"})}, store=store,
                      config={"configurable": {"user_email": "a@x.com", "thread_id": "t3"}})
        result = _run_in_graph(lambda s: {"out": search.invoke({"query": "secret"})}, store=store,
                               config={"configurable": {"user_email": "b@x.com", "thread_id": "t4"}})
        assert "secret A" not in result["out"]


class TestAgentsAreMemoryCapable:
    def test_agents_bind_the_memory_tools_when_a_store_exists(self) -> None:
        from openstategraph.compile.node_runtime import NodeRuntime
        from openstategraph.compile.workflow_compiler import CompiledPlan

        runtime = NodeRuntime(model=None, store=InMemoryStore())
        node = {"id": "a1", "type": "agent.llm", "data": {}}
        runtime.factory({"nodes": [node], "edges": []})("a1", node, CompiledPlan())
        assert {"save_memory", "search_memory"} <= set(runtime.last_bound_tools)

    def test_no_store_means_no_memory_tools(self) -> None:
        from openstategraph.compile.node_runtime import NodeRuntime
        from openstategraph.compile.workflow_compiler import CompiledPlan

        runtime = NodeRuntime(model=None)
        node = {"id": "a1", "type": "agent.llm", "data": {}}
        runtime.factory({"nodes": [node], "edges": []})("a1", node, CompiledPlan())
        assert "save_memory" not in runtime.last_bound_tools


class TestDurableCheckpointer:
    def test_sqlite_is_opt_in_via_settings(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        saver = checkpointer_for({"checkpointer": "sqlite"}, "my-flow", fallback=None)
        assert type(saver).__name__ == "SqliteSaver"
        assert (tmp_path / ".dev" / "checkpoints-my-flow.sqlite").exists()

    def test_anything_else_keeps_the_fallback(self) -> None:
        sentinel = object()
        assert checkpointer_for(None, "x", fallback=sentinel) is sentinel
        assert checkpointer_for({"checkpointer": "memory"}, "x", fallback=sentinel) is sentinel


class TestWorkflowMiddlewareDiscovery:
    """Ticket 32: middlewares/<slot>.py fills-or-replaces a named slot."""

    def test_a_dropped_file_becomes_a_named_slot(self, tmp_path) -> None:
        from openstategraph.api.capability_discovery import discover_middlewares
        mw_dir = tmp_path / "middlewares"
        mw_dir.mkdir()
        (mw_dir / "audit.py").write_text("MIDDLEWARE = object()\n")
        found = discover_middlewares(tmp_path, "test-flow")
        assert set(found) == {"audit"}

    def test_a_file_without_MIDDLEWARE_is_skipped_loudly_not_fatally(self, tmp_path) -> None:
        from openstategraph.api.capability_discovery import discover_middlewares
        mw_dir = tmp_path / "middlewares"
        mw_dir.mkdir()
        (mw_dir / "broken.py").write_text("x = 1\n")
        assert discover_middlewares(tmp_path, "test-flow") == {}

    def test_workflow_slots_reach_every_agents_contributions(self) -> None:
        from openstategraph.compile.node_runtime import NodeRuntime
        sentinel = object()
        runtime = NodeRuntime(model=None, workflow_middleware={"audit": sentinel})
        assert runtime.workflow_middleware["audit"] is sentinel


class TestMemoryScopes:
    """User model (2026-08-08): user / workflow / app scopes, one search."""

    def test_workflow_scope_lands_in_the_slug_namespace(self) -> None:
        store = InMemoryStore()
        save, _ = memory_tools()
        _run_in_graph(
            lambda s: {"out": save.invoke({"fact": "vgsales ranks tie-break by name", "scope": "workflow"})},
            store=store,
            config={"configurable": {"thread_id": "t", "workflow_slug": "tabular-analytics"}},
        )
        assert store.search(("workflow-memory", "tabular-analytics"))

    def test_search_reads_all_scopes_and_labels_provenance(self) -> None:
        store = InMemoryStore()
        save, search = memory_tools()
        config = {"configurable": {"thread_id": "t", "user_email": "a@x.com",
                                   "workflow_slug": "tabular-analytics"}}
        _run_in_graph(lambda s: {"out": save.invoke({"fact": "likes concise answers"})},
                      store=store, config=config)
        _run_in_graph(lambda s: {"out": save.invoke({"fact": "Global_Sales is authoritative", "scope": "workflow"})},
                      store=store, config=config)
        _run_in_graph(lambda s: {"out": save.invoke({"fact": "the platform has 8 workflows", "scope": "app"})},
                      store=store, config=config)
        result = _run_in_graph(lambda s: {"out": search.invoke({"query": "a"})},
                               store=store, config=config)
        out = result["out"]
        assert "[user]" in out and "[workflow]" in out and "[app]" in out

    def test_app_scope_is_shared_across_workflows(self) -> None:
        store = InMemoryStore()
        save, search = memory_tools()
        _run_in_graph(lambda s: {"out": save.invoke({"fact": "shared finding", "scope": "app"})},
                      store=store,
                      config={"configurable": {"thread_id": "t1", "workflow_slug": "concierge"}})
        result = _run_in_graph(lambda s: {"out": search.invoke({"query": "shared"})},
                               store=store,
                               config={"configurable": {"thread_id": "t2", "workflow_slug": "chinook-nl-to-sql"}})
        assert "shared finding" in result["out"]
