"""The owner's sentence, taken apart into the findings it actually contains.

> *3.5 mins, 4 tool calls, called 3 same tools -> answers one different ->
> answer correct -> move to next execution step*

That reads as one observation and is three detectors and a label
(`a-run-that-teaches/01`). This file pins the two that are findings, the one
that is not, and the label that cannot be computed at all.

**A and B do not share a detector, and the reason is the remedy.** The same
call answered the same way is *waste* — a lap the run did not need, whose fix
is usually a note the agent already had. The same call answered *differently*
is *information*: either the world moved between the calls, which belongs in a
lens declaration, or the tool is non-deterministic. Reporting the second as
waste would delete the interesting case, so they are two names and neither
inherits the other's remedy.

**What the real store said, and it decided two of the rules below.** Run over
the two `runs.sqlite` files this machine actually holds — 39 turns across
`stress-review`, `stress-deep`, `stress-parallel-drop`, `stress-bad-*` and a
private 28-node package:

- **A fired 12 times**, including the instance the owner watched:
  `service_registry {"service": "checkout-api"}`, twice in one `stress-deep`
  run, byte-identical result both times. One `stress-review` run asked
  `service_registry {"service": "ledger-svc"}` **four** times in 78 seconds.
- **B fired zero times** — and three times before the argument rule below,
  every one of them false. That is the whole evidence for it.
- **`RunRecord.statements` was `[]` on all 39 rows**, that package included. It
  is the source the ticket named first and it holds nothing on this machine,
  because it admits only an argument some recogniser accepted as a *statement*.
  So the calls come from the checkpointer, through `read_thread`, and this file
  says so rather than leaving the next reader to rediscover it.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

from openstategraph import run_findings as run_findings_module
from openstategraph.api.audience import Audience
from openstategraph.run_findings import (
    REDUNDANT_TOOL_CALL,
    UNSTABLE_TOOL_RESULT,
    RunFinding,
    grouping_key,
    normalised_arguments,
    run_findings,
)
from openstategraph.run_sinks import RunRecord

THREAD = "run-1"


class _Stub:
    """One stored checkpoint, holding the cumulative message channel."""

    def __init__(self, step: int, messages: list[Any], *, namespace: str = "") -> None:
        self.config = {
            "configurable": {"thread_id": THREAD, "checkpoint_ns": namespace}
        }
        self.checkpoint = {
            "id": f"cp-{step}",
            "ts": f"2026-08-29T16:0{step}:00+00:00",
            "channel_values": {"messages": list(messages)},
            "updated_channels": ["messages"],
        }
        self.metadata = {"step": step, "source": "loop", "workflow_slug": "stress-deep"}
        self.pending_writes = ()


class _Saver:
    """A saver holding exactly these checkpoints, newest first as LangGraph's is."""

    def __init__(self, tuples: list[Any]) -> None:
        self._tuples = list(reversed(tuples))

    def list(self, config: Any, *, limit: int = 200) -> list[Any]:
        return self._tuples[:limit]


def _call(call_id: str, name: str, args: dict[str, Any]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"id": call_id, "name": name, "args": args, "type": "tool_call"}],
    )


def _answer(call_id: str, name: str, text: str) -> ToolMessage:
    return ToolMessage(content=text, tool_call_id=call_id, name=name)


def _thread(*exchanges: tuple[str, str, dict[str, Any], str]) -> list[Any]:
    """A thread whose every superstep asks one tool and gets one answer back.

    The message channel is cumulative — every checkpoint holds the whole
    history — so each step is built from everything before it.
    """
    messages: list[Any] = []
    tuples: list[Any] = []
    for step, (call_id, name, args, result) in enumerate(exchanges):
        messages = [*messages, _call(call_id, name, args)]
        tuples.append(_Stub(step * 2, messages))
        messages = [*messages, _answer(call_id, name, result)]
        tuples.append(_Stub(step * 2 + 1, messages))
    return tuples


