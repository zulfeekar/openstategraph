"""A remembered fact survives a restart — install-experience wave 2.

The asymmetry this closes, stated as it was found. The checkpointer became
durable by default in ticket 05 and says so in one startup line. The Store did
not, and said nothing at all — so `save_memory` cheerfully answered
*"Remembered (user)."* into an `InMemoryStore` that dies with the process. A
true sentence about a fact that will not survive lunch, with no line anywhere
warning that it would not.

The asymmetry was deliberate once, and argued: a lost approval is a
correctness bug, lost memories are a quality regression
(`memory-architecture.md`). What changed is the standard — "one line to a
working canvas" includes memories surviving the restart the dev stack performs
on every file save.

`TestSurvivesARestart` is the test that matters, and it is the checkpointer's
own restart test pointed at the Store: save a fact, throw the whole services
object away, build a new one against the same state directory, and ask for the
fact back. An `InMemoryStore` cannot pass it.
"""

from __future__ import annotations

import sys

from openstategraph.api.services import WorkflowServices
from openstategraph.install_hint import install_hint
from openstategraph.memory import (
    IN_MEMORY_CHECKPOINT,
    MEMORY_FILE_NAME,
    MEMORY_PATH_ENV,
    MEMORY_TTL_ENV,
    STATE_DIR_NAME,
    build_store,
    memory_path,
)

NAMESPACE = ("memories", "a@x_com")


