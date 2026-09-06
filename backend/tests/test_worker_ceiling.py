"""The worker ceiling is enforced, not documented.

Ticket 06 (scale-and-adopt) decided: this project **refuses** multi-worker
rather than supporting it. Two independent in-process mechanisms make a second
worker wrong — `SqliteSaver`/`SqliteStore` serialise writes with a
`threading.Lock` held per instance, and the catalogue-events fan-out
(`api/catalogue_events.py`) is an in-process deque — and the failure mode of
ignoring either is silent: a paused `human.approval` written by two processes
at once, and a `/api/events` subscriber that never hears about the publish that
happened in the other worker.

So these tests guard the two halves of the refusal:

- **What we can see, we name.** `WEB_CONCURRENCY`, `UVICORN_WORKERS` and
  `openstategraph serve --workers N` are read directly and refused before a
  socket is bound.
- **What we cannot see, we still catch.** `uvicorn --workers 4` and
  `gunicorn -w 4` leave no environment trace, so the serving process takes an
  OS-level exclusive lock on a file in the state directory. The *second*
  process to try is refused, whoever launched it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

from openstategraph import deployment


class TestConfiguredWorkerCount:
    """Reading the deployment's own answer, from the places it is written."""

    def test_nothing_configured_is_not_a_refusal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in deployment.WORKER_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
        assert deployment.configured_worker_count() is None
        assert deployment.check_worker_count() is None

    def test_one_worker_is_the_supported_configuration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WEB_CONCURRENCY", "1")
        assert deployment.configured_worker_count() == (1, "WEB_CONCURRENCY")
        assert deployment.check_worker_count() is None

    @pytest.mark.parametrize("name", deployment.WORKER_ENV_VARS)
    def test_every_env_spelling_is_read(self, name: str, monkeypatch: pytest.MonkeyPatch) -> None:
        for other in deployment.WORKER_ENV_VARS:
            monkeypatch.delenv(other, raising=False)
        monkeypatch.setenv(name, "4")
        assert deployment.configured_worker_count() == (4, name)

    def test_a_junk_value_is_not_a_refusal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Refusing on `WEB_CONCURRENCY=auto` would break a deployment over a
        value we could not even read. Unreadable means unknown, and unknown
        falls through to the lock, which needs no cooperation."""
        for name in deployment.WORKER_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("WEB_CONCURRENCY", "auto")
        assert deployment.configured_worker_count() is None

    def test_an_explicit_argument_outranks_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`convention < config file < environment < explicit argument` — the
        project-wide precedence rule, applied here too."""
        monkeypatch.setenv("WEB_CONCURRENCY", "1")
        message = deployment.check_worker_count(explicit=3)
        assert message is not None
        assert "--workers 3" in message


