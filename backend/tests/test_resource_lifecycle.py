"""Everything allocated has an owner and a close path — ticket 05.

The leak this file exists to prevent is not theoretical. `WorkflowServices`
opens two sqlite connections (a checkpointer under the workflows root, and a
long-term memory `Store` when `OPENSTATEGRAPH_MEMORY_PATH` is set), and
`checkpointer_for` opens a *third* whenever a document carries
`settings.checkpointer: "sqlite"`. Nothing closed any of them: neither
langgraph's `SqliteSaver` nor its `SqliteStore` defines `close()` or
`__exit__`, so "the library handles it" was never true. A long-lived process
that loads workflows on demand — which is exactly what the HTTP and MCP
transports are — accumulated one OS file handle per load until it hit the
process limit.

The ownership rule under test: **what this process opened, this process
closes; what a caller injected stays theirs.** Closing an injected saver
would be worse than leaking one, because the caller is still using it.
"""

from __future__ import annotations

import sqlite3

import pytest

from openstategraph.api.services import WorkflowServices
from openstategraph.memory import CHECKPOINT_PATH_ENV


def _is_closed(resource: object) -> bool:
    """Proof by use, not by a flag: a closed sqlite3 connection raises."""
    conn = getattr(resource, "conn", None)
    if conn is None:
        return False
    try:
        conn.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        return True
    return False


@pytest.fixture()
def durable(tmp_path, monkeypatch):
    """Services whose checkpointer and memory store are both real sqlite."""
    monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
    monkeypatch.setenv("OPENSTATEGRAPH_MEMORY_PATH", str(tmp_path / "memory.sqlite"))
    return WorkflowServices(tmp_path)


