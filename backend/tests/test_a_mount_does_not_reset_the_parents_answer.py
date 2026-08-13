"""A mounted child's turn-reset is the child's, not the run's.

`_input` opens every turn by writing `RESET` to the channels that must not
survive it — `answer`, `outputs`, `decisions`. A mounted child runs its **own**
`input.text` node, so that marker arrives mid-run, namespaced under the mount.

The fold in `_run_frames` already knew this: `decisions` and `outputs` both
strip `RESET` before accumulating, with the reason recorded in place (a
router's branch read `None` whenever a subgraph ran after it). `answer` was
left out of that treatment, and it is the one channel where the marker is not
merely ignored but *destructive* — `keep_latest_nonempty` clears on `RESET` by
design, so one child frame empties the answer the fold had already collected.

`concierge` masks it: its mount runs before `out1`, which writes the answer
again on the way out. Every shape that produces an answer *before* a mount
loses it outright — agent → mount, two mounts in series, a grader's `pass`
into a mount — and the run reports success with nothing to show.

Scripted frames, not a live graph: the defect is in the fold's arithmetic, and
the scripted form states the ordering that triggers it in six lines.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from openstategraph.api.audience import Audience
from openstategraph.api.streaming import _run_frames
from openstategraph.compile.node_runtime import RESET

KNOWN = {"a1": "a1", "wf_music": "wf-music", "out1": "out1"}
MOUNT_NS = ("wf_music:2f0b",)


def _frames(chunks: list[Any]) -> list[tuple[str, dict[str, Any]]]:
    class _Graph:
        def stream(self, *_a: Any, **_k: Any) -> Any:
            return iter(chunks)

        def get_state(self, _config: Any) -> Any:
            return SimpleNamespace(next=(), tasks=())

        def get_graph(self, **_k: Any) -> Any:
            return SimpleNamespace(draw_mermaid=lambda: "graph TD;")

    runtime = SimpleNamespace(
        unresolved_tools=[], unresolved_functions=[], unresolved_subgraphs=[]
    )
    out: list[tuple[str, dict[str, Any]]] = []
    for raw in _run_frames(
        _Graph(),
        {},
        {"configurable": {"thread_id": "t1", "workflow_slug": "parent-flow"}},
        SimpleNamespace(warnings=[]),
        KNOWN,
        runtime,
        "t1",
        Audience.DEVELOPER,
    ):
        head, _, body = raw.partition("\n")
        out.append((head[len("event: ") :], json.loads(body.partition("data: ")[2])))
    return out


def _done(chunks: list[Any]) -> dict[str, Any]:
    return next(payload for name, payload in _frames(chunks) if name == "done")


ANSWER = "Iron Maiden, with $138.60."


class TestAMountDoesNotResetTheRunsAnswer:
    def test_an_answer_produced_before_a_mount_survives_the_mounts_input_node(
        self,
    ) -> None:
        """The defect, in the ordering that exposes it."""
        done = _done(
            [
                ((), "updates", {"a1": {"answer": ANSWER, "outputs": {"a1": ANSWER}}}),
                (
                    MOUNT_NS,
                    "updates",
                    {"in1": {"answer": RESET, "outputs": {RESET: "", "in1": "q"}}},
                ),
                ((), "updates", {"wf_music": {"outputs": {"wf-music": ""}}}),
            ]
        )
        assert done["answer"] == ANSWER

    def test_the_reset_marker_never_reaches_a_client_as_an_answer(self) -> None:
        """Belt and braces: even alone, the marker is machinery, not prose."""
        done = _done(
            [(MOUNT_NS, "updates", {"in1": {"answer": RESET, "outputs": {"in1": "q"}}})]
        )
        assert RESET not in done["answer"]

    def test_a_later_real_answer_still_wins(self) -> None:
        """Stripping the marker must not freeze the channel: the last
        non-empty write is still the answer."""
        done = _done(
            [
                ((), "updates", {"a1": {"answer": "draft"}}),
                (MOUNT_NS, "updates", {"in1": {"answer": RESET}}),
                ((), "updates", {"out1": {"answer": ANSWER, "outputs": {"out1": ANSWER}}}),
            ]
        )
        assert done["answer"] == ANSWER