def _fanout_thread(
    *exchanges: tuple[str, str, dict[str, Any], str, str]
) -> list[Any]:
    """`_thread`, but each exchange names its own `checkpoint_ns`.

    `kanban-patrol/13`. Each namespace's `messages` channel is cumulative
    **on its own** — a dispatched worker gets a fresh channel, which is what a
    worker *is* (`run_findings.py`'s own module docstring) — so a call in
    namespace `w_trends:1` never appears in namespace `w_trends:2`'s history.
    Building every namespace's own two-step call/answer pair independently,
    then concatenating, gives exactly that shape without pretending fan-out
    workers share a channel they never share in a real run.
    """
    by_namespace: dict[str, list[tuple[str, str, dict[str, Any], str]]] = {}
    for call_id, name, args, result, namespace in exchanges:
        by_namespace.setdefault(namespace, []).append((call_id, name, args, result))

    tuples: list[Any] = []
    step = 0
    for namespace, calls in by_namespace.items():
        messages: list[Any] = []
        for call_id, name, args, result in calls:
            messages = [*messages, _call(call_id, name, args)]
            tuples.append(_Stub(step, messages, namespace=namespace))
            step += 1
            messages = [*messages, _answer(call_id, name, result)]
            tuples.append(_Stub(step, messages, namespace=namespace))
            step += 1
    return tuples


def _record(**overrides: Any) -> RunRecord:
    fields: dict[str, Any] = {
        "kind": "run",
        "at": "2026-08-29T16:09:46+02:00",
        "workflow_slug": "stress-deep",
        "thread_id": THREAD,
        "seconds": 13.002,
        "attempts": 1,
    }
    fields.update(overrides)
    return RunRecord(**fields)


def _findings(
    tuples: list[Any],
    records: list[RunRecord] | None = None,
    *,
    limit: int | None = None,
) -> list[Any]:
    """The findings in these checkpoints, read at the module's own bound.

    `limit` is left unsaid unless a test is about the bound, so every test
    written before `kanban-patrol/11` still exercises the default rather than
    a number this helper chose.
    """
    bound = {} if limit is None else {"limit": limit}
    return run_findings(
        [_Saver(tuples)],
        records if records is not None else [_record()],
        audience=Audience.DEVELOPER,
        **bound,
    )


class TestTheSameCallAnsweredTheSameWay:
    """A, and it is waste."""

    def test_it_is_named_for_the_waste_and_not_for_the_difference(self) -> None:
        found = _findings(
            _thread(
                ("c1", "service_registry", {"service": "checkout-api"}, "owner: payments"),
                ("c2", "service_registry", {"service": "checkout-api"}, "owner: payments"),
            )
        )
        assert [finding.name for finding in found] == [REDUNDANT_TOOL_CALL]
        assert found[0].tool == "service_registry"
        assert found[0].calls == 2
        assert found[0].distinct_results == 1

    def test_one_call_is_not_a_finding(self) -> None:
        assert (
            _findings(
                _thread(("c1", "service_registry", {"service": "checkout-api"}, "owner"))
            )
            == []
        )

    def test_two_different_tools_asked_alike_are_two_calls(self) -> None:
        assert (
            _findings(
                _thread(
                    ("c1", "service_registry", {"service": "a"}, "same"),
                    ("c2", "change_policy", {"service": "a"}, "same"),
                )
            )
            == []
        )


class TestTheSameCallAnsweredDifferently:
    """B, and it is information — the more valuable of the two."""

    def test_it_is_its_own_name_and_carries_every_answer_it_saw(self) -> None:
        found = _findings(
            _thread(
                ("c1", "service_registry", {"service": "ledger-svc"}, "oncall: Ada"),
                ("c2", "service_registry", {"service": "ledger-svc"}, "oncall: Bo"),
            )
        )
        assert [finding.name for finding in found] == [UNSTABLE_TOOL_RESULT]
        assert found[0].distinct_results == 2
        assert len(found[0].result_digests) == 2

    def test_a_run_never_reports_one_pair_as_both(self) -> None:
        found = _findings(
            _thread(
                ("c1", "service_registry", {"service": "a"}, "one"),
                ("c2", "service_registry", {"service": "a"}, "two"),
                ("c3", "change_policy", {"clause": "all"}, "CP-1"),
                ("c4", "change_policy", {"clause": "all"}, "CP-1"),
            )
        )
        assert sorted(finding.name for finding in found) == [
            REDUNDANT_TOOL_CALL,
            UNSTABLE_TOOL_RESULT,
        ]