class TestServicesCloseWhatTheyOpened:
    def test_the_checkpointer_connection_is_closed(self, durable) -> None:
        checkpointer = durable.checkpointer
        assert not _is_closed(checkpointer), "fixture must open a real sqlite saver"

        durable.close()

        assert _is_closed(checkpointer)

    def test_the_memory_store_connection_is_closed(self, durable) -> None:
        store = durable.memory_store
        assert not _is_closed(store), "fixture must open a real sqlite store"

        durable.close()

        assert _is_closed(store)

    def test_it_is_a_context_manager(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        with WorkflowServices(tmp_path) as services:
            checkpointer = services.checkpointer

        assert _is_closed(checkpointer)

    def test_closing_twice_is_not_an_error(self, durable) -> None:
        durable.close()
        durable.close()

    def test_a_never_asked_for_checkpointer_is_not_opened_by_close(
        self, tmp_path, monkeypatch
    ) -> None:
        """`close()` must not be the thing that creates the file — the property
        is lazy on purpose, and a close that resolves it would open a handle
        one instruction before closing it."""
        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        services = WorkflowServices(tmp_path)

        services.close()

        assert not (tmp_path / ".openstategraph").exists()


class TestInjectedResourcesStayTheCallers:
    def test_an_injected_checkpointer_is_not_closed(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        from langgraph.checkpoint.sqlite import SqliteSaver

        conn = sqlite3.connect(tmp_path / "mine.sqlite", check_same_thread=False)
        mine = SqliteSaver(conn)
        mine.setup()

        services = WorkflowServices(tmp_path, checkpointer=mine)
        services.close()

        assert not _is_closed(mine)
        conn.close()

    def test_an_injected_store_is_not_closed(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        from langgraph.store.memory import InMemoryStore

        mine = InMemoryStore()
        services = WorkflowServices(tmp_path, store=mine)

        services.close()

        assert services.memory_store is mine


class TestALoadedWorkflowClosesItsOwn:
    def test_load_workflow_closes_the_checkpointer_it_opened(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        monkeypatch.delenv("OPENSTATEGRAPH_MEMORY_PATH", raising=False)
        import json

        from conftest import RespondingModel

        from openstategraph import load_workflow
        from openstategraph.scaffold import starter_document

        package = tmp_path / "closable"
        package.mkdir()
        (package / "workflow.json").write_text(json.dumps(starter_document("closable")))

        workflow = load_workflow(package, model=RespondingModel([], default="ok"))
        checkpointer = workflow.graph.checkpointer
        assert not _is_closed(checkpointer)

        workflow.close()

        assert _is_closed(checkpointer)

    def test_it_is_a_context_manager_too(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        import json

        from conftest import RespondingModel

        from openstategraph import load_workflow
        from openstategraph.scaffold import starter_document

        package = tmp_path / "scoped"
        package.mkdir()
        (package / "workflow.json").write_text(json.dumps(starter_document("scoped")))

        with load_workflow(package, model=RespondingModel([], default="ok")) as workflow:
            checkpointer = workflow.graph.checkpointer

        assert _is_closed(checkpointer)


class TestReadOnlySqliteConnectionsAreClosed:
    """`with sqlite3.connect(...) as conn:` does **not** close the connection.

    That is the whole finding. sqlite3's connection context manager is a
    *transaction* manager — it commits or rolls back on exit and leaves the
    connection (and its file descriptor) open. Both read-only SQL surfaces
    used it: the Chinook-style `sql_*` tools an agent calls on every turn, and
    the knowledge builder's schema introspection, which opens a *nested*
    connection per table because `table_schema` calls `list_tables` inside its
    own block. A long-running agent loop therefore leaked one descriptor per
    tool call until the process hit its limit.
    """

    @pytest.fixture()
    def chinook(self, tmp_path):
        path = tmp_path / "tiny.sqlite"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE artist (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute(
            "CREATE TABLE album (id INTEGER PRIMARY KEY, artist_id INTEGER "
            "REFERENCES artist(id))"
        )
        conn.execute("INSERT INTO artist VALUES (1, 'Miles')")
        conn.commit()
        conn.close()
        return path

    @pytest.fixture()
    def opened(self, monkeypatch):
        """Every connection sqlite3 hands out during the test, in order."""
        connections: list[sqlite3.Connection] = []
        real = sqlite3.connect

        def recording(*args, **kwargs):
            conn = real(*args, **kwargs)
            connections.append(conn)
            return conn

        monkeypatch.setattr(sqlite3, "connect", recording)
        return connections

    def _all_closed(self, connections) -> bool:
        assert connections, "the call under test opened no connection at all"
        for conn in connections:
            try:
                conn.execute("SELECT 1")
            except sqlite3.ProgrammingError:
                continue
            return False
        return True

    def test_the_sql_explorer_tools_close_theirs(
        self, chinook, opened, monkeypatch
    ) -> None:
        import openstategraph.prebuilt_sql as sql

        # The tools jail their database path to the workflows root, so the
        # root is what has to move for a temporary database to be reachable.
        monkeypatch.setattr(sql, "workflows_root", lambda: chinook.parent)

        for tool, kwargs in (
            (sql.SqlListTablesTool(database="tiny.sqlite"), {}),
            (sql.SqlGetSchemaTool(database="tiny.sqlite"), {"table": "album"}),
            (sql.SqlQueryTool(database="tiny.sqlite"), {"query": "SELECT * FROM artist"}),
        ):
            assert tool.run(**kwargs).error is None

        assert self._all_closed(opened)

    def test_the_schema_introspector_closes_every_nested_one(
        self, chinook, opened
    ) -> None:
        from openstategraph.knowledge_engines import SqliteEngineAdapter

        adapter = SqliteEngineAdapter()
        ref = f"sqlite://{chinook}"
        adapter.list_tables(ref)
        adapter.table_schema(ref, "album")
        adapter.sample(ref, "artist")

        assert self._all_closed(opened)


class TestAPerWorkflowSaverIsOpenedOnceNotPerRequest:
    """`settings.checkpointer: "sqlite"` used to call `memory.checkpointer_for`
    at every run, stream, resume and MCP invocation — and each call opened a
    fresh `sqlite3` connection to the *same* file that nothing ever closed.

    Both defects have one cause and one fix: the saver is a per-workflow
    resource, so the services object owns it, hands out the same one, and
    closes it. (It is also correctness, not only economy: the sqlite saver's
    only concurrency control is a `threading.Lock` *per instance*, so two
    savers on one file are two locks guarding nothing.)
    """

    def test_the_same_saver_comes_back_every_time(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        monkeypatch.chdir(tmp_path)
        services = WorkflowServices(tmp_path)
        settings = {"checkpointer": "sqlite"}

        first = services.checkpointer_for(settings, "billing")
        second = services.checkpointer_for(settings, "billing")

        assert first is second
        assert first is not services.checkpointer
        services.close()

    def test_two_workflows_keep_separate_files(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        monkeypatch.chdir(tmp_path)
        services = WorkflowServices(tmp_path)
        settings = {"checkpointer": "sqlite"}

        assert services.checkpointer_for(settings, "a") is not services.checkpointer_for(
            settings, "b"
        )
        services.close()

    def test_a_document_that_does_not_ask_gets_the_process_default(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        services = WorkflowServices(tmp_path)

        assert services.checkpointer_for({}, "billing") is services.checkpointer
        services.close()

    def test_closing_the_services_closes_every_per_workflow_saver(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        monkeypatch.chdir(tmp_path)
        services = WorkflowServices(tmp_path)
        saver = services.checkpointer_for({"checkpointer": "sqlite"}, "billing")
        assert not _is_closed(saver)

        services.close()

        assert _is_closed(saver)


class TestTheServerReleasesWhatItServedWith:
    """Install-experience ticket 11 — `close()` was implemented and unreachable.

    `single_server_lifespan(services)` took the object and never touched it:
    its `finally` released the single-server lock and nothing else, there is no
    shutdown event handler anywhere in the repository, and `cmd_serve` hands
    the app to uvicorn by import string and closes nothing. Everything above in
    this file was therefore true of an object no served process ever called.
    """

    def test_the_lifespan_closes_the_services_it_was_built_with(
        self, tmp_path, monkeypatch
    ) -> None:
        from fastapi.testclient import TestClient

        from openstategraph.api.main import create_app

        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        monkeypatch.setenv("OPENSTATEGRAPH_MEMORY_PATH", str(tmp_path / "memory.sqlite"))
        app = create_app(workflows_root=tmp_path)
        services = app.state.services
        # Captured before shutdown: both are lazy properties that would
        # cheerfully re-open the file this test is asserting was closed.
        checkpointer = services.checkpointer
        store = services.memory_store
        assert not _is_closed(checkpointer), "fixture must open a real sqlite saver"
        assert not _is_closed(store), "fixture must open a real sqlite store"

        # Entering and leaving `TestClient` runs the app's real lifespan, both
        # halves — which is the only thing that distinguishes this from calling
        # `services.close()` by hand and proving nothing.
        with TestClient(app):
            pass

        assert _is_closed(checkpointer)
        assert _is_closed(store)

    def test_a_per_workflow_saver_opened_by_a_run_is_released_too(
        self, tmp_path, monkeypatch
    ) -> None:
        """The ticket-06 cache is bounded by `close()` and by nothing else."""
        from fastapi.testclient import TestClient

        from openstategraph.api.main import create_app

        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        monkeypatch.chdir(tmp_path)
        app = create_app(workflows_root=tmp_path)
        services = app.state.services
        saver = services.checkpointer_for({"checkpointer": "sqlite"}, "billing")
        assert not _is_closed(saver)

        with TestClient(app):
            pass

        assert _is_closed(saver)

    def test_the_lock_is_released_even_if_closing_raises(self, tmp_path, monkeypatch) -> None:
        """The two failures stay separate: a stuck lock outlives the process."""
        from fastapi.testclient import TestClient

        from openstategraph.api.main import create_app
        from openstategraph.deployment import SingleServerLock
        from openstategraph.state_dir import state_dir

        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        app = create_app(workflows_root=tmp_path)

        def explode() -> None:
            raise RuntimeError("a saver whose close() raises")

        # Set and removed by hand rather than through `monkeypatch`, which
        # would restore it at teardown — i.e. after conftest's autouse
        # release fixture has already called the exploding close.
        app.state.services.close = explode  # type: ignore[method-assign]
        with TestClient(app):
            pass
        del app.state.services.close

        # Acquirable again: the lock did not survive the failed close.
        lock = SingleServerLock(state_dir(tmp_path))
        lock.acquire()
        lock.release()


class TestTheSuiteItselfReleasesWhatItOpens:
    """The other half of ticket 11: 104 `create_app(` call sites, none closing.

    Pinned across two tests rather than inside one, because the thing under
    test *is* the teardown — a fixture that closes at the end of a test cannot
    be observed by that same test. pytest runs a class's tests in definition
    order, and the first hands the second the object it left open.
    """

    opened: list[object] = []

    def test_a_test_may_leave_a_durable_services_object_open(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        monkeypatch.setenv("OPENSTATEGRAPH_MEMORY_PATH", str(tmp_path / "memory.sqlite"))
        services = WorkflowServices(tmp_path)

        # The services object is kept alive on purpose — that is the case the
        # fixture exists for. One that is *dropped* needs nothing from us: the
        # `SqliteSaver` connection is released on collection, which is the
        # property `test_production_audit_2026_08_15.py` measures over 25
        # compile cycles, and it is why the fixture holds weak references.
        self.opened[:] = [services, services.checkpointer, services.memory_store]

        assert not any(_is_closed(resource) for resource in self.opened[1:])
        # ...and deliberately no `services.close()`. That omission is the
        # thing being tested.

    def test_the_previous_tests_handles_were_released_at_its_teardown(self) -> None:
        assert self.opened, "the test above must run first and leave two handles"
        assert all(_is_closed(resource) for resource in self.opened[1:]), (
            "an autouse fixture in conftest.py is meant to close every "
            "WorkflowServices a test constructs; nothing closed these"
        )
