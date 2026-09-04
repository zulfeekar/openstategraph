"""`session_id` has a writer, and the one door with no sitting says so.

`memory-and-replay/45`. The field was a complete feature except for a writer:
declared on `RunRequest`, carried into `configurable` by every door, persisted
by LangGraph into each checkpoint's metadata, read back onto `ThreadSummary`
and `RunRecord`, and filterable on `GET /api/threads?session_id=`, on
`openstategraph threads list --session` and on `runs list --session` — and
`""` on every real run, because the only client that opens these doors never
sent one. **A filter that always matches everything is worse than an absent
one**: it reads as a working feature and silently returns the whole listing.

The writer is `src/core/runtime/browserSession.ts`, and the three decisions the
ticket asked for are argued there and pinned here.

**Who mints it.** The client, which is not a contradiction of
`principal.py`. That module refuses a client-supplied `user_email` because that
value *keys a per-person memory namespace* — the danger it names is
client-supplied **and privilege-bearing**. `session_id` bears none: it enters no
Store namespace, no guard reads it, and it changes no run's behaviour. The proof
this is the existing rule rather than a new exemption is `thread_id`, which the
client has always minted and which *selects a checkpoint to continue* — strictly
more power than a listing label.

**Its lifetime.** One browser tab, held in `sessionStorage`. Deliberately a
second key beside `DRAFT_SESSION_KEY`, which is the same word on a different
concept — see `src/app/aSittingIsNotTheOpenWorkflow.test.ts`.

**The MCP door.** Never *minted*, and `TestTheDoorWithNoSitting` below is the
positive assertion of that rather than a silence somebody later reads as an
oversight. Since `kanban-patrol/08` it may be *declared* by the caller, which
is a different act — see that class's docstring for why the two are not the
same fact.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from openstategraph.run_sinks import RunRecord, read_runs, reset_run_sink_registry


def _n(i: str, t: str, **d: Any) -> dict[str, Any]:
    return {"id": i, "type": t, "data": d, "position": {"x": 0, "y": 0}}


def _document() -> dict[str, Any]:
    """Input → output. It runs, it answers, and it reaches no model at all."""
    return {
        "version": 2,
        "name": "Echo",
        "nodes": [_n("in1", "input.text"), _n("out1", "output.formatted")],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "out1", "portId": "result"},
            }
        ],
    }


@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "runs.sqlite"
    monkeypatch.setenv("OPENSTATEGRAPH_RUN_STORE_PATH", str(path))
    reset_run_sink_registry()
    yield path
    reset_run_sink_registry()


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    from openstategraph.api.main import create_app

    root = tmp_path / "workflows"
    root.mkdir()
    return TestClient(create_app(workflows_root=root))


def _rows(store: Path) -> list[RunRecord]:
    return read_runs(store, limit=50)


class TestTheDoorsTheEditorOpens:
    """The reproduction, run the way the editor runs it.

    The client sends one body through `runBody` to all three of these, so a
    sitting that reached the row on one door and not another would be the
    hand-copied-body defect that builder exists to have ended.
    """

    def test_the_blocking_door_records_the_sitting(
        self, store: Path, client: TestClient
    ) -> None:
        response = client.post(
            "/api/runs",
            json={
                "workflow": _document(),
                "question": "what did this sitting do",
                "thread_id": "http-1",
                "session_id": "sess-abc123",
            },
        )
        assert response.status_code == 200, response.text

        assert [row.session_id for row in _rows(store)] == ["sess-abc123"]

    def test_the_streaming_door_records_the_sitting(
        self, store: Path, client: TestClient
    ) -> None:
        """The door both shipped UIs actually use."""
        response = client.post(
            "/api/runs/stream",
            json={
                "workflow": _document(),
                "question": "what did this sitting do",
                "thread_id": "stream-1",
                "session_id": "sess-abc123",
            },
        )
        assert response.status_code == 200, response.text

        assert [row.session_id for row in _rows(store)] == ["sess-abc123"]


class TestTheFilterNoLongerMatchesEverything:
    """The consequence, stated as the question a QA engineer actually asks.

    *What did this person do in this sitting* is a different question from
    *what happened in this conversation*, and until there was a writer the
    former returned the latter's entire history.
    """

    def test_two_sittings_are_two_listings(self, store: Path, client: TestClient) -> None:
        for thread, sitting in (("t-1", "sess-one"), ("t-2", "sess-two"), ("t-3", "sess-one")):
            response = client.post(
                "/api/runs",
                json={
                    "workflow": _document(),
                    "question": "q",
                    "thread_id": thread,
                    "session_id": sitting,
                },
            )
            assert response.status_code == 200, response.text

        listing = client.get("/api/threads", params={"session_id": "sess-one"})
        assert listing.status_code == 200, listing.text
        threads = {row["thread_id"] for row in listing.json()["threads"]}

        assert threads == {"t-1", "t-3"}, (
            "a session filter that returns every thread is the defect this "
            "ticket exists to end"
        )


class TestTheDoorWithNoSitting:
    """MCP mints no sitting, and this is the assertion that says so.

    Three reasons, and the third is the one that would be discovered as a bug
    six months after somebody "fixed" the first two:

    1. An MCP client is a model, not a person at a tab. There is no sitting to
       *mint*, which is a different fact from the one next door — `user_email`
       is empty there for *safety*, this one for *ontology*.
    2. Minting one per call would make `session_id` a synonym for `thread_id`,
       which is minted per call on that transport. A session grouping exactly
       one thread groups nothing.
    3. It would break the axis `43` settled the field on — a thread is one
       conversation, a session groups several — by making `runs list --session`
       return exactly one row forever. A filter that always matches one thing
       is the same defect as one that always matches everything, mirrored.

    Empty is still *written*, not omitted, for the reason the door already
    records: the key set is what a reader compares across doors, and an absent
    key cannot be told from a forgotten one.

    ## The narrowing — `kanban-patrol/08`

    This class asserted the literal `""` until 2026-09-04, and the assertion
    was one word wider than its own argument. All three reasons above are
    about **minting**: the server inventing a grouping nobody asked for. None
    of them is an argument against a *caller* naming a sitting it is genuinely
    in, and a caller doing so satisfies 2 and 3 rather than breaking them — an
    agent working board card `X` opens several threads while working it, and
    `card:X` is exactly the several-threads grouping the field is for.

    So the pin is now on the mint, which is what was ever being defended: the
    only thing this door may write is the caller's own value, defaulting to
    `""`. A `uuid`, a `thread_id`, or a timestamp reaching this field is the
    defect, and it is still red.
    """

    def _bound_session_values(self) -> list[Any]:
        source = Path(__file__).resolve().parents[1] / "openstategraph" / "mcp_server.py"
        tree = ast.parse(source.read_text())
        bound: list[Any] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "session_id":
                    bound.append(value)
        return bound

    def test_the_mcp_door_mints_no_sitting(self) -> None:
        bound = self._bound_session_values()

        assert bound, "the MCP door stopped carrying `session_id` at all"
        for value in bound:
            rendered = ast.unparse(value)
            assert rendered == "''" or "session_id" in rendered, (
                f"The MCP door binds {rendered} as a session_id. It may write the "
                "caller's own value or an empty string, and nothing else — a "
                "minted one is a synonym for thread_id. See this class's "
                "docstring before changing it."
            )

    def test_an_mcp_caller_that_names_no_sitting_still_gets_an_empty_one(self) -> None:
        """The default is the old behaviour, unchanged: every caller that is
        not working the patrol board writes `""`, exactly as before."""
        import inspect

        from openstategraph.mcp_server import WorkflowRuns

        assert inspect.signature(WorkflowRuns.run).parameters["session_id"].default is None
        for value in self._bound_session_values():
            rendered = ast.unparse(value)
            assert rendered == "''" or rendered.endswith("or '')"), (
                f"{rendered} does not fall back to an empty string when the "
                "caller named no sitting."
            )

    def test_the_reason_is_written_where_somebody_would_change_it(self) -> None:
        """A deliberate absence with no argument beside it reads as an omission."""
        source = Path(__file__).resolve().parents[1] / "openstategraph" / "mcp_server.py"
        text = source.read_text()

        assert "There is no session here to name." in text