class TestWhatCountsAsTheSameCall:
    """The rule, and the two things it deliberately misses."""

    def test_key_order_is_not_a_difference(self) -> None:
        assert normalised_arguments('{"a": 1, "b": 2}') == normalised_arguments(
            '{"b": 2, "a": 1}'
        )

    def test_whitespace_is_not_a_difference(self) -> None:
        assert normalised_arguments('{"a":  1}') == normalised_arguments('{"a": 1}')

    def test_list_order_is_a_difference_because_it_is_one(self) -> None:
        assert normalised_arguments('{"a": [1, 2]}') != normalised_arguments(
            '{"a": [2, 1]}'
        )

    def test_a_spelling_the_model_chose_is_a_different_call(self) -> None:
        """What it misses, stated as a test rather than as a paragraph.

        `{"service": "billing-service"}` and `{"service_name": "Billing"}` are
        one question to a person and two calls here. Both are in the real
        store. Closing that gap needs the tool's own schema, and a normaliser
        that guessed would report a run for asking two genuinely different
        things.
        """
        assert normalised_arguments('{"service": "billing"}') != normalised_arguments(
            '{"service_name": "billing"}'
        )

    def test_arguments_that_were_never_recorded_are_not_a_call(self) -> None:
        """The rule the real store bought, and it cost three false findings.

        `_ToolCallReader` reports a `ToolMessage` whose request is gone with no
        arguments at all — a truncated history, or a thread joined mid-run.
        Grouped on `""` those calls are "the same call" by construction, and
        their results differ because they answered different questions. Every
        B on this machine's two stores was one of these, and all three
        disappear when an unknown argument stops counting as a known one.
        """
        messages: list[Any] = [
            _answer("gone-1", "service_registry", "checkout-api"),
            _answer("gone-2", "service_registry", "ledger-svc"),
        ]
        tuples = [_Stub(0, messages[:1]), _Stub(1, messages)]
        assert _findings(tuples) == []


class TestHowLongItTookIsNotAFinding:
    """C, argued rather than shipped.

    `launch-readiness/109` measured 97-99% of a turn as model latency the owner
    chose — 14.02 s wall against 0.14 s of ours. A detector reporting *the
    model was slow* fires every night and names nothing anyone can fix.

    A per-workflow baseline is the only honest form and the real store cannot
    carry one: `stress-review` spans 7.35 s to 78.40 s over six runs (10.7x),
    `stress-parallel-drop` 2.20 s to 7.34 s over eleven (3.3x). An outlier rule
    over that spread reports the spread.

    So duration survives where the owner put it — attached to the observation,
    as the size of what the waste cost — and never as an alarm of its own.
    """

    def test_no_finding_is_named_for_a_duration(self) -> None:
        found = _findings(
            _thread(
                ("c1", "service_registry", {"service": "a"}, "same"),
                ("c2", "service_registry", {"service": "a"}, "same"),
            ),
            [_record(seconds=3600.0)],
        )
        assert {finding.name for finding in found} == {REDUNDANT_TOOL_CALL}

    def test_a_slow_run_with_nothing_repeated_says_nothing(self) -> None:
        assert (
            _findings(
                _thread(("c1", "service_registry", {"service": "a"}, "one")),
                [_record(seconds=3600.0, attempts=9)],
            )
            == []
        )

    def test_the_duration_rides_on_the_finding_it_explains(self) -> None:
        found = _findings(
            _thread(
                ("c1", "service_registry", {"service": "a"}, "same"),
                ("c2", "service_registry", {"service": "a"}, "same"),
            ),
            [_record(seconds=78.404, attempts=3)],
        )
        assert found[0].runs[0].seconds == 78.404
        assert found[0].runs[0].attempts == 3
        assert found[0].thread_tool_calls == 2


