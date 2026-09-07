"""Zero-width characters do not survive publication — `osg-agent-experience/87`.

A live run on 2026-09-06 published a table row whose last cell read

    ... | 12 tracks (<a run of U+200B>); **source: main.tracks_latest**

The parentheses held a run of zero-width spaces. A reader sees empty
brackets; a reader who copies the line carries the characters into a report;
a reader who greps or diffs the text gets a result they cannot explain.

They are the model's own output, and nothing between the model and the reader
removed them. The rule belongs at the seam where an answer becomes something a
reader receives — `compile.state.published_answer`, the one place every door
reads the answer through — and not in every developer's prompt, because a rule
in a prompt is a request and these characters are invisible to the model that
would have to obey it.

The narrowness is the safety, and it is asserted here as hard as the stripping
is: a joiner between two non-ASCII characters is doing a script's work, and the
visible text either side of a stripped character is returned byte for byte.
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.state import published_answer, strip_invisible
from openstategraph.compile.workflow_compiler import WorkflowCompiler, run_health_from_state

ZWSP = "​"
ZWNJ = "‌"
ZWJ = "‍"
BOM = "﻿"


def _edge(src: str, src_port: str, dst: str, dst_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": src_port},
        "target": {"nodeId": dst, "portId": dst_port},
    }


def _document(outputs: int = 1) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        {"id": "f1", "type": "function.speak", "position": {"x": 200, "y": 0}, "data": {}},
    ]
    edges = [_edge("in1", "text", "f1", "candidate")]
    for index in range(outputs):
        nodes.append(
            {
                "id": f"out{index}",
                "type": "output.formatted",
                "position": {"x": 400, "y": 90 * index},
                "data": {},
            }
        )
        edges.append(_edge("f1", "report", f"out{index}", "result"))
    return {"version": 2, "name": "speaker", "nodes": nodes, "edges": edges}


def _run(said: str, outputs: int = 1) -> dict[str, Any]:
    """The whole graph, with a package function standing in for the model.

    Nothing here resolves a model: the defect is in what publication does with
    text, so the text is supplied directly.
    """
    document = _document(outputs)
    runtime = NodeRuntime(functions={"function.speak": lambda text: said})
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    return graph.invoke(
        {"question": "say it", "attempts": 0, "decisions": {}, "outputs": {}, "revisions": {}}
    )


class TestTheRunThatWasReported:
    def test_the_published_answer_carries_no_zero_width_run(self) -> None:
        final = _run(f"12 tracks ({ZWSP * 4})")

        assert published_answer(final) == "12 tracks ()"

    def test_a_byte_order_mark_does_not_survive(self) -> None:
        final = _run(f"{BOM}Blue Train | Coltrane")

        assert published_answer(final) == "Blue Train | Coltrane"

    def test_a_neighbouring_answer_is_returned_byte_for_byte(self) -> None:
        clean = "Blue Train | Coltrane [US] | 12 tracks; **source: main.tracks_latest**"
        final = _run(clean)

        assert published_answer(final) == clean

    def test_the_join_of_two_exits_is_cleaned_too(self) -> None:
        """`published_answer` joins when a run finishes at more than one Output.

        The join is the other half of the seam and used to be reachable
        without passing the rule.
        """
        final = _run(f"one{ZWSP}", outputs=2)

        assert ZWSP not in published_answer(final)


class TestWhatIsLeftAlone:
    """Tolerant in reading, strict in trusting — the rule may not eat a script."""

    def test_an_emoji_joiner_sequence_survives(self) -> None:
        family = f"\U0001f468{ZWJ}\U0001f469{ZWJ}\U0001f467"

        assert strip_invisible(family) == (family, 0)

    def test_a_devanagari_non_joiner_survives(self) -> None:
        word = f"क{ZWNJ}्ष"

        assert strip_invisible(word) == (word, 0)

    def test_an_arabic_direction_mark_survives(self) -> None:
        line = "مرحبا‏ 42"

        assert strip_invisible(line) == (line, 0)

    def test_ordinary_whitespace_and_punctuation_are_untouched(self) -> None:
        text = "a\tb\n c — d e"

        assert strip_invisible(text) == (text, 0)


class TestTheDeveloperChannelSaysItHappened:
    def test_it_counts_what_was_removed(self) -> None:
        final = _run(f"12 tracks ({ZWSP * 4})")
        said = " ".join(run_health_from_state(final).silent)

        assert "4" in said
        assert "invisible" in said

    def test_it_publishes_no_positions_and_no_code_points(self) -> None:
        """Counts only, the way a redaction report is counts only."""
        final = _run(f"12 tracks ({ZWSP * 4})")
        said = " ".join(run_health_from_state(final).silent)

        assert ZWSP not in said
        assert "200b" not in said.lower()
        assert "U+" not in said

    def test_a_clean_answer_says_nothing(self) -> None:
        """A channel that speaks on the happy path is one people learn to skip."""
        final = _run("12 tracks")
        said = " ".join(run_health_from_state(final).silent)

        assert "invisible" not in said

    def test_it_is_not_a_failure(self) -> None:
        final = _run(f"12 tracks ({ZWSP * 4})")

        assert run_health_from_state(final).failures == []
