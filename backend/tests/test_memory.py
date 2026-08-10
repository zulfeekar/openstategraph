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
        """The file lands in the **state dir**, not in `./.dev` — scale-and-adopt
        ticket 03. It was cwd-relative, so a workflow run from someone's home
        directory created `~/.dev/`."""
        monkeypatch.chdir(tmp_path)
        saver = checkpointer_for(
            {"checkpointer": "sqlite"}, "my-flow", fallback=None, workflows_root_dir=tmp_path
        )
        assert type(saver).__name__ == "SqliteSaver"
        assert (tmp_path / ".openstategraph" / "checkpoints-my-flow.sqlite").exists()
        assert not (tmp_path / ".dev").exists()

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
            lambda s: {"out": save.invoke({"fact": "chinook revenue sums InvoiceLine amounts", "scope": "workflow"})},
            store=store,
            config={"configurable": {"thread_id": "t", "workflow_slug": "chinook-nl-to-sql"}},
        )
        assert store.search(("workflow-memory", "chinook-nl-to-sql"))

    def test_search_reads_all_scopes_and_labels_provenance(self) -> None:
        store = InMemoryStore()
        save, search = memory_tools()
        config = {"configurable": {"thread_id": "t", "user_email": "a@x.com",
                                   "workflow_slug": "chinook-nl-to-sql"}}
        _run_in_graph(lambda s: {"out": save.invoke({"fact": "likes concise answers"})},
                      store=store, config=config)
        _run_in_graph(lambda s: {"out": save.invoke({"fact": "Global_Sales is authoritative", "scope": "workflow"})},
                      store=store, config=config)
        _run_in_graph(lambda s: {"out": save.invoke({"fact": "the platform has 8 workflows", "scope": "app"})},
                      store=store, config=config)
        result = _run_in_graph(lambda s: {"out": search.invoke({"query": "a"})},
                               store=store, config=config)
        out = result["out"]
        # App hits carry their originating slug — the spine stays auditable.
        assert "[user]" in out and "[workflow]" in out
        assert "[app via chinook-nl-to-sql]" in out

    def test_app_scope_writes_are_stamped_with_the_originating_slug(self) -> None:
        """The spine is auditable: any workflow may contribute app-wide
        learnings, but every deposit records which workflow made it."""
        store = InMemoryStore()
        save, search = memory_tools()
        _run_in_graph(lambda s: {"out": save.invoke({"fact": "billing runs Mondays", "scope": "app"})},
                      store=store,
                      config={"configurable": {"thread_id": "t", "workflow_slug": "chinook-nl-to-sql"}})
        items = store.search(("app-memory",))
        assert [i.value.get("workflow") for i in items] == ["chinook-nl-to-sql"]
        result = _run_in_graph(lambda s: {"out": search.invoke({"query": "billing"})},
                               store=store,
                               config={"configurable": {"thread_id": "t2", "workflow_slug": "concierge"}})
        assert "[app via chinook-nl-to-sql]" in result["out"]

    def test_the_tools_offer_no_way_to_name_another_workflows_namespace(self) -> None:
        """A child cannot write another workflow's workflow-scope: the slug is
        config-derived, never a tool argument."""
        save, search = memory_tools()
        assert set(save.args) == {"fact", "scope"}
        assert set(search.args) == {"query"}

    def test_search_caps_each_scope_so_a_hoarder_cannot_flood_the_prompt(self) -> None:
        store = InMemoryStore()
        save, search = memory_tools()
        config = {"configurable": {"thread_id": "t", "user_email": "a@x.com"}}
        for i in range(10):
            _run_in_graph(lambda s, i=i: {"out": save.invoke({"fact": f"note {i} about cats"})},
                          store=store, config=config)
        result = _run_in_graph(lambda s: {"out": search.invoke({"query": "cats"})},
                               store=store, config=config)
        assert len([line for line in result["out"].splitlines() if line.startswith("- [user]")]) <= 4

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