class TestWhoMayReadOne:
    """A finding quotes machinery, so it inherits the boundary that gates it."""

    def test_the_audience_has_no_default(self) -> None:
        parameter = inspect.signature(run_findings).parameters["audience"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty

    def test_a_customer_is_told_nothing_rather_than_told_less(self) -> None:
        tuples = _thread(
            ("c1", "service_registry", {"service": "a"}, "same"),
            ("c2", "service_registry", {"service": "a"}, "same"),
        )
        assert (
            run_findings([_Saver(tuples)], [_record()], audience=Audience.CUSTOMER) == []
        )

    def test_the_result_is_never_quoted_back(self) -> None:
        """A digest proves the equality; the text is the customer's data."""
        found = _findings(
            _thread(
                ("c1", "service_registry", {"service": "a"}, "owner: payments-team"),
                ("c2", "service_registry", {"service": "a"}, "owner: payments-team"),
            )
        )
        rendered = found[0].model_dump_json()
        assert "payments-team" not in rendered
        assert found[0].result_digests


class TestItReadsAndOnlyReads:
    def test_the_module_can_neither_delete_nor_export(self) -> None:
        """`run_sinks` is under this assertion and a reader of it inherits it.

        The store is local by default and no network exporter ships at all —
        absent, not disabled. A detector is the first thing anybody would be
        tempted to hang one off, so the refusal is pinned at the detector too.
        """
        source = inspect.getsource(
            __import__("openstategraph.run_findings", fromlist=["x"])
        ).lower()
        for forbidden in (
            "delete",
            "drop ",
            "vacuum",
            "prune",
            "sweep",
            "expire",
            "purge",
            "import requests",
            "import httpx",
            "import urllib",
        ):
            assert forbidden not in source, forbidden


class TestNothingFoundIsAnAnswer:
    def test_a_thread_the_savers_do_not_hold_is_silence(self) -> None:
        assert run_findings([_Saver([])], [_record()], audience=Audience.DEVELOPER) == []

    def test_a_row_with_no_thread_is_skipped_rather_than_guessed_at(self) -> None:
        assert (
            run_findings(
                [_Saver(_thread(("c1", "t", {"a": 1}, "x"), ("c2", "t", {"a": 1}, "x")))],
                [_record(thread_id="")],
                audience=Audience.DEVELOPER,
            )
            == []
        )


class _ProviderCall:
    """A tool call whose arguments arrived as the provider's own string.

    `api/threads._call_field` reads a tool call off *"a provider object with
    attributes"* as well as off a `dict`, in its own words — so the arguments
    this module is handed are not always something `AIMessage` validated into a
    `dict`. `AIMessage` refuses a string `args`; this shape is what the reader
    documents itself as also accepting, and it is the shape through which a
    whitespace-only argument reaches the grouping.
    """

    def __init__(self, call_id: str, name: str, arguments: Any) -> None:
        self.content = ""
        self.tool_calls = [
            {"id": call_id, "name": name, "args": arguments, "type": "tool_call"}
        ]


def _raw_thread(*exchanges: tuple[str, str, Any, str]) -> list[Any]:
    """`_thread`, but the arguments are passed through exactly as given."""
    messages: list[Any] = []
    tuples: list[Any] = []
    for step, (call_id, name, arguments, result) in enumerate(exchanges):
        messages = [*messages, _ProviderCall(call_id, name, arguments)]
        tuples.append(_Stub(step * 2, messages))
        messages = [*messages, _answer(call_id, name, result)]
        tuples.append(_Stub(step * 2 + 1, messages))
    return tuples


class TestTheKeyIsTheGuard:
    """`the-cost-of-one-more/09`. The empty argument came back, one line below
    the guard written to refuse it.

    The rule that *an argument we do not know is not an argument* was enforced
    on the **raw** string while the key was built from the **normalised** one.
    Everything that is truthy and normalises to nothing therefore walked
    through: `'   '`, `'\\t\\n'`, and every other whitespace spelling. That is
    the same collapse the three false B findings were bought to end,
    reconstituted by the line underneath.

    The fix is not a second copy of the guard — two doors into one grouping
    with one of them watched is the shape this repository names as the defect
    one level up. The guard is inside the key, and the census below is what
    keeps it the only door.
    """

    def test_two_whitespace_calls_of_one_tool_are_not_one_call(self) -> None:
        """The red test: truthy arguments, empty key, unrelated calls."""
        assert (
            _findings(
                _raw_thread(
                    ("c1", "service_registry", "   ", "owner: payments"),
                    ("c2", "service_registry", "\t\n", "owner: ledger"),
                )
            )
            == []
        )

    def test_the_key_refuses_every_string_that_identifies_no_call(self) -> None:
        for arguments in ("", "   ", "\t\n", "\n\n", " \t "):
            assert grouping_key("service_registry", arguments) is None, arguments

    def test_a_tool_called_twice_with_no_arguments_is_a_real_repeat(self) -> None:
        """The one collapse that is deliberate, and it was nowhere written down.

        `{}` is *this tool takes no arguments and the run asked it twice* — a
        known argument, and waste. An empty **string** is *we do not know what
        it was asked*. They looked identical to the old guard and they are two
        different facts.
        """
        assert grouping_key("clock", "{}") == ("clock", "{}")
        assert grouping_key("clock", "{ }") == grouping_key("clock", "{}")

        found = _findings(
            _thread(
                ("c1", "clock", {}, "12:00"),
                ("c2", "clock", {}, "12:00"),
            )
        )
        assert [finding.name for finding in found] == [REDUNDANT_TOOL_CALL]

    def test_two_long_arguments_of_one_length_are_not_the_same_call(self) -> None:
        """`_cap`'s `(+N chars)` disambiguates only values of *different* lengths.

        Two arguments that share their first 4,000 characters and their length
        render identically, and were reported as one call answered two ways —
        a false B, aimed at the largest payloads a run makes.
        """
        shared = "a" * 4200
        assert (
            _findings(
                _raw_thread(
                    ("c1", "query", '{"q": "' + shared + 'X"}', "17 rows"),
                    ("c2", "query", '{"q": "' + shared + 'Y"}', "3 rows"),
                )
            )
            == []
        )

    def test_the_marker_it_refuses_is_the_one_the_cap_actually_writes(self) -> None:
        """Recognised by shape, so pin the shape against the thing that makes it.

        This module reads a display projection to do analysis; it asks
        `api/threads` for nothing and matches the tail `_cap` appends. That is
        a copy of a decision made elsewhere, so it is pinned to the decision
        rather than to a paragraph — the day the marker changes, this is red
        instead of the detector quietly recognising nothing.
        """
        from openstategraph.api import threads

        capped = threads._cap("z" * 100_000)

        assert capped != "z" * 100_000
        assert run_findings_module._TRUNCATED.search(capped)
        assert not run_findings_module._TRUNCATED.search("z" * 10)

    def test_the_module_builds_a_grouping_key_in_exactly_one_place(self) -> None:
        """The census, which is what makes "no second door" a fact.

        A guard beside the key was correct on the day it was written and was
        bypassed by the next line. So the question this asks is not *is the
        guard right* but *how many places build a key at all* — and the answer
        must be one. `normalised_arguments` is the thing a key is made of, so
        every call to it in this module is counted, and every one must be
        inside `grouping_key`.
        """
        import ast

        source = Path(run_findings_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)

        doors = [
            function.name
            for function in ast.walk(tree)
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "normalised_arguments"
        ]

        assert doors == ["grouping_key"], (
            f"a grouping key is built in {sorted(set(doors))} — every guard "
            "written at one of those call sites is a guard the others walk past"
        )

    def test_a_refused_call_is_still_counted_as_a_call_the_run_made(self) -> None:
        """Refusing to group is not refusing to have happened.

        `thread_tool_calls` is what the conversation cost. A call whose
        arguments this module cannot read still cost a lap.
        """
        found = _findings(
            _raw_thread(
                ("c1", "service_registry", {"service": "a"}, "same"),
                ("c2", "service_registry", {"service": "a"}, "same"),
                ("c3", "service_registry", "   ", "unrelated"),
            )
        )
        assert [finding.name for finding in found] == [REDUNDANT_TOOL_CALL]
        assert found[0].calls == 2
        assert found[0].thread_tool_calls == 3


#: A bound small enough that a hand-written thread can be driven past it, and
#: a fixture on each side of it. `_BOUND` keeps the newest six checkpoints, so
#: `_OLDER` + `_DUPLICATE` (ten checkpoints) is a bounded read and `_DUPLICATE`
#: alone (four) is a complete one. Both hold the same repeat, so the finding
#: they produce is the same finding — which is the whole point.
_BOUND = 6

_OLDER: tuple[tuple[str, str, dict[str, Any], str], ...] = (
    ("c1", "change_policy", {"clause": "one"}, "CP-1"),
    ("c2", "change_policy", {"clause": "two"}, "CP-2"),
    ("c3", "change_policy", {"clause": "three"}, "CP-3"),
)

_DUPLICATE: tuple[tuple[str, str, dict[str, Any], str], ...] = (
    ("c4", "service_registry", {"service": "checkout-api"}, "owner: payments"),
    ("c5", "service_registry", {"service": "checkout-api"}, "owner: payments"),
)


class TestAFindingSaysWhetherTheThreadWasBounded:
    """`kanban-patrol/11`. A finding read from a fifth of a thread was shaped
    exactly like one read from all of it.

    `read_thread` keeps the **newest** `limit` checkpoints and it does say so
    — `the-cost-of-one-more/06` put a `ThreadTruncation` on the response for
    precisely this reason. `_findings_in` never read it. So the two states
    arrived at a consumer identical, and a consumer receives findings rather
    than the read that produced them.

    Measured on `089c23a7-a610-4e29-a75c-f876636db06c`, a real thread of 346
    checkpoints in this checkout's checkpointer, and re-run against it before
    this test was written:

    | | `limit=200` (the default) | `limit=2000` |
    | --- | --- | --- |
    | steps read | 200 | 346 |
    | tool calls seen | 89 | 133 |
    | findings emitted | 8 | 9 |
    | `thread_tool_calls` reported | 89 | 133 |

    A third of the evidence invisible, one finding lost outright, and the only
    cost figure a card could quote understated by 44 — with nothing on any of
    the eight findings to say the read had been cut. `calls=10` against a true
    figure of 15 is not a rounding error, it is a false statement about
    somebody's run.

    The remedy is the one this product already chose for a gate judging an
    answer against evidence it could only partly see: **disclose that it could
    not see everything.** Not *guess at the rest*, and not *raise the number* —
    the ticket takes no position on the default and neither does this file.
    """

    def test_a_thread_read_past_the_bound_is_distinguishable_from_one_under_it(
        self,
    ) -> None:
        """The red one. Both threads hold the same repeat; only one was cut.

        The two findings agree on every field a reader would act on — same
        name, same tool, same arguments, same `calls`, same digests — because
        the repeat itself is inside the window either way. That agreement is
        the defect stated as an assertion: nothing in the shape of the first
        one says it was assembled from a window rather than from a run.
        """
        bounded = _findings(_thread(*_OLDER, *_DUPLICATE), limit=_BOUND)
        whole = _findings(_thread(*_DUPLICATE), limit=_BOUND)

        assert [finding.name for finding in bounded] == [REDUNDANT_TOOL_CALL]
        assert [finding.name for finding in whole] == [REDUNDANT_TOOL_CALL]
        assert (bounded[0].tool, bounded[0].arguments, bounded[0].calls) == (
            whole[0].tool,
            whole[0].arguments,
            whole[0].calls,
        )
        assert bounded[0].result_digests == whole[0].result_digests

        assert bounded[0].truncation is not None
        assert whole[0].truncation is None

    def test_the_bound_that_applied_rides_on_the_finding(self) -> None:
        """*Whether* and *at what limit*, both on the finding itself.

        Spelled key by key rather than by presence: the day this structure
        gains a key nobody meant to publish, this is red rather than quietly
        wider.
        """
        bounded = _findings(_thread(*_OLDER, *_DUPLICATE), limit=_BOUND)
        truncation = bounded[0].truncation

        assert truncation is not None
        assert truncation.model_dump() == {
            "kept": _BOUND,
            "end": "oldest",
            "limit": _BOUND,
            "message": truncation.message,
        }
        assert truncation.limit == _BOUND
        assert truncation.kept == _BOUND
        assert truncation.end == "oldest"
        assert truncation.message

    def test_the_finding_repeats_the_read_s_verdict_rather_than_deciding_one(
        self,
    ) -> None:
        """One fact, computed once — the census, not the paragraph.

        `read_thread` already knows it was cut; it reads one row past its own
        bound to find out. A second opinion assembled here from `len(steps)`
        and `limit` would be a second answer to a question that has one, and
        two computations of one fact are how they come to disagree. So the
        finding carries the object `read_thread` returned, and this counts the
        places that could have built a different one.
        """
        import ast

        source = Path(run_findings_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)

        built = [
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ThreadTruncation"
        ]
        assert built == [], (
            "a truncation is constructed in this module — the read that "
            "already computed one is one function call away"
        )

        read = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr == "truncation"
            and isinstance(node.ctx, ast.Load)
        ]
        assert len(read) == 1, (
            f"the read's truncation is consulted in {len(read)} places — one "
            "of them will one day be the stale one"
        )

    def test_the_marker_it_carries_is_the_one_the_read_actually_returned(
        self,
    ) -> None:
        """Pinned to the decision, not to a copy of it.

        The same savers, the same thread, the same bound — through the reader
        directly, and through the detector. Whatever `read_thread` says about
        the window is what the finding says, down to the sentence.
        """
        from openstategraph.api.threads import read_thread

        tuples = _thread(*_OLDER, *_DUPLICATE)
        history = read_thread(
            [_Saver(tuples)], THREAD, audience=Audience.DEVELOPER, limit=_BOUND
        )

        assert history is not None
        assert history.truncation is not None
        assert _findings(tuples, limit=_BOUND)[0].truncation == history.truncation

    def test_a_complete_read_is_null_rather_than_a_row_of_zeroes(self) -> None:
        """A truncation of nothing is not a truncation.

        `_truncation` returns `None` on a complete read for the reason it
        gives about durations: *is this field true* is the reading everybody
        will write, and a zeroed row answers yes.
        """
        assert _findings(_thread(*_DUPLICATE), limit=_BOUND)[0].truncation is None

    def test_a_finding_still_defaults_to_every_field_it_had(self) -> None:
        """The additive test. A new field may not move an old one.

        A finding is read by a scheduled agent that was written against the
        shape before this ticket, so the defaults are spelled out whole: an
        unset marker reads as *nothing claimed*, not as *complete*, and every
        other field still starts where it started.
        """
        assert RunFinding(name=REDUNDANT_TOOL_CALL).model_dump() == {
            "name": REDUNDANT_TOOL_CALL,
            "thread_id": "",
            "workflow_slug": "",
            "tool": "",
            "arguments": "",
            "calls": 0,
            "distinct_results": 0,
            "result_digests": [],
            "checkpoints": [],
            "thread_tool_calls": 0,
            "distinct_namespaces": 0,
            "runs": [],
            "truncation": None,
        }

    def test_the_name_is_still_an_open_string(self) -> None:
        """The rule this change was not allowed to break.

        `name` is deliberately not an enum: a consumer meeting a name it does
        not know must skip that finding rather than fail to parse the list it
        arrived in. Adding a field is exactly the moment somebody tidies that
        into an enum, so it is pinned here beside the addition.
        """
        finding = RunFinding(name="a-detector-nobody-has-written-yet")
        assert finding.name == "a-detector-nobody-has-written-yet"
        assert finding.truncation is None


