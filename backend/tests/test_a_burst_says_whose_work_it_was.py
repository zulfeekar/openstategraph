"""A recording names the canvas node that owned it — `memory-and-replay` 74.

## The finding

`47` records `token` frames and keys a burst on `node`, `namespace`, `block`,
`kind` and `withheld`. Inside an agent, `node` is LangGraph's own loop node —
`model` and `tools` — so a real recording of `chinook-assistant` reads:

    model / tools / model / tools / model / tools / model / tools / agent-sql

Eight of those nine bursts do not say which canvas node was working. Only the
last one, where the loop had finished and the agent's own node reported, does.

**The frame already carried the answer.** `_token_frame` attaches `activeNode`
to every `token` frame, and its comment says exactly why: *"a `token` frame is
the only one that arrives while a node is STILL WORKING. `updates` fires on
completion, so a highlight fed by update frames alone can only ever show who
last finished."* The recorder read every other field of that frame and dropped
this one.

This is `launch-readiness/108` at one remove. That ticket found the live
timeline charging an agent's thinking to the node before it, and fixed it by
making the fold read `activeNode` — *"this field is the run saying whose
seconds they are."* A store that keeps the seconds and not the owner cannot be
made to answer it later, however good the reader is.

## What changes, and what does not

One column. A burst is keyed on the owner as well, because a burst is *one
node's output* and the owner changing is the identity changing — which is the
same rule the other five key fields already state. Nothing about a stored
burst's text, offsets or cadence moves, and a store one column behind reads
back exactly as it did (`_reconcile` and
`test_a_store_one_column_behind_keeps_its_runs.py` are the standing account of
that); an old row's owner is `""`, which is *this recording did not say* and
never a node named after the fact.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openstategraph.api.burst_recorder import BurstRecorder  # noqa: E402
from openstategraph.run_sinks import (  # noqa: E402
    RunRecord,
    SqliteRunSink,
    read_runs,
)


def _chunk(seq: int, elapsed: int, content: str, *, node: str, active: str) -> dict[str, object]:
    return {
        "seq": seq,
        "elapsedMs": elapsed,
        "content": content,
        "node": node,
        "activeNode": active,
        "namespace": [],
        "block": "text",
        "kind": "model",
    }


class TestTheRecorder:
    def test_a_burst_carries_the_node_the_run_said_was_working(self) -> None:
        recorder = BurstRecorder("developer")
        recorder.chunk(_chunk(1, 100, "Ro", node="model", active="agent-sql"))
        recorder.chunk(_chunk(2, 140, "ck", node="model", active="agent-sql"))
        bursts = recorder.bursts()
        assert [burst.active_node for burst in bursts] == ["agent-sql"]
        assert bursts[0].node == "model"

    def test_the_owner_changing_starts_a_new_burst(self) -> None:
        """A burst is *one node's output*, and two agents' loops both run
        through a LangGraph node called `model`. Folded on the loop name alone
        they would be one burst attributed to whichever spoke first."""
        recorder = BurstRecorder("developer")
        recorder.chunk(_chunk(1, 100, "a", node="model", active="agent-one"))
        recorder.chunk(_chunk(2, 200, "b", node="model", active="agent-two"))
        assert [burst.active_node for burst in recorder.bursts()] == ["agent-one", "agent-two"]

    def test_a_frame_that_named_nobody_says_nothing(self) -> None:
        recorder = BurstRecorder("developer")
        recorder.chunk(_chunk(1, 100, "a", node="model", active=""))
        assert recorder.bursts()[0].active_node == ""


class TestTheStore:
    def test_the_column_survives_a_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "runs.sqlite"
        sink = SqliteRunSink(path)
        recorder = BurstRecorder("developer")
        recorder.chunk(_chunk(1, 100, "Rock", node="model", active="agent-sql"))
        sink.record(
            RunRecord(
                at="2026-08-30T09:00:00+0000",
                workflow_slug="chinook-assistant",
                thread_id="t-a",
                question="Which genre earned most?",
                answer="Rock",
                bursts=recorder.bursts(),
            )
        )
        sink.close()
        rows = read_runs(path, with_bursts=True, audience="developer")
        assert [burst.active_node for burst in rows[0].bursts] == ["agent-sql"]