class TestScopeThreadingAcrossSubgraphs:
    """The spine rule: every mounted child workflow has its OWN workflow-scope
    namespace. The parent's config crosses the boundary, but `workflow_slug`
    is overridden to the child's own slug at the mount — otherwise a child's
    save_memory(scope="workflow") would leak into the parent's namespace."""

    CHILD = {
        "version": 2,
        "name": "child",
        "nodes": [
            {"id": "cin", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "cf", "type": "function.probe", "position": {"x": 100, "y": 0}, "data": {}},
            {"id": "cout", "type": "output.formatted", "position": {"x": 200, "y": 0}, "data": {}},
        ],
        "edges": [
            {"source": {"nodeId": "cin", "portId": "text"}, "target": {"nodeId": "cf", "portId": "candidate"}},
            {"source": {"nodeId": "cf", "portId": "report"}, "target": {"nodeId": "cout", "portId": "result"}},
        ],
    }

    @staticmethod
    def _parent(node_type: str = "workflow.subgraph") -> dict:
        return {
            "version": 2,
            "name": "parent",
            "nodes": [
                {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
                {"id": "sub1", "type": node_type, "position": {"x": 200, "y": 0}, "data": {"workflow": "child-flow"}},
                {"id": "out1", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
            ],
            "edges": [
                {"source": {"nodeId": "in1", "portId": "text"}, "target": {"nodeId": "sub1", "portId": "candidate"}},
                {"source": {"nodeId": "sub1", "portId": "report"}, "target": {"nodeId": "out1", "portId": "result"}},
            ],
        }

    def _run(self, store, node_type: str = "workflow.subgraph"):
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        save, _ = memory_tools()

        def probe(text: str) -> str:
            return save.invoke({"fact": f"finding about {text}", "scope": "workflow"})

        runtime = NodeRuntime(
            document_loader={"child-flow": self.CHILD}.__getitem__,
            functions={"function.probe": probe},
            store=store,
        )
        document = self._parent(node_type)
        graph = WorkflowCompiler().build(
            document, RunState, runtime.factory(document), store=store
        )
        return graph.invoke(
            {"question": "q", "attempts": 0, "decisions": {}, "outputs": {}},
            {"configurable": {"thread_id": "t", "workflow_slug": "parent-flow",
                              "user_email": "a@x.com"}},
        )

    def test_a_childs_workflow_memory_lands_in_the_childs_own_slug(self) -> None:
        store = InMemoryStore()
        self._run(store)
        assert store.search(("workflow-memory", "child-flow"))

    def test_a_childs_workflow_memory_never_leaks_into_the_parents_slug(self) -> None:
        store = InMemoryStore()
        self._run(store)
        assert not store.search(("workflow-memory", "parent-flow"))

    def test_a_team_mounts_child_memory_the_same_way(self) -> None:
        store = InMemoryStore()
        self._run(store, node_type="team.workflow")
        assert store.search(("workflow-memory", "child-flow"))
        assert not store.search(("workflow-memory", "parent-flow"))

    def test_the_parents_own_nodes_still_write_the_parents_slug(self) -> None:
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        store = InMemoryStore()
        save, _ = memory_tools()
        document = {
            "version": 2,
            "name": "solo",
            "nodes": [
                {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
                {"id": "f1", "type": "function.probe", "position": {"x": 100, "y": 0}, "data": {}},
                {"id": "out1", "type": "output.formatted", "position": {"x": 200, "y": 0}, "data": {}},
            ],
            "edges": [
                {"source": {"nodeId": "in1", "portId": "text"}, "target": {"nodeId": "f1", "portId": "candidate"}},
                {"source": {"nodeId": "f1", "portId": "report"}, "target": {"nodeId": "out1", "portId": "result"}},
            ],
        }
        runtime = NodeRuntime(
            functions={"function.probe": lambda text: save.invoke({"fact": "parent fact", "scope": "workflow"})},
            store=store,
        )
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document), store=store)
        graph.invoke({"question": "q", "attempts": 0, "decisions": {}, "outputs": {}},
                     {"configurable": {"thread_id": "t", "workflow_slug": "parent-flow"}})
        assert store.search(("workflow-memory", "parent-flow"))

    def test_user_scope_follows_the_person_through_a_mounted_child(self) -> None:
        """user_email crosses the mount untouched — the person is the same
        person inside every workflow (permissive read, one identity)."""
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        store = InMemoryStore()
        save, _ = memory_tools()

        runtime = NodeRuntime(
            document_loader={"child-flow": self.CHILD}.__getitem__,
            functions={"function.probe": lambda text: save.invoke({"fact": "prefers metric"})},
            store=store,
        )
        document = self._parent()
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document), store=store)
        graph.invoke({"question": "q", "attempts": 0, "decisions": {}, "outputs": {}},
                     {"configurable": {"thread_id": "t", "workflow_slug": "parent-flow",
                                       "user_email": "a@x.com"}})
        assert store.search((USER_MEMORY_NAMESPACE, "a@x_com"))


class TestDurableStore:
    """OPENSTATEGRAPH_MEMORY_PATH opts the long-term Store into sqlite —
    memories survive a restart. Default stays in-memory (dev tool). The
    single-worker constraint applies: one uvicorn worker, one connection."""

    def test_default_is_in_memory(self, monkeypatch) -> None:
        from openstategraph.memory import build_store
        monkeypatch.delenv("OPENSTATEGRAPH_MEMORY_PATH", raising=False)
        assert type(build_store()).__name__ == "InMemoryStore"

    def test_env_path_makes_memories_survive_a_reopen(self, tmp_path, monkeypatch) -> None:
        from openstategraph.memory import build_store
        path = tmp_path / "memory.sqlite"
        monkeypatch.setenv("OPENSTATEGRAPH_MEMORY_PATH", str(path))
        first = build_store()
        first.put(("memories", "a@x_com"), "k1", {"fact": "durable"})
        second = build_store()  # a fresh process would do exactly this
        items = second.search(("memories", "a@x_com"))
        assert [i.value["fact"] for i in items] == ["durable"]
        assert path.exists()

    def test_a_bad_path_degrades_to_in_memory_not_a_crash(self, tmp_path, monkeypatch) -> None:
        from openstategraph.memory import build_store
        # A directory is not a database file — the honest degrade is in-memory.
        monkeypatch.setenv("OPENSTATEGRAPH_MEMORY_PATH", str(tmp_path))
        store = build_store()
        store.put(("memories", "x"), "k", {"fact": "still works"})
        assert store.search(("memories", "x"))


class TestAmbientKnowledgeEfficiency:
    """The ambient rule must not re-scan knowledge/ for every agent it
    binds: one runtime construction, one directory scan."""

    def test_the_directory_is_scanned_once_per_runtime(self, tmp_path, monkeypatch) -> None:
        from openstategraph.compile.node_runtime import NodeRuntime

        (tmp_path / "knowledge").mkdir()
        (tmp_path / "knowledge" / "topic.md").write_text("hint\n\nbody\n")

        import openstategraph.prebuilt_knowledge as pk
        calls = {"n": 0}
        real = pk.ambient_knowledge_tool

        def counting(package_dir, **kwargs):
            calls["n"] += 1
            return real(package_dir, **kwargs)

        monkeypatch.setattr(pk, "ambient_knowledge_tool", counting)

        runtime = NodeRuntime(model=None, knowledge_package_dir=tmp_path)
        for _ in range(3):
            tools: list = []
            runtime._attach_ambient_knowledge(tools)
            assert [t.name for t in tools] == ["knowledge_lookup"]
        assert calls["n"] == 1