class TestACardCannotTellWorkersApartFromRepeats:
    """`kanban-patrol/13`. `calls=19` alone cannot say which of two very
    different things happened:

    - One node called the same tool nineteen times in sequence. Waste — the
      remedy is a note the agent already had.
    - Nineteen parallel fan-out workers each called it once. Not waste in the
      same sense — the run paid for it, but the remedy, if any, is a shared
      lookup *across* workers, not a tool note.

    Today `RunFinding` cannot distinguish the two: nothing on it says *where*
    a call happened, only that it happened. **The red test, confirmed before
    the fix**: both threads below produced findings that were identical apart
    from checkpoint ids — same `tool`, same `arguments`, same `calls=19`, same
    `distinct_results`, same digests. `distinct_namespaces` is the fix: `1` for
    nineteen calls in one namespace, `19` for nineteen calls in nineteen
    sibling namespaces — while `calls` stays `19` in both, because pooling
    itself is unchanged (`run_findings.py:99`).
    """

    def test_nineteen_sequential_calls_in_one_namespace_is_one_namespace(self) -> None:
        exchanges = tuple(
            (f"c{i}", "sql_list_tables", {"schema": "public"}, "same-rows")
            for i in range(19)
        )
        found = _findings(_thread(*exchanges))

        assert [finding.name for finding in found] == [REDUNDANT_TOOL_CALL]
        assert found[0].calls == 19
        assert found[0].distinct_namespaces == 1

    def test_nineteen_sibling_workers_each_calling_once_is_nineteen_namespaces(
        self,
    ) -> None:
        exchanges = tuple(
            (
                f"c{i}",
                "sql_list_tables",
                {"schema": "public"},
                "same-rows",
                f"w_trends:{i}",
            )
            for i in range(19)
        )
        found = _findings(_fanout_thread(*exchanges))

        assert [finding.name for finding in found] == [REDUNDANT_TOOL_CALL]
        assert found[0].calls == 19
        assert found[0].distinct_namespaces == 19

    def test_the_two_shapes_differ_only_in_the_shape_and_nothing_else(self) -> None:
        """Same tool, same arguments, same result, same count — the only
        thing this ticket says must differ, and nothing else may."""
        sequential = _findings(
            _thread(
                *(
                    (f"c{i}", "sql_list_tables", {"schema": "public"}, "same-rows")
                    for i in range(19)
                )
            )
        )[0]
        fanout = _findings(
            _fanout_thread(
                *(
                    (
                        f"c{i}",
                        "sql_list_tables",
                        {"schema": "public"},
                        "same-rows",
                        f"w_trends:{i}",
                    )
                    for i in range(19)
                )
            )
        )[0]

        assert sequential.tool == fanout.tool
        assert sequential.arguments == fanout.arguments
        assert sequential.calls == fanout.calls == 19
        assert sequential.distinct_results == fanout.distinct_results
        assert sequential.result_digests == fanout.result_digests
        assert sequential.distinct_namespaces != fanout.distinct_namespaces
        assert (sequential.distinct_namespaces, fanout.distinct_namespaces) == (1, 19)

    def test_some_fan_out_some_real_repetition_is_the_in_between_reading(
        self,
    ) -> None:
        """Nineteen calls, three namespaces — not pure fan-out, not a pure
        sequential repeat. `distinct_namespaces` says exactly that: `3`."""
        exchanges = tuple(
            (
                f"c{i}",
                "sql_list_tables",
                {"schema": "public"},
                "same-rows",
                f"w_trends:{i % 3}",
            )
            for i in range(19)
        )
        found = _findings(_fanout_thread(*exchanges))

        assert found[0].calls == 19
        assert found[0].distinct_namespaces == 3
