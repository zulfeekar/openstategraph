"""The memory system (tickets 65+47): store, namespaces, prebuilt tools."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.store.memory import InMemoryStore

from openstategraph.compile.workflow_compiler import CompiledPlan

from openstategraph.memory import (
    MEMORY_TTL_ENV,
    USER_MEMORY_NAMESPACE,
    MemoryScope,
    _user_namespace,
    build_store,
    checkpointer_for,
    memory_ttl,
    memory_preconditions,
    memory_settings,
    memory_tools,
)


#: The repository root, so package-shipped files resolve wherever pytest runs.
REPO = Path(__file__).resolve().parents[2]


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
        save, search, _ = memory_tools()
        config = {"configurable": {"user_email": "Me@Zulfeekar.com", "thread_id": "t1"}}

        _run_in_graph(lambda s: {"out": save.invoke({"fact": "favourite genre is Rock"})},
                      store=store, config=config)
        # Namespace is normalised (lowercased) — the same person is one key.
        items = store.search((USER_MEMORY_NAMESPACE, "me@zulfeekar_com"))
        assert [i.value["fact"] for i in items] == ["favourite genre is Rock"]

        result = _run_in_graph(lambda s: {"out": search.invoke({"query": "genre"})},
                               store=store, config=config)
        assert "Rock" in result["out"]

    def test_an_unidentified_run_has_nowhere_to_put_a_fact_about_a_person(self) -> None:
        """Reversed by memory-hardening ticket 01, deliberately.

        This test used to be `..._gets_the_anonymous_namespace_not_an_error`
        and pinned the fold to `("memories", "anonymous")` as intended
        behaviour. It was not a degradation, it was a **merge**: one bucket
        shared by every unidentified person on the deployment, while the tool
        told the model it holds "facts about this person".
        """
        store = InMemoryStore()
        save, _, _ = memory_tools()
        said = _run_in_graph(lambda s: {"out": save.invoke({"fact": "likes tables"})},
                             store=store, config={"configurable": {"thread_id": "t2"}})["out"]
        # "NOT SAVED" leads, because a refusal a model can gloss is a
        # refusal a user hears as success — observed live, see the ticket.
        assert said.startswith("NOT SAVED.") and "no identified user" in said
        assert not store.search((USER_MEMORY_NAMESPACE, "anonymous"))

    def test_the_refusal_names_a_scope_that_would_have_worked(self) -> None:
        # A refusal an agent cannot act on is a dead end; this one is not.
        store = InMemoryStore()
        save, _, _ = memory_tools()
        config = {"configurable": {"thread_id": "t", "workflow_slug": "w"}}
        said = _run_in_graph(lambda s: {"out": save.invoke({"fact": "a finding"})},
                             store=store, config=config)["out"]
        assert "scope='workflow'" in said
        _run_in_graph(
            lambda s: {"out": save.invoke({"fact": "a finding", "scope": "workflow"})},
            store=store, config=config)
        assert store.search(("workflow-memory", "w"))

    def test_users_never_see_each_others_memories(self) -> None:
        store = InMemoryStore()
        save, search, _ = memory_tools()
        _run_in_graph(lambda s: {"out": save.invoke({"fact": "secret A"})}, store=store,
                      config={"configurable": {"user_email": "a@x.com", "thread_id": "t3"}})
        result = _run_in_graph(lambda s: {"out": search.invoke({"query": "secret"})}, store=store,
                               config={"configurable": {"user_email": "b@x.com", "thread_id": "t4"}})
        assert "secret A" not in result["out"]


class TestAMemoryCanBeForgotten:
    """Memory-hardening ticket 04 — the Store contract has `delete`; we never
    surfaced it.

    A wrong fact was permanent. Worse than permanent: `search_memory` caps each
    scope at 4 results, so stale junk does not merely sit there, it **crowds
    correct facts out of the window**. And once identity is real (ticket 01),
    a person's stored facts with no way to remove them is a data-subject-rights
    problem, not only an annoyance.
    """

    def test_search_hands_back_a_handle_so_a_fact_can_be_named_again(self) -> None:
        # Deletion needs a referent. Text alone is not one — two facts can read
        # alike, and a model quoting prose back is guessing.
        store = InMemoryStore()
        save, search, _forget = memory_tools()
        config = {"configurable": {"workflow_slug": "w", "thread_id": "t"}}
        _run_in_graph(
            lambda s: {"out": save.invoke({"fact": "invoices run monthly",
                                           "scope": "workflow"})},
            store=store, config=config)
        listed = _run_in_graph(lambda s: {"out": search.invoke({"query": "invoices"})},
                               store=store, config=config)["out"]
        assert re.search(r"\[workflow · [0-9a-f]{8}\]", listed)

    def test_a_fact_named_by_its_handle_is_gone(self) -> None:
        store = InMemoryStore()
        save, search, forget = memory_tools()
        config = {"configurable": {"workflow_slug": "w", "thread_id": "t"}}
        _run_in_graph(
            lambda s: {"out": save.invoke({"fact": "the name is Brian",
                                           "scope": "workflow"})},
            store=store, config=config)
        listed = _run_in_graph(lambda s: {"out": search.invoke({"query": "Brian"})},
                               store=store, config=config)["out"]
        handle = re.search(r"· ([0-9a-f]{8})\]", listed).group(1)  # type: ignore[union-attr]

        said = _run_in_graph(lambda s: {"out": forget.invoke({"memory_id": handle})},
                             store=store, config=config)["out"]
        assert said.startswith("Forgotten")
        assert not store.search(("workflow-memory", "w"))

    def test_an_unknown_handle_is_refused_and_says_so(self) -> None:
        store = InMemoryStore()
        _save, _search, forget = memory_tools()
        said = _run_in_graph(lambda s: {"out": forget.invoke({"memory_id": "deadbeef"})},
                             store=store, config={"configurable": {"thread_id": "t"}})["out"]
        assert said.startswith("NOT FORGOTTEN")

    def test_it_cannot_reach_a_scope_this_workflow_does_not_use(self) -> None:
        # The same containment `save_memory` has: a tool must not become a way
        # to touch a namespace the declaration excluded.
        store = InMemoryStore()
        everything = memory_tools()
        config = {"configurable": {"workflow_slug": "w", "thread_id": "t"}}
        _run_in_graph(
            lambda s: {"out": everything[0].invoke({"fact": "a workflow fact",
                                                    "scope": "workflow"})},
            store=store, config=config)
        key = store.search(("workflow-memory", "w"))[0].key

        narrowed = memory_tools(memory_settings({"memory": {"scopes": ["app"]}})[0])
        said = _run_in_graph(lambda s: {"out": narrowed[2].invoke({"memory_id": key[:8]})},
                             store=store, config=config)["out"]
        assert said.startswith("NOT FORGOTTEN")
        assert store.search(("workflow-memory", "w"))


class TestRetentionIsTheDurableStoresToOffer:
    """Ticket 04's second half — and the honest half of it.

    `SqliteStore` accepts a `TTLConfig` and runs a sweeper; `InMemoryStore`'s
    constructor takes `index` and nothing else. LangGraph's `store.ttl` block
    is Agent Server configuration, which this project does not use — so
    retention is available exactly where it matters and is refused loudly
    where it is not.
    """

    def test_unset_means_items_do_not_expire(self, monkeypatch) -> None:
        monkeypatch.delenv(MEMORY_TTL_ENV, raising=False)
        assert memory_ttl() is None

    def test_it_is_minutes_and_none_means_unbounded(self, monkeypatch) -> None:
        # `int | None`, never a sentinel — a non-finite number is unrepresentable
        # in the config this eventually rides in.
        monkeypatch.setenv(MEMORY_TTL_ENV, "10080")
        config = memory_ttl()
        assert config is not None and config["default_ttl"] == 10080

    def test_a_nonsense_value_degrades_loudly_rather_than_crashing(
        self, monkeypatch, caplog
    ) -> None:
        monkeypatch.setenv(MEMORY_TTL_ENV, "seven days")
        with caplog.at_level(logging.WARNING, logger="openstategraph.memory"):
            assert memory_ttl() is None
        assert any(MEMORY_TTL_ENV in r.getMessage() for r in caplog.records)

    def test_asking_for_retention_without_a_durable_store_is_reported(
        self, monkeypatch, caplog
    ) -> None:
        # The named-extra degradation shape this module already uses: the user
        # asked for expiry and would otherwise never learn they did not get it.
        monkeypatch.setenv(MEMORY_TTL_ENV, "60")
        monkeypatch.delenv("OPENSTATEGRAPH_MEMORY_PATH", raising=False)
        monkeypatch.delenv("OPENSTATEGRAPH_POSTGRES_URL", raising=False)
        with caplog.at_level(logging.WARNING, logger="openstategraph.memory"):
            build_store()
        assert any("in-memory" in r.getMessage().lower() and MEMORY_TTL_ENV in r.getMessage()
                   for r in caplog.records)


class TestTheAppSpineIsWiredNotJustDescribed:
    """Memory-hardening ticket 05.

    `memory.py` and `docs/decisions/memory-architecture.md` both described the
    concierge as "the app spine … where cross-workflow findings are deposited".
    `workflows/concierge/` had no `skills/` directory and no occurrence of the
    word "memory" anywhere in it, so the only writer of `("app-memory",)` was
    an agent spontaneously passing `scope="app"` after reading a tool
    docstring that every agent in every workflow sees equally.

    The mechanism was real and tested; the **policy** was fiction — knowledge
    stated in two documents and implemented in zero, which is the DRY rule in
    its documentation form.
    """

    def test_the_concierge_carries_an_app_memory_skill(self) -> None:
        from openstategraph.api.capability_discovery import discover_skills

        context = discover_skills(REPO / "workflows/concierge")
        assert "app" in context.lower() and "memory" in context.lower()

    def test_the_skill_reaches_the_agents_of_that_package(self) -> None:
        # A skill file nobody loads is the same fiction one layer down, so this
        # asserts the discovery path rather than the file's existence.
        from openstategraph.api.services import WorkflowServices

        services = WorkflowServices(REPO / "workflows")
        runtime = services.runtime_for(
            "concierge", {"version": 2, "name": "c", "nodes": [], "edges": []}, None
        )
        assert "app" in runtime.services.skills_context.lower()

    def test_a_package_without_the_skill_is_unaffected(self) -> None:
        # The spine is the concierge's job, not an ambient instruction every
        # workflow inherits — app scope stays permissive-write by design.
        from openstategraph.api.capability_discovery import discover_skills

        assert "app-memory" not in discover_skills(REPO / "workflows/chinook-assistant")


class TestMemoryScopeIsANamedEnum:
    """Memory-hardening ticket 02 — the scope set is one declaration.

    It used to be four copies of the same knowledge: an if/elif chain in
    `_namespace_for`, a hardcoded three-pair tuple in `search_memory`, and
    prose in two docstrings. A scope outside the set fell through the chain
    into the **user** namespace and the tool reported success naming a scope
    that does not exist — `save_memory(fact, scope="global")` stored a
    cross-workflow finding in one person's private namespace and answered
    "Remembered (global)."

    That is this project's own reducers-are-a-named-enum rule in a different
    noun, and the RouterNode lesson in tool form: a confirmation that names
    something other than what happened.
    """

    def test_every_member_resolves_a_namespace(self) -> None:
        # Exhaustive by construction: a member that forgot its resolver
        # cannot exist, because the resolver is how a member is declared.
        config = {"configurable": {"user_email": "a@x.com", "workflow_slug": "w",
                                   "thread_id": "t"}}
        seen = _run_in_graph(
            lambda s: {"out": repr([tuple(m.namespace) for m in MemoryScope])},
            store=InMemoryStore(), config=config)["out"]
        assert seen == repr([("memories", "a@x_com"), ("workflow-memory", "w"),
                             ("app-memory",)])

    def test_the_three_scopes_are_the_whole_set(self) -> None:
        assert [m.value for m in MemoryScope] == ["user", "workflow", "app"]

    def test_an_unknown_scope_is_refused_not_rerouted_to_the_user(self) -> None:
        # The defect this ticket exists for: "global" is not a scope, and the
        # old chain silently made it mean "user".
        store = InMemoryStore()
        save, _, _ = memory_tools()
        config = {"configurable": {"user_email": "a@x.com", "thread_id": "t"}}

        def _attempt(_s: Any) -> dict[str, str]:
            try:
                save.invoke({"fact": "cross-workflow finding", "scope": "global"})
            except Exception as exc:  # the tool layer's own validation
                return {"out": type(exc).__name__}
            return {"out": "accepted"}

        assert _run_in_graph(_attempt, store=store, config=config)["out"] != "accepted"
        assert not store.search((USER_MEMORY_NAMESPACE, "a@x_com"))

    def test_the_confirmation_names_the_scope_actually_written(self) -> None:
        # Asserts the *value*, not merely that a confirmation came back.
        store = InMemoryStore()
        save, _, _ = memory_tools()
        config = {"configurable": {"user_email": "a@x.com", "workflow_slug": "w",
                                   "thread_id": "t"}}
        for scope in ("user", "workflow", "app"):
            said = _run_in_graph(
                lambda s, sc=scope: {"out": save.invoke({"fact": f"f-{sc}", "scope": sc})},
                store=store, config=config)["out"]
            assert said == f"Remembered ({scope})."

    def test_the_model_is_handed_the_closed_set_not_prose(self) -> None:
        # The reason this is worth doing at all: an enum reaches the model as
        # a JSON-Schema `enum`, so an out-of-set scope becomes a validation
        # error it can see and retry instead of a silent success.
        save, _, _ = memory_tools()
        schema = save.get_input_schema().model_json_schema()
        published = [d["enum"] for d in schema.get("$defs", {}).values() if "enum" in d]
        published += [p["enum"] for p in schema["properties"].values() if "enum" in p]
        assert published == [["user", "workflow", "app"]]

    def test_the_scope_description_the_model_pays_for_stays_short(self) -> None:
        # Found while verifying the enum: Pydantic renders a class docstring
        # as the parameter's `description`, so the first version of this shipped
        # ~250 words of engineering history to the model on every request. The
        # rationale belongs in a comment; this is the guard that keeps it there.
        from langchain_core.utils.function_calling import convert_to_openai_tool

        save, _, _ = memory_tools()
        params = convert_to_openai_tool(save)["function"]["parameters"]
        assert len(params["properties"]["scope"].get("description", "")) < 120


class TestMemoryIsDeclaredInSettings:
    """Memory-hardening ticket 03 — `settings.memory`, typed.

    The map's settled design is *(c) with (a) as its runtime consequence*:
    a workflow **declares** which scopes it uses, and a scope whose
    preconditions are absent is a reported finding rather than a silent
    default. Before this there was no `settings.memory` at all — the only
    document-level memory knob was `settings.checkpointer`, a stringly key on
    an untyped dict, validated nowhere.
    """

    def test_no_declaration_means_every_scope_exactly_as_before(self) -> None:
        settings, findings = memory_settings(None)
        assert settings.enabled and settings.scopes == tuple(MemoryScope)
        assert findings == []

    def test_disabled_means_no_memory_tools_even_with_a_store(self) -> None:
        settings, _ = memory_settings({"memory": {"enabled": False}})
        assert memory_tools(settings) == []

    def test_a_declared_subset_is_the_only_set_the_model_is_offered(self) -> None:
        # Narrowing the *schema*, not refusing at call time: telling a model
        # about a scope it may not use and then rejecting it is the same
        # defect ticket 02 removed, one layer up.
        settings, _ = memory_settings({"memory": {"scopes": ["user", "app"]}})
        save, _search, _forget = memory_tools(settings)
        published = save.get_input_schema().model_json_schema()["properties"]["scope"]
        assert published["enum"] == ["user", "app"]

    def test_a_declared_subset_is_also_the_only_set_search_reads(self) -> None:
        store = InMemoryStore()
        everything = memory_tools()
        narrowed = memory_tools(memory_settings({"memory": {"scopes": ["user"]}})[0])
        config = {"configurable": {"user_email": "a@x.com", "workflow_slug": "w",
                                  "thread_id": "t"}}
        for scope in ("user", "workflow"):
            _run_in_graph(
                lambda s, sc=scope: {"out": everything[0].invoke({"fact": f"a {sc} fact",
                                                                 "scope": sc})},
                store=store, config=config)

        result = _run_in_graph(lambda s: {"out": narrowed[1].invoke({"query": "fact"})},
                               store=store, config=config)["out"]
        assert "a user fact" in result and "a workflow fact" not in result

    def test_an_unknown_scope_is_reported_and_the_valid_ones_survive(self) -> None:
        settings, findings = memory_settings({"memory": {"scopes": ["user", "galaxy"]}})
        assert settings.scopes == (MemoryScope.USER,)
        assert any("galaxy" in f for f in findings)

    def test_an_unknown_key_is_reported_rather_than_ignored(self) -> None:
        # A typo in a declaration that silently does nothing is the failure
        # mode a typed block exists to remove.
        _settings, findings = memory_settings({"memory": {"scopez": ["user"]}})
        assert any("scopez" in f for f in findings)

    def test_declaring_memory_with_no_store_names_the_missing_precondition(self) -> None:
        findings = memory_preconditions(memory_settings({"memory": {"scopes": ["user"]}})[0],
                                        store=None)
        assert findings and "store" in findings[0].lower()
        assert memory_preconditions(memory_settings(None)[0], store=InMemoryStore()) == []


class TestDegradationIsNeverSilent:
    """Memory-hardening ticket 07 — three `except Exception: pass` blocks.

    Two of them swallowed a `get_config()` failure into `""`, which folds to
    `"anonymous"`/`"unsaved"` — so a config-propagation bug and a user who
    declined to identify produced the *identical* outcome with no signal.
    That is the machinery that made the shared-namespace merge silent.

    The third dropped a whole scope from search results when its `store.search`
    raised: a Postgres store with one corrupt namespace would quietly halve
    memory and nothing would say so.

    The module already defines a named logger for exactly this, and says why
    (`memory.py`, `_log`): "messages whose entire job is to be noticed."
    """

    def test_a_scope_whose_store_raises_is_reported_not_dropped(self, caplog) -> None:
        class OneBadScope(InMemoryStore):
            def search(self, namespace, **kwargs):  # type: ignore[override]
                if namespace[0] == "workflow-memory":
                    raise RuntimeError("namespace is corrupt")
                return super().search(namespace, **kwargs)

        store = OneBadScope()
        save, search, _ = memory_tools()
        config = {"configurable": {"user_email": "a@x.com", "workflow_slug": "w",
                                  "thread_id": "t"}}
        _run_in_graph(lambda s: {"out": save.invoke({"fact": "a user fact"})},
                      store=store, config=config)

        with caplog.at_level(logging.WARNING, logger="openstategraph.memory"):
            result = _run_in_graph(lambda s: {"out": search.invoke({"query": "fact"})},
                                   store=store, config=config)

        # The surviving scopes still answer — a bad scope degrades, not fails.
        assert "a user fact" in result["out"]
        assert any("workflow-memory" in r.getMessage() for r in caplog.records)

    def test_no_identity_and_no_config_at_all_say_different_things(self, caplog) -> None:
        """The distinction the whole ticket is about.

        Both mean "no user scope for this run". One is a person who declined
        to identify — normal. The other is `configurable` failing to reach this
        code — a bug. Before this they were the same silence.
        """
        store = InMemoryStore()
        save, _, _ = memory_tools()

        with caplog.at_level(logging.DEBUG, logger="openstategraph.memory"):
            _run_in_graph(lambda s: {"out": save.invoke({"fact": "likes tables"})},
                          store=store, config={"configurable": {"thread_id": "t"}})
        declined = [r.getMessage() for r in caplog.records]
        caplog.clear()

        with caplog.at_level(logging.DEBUG, logger="openstategraph.memory"):
            # Outside a graph there is no config to read at all.
            assert _user_namespace() is None
        unreachable = [r.getMessage() for r in caplog.records]

        assert declined and unreachable
        assert set(declined).isdisjoint(unreachable)


class TestAgentsAreMemoryCapable:
    """Binding is capability-by-configuration: a store's presence turns the
    tools on, and `settings.memory` narrows what they offer."""

    def test_agents_bind_the_memory_tools_when_a_store_exists(self) -> None:
        from openstategraph.compile.node_runtime import NodeRuntime

        runtime = NodeRuntime(model=None, store=InMemoryStore())
        node = {"id": "a1", "type": "agent.llm", "data": {}}
        runtime.factory({"nodes": [node], "edges": []})("a1", node, CompiledPlan())
        assert {"save_memory", "search_memory"} <= set(runtime.last_bound_tools)

    def test_no_store_means_no_memory_tools(self) -> None:
        from openstategraph.compile.node_runtime import NodeRuntime

        runtime = NodeRuntime(model=None)
        node = {"id": "a1", "type": "agent.llm", "data": {}}
        runtime.factory({"nodes": [node], "edges": []})("a1", node, CompiledPlan())
        assert "save_memory" not in runtime.last_bound_tools

    def test_a_documents_declaration_reaches_the_agent_that_binds_the_tools(
        self, tmp_path
    ) -> None:
        """Ticket 03 end to end — the hop the unit tests cannot prove.

        `memory_settings` parsing correctly is worth nothing if nothing carries
        the result from the document to `NodeRuntime`. This walks the real path:
        a document with a `settings.memory` block, through `runtime_for`, to the
        tool schema an agent is actually handed.
        """
        from openstategraph.api.services import WorkflowServices

        services = WorkflowServices(tmp_path, store=InMemoryStore())
        document = {
            "version": 2, "name": "declared", "nodes": [], "edges": [],
            "settings": {"memory": {"scopes": ["workflow"]}},
        }
        warnings: list[str] = []
        runtime = services.runtime_for(None, document, None, warnings=warnings)

        # The hop itself. What the narrowed set then does to the tool schema is
        # `test_a_declared_subset_is_the_only_set_the_model_is_offered`.
        assert runtime.services.memory.scopes == (MemoryScope.WORKFLOW,)
        assert warnings == []

        node = {"id": "a1", "type": "agent.llm", "data": {}}
        runtime.factory({"nodes": [node], "edges": []})("a1", node, CompiledPlan())
        assert {"save_memory", "search_memory"} <= set(runtime.last_bound_tools)

    def test_declaring_memory_with_no_store_is_reported_on_the_run(self, tmp_path) -> None:
        # The finding rides the channel every unresolved capability uses, so a
        # deployment that cannot honour a declaration says so on the run itself.
        from openstategraph.api.registries import runtime_warnings
        from openstategraph.api.services import WorkflowServices

        class NoMemory(WorkflowServices):
            @property
            def memory_store(self):  # type: ignore[override]
                return None

            @memory_store.setter
            def memory_store(self, _value) -> None:
                return

        services = NoMemory(tmp_path)
        runtime = services.runtime_for(
            None,
            {"version": 2, "name": "d", "nodes": [], "edges": [],
             "settings": {"memory": {"scopes": ["user"]}}},
            None,
        )
        assert any("no memory store is configured" in w for w in runtime_warnings(runtime))


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
        assert runtime.services.workflow_middleware["audit"] is sentinel


class TestMemoryScopes:
    """User model (2026-08-08): user / workflow / app scopes, one search."""

    def test_workflow_scope_lands_in_the_slug_namespace(self) -> None:
        store = InMemoryStore()
        save, _, _ = memory_tools()
        _run_in_graph(
            lambda s: {"out": save.invoke({"fact": "chinook revenue sums InvoiceLine amounts", "scope": "workflow"})},
            store=store,
            config={"configurable": {"thread_id": "t", "workflow_slug": "chinook-assistant"}},
        )
        assert store.search(("workflow-memory", "chinook-assistant"))

    def test_search_reads_all_scopes_and_labels_provenance(self) -> None:
        store = InMemoryStore()
        save, search, _ = memory_tools()
        config = {"configurable": {"thread_id": "t", "user_email": "a@x.com",
                                   "workflow_slug": "chinook-assistant"}}
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
        # `· <handle>` is ticket 04: every row is nameable again, which is
        # what `forget_memory` resolves against.
        assert "[user · " in out and "[workflow · " in out
        assert "[app via chinook-assistant · " in out

    def test_app_scope_writes_are_stamped_with_the_originating_slug(self) -> None:
        """The spine is auditable: any workflow may contribute app-wide
        learnings, but every deposit records which workflow made it."""
        store = InMemoryStore()
        save, search, _ = memory_tools()
        _run_in_graph(lambda s: {"out": save.invoke({"fact": "billing runs Mondays", "scope": "app"})},
                      store=store,
                      config={"configurable": {"thread_id": "t", "workflow_slug": "chinook-assistant"}})
        items = store.search(("app-memory",))
        assert [i.value.get("workflow") for i in items] == ["chinook-assistant"]
        result = _run_in_graph(lambda s: {"out": search.invoke({"query": "billing"})},
                               store=store,
                               config={"configurable": {"thread_id": "t2", "workflow_slug": "concierge"}})
        assert "[app via chinook-assistant · " in result["out"]

    def test_the_tools_offer_no_way_to_name_another_workflows_namespace(self) -> None:
        """A child cannot write another workflow's workflow-scope: the slug is
        config-derived, never a tool argument."""
        save, search, _ = memory_tools()
        assert set(save.args) == {"fact", "scope"}
        assert set(search.args) == {"query"}

    def test_search_caps_each_scope_so_a_hoarder_cannot_flood_the_prompt(self) -> None:
        store = InMemoryStore()
        save, search, _ = memory_tools()
        config = {"configurable": {"thread_id": "t", "user_email": "a@x.com"}}
        for i in range(10):
            _run_in_graph(lambda s, i=i: {"out": save.invoke({"fact": f"note {i} about cats"})},
                          store=store, config=config)
        result = _run_in_graph(lambda s: {"out": search.invoke({"query": "cats"})},
                               store=store, config=config)
        assert len([line for line in result["out"].splitlines() if line.startswith("- [user]")]) <= 4

    def test_app_scope_is_shared_across_workflows(self) -> None:
        store = InMemoryStore()
        save, search, _ = memory_tools()
        _run_in_graph(lambda s: {"out": save.invoke({"fact": "shared finding", "scope": "app"})},
                      store=store,
                      config={"configurable": {"thread_id": "t1", "workflow_slug": "concierge"}})
        result = _run_in_graph(lambda s: {"out": search.invoke({"query": "shared"})},
                               store=store,
                               config={"configurable": {"thread_id": "t2", "workflow_slug": "chinook-assistant"}})
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

        save, _, _ = memory_tools()

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
        self._run(store, node_type="workflow.subgraph")
        assert store.search(("workflow-memory", "child-flow"))
        assert not store.search(("workflow-memory", "parent-flow"))

    def test_the_parents_own_nodes_still_write_the_parents_slug(self) -> None:
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        store = InMemoryStore()
        save, _, _ = memory_tools()
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
        save, _, _ = memory_tools()

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
