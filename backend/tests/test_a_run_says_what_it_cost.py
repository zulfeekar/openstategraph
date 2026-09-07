"""What a run cost reaches the wire — `memory-and-replay` 56.

`token` frames carried `usage`, developer-only, **per chunk**. No frame carried
a total. A client that wanted "what did this run cost" had to sum every token
frame it saw, which is wrong if it joined late, wrong if it reconnected, and —
the pointed half — **impossible for a failed run**, because `error` carried
`threadId` and `detail` and nothing else. The tokens spent before a failure are
the ones a reader most wants counted.

Reproduced live on `stress-review` (2026-08-29, `ollama:gpt-oss:120b-cloud`):
377 frames, 300 of them `token`, and the terminal `done` frame's keys were
`threadId, answer, decisions, routes, outputs, nested, attempts, mermaid,
publishedRejected, developer` plus the clock. No usage anywhere.

## The four decisions

**A field, not a fourth frame kind.** 54 refused a second child-ending kind
because `error` is terminal for the whole run and a rule with an exception in
it is worse than a value; the same argument forbids a `usage` frame here from
the other direction. A frame *after* the terminal frame would break the
protocol guarantee that exactly one of `TERMINAL_EVENTS` is last, and one
*before* it would be a frame a client that stops at the ending never sees.

**On all three terminal frames, not two.** AG-UI names `RUN_FINISHED` and
`RUN_ERROR`; we have a third, `interrupt`, because a paused run is a real
LangGraph checkpoint here and not a finished run (49 records that as one of the
three things we have that they do not). A paused run has spent tokens too, and
"the terminal frame carries the cost, except that one" is exactly the rule with
an exception in it that 54 refused.

**A measurement, not a sum.** `run_turn` already enters LangChain's
`get_usage_metadata_callback` for the whole turn, so the numbers are the
provider's own, keyed by model — including model calls whose chunks never
produced a `token` frame at all. Summing the frames would be the same
arithmetic done in a worse place, and it would miss those.

**A list, because a run can use more than one model.** A grader on one
provider and an agent on another have two prices, and one summed integer hides
that. The list also cannot be mistaken for `token.usage`, which is one
message's flat object: same word, two frames, two shapes a typed client keeps
apart.

## The audience

`docs/api.md` promises, in writing, that a customer's stored `tokens` reads
*"`null`, always, exactly as `usage` is on a customer's stream"*. A run total
that leaked past that would be a regression on a promise, so it does not: a
customer's terminal frame carries `usage: null`, which is the shape
`token.usage` has carried them all along. The key is present rather than
absent, for the reason `progress.detail` is — otherwise "not for you" and "no
model was called" would be one wire shape, and the second is `[]`.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from conftest import ScriptedGraph, drive_fold

from openstategraph.compile.diagnostics import CompileDiagnostics

from openstategraph.api.audience import Audience, run_usage
from openstategraph.api.streaming import FRAME_FIELDS, TERMINAL_EVENTS, _stream_run


# --------------------------------------------------------------------------
# The vocabulary


def test_every_terminal_frame_declares_the_cost() -> None:
    for name in TERMINAL_EVENTS:
        assert "usage" in FRAME_FIELDS[name], name


def test_no_fourth_terminal_kind_was_invented() -> None:
    assert TERMINAL_EVENTS == ("done", "interrupt", "error")
    assert "usage" not in FRAME_FIELDS["update"]


# --------------------------------------------------------------------------
# The shape


_SPENT = {
    "gpt-oss:120b-cloud": {"input_tokens": 1436, "output_tokens": 86, "total_tokens": 1522},
    "claude-haiku": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
}


def test_a_developer_is_given_one_row_per_model() -> None:
    assert run_usage(_SPENT, Audience.DEVELOPER) == [
        {"model": "claude-haiku", "inputTokens": 12, "outputTokens": 3, "totalTokens": 15},
        {
            "model": "gpt-oss:120b-cloud",
            "inputTokens": 1436,
            "outputTokens": 86,
            "totalTokens": 1522,
        },
    ]


def test_the_rows_are_ordered_so_two_recordings_of_one_run_agree() -> None:
    assert [row["model"] for row in run_usage(_SPENT, Audience.DEVELOPER) or []] == sorted(_SPENT)


def test_a_run_that_called_no_model_says_so_rather_than_saying_nothing() -> None:
    """`[]` is a measurement — nobody spent anything. `null` is the audience
    boundary. Collapsing them would make an input-only workflow look like a
    customer."""
    assert run_usage({}, Audience.DEVELOPER) == []


def test_a_customer_reads_null_exactly_as_the_guide_promises() -> None:
    assert run_usage(_SPENT, Audience.CUSTOMER) is None


def test_a_malformed_provider_report_costs_its_own_row_and_not_the_run() -> None:
    """Provider metadata is third-party data — `TokenUsage`'s own rule. A
    number that cannot be read is zero here, never an exception on the one
    frame a client is waiting for."""
    rows = run_usage({"weird": {"input_tokens": "lots"}, "fine": {"total_tokens": 4}},
                     Audience.DEVELOPER)

    assert rows == [
        {"model": "fine", "inputTokens": 0, "outputTokens": 0, "totalTokens": 4},
        {"model": "weird", "inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
    ]


def test_a_reading_that_is_not_a_mapping_at_all_is_skipped() -> None:
    assert run_usage({"odd": None}, Audience.DEVELOPER) == []


# --------------------------------------------------------------------------
# On the wire


class _Graph:
    def __init__(self, chunks: list[Any], *, explode: bool = False) -> None:
        self._chunks = chunks
        self._explode = explode

    def stream(self, *_args: Any, **_kwargs: Any) -> Any:
        if self._explode:

            def boom() -> Any:
                raise RuntimeError("the graph died")
                yield  # pragma: no cover

            return boom()
        return iter(self._chunks)

    def get_state(self, _config: Any) -> Any:
        return SimpleNamespace(next=(), tasks=())

    def get_graph(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(draw_mermaid=lambda: "graph TD;")


def _frames(
    chunks: list[Any], audience: Any = None, *, explode: bool = False
) -> list[tuple[str, dict[str, Any]]]:
    raw = drive_fold(
        _stream_run(
            ScriptedGraph(_Graph(chunks, explode=explode)),
            {"question": "q"},
            {"configurable": {"thread_id": "t"}},
            SimpleNamespace(warnings=[]),
            {"in1": "in1"},
            SimpleNamespace(diagnostics=CompileDiagnostics()),
            "t",
            audience or Audience.DEVELOPER,
        )
    )
    out: list[tuple[str, dict[str, Any]]] = []
    for frame in raw:
        name = frame.split("event: ", 1)[1].split("\n", 1)[0]
        out.append((name, json.loads(frame.split("data: ", 1)[1])))
    return out


_ONE_STEP = [((), "updates", {"in1": {"outputs": {"in1": "hello"}}})]


def test_the_finished_run_reports_its_cost() -> None:
    done = next(p for name, p in _frames(_ONE_STEP) if name == "done")

    assert done["usage"] == []


def test_the_failed_run_reports_its_cost_too() -> None:
    """The half we would most have been tempted to skip. A run that died has
    still been paid for."""
    frames = _frames([], explode=True)
    error = next(p for name, p in frames if name == "error")

    assert "usage" in error
    assert error["usage"] == []


def test_a_customer_is_told_nothing_about_what_the_run_cost() -> None:
    for name, payload in _frames(_ONE_STEP, Audience.CUSTOMER):
        if name in TERMINAL_EVENTS:
            assert payload["usage"] is None, name


def test_a_customers_failed_run_is_priced_at_null_as_well() -> None:
    error = next(p for name, p in _frames([], Audience.CUSTOMER, explode=True) if name == "error")

    assert error["usage"] is None
