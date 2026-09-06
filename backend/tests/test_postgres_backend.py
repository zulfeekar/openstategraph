"""The opt-in Postgres checkpointer and store — scale-and-adopt ticket 06.

**What this is and is not.** Postgres is shipped so a real deployment can keep
paused approvals and long-term memories in a database its operators already
back up, instead of a sqlite file next to the process. It is **not** the lift
on the worker ceiling: `openstategraph.deployment` still refuses more than one
worker with Postgres configured, because the catalogue-events fan-out has no
cross-process transport. `test_worker_ceiling.py` pins that half.

**No live database here.** These tests exercise the seam — resolution,
precedence, degradation and redaction — against a stub module installed in
`sys.modules`. What a real `PostgresSaver` does with a real connection is
`langgraph-checkpoint-postgres`'s test suite's job, and duplicating it here
would mean an integration dependency in a unit suite for no extra evidence.
What is genuinely ours is: which URL wins, what happens when the extra is not
installed, and whether the password ever reaches a log.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from openstategraph import memory, postgres

DSN = "postgresql://osg:hunter2@db.internal:5432/openstategraph"


class StubSaver:
    def __init__(self, conn: Any) -> None:
        self.conn = conn
        self.setup_calls = 0

    def setup(self) -> None:
        self.setup_calls += 1


class StubStore(StubSaver):
    pass


class StubPool:
    """Stands in for `psycopg_pool.ConnectionPool`."""

    def __init__(self, conninfo: str, **kwargs: Any) -> None:
        self.conninfo = conninfo
        self.kwargs = kwargs
        self.opened = False
        self.closed = False

    def open(self, wait: bool = False, timeout: float = 30.0) -> None:
        self.opened = True

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def stub_postgres(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Install fake `langgraph.checkpoint.postgres`, `langgraph.store.postgres`
    and `psycopg_pool` modules for the duration of one test."""
    import types

    saver_module = types.ModuleType("langgraph.checkpoint.postgres")
    saver_module.PostgresSaver = StubSaver  # type: ignore[attr-defined]
    store_module = types.ModuleType("langgraph.store.postgres")
    store_module.PostgresStore = StubStore  # type: ignore[attr-defined]
    pool_module = types.ModuleType("psycopg_pool")
    pool_module.ConnectionPool = StubPool  # type: ignore[attr-defined]
    rows_module = types.ModuleType("psycopg.rows")
    rows_module.dict_row = object()  # type: ignore[attr-defined]

    for name, module in (
        ("langgraph.checkpoint.postgres", saver_module),
        ("langgraph.store.postgres", store_module),
        ("psycopg_pool", pool_module),
        ("psycopg.rows", rows_module),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    return saver_module


@pytest.fixture(autouse=True)
def _no_inherited_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(postgres.POSTGRES_URL_ENV, raising=False)


class TestUrlResolution:
    def test_unset_is_none(self) -> None:
        assert postgres.postgres_url() is None
        assert postgres.configured() is False

    def test_the_environment_names_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(postgres.POSTGRES_URL_ENV, DSN)
        assert postgres.postgres_url() == DSN
        assert postgres.configured() is True

    def test_whitespace_is_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(postgres.POSTGRES_URL_ENV, "  ")
        assert postgres.postgres_url() is None

    def test_the_config_file_cannot_hold_it(self) -> None:
        """A DSN carries a password, `openstategraph.yaml` is committed, and
        `config_file._reject_secrets` exists to keep credentials out of it. So
        the URL is environment-only *by construction*, and the config schema
        must not grow a field for it."""
        from openstategraph.config_file import OpenStateGraphConfig

        assert "postgres" not in " ".join(OpenStateGraphConfig.model_fields)


class TestRedaction:
    """A DSN in a log is a password in a log."""

    def test_the_password_never_survives(self) -> None:
        assert "hunter2" not in postgres.redacted(DSN)

    def test_what_is_left_is_still_diagnosable(self) -> None:
        redacted = postgres.redacted(DSN)
        assert "db.internal" in redacted
        assert "openstategraph" in redacted
        assert "osg" in redacted

    def test_a_dsn_with_no_password_is_unchanged(self) -> None:
        plain = "postgresql://db.internal:5432/osg"
        assert postgres.redacted(plain) == plain

    def test_a_keyword_dsn_is_redacted_too(self) -> None:
        assert "hunter2" not in postgres.redacted("host=db user=osg password=hunter2")

    def test_the_error_for_an_unreachable_database_is_redacted(
        self, monkeypatch: pytest.MonkeyPatch, stub_postgres: Any
    ) -> None:
        def _explode(*args: Any, **kwargs: Any) -> Any:
            raise OSError("connection refused")

        monkeypatch.setattr(StubPool, "open", _explode)
        monkeypatch.setenv(postgres.POSTGRES_URL_ENV, DSN)

        with pytest.raises(postgres.PostgresUnavailable) as caught:
            postgres.checkpointer(DSN)
        assert "hunter2" not in str(caught.value)
        assert "db.internal" in str(caught.value)


class TestTheExtraIsRequired:
    def test_a_missing_package_names_the_install_line(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """And does **not** fall back to sqlite. Nobody sets
        `OPENSTATEGRAPH_POSTGRES_URL` by accident; quietly writing their
        approvals to a local file instead is a data-location surprise they
        would discover at restore time."""
        import builtins

        real_import = builtins.__import__

        def _refuse(name: str, *args: Any, **kwargs: Any) -> Any:
            if name.startswith(("langgraph.checkpoint.postgres", "psycopg")):
                raise ImportError(f"No module named {name!r}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _refuse)

        with pytest.raises(ImportError) as caught:
            postgres.checkpointer(DSN)
        assert "openstategraph[postgres]" in str(caught.value)


class TestTheCheckpointerAndStore:
    def test_the_saver_is_built_and_set_up(
        self, monkeypatch: pytest.MonkeyPatch, stub_postgres: Any
    ) -> None:
        saver = postgres.checkpointer(DSN)
        assert isinstance(saver, StubSaver)
        assert saver.setup_calls == 1

    def test_it_uses_a_pool_so_request_threads_do_not_serialise(
        self, stub_postgres: Any
    ) -> None:
        """A single `psycopg.Connection` would put every request thread behind
        one lock — trading sqlite's per-instance lock for an identical one and
        buying nothing."""
        saver = postgres.checkpointer(DSN)
        assert isinstance(saver.conn, StubPool)
        assert saver.conn.opened is True
        assert saver.conn.kwargs["kwargs"]["autocommit"] is True

    def test_the_store_is_built_and_set_up(self, stub_postgres: Any) -> None:
        store = postgres.store(DSN)
        assert isinstance(store, StubStore)
        assert store.setup_calls == 1

    def test_close_resource_releases_the_pool(self, stub_postgres: Any) -> None:
        """`memory.close_resource` closes whatever is on `.conn`; a pool has to
        be one of the things it knows how to release, or a long-lived process
        leaks connections on every reload."""
        saver = postgres.checkpointer(DSN)
        memory.close_resource(saver)
        assert saver.conn.closed is True


class TestPrecedence:
    """`convention < config file < environment < explicit argument`, and within
    the environment the *more specific* answer wins."""

    def test_postgres_is_used_when_nothing_more_specific_is_set(
        self, monkeypatch: pytest.MonkeyPatch, stub_postgres: Any
    ) -> None:
        monkeypatch.delenv(memory.CHECKPOINT_PATH_ENV, raising=False)
        monkeypatch.setenv(postgres.POSTGRES_URL_ENV, DSN)
        assert isinstance(memory.build_checkpointer(), StubSaver)

    def test_an_explicit_checkpoint_path_still_wins(
        self, monkeypatch: pytest.MonkeyPatch, stub_postgres: Any, tmp_path
    ) -> None:
        """`OPENSTATEGRAPH_CHECKPOINT_PATH` names one file outright. Someone who
        set both meant the more specific one."""
        monkeypatch.setenv(postgres.POSTGRES_URL_ENV, DSN)
        monkeypatch.setenv(memory.CHECKPOINT_PATH_ENV, str(tmp_path / "cp.sqlite"))
        assert not isinstance(memory.build_checkpointer(), StubSaver)

    def test_opting_out_of_durability_still_works(
        self, monkeypatch: pytest.MonkeyPatch, stub_postgres: Any
    ) -> None:
        monkeypatch.setenv(postgres.POSTGRES_URL_ENV, DSN)
        monkeypatch.setenv(memory.CHECKPOINT_PATH_ENV, "memory")
        saver = memory.build_checkpointer()
        assert not isinstance(saver, StubSaver)
        assert type(saver).__name__ == "InMemorySaver"

    def test_the_store_follows_the_same_rule(
        self, monkeypatch: pytest.MonkeyPatch, stub_postgres: Any
    ) -> None:
        monkeypatch.delenv("OPENSTATEGRAPH_MEMORY_PATH", raising=False)
        monkeypatch.setenv(postgres.POSTGRES_URL_ENV, DSN)
        assert isinstance(memory.build_store(), StubStore)

    def test_an_explicit_memory_path_still_wins_for_the_store(
        self, monkeypatch: pytest.MonkeyPatch, stub_postgres: Any, tmp_path
    ) -> None:
        monkeypatch.setenv(postgres.POSTGRES_URL_ENV, DSN)
        monkeypatch.setenv("OPENSTATEGRAPH_MEMORY_PATH", str(tmp_path / "mem.sqlite"))
        assert not isinstance(memory.build_store(), StubStore)


class TestItIsAnExtra:
    def test_the_package_declares_it(self) -> None:
        """Declared, pinned and reachable from `[all]` — an undeclared optional
        import is the exact trap `_extras` exists to close."""
        import tomllib
        from pathlib import Path

        pyproject = Path(memory.__file__).resolve().parents[1] / "pyproject.toml"
        extras = tomllib.loads(pyproject.read_text())["project"]["optional-dependencies"]

        assert "postgres" in extras
        assert any("langgraph-checkpoint-postgres" in dep for dep in extras["postgres"])
        assert any("psycopg" in dep for dep in extras["postgres"])
        assert any("postgres" in dep for dep in extras["all"])

    def test_importing_it_pulls_in_nothing(self) -> None:
        """`openstategraph.postgres` is imported unconditionally by `memory`, so
        it must not import psycopg or langgraph at module scope — otherwise the
        lean core stops being lean for every install that never uses it."""
        import ast
        from pathlib import Path

        tree = ast.parse(Path(postgres.__file__).read_text())
        module_scope = [
            name
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for name in ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                         [alias.name for alias in node.names])
        ]

        assert not [n for n in module_scope if n.startswith(("psycopg", "langgraph"))]