class TestTheDefaultLocation:
    """Nothing configured must still mean durable, and it must land beside the
    checkpointer rather than in a second place nobody thinks to back up."""

    def test_the_default_is_a_sqlite_file_in_the_state_directory(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.delenv(MEMORY_PATH_ENV, raising=False)
        assert memory_path(tmp_path) == tmp_path / STATE_DIR_NAME / MEMORY_FILE_NAME

    def test_an_explicit_path_wins(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv(MEMORY_PATH_ENV, str(tmp_path / "elsewhere.sqlite"))
        assert memory_path(tmp_path) == tmp_path / "elsewhere.sqlite"

    def test_memory_is_the_opt_out(self, tmp_path, monkeypatch) -> None:
        """The same word the checkpointer uses, on purpose: one spelling for
        one idea. A stateless container should not have to learn two."""
        monkeypatch.setenv(MEMORY_PATH_ENV, IN_MEMORY_CHECKPOINT)
        assert memory_path(tmp_path) is None

    def test_the_default_store_is_durable(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv(MEMORY_PATH_ENV, raising=False)
        monkeypatch.delenv("OPENSTATEGRAPH_POSTGRES_URL", raising=False)
        store = build_store(tmp_path)
        assert type(store).__name__ == "SqliteStore"
        assert (tmp_path / STATE_DIR_NAME / MEMORY_FILE_NAME).exists()


class TestItSaysWhichOneItGot:
    """The line the Store never had. Worded to match the checkpointer's pair,
    because a reader scanning a startup log should see the two facts in the
    same shape."""

    def test_persistence_is_announced_with_the_path(
        self, tmp_path, monkeypatch, caplog
    ) -> None:
        monkeypatch.delenv(MEMORY_PATH_ENV, raising=False)
        with caplog.at_level("INFO", logger="openstategraph.memory"):
            build_store(tmp_path)
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "memories persist at" in message
        assert STATE_DIR_NAME in message

    def test_the_in_memory_opt_out_is_announced_as_a_loss(
        self, tmp_path, monkeypatch, caplog
    ) -> None:
        monkeypatch.setenv(MEMORY_PATH_ENV, IN_MEMORY_CHECKPOINT)
        with caplog.at_level("WARNING", logger="openstategraph.memory"):
            build_store(tmp_path)
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "memories are in-memory and will NOT survive a restart" in message

    def test_the_two_messages_are_disjoint(self, tmp_path, monkeypatch, caplog) -> None:
        """Neither is a substring of the other, so `grep` on a log answers the
        question rather than matching both."""
        monkeypatch.delenv(MEMORY_PATH_ENV, raising=False)
        with caplog.at_level("INFO", logger="openstategraph.memory"):
            build_store(tmp_path)
        durable = " ".join(r.getMessage() for r in caplog.records)
        caplog.clear()
        monkeypatch.setenv(MEMORY_PATH_ENV, IN_MEMORY_CHECKPOINT)
        with caplog.at_level("WARNING", logger="openstategraph.memory"):
            build_store(tmp_path)
        volatile = " ".join(r.getMessage() for r in caplog.records)
        assert "NOT survive" not in durable
        assert "persist at" not in volatile

    def test_a_missing_sqlite_package_degrades_loudly_and_names_the_extra(
        self, tmp_path, monkeypatch, caplog
    ) -> None:
        """The default is sqlite now, so an install without the extra must say
        so — the same rule the checkpointer already obeys."""
        monkeypatch.delenv(MEMORY_PATH_ENV, raising=False)
        monkeypatch.setitem(sys.modules, "langgraph.store.sqlite", None)
        with caplog.at_level("WARNING", logger="openstategraph.memory"):
            store = build_store(tmp_path)
        message = " ".join(r.getMessage() for r in caplog.records)
        assert type(store).__name__ == "InMemoryStore"
        assert install_hint("sqlite") in message
        assert "memories are in-memory and will NOT survive a restart" in message

    def test_retention_without_a_durable_store_is_still_reported(
        self, tmp_path, monkeypatch, caplog
    ) -> None:
        """Unchanged in meaning, narrowed in trigger: asking for expiry now
        only goes unanswered when someone *opted out* of durability."""
        monkeypatch.setenv(MEMORY_PATH_ENV, IN_MEMORY_CHECKPOINT)
        monkeypatch.setenv(MEMORY_TTL_ENV, "60")
        with caplog.at_level("WARNING", logger="openstategraph.memory"):
            build_store(tmp_path)
        assert any(MEMORY_TTL_ENV in r.getMessage() for r in caplog.records)


class TestOneSeam:
    """`WorkflowServices` is the assembly point for the Store exactly as it is
    for the checkpointer, and ownership stays recorded rather than inferred."""

    def test_services_default_the_store_from_their_own_root(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.delenv(MEMORY_PATH_ENV, raising=False)
        services = WorkflowServices(tmp_path)
        assert type(services.memory_store).__name__ == "SqliteStore"
        assert (tmp_path / STATE_DIR_NAME / MEMORY_FILE_NAME).exists()
        services.close()

    def test_an_injected_store_wins_and_nothing_is_opened(
        self, tmp_path, monkeypatch
    ) -> None:
        """The reuse seam, unchanged by durability: what the caller lends us
        stays theirs, and we open no file of our own."""
        from langgraph.store.memory import InMemoryStore

        monkeypatch.delenv(MEMORY_PATH_ENV, raising=False)
        mine = InMemoryStore()
        services = WorkflowServices(tmp_path, memory_store=mine)
        assert services.memory_store is mine
        assert not (tmp_path / STATE_DIR_NAME / MEMORY_FILE_NAME).exists()

    def test_an_injected_store_is_not_closed_by_us(self, tmp_path, monkeypatch) -> None:
        """Ownership is recorded at construction, never inferred at close —
        `close_resource` would happily shut a caller's own connection."""
        monkeypatch.delenv(MEMORY_PATH_ENV, raising=False)
        closed: list[str] = []

        class Connection:
            def close(self) -> None:
                closed.append("closed")

        class Borrowed:
            """A store shaped like the one a host application would lend us —
            it holds its own connection, which is the thing that must survive
            our `close()`."""

            conn = Connection()

        services = WorkflowServices(tmp_path, memory_store=Borrowed())  # type: ignore[arg-type]
        services.close()
        assert closed == []


class TestSurvivesARestart:
    """The test the parent ticket asked for. Everything the first process held
    is unreachable; only the file on disk crosses."""

    def test_a_fact_saved_before_a_restart_is_recalled_after(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.delenv(MEMORY_PATH_ENV, raising=False)

        before = WorkflowServices(tmp_path)
        before.memory_store.put(NAMESPACE, "k1", {"fact": "the invoice totals sum InvoiceLine"})
        before.close()
        del before

        after = WorkflowServices(tmp_path)
        try:
            found = after.memory_store.search(NAMESPACE)
            assert [item.value["fact"] for item in found] == [
                "the invoice totals sum InvoiceLine"
            ]
        finally:
            after.close()

    def test_the_same_fact_is_lost_when_the_store_is_opted_out(
        self, tmp_path, monkeypatch
    ) -> None:
        """The negative control. With the opt-out — which is what *every*
        install got until this wave — the second process has never heard of the
        fact. If this ever starts recalling one, the test above has stopped
        proving anything."""
        monkeypatch.setenv(MEMORY_PATH_ENV, IN_MEMORY_CHECKPOINT)

        before = WorkflowServices(tmp_path)
        before.memory_store.put(NAMESPACE, "k1", {"fact": "gone by lunch"})
        before.close()
        del before

        after = WorkflowServices(tmp_path)
        assert after.memory_store.search(NAMESPACE) == []
        after.close()