class TestRefusalMessage:
    """A refusal that does not say what to do instead is just a crash."""

    def test_it_names_both_reasons_and_the_fix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WEB_CONCURRENCY", "8")
        message = deployment.check_worker_count()
        assert message is not None
        for expected in ("WEB_CONCURRENCY=8", "checkpoint", "catalogue", "--workers 1"):
            assert expected in message

    def test_postgres_is_not_advertised_as_the_lift(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Half the fix is shipped (`[postgres]`) and half is not (the events
        fan-out). A message that named only the shipped half would send a
        deployer to configure Postgres and try again — and the second attempt
        must be refused too, for a reason they were told about the first time."""
        monkeypatch.setenv("WEB_CONCURRENCY", "2")
        message = deployment.check_worker_count()
        assert message is not None
        assert "postgres" in message.lower()
        assert "not enough" in message.lower()


class TestServeLock:
    """The half of the refusal that needs no cooperation from the launcher."""

    def test_it_is_acquired_and_released(self, tmp_path) -> None:
        lock = deployment.SingleServerLock(tmp_path)
        lock.acquire()
        try:
            assert lock.path.exists()
        finally:
            lock.release()

    def test_the_same_process_may_hold_it_twice(self, tmp_path) -> None:
        """Two `create_app()` calls in one process are two *threads* sharing one
        `SqliteSaver`, which is the supported case. Only another *process* is
        the hazard, so the lock is refcounted within this one — otherwise the
        test suite, and any embedder holding two apps, would refuse itself."""
        first = deployment.SingleServerLock(tmp_path)
        second = deployment.SingleServerLock(tmp_path)
        first.acquire()
        second.acquire()
        first.release()
        # Still held by `second`: a subprocess must still be refused.
        assert _second_process_refused(tmp_path)
        second.release()

    def test_another_process_is_refused_with_the_reason(self, tmp_path) -> None:
        lock = deployment.SingleServerLock(tmp_path)
        lock.acquire()
        try:
            assert _second_process_refused(tmp_path)
        finally:
            lock.release()

    def test_release_hands_it_on(self, tmp_path) -> None:
        lock = deployment.SingleServerLock(tmp_path)
        lock.acquire()
        lock.release()
        assert not _second_process_refused(tmp_path)

    def test_releasing_twice_is_harmless(self, tmp_path) -> None:
        lock = deployment.SingleServerLock(tmp_path)
        lock.acquire()
        lock.release()
        lock.release()


def _second_process_refused(state_dir) -> bool:
    """Whether a genuinely separate OS process is refused the lock.

    A subprocess and not a thread: `fcntl.flock` is held per *file
    description*, and the thing under test is precisely that two OS processes
    cannot both serve. A thread would prove nothing.
    """
    script = textwrap.dedent(
        f"""
        from openstategraph import deployment
        lock = deployment.SingleServerLock({str(state_dir)!r})
        try:
            lock.acquire()
        except deployment.AnotherServerIsRunning as exc:
            print("REFUSED", str(exc))
        else:
            print("ACQUIRED")
        """
    )
    env = dict(os.environ, PYTHONPATH=str(_backend_dir()))
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=60
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.startswith("REFUSED")


def _backend_dir():
    from pathlib import Path

    return Path(__file__).resolve().parents[1]


class TestServeCommandRefuses:
    """`openstategraph serve --workers 2` never reaches uvicorn."""

    def test_it_exits_nonzero_before_binding(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from openstategraph import cli

        def _never(*args: object, **kwargs: object) -> object:  # pragma: no cover
            raise AssertionError("a socket was bound despite the refusal")

        monkeypatch.setattr("openstategraph.api.listening.bind_listener", _never)
        code = cli.main(["serve", "--workers", "2"])
        assert code != 0
        assert "--workers 1" in capsys.readouterr().err

    def test_one_worker_is_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The flag exists to refuse, but `--workers 1` is a legitimate thing
        for a deploy script to say, and saying it must not be an error."""
        assert deployment.check_worker_count(explicit=1) is None

    def test_a_locked_state_directory_is_refused_before_the_urls_print(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path
    ) -> None:
        """workflow-gallery/40: the third refusal — the state-directory lock —
        used to live only in the FastAPI lifespan, which runs *after*
        `bind_listener` and after the three URLs are printed. A second
        `serve` against a directory another server already holds must be
        refused before anything is bound or printed, exactly like the
        `--workers` and port refusals above.
        """
        from openstategraph import cli

        monkeypatch.setenv("OPENSTATEGRAPH_STATE_DIR", str(tmp_path))

        # A genuinely different lock object with the same path still conflicts
        # at the OS level unless it is the same *process* — which the flock
        # refcounting in `deployment._HELD` would otherwise paper over. Take
        # the lock in a real subprocess so the ceiling test's own process
        # cannot "see" it as already held.
        script = textwrap.dedent(
            f"""
            import time
            from openstategraph import deployment
            lock = deployment.SingleServerLock({str(tmp_path)!r})
            lock.acquire()
            time.sleep(5)
            """
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", script],
            env=dict(os.environ, PYTHONPATH=str(_backend_dir())),
        )
        try:
            # Give the subprocess a moment to actually take the lock.
            import time as _time

            for _ in range(50):
                try:
                    probe_lock = deployment.SingleServerLock(tmp_path)
                    probe_lock.acquire()
                except deployment.AnotherServerIsRunning:
                    break
                else:
                    probe_lock.release()
                    _time.sleep(0.1)
            else:  # pragma: no cover - defensive
                pytest.fail("subprocess never took the lock")

            def _never(*args: object, **kwargs: object) -> object:  # pragma: no cover
                raise AssertionError("a socket was bound despite the lock refusal")

            monkeypatch.setattr("openstategraph.api.listening.bind_listener", _never)
            code = cli.main(["serve", "--port", "0"])
            captured = capsys.readouterr()
            assert code != 0
            assert "editor" not in captured.out
            assert "already holds" in captured.err
        finally:
            proc.terminate()
            proc.wait(timeout=5)
