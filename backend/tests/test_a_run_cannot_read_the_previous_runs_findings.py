"""A run must not answer out of the previous run's findings — `launch-readiness/149`.

Measured live on an MCP package, three consecutive runs of one question in one
server process: **run 2 called no query tool at all** and answered, fluently,
out of the `/findings/*.json` files run 1 had written. Nothing on screen
separated that answer from a fetched one.

The cause was a store keyed on nothing that varies: `_ROOTS` held one root per
package **per process**, so every run of that package on a long-lived server
shared one writable scratch directory — across runs, across conversations,
across people.

Two facts settle the lifetime, and both are read off what is installed rather
than off what would be tidy:

- **`run_id` does not reach this seam.** On `langgraph 1.2.10` a plain
  `.invoke()` populates `configurable["__pregel_runtime"].execution_info` with
  `run_id=None`; what a node can always read is `configurable["thread_id"]`,
  which is also the key the checkpointer uses and the value
  `POST /api/runs/resume` requires back. A store keyed on something the graph
  does not carry is not a fix.
- **A thread is the unit a resume preserves.** `Command(resume=...)` continues
  the same thread, and an offload pointer already sitting in that thread's
  transcript has to keep resolving. Per-thread is therefore the *narrowest*
  scope that does not invent a second bug.

So these tests drive **two runs through a real graph** rather than poking the
root table: a table keyed correctly and never consulted at run time would pass
the second kind of test and fail the first.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("deepagents")

from langgraph.graph import END, START, StateGraph  # noqa: E402
from typing_extensions import TypedDict  # noqa: E402

from openstategraph.abc import deep_tier_offload  # noqa: E402
from openstategraph.abc.deep_tier_offload import (  # noqa: E402
    HARNESS_PREAMBLE,
    plan_disclosure,
)

SURFACE = ("read_file", "grep", "mcp_execute_sql")


class _S(TypedDict):
    out: str


def _run(backend, action, thread_id: str) -> str:
    """One graph run, on `thread_id`, doing `action(backend)` inside a node.

    A real `StateGraph` and a real `thread_id` in `configurable`, because that
    is the only place `langgraph.config.get_config()` answers — the seam this
    ticket turns on. A helper that called `action` directly would test the
    root table and not the run.
    """

    def node(_state: _S) -> dict[str, str]:
        return {"out": action(backend)}

    graph = StateGraph(_S)
    graph.add_node("n", node)
    graph.add_edge(START, "n")
    graph.add_edge("n", END)
    return graph.compile().invoke(
        {"out": ""}, config={"configurable": {"thread_id": thread_id}}
    )["out"]


def _write(text: str):
    def action(backend) -> str:
        backend.write("/findings/ports.json", text)
        return "written"

    return action


def _read(backend) -> str:
    return _text(backend.read("/findings/ports.json"))


def _text(result) -> str:
    """The content of a `ReadResult`, or `""` when the file was not there."""
    if result.error or not result.file_data:
        return ""
    return str(result.file_data["content"])


def _backend(tmp_path):
    return plan_disclosure(
        package_dir=tmp_path, tool_surface=SURFACE, shares_backend=True
    ).backend


class TestAcrossRuns:
    def test_a_later_run_cannot_read_what_an_earlier_run_wrote(self, tmp_path) -> None:
        """The defect, exactly as it was observed.

        One process, one compiled agent, one package — two runs. The second
        must not find the first's file, because the answer it would build out
        of it is stale by an unknown amount and looks identical to a fetched
        one.
        """
        backend = _backend(tmp_path)
        _run(backend, _write("the ports run 1 fetched"), thread_id="run-1")
        assert _run(backend, _read, thread_id="run-2") == ""

    def test_a_resume_still_finds_what_the_interrupted_run_wrote(
        self, tmp_path
    ) -> None:
        """The bug on the other side of the line, and why per-run was rejected.

        A resume is the *same* thread by construction — `POST /api/runs/resume`
        refuses any other. An offload pointer written before the interrupt is
        still sitting in that thread's transcript, so a store that vanished
        between the two halves of one conversation would hand the model a path
        it cannot follow.
        """
        backend = _backend(tmp_path)
        _run(backend, _write("fetched before the interrupt"), thread_id="run-1")
        assert _run(backend, _read, thread_id="run-1") == "fetched before the interrupt"

    def test_two_packages_never_share_a_store_within_one_thread(
        self, tmp_path
    ) -> None:
        """Package scoping is not weakened by adding thread scoping to it."""
        a = _backend(tmp_path / "a")
        b = _backend(tmp_path / "b")
        _run(a, _write("package a"), thread_id="t")
        assert _run(b, _read, thread_id="t") == ""

    def test_a_run_with_no_thread_is_its_own_store_and_not_everyone_elses(
        self, tmp_path
    ) -> None:
        """A script or a unit test carries no run config; `{}` is a complete answer.

        It gets the one unscoped store rather than an error — the same
        behaviour this seam has always had off the graph — and that store is
        not the one any thread reads.
        """
        backend = _backend(tmp_path)
        backend.write("/findings/ports.json", "written with no thread")
        assert _run(backend, _read, thread_id="run-1") == ""
        assert _read(backend) == "written with no thread"


class TestWhatIsSharedOnPurpose:
    def test_a_disclosed_skill_is_readable_in_every_thread(self, tmp_path) -> None:
        """Isolation is of what the *agent* wrote, never of what it was given.

        Skills are projected read-only from the package, so every thread's
        store must carry them — otherwise the paths in the disclosure prompt
        are dangling in every run but the first, which is the same class of
        defect pointed the other way.
        """
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "house-style.md").write_text(
            "---\nname: house-style\ndescription: how this package writes SQL\n---\n"
            + ("body. " * 400),
            encoding="utf-8",
        )
        plan = plan_disclosure(
            package_dir=tmp_path, tool_surface=SURFACE, shares_backend=True
        )
        assert plan.disclosed == ("house-style",)

        def read_skill(backend) -> str:
            return _text(backend.read("/skills/house-style/SKILL.md"))

        assert "house-style" in _run(plan.backend, read_skill, thread_id="run-1")
        assert "house-style" in _run(plan.backend, read_skill, thread_id="run-2")


class TestTheStoreIsBounded:
    def test_an_idle_thread_store_is_swept(self, tmp_path, monkeypatch) -> None:
        """`launch-readiness/96` in another costume, refused in advance.

        Per-thread means one directory per conversation, and a server that
        never removes them grows without bound. A store untouched for
        `THREAD_ROOT_TTL_SECONDS` belongs to a conversation nobody is in.
        """
        backend = _backend(tmp_path)
        _run(backend, _write("old"), thread_id="run-1")
        clock = time.monotonic() + deep_tier_offload.THREAD_ROOT_TTL_SECONDS + 1
        monkeypatch.setattr(deep_tier_offload.time, "monotonic", lambda: clock)
        _run(backend, _write("new"), thread_id="run-2")
        monkeypatch.undo()
        assert _run(backend, _read, thread_id="run-1") == ""


class TestThePreambleSaysWhatIsTrue:
    def test_it_no_longer_claims_the_filesystem_is_private_to_the_run(self) -> None:
        """`120` shipped the sentence an hour before `149` was filed.

        A locked, non-editable sentence that lies is worse than an empty one —
        that is `120`'s own argument, and it applies to `120`'s own text.
        """
        assert "private to this run" not in HARNESS_PREAMBLE

    def test_it_names_the_conversation_as_the_boundary(self) -> None:
        assert "conversation" in HARNESS_PREAMBLE
        assert "confined" in HARNESS_PREAMBLE

    def test_it_warns_that_a_file_may_be_from_an_earlier_turn(self) -> None:
        """The honest half of per-thread.

        A conversation-wide store is the right lifetime and it is *not* a
        fresh one each turn, so the model has to be told the one thing that
        follows: a file it finds may be what a tool returned earlier, not what
        it would return now.
        """
        assert "earlier in this conversation" in HARNESS_PREAMBLE
