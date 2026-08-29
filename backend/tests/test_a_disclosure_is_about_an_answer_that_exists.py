"""`launch-readiness/155`: a disclosure attached to an answer never given.

A live `cpl-mcp` run of 2026-08-28 did not answer. It asked the user which
sense of *"Persian Gulf"* they meant — location or transit — and the run's
answer then ended with `_output`'s disclosure paragraph:

    You asked for "persian gulf". This data holds no such value, so the answer
    **above is for** Middle East Gulf (MEG) on
    `cargoflow_latest.load_shipping_region_v2` …

There is no answer above. The paragraph asserts a substitution was applied to
a result that does not exist, and it does so in the one place `127` built to be
trustworthy.

## The fact the sentence is chosen by

`resolve.vocabulary` mints the `Substitution` when it **resolves the word**,
before the model runs, and nothing between there and `_output` asked whether
the run went on to *use* the resolution. The record was honest about the
resolver and dishonest about the answer.

The check cannot be "did the model use it" — `127`'s whole argument is that the
disclosure is not the model's to forget — and it cannot be a search of the
prose for the canonical value, which the live non-answer contains anyway
(*"location → MEG"*). The evidence for *"the answer is for this value"* is a
**statement carrying it**, and `counted_rows.exchanges_in` already holds every
statement a run executed, on both rails.

Two live runs on `cpl-mcp`, 2026-08-29, are why it is that and not "did any
tool run". The first called no tool at all; the second called two and queried
neither axis, and both published *"the answer above is for Middle East Gulf
(MEG) on `cargoflow_latest.load_shipping_region_v2`"* over a refusal. A
tool-ran check passes the second.

It is measured **per value**, because one word resolves on two axes here at
once — a shipping region and a chokepoint geofence — and a run that queried one
of them was disclosed as being *"for"* both.

`NO_ANSWER_PRODUCED` is the neighbouring case and was already handled; this is
the *non-empty non-answer*, which looks like a success to every other check.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from openstategraph.abc import tool_notes
from openstategraph.abc.tool_notes import Substitution, record_notes, take_notes
from openstategraph.compile.node_runtime import NodeRuntime
from openstategraph.compile.workflow_compiler import (
    CompiledPlan,
    values_no_statement_carried,
)
from openstategraph.counted_rows import statement_was_answered

THREAD = "155-thread"

#: What the live run actually said instead of answering.
CLARIFYING_NON_ANSWER = (
    'Which sense of "Persian Gulf" do you mean? Tell me which sense you want '
    "(location → MEG; transit → persian-gulf-entry) and I will run it."
)


@pytest.fixture(autouse=True)
def _a_run_to_record_against(monkeypatch: pytest.MonkeyPatch) -> Any:
    take_notes(THREAD)
    monkeypatch.setattr(tool_notes, "_current_thread", lambda: THREAD)
    yield
    take_notes(THREAD)


def _output_run(answer: str, tool_use: dict[str, Any] | None = None) -> dict[str, Any]:
    runtime = NodeRuntime(model=None)
    document = {
        "nodes": [
            {"id": "a1", "type": "agent.llm", "data": {}},
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "a1", "portId": "result"},
                "target": {"nodeId": "out1", "portId": "result"},
            }
        ],
    }
    plan = CompiledPlan(nodes=["a1", "out1"], edges=[("a1", "out1")], conditional={})
    run = runtime.factory(document)("out1", document["nodes"][1], plan)
    state: dict[str, Any] = {"outputs": {"a1": answer}, "answer": "", "question": "q"}
    if tool_use is not None:
        state["tool_use"] = tool_use
    return run(state)


def _meg() -> Substitution:
    return Substitution(
        user_term="persian gulf",
        axis="load_shipping_region_v2",
        canonical_value="Middle East Gulf (MEG)",
        how_matched="declared_synonym",
    )


#: An agent holding the CPL MCP tools that queried nothing — the live shape of
#: both 2026-08-29 runs, one of which had called two tools all the same.
NOTHING_QUERIED: dict[str, Any] = {
    "a1": {"bound": ["mcp_execute_sql"], "ran": ["mcp_list_sources"], "queries": []}
}
#: The shape three live runs of 2026-08-29 actually produced: the statement
#: *was* sent, carried the value, and the warehouse answered `{"ok": false}` —
#: an invalid column — after which the agent refused. The Python repr of MCP
#: content blocks is verbatim what `tool_report` records.
#: What the warehouse actually answered, wrapped the way an MCP tool's content
#: reaches `tool_report` — a Python **repr** of the content blocks, which is
#: `str(message.content)` and not JSON. Built with `repr` rather than typed out
#: so the fixture cannot drift from the shape the runtime records.
_FAILED_RESULT = repr(
    [
        {
            "type": "text",
            "text": json.dumps(
                {
                    "ok": False,
                    "error_code": "internal_error",
                    "message": "[42S22] Invalid column name 'sea_temperature'.",
                }
            ),
        }
    ]
)

#: The same payload as the record actually keeps it: `tool_report` caps a
#: result at 2 000 characters and an ODBC message is longer, so the repr
#: arrives cut mid-string and no parser will take it. Three live refusals on
#: 2026-08-29 were all this shape, and a fixture that parses cleanly would have
#: let the fix through while the live runs stayed wrong.
_TRUNCATED_FAILURE = _FAILED_RESULT[:120]

STATEMENT_TRUNCATED: dict[str, Any] = {
    "a1": {
        "bound": ["mcp_execute_sql"],
        "ran": ["mcp_execute_sql"],
        "queried": ["mcp_execute_sql"],
        "queries": [
            {
                "sql": "SELECT AVG(sea_temperature) FROM sm.cargoflow_latest WHERE "
                "load_shipping_region_v2 = 'Middle East Gulf (MEG)'",
                "result": _TRUNCATED_FAILURE,
            }
        ],
    }
}

STATEMENT_FAILED: dict[str, Any] = {
    "a1": {
        "bound": ["mcp_execute_sql"],
        "ran": ["mcp_execute_sql"],
        "queried": ["mcp_execute_sql"],
        "queries": [
            {
                "sql": "SELECT AVG(sea_temperature) FROM sm.cargoflow_latest WHERE "
                "load_shipping_region_v2 = 'Middle East Gulf (MEG)'",
                "result": _FAILED_RESULT,
            }
        ],
    }
}

#: The same agent, having actually filtered on the canonical value.
MEG_QUERIED: dict[str, Any] = {
    "a1": {
        "bound": ["mcp_execute_sql"],
        "ran": ["mcp_execute_sql"],
        "queries": [
            {
                "sql": "SELECT port FROM cargoflow_latest WHERE "
                "load_shipping_region_v2 = 'Middle East Gulf (MEG)'",
                "result": "68 rows",
            }
        ],
    }
}


class TestARunThatAnsweredNothing:
    def test_does_not_tell_the_reader_what_the_answer_above_was_for(self) -> None:
        record_notes((_meg(),))
        answer = _output_run(CLARIFYING_NON_ANSWER, NOTHING_QUERIED)["answer"]
        assert "the answer above is for" not in answer

    def test_still_says_what_the_word_was_taken_to_mean(self) -> None:
        """The disclosure is not withdrawn — `127` still holds. Only the claim
        about a result that does not exist is."""
        record_notes((_meg(),))
        answer = _output_run(CLARIFYING_NON_ANSWER, NOTHING_QUERIED)["answer"]
        assert "persian gulf" in answer
        assert "Middle East Gulf (MEG)" in answer
        assert "a synonym this data declares for it" in answer

    def test_says_what_was_measured_rather_than_what_did_not_happen(self) -> None:
        """`UncoveredWindow`'s property: the clause is checkable. This one can
        only see statements, so *"nothing came from that data"* — a claim about
        every rail there is — is not the sentence it may make."""
        record_notes((_meg(),))
        answer = _output_run(CLARIFYING_NON_ANSWER, NOTHING_QUERIED)["answer"]
        assert "No statement this run ran carried that value" in answer

    def test_the_model_naming_the_canonical_value_does_not_settle_it(self) -> None:
        """The live non-answer contains "MEG" — so a search of the prose for
        the canonical value would have passed this run, which is why the fact
        is read off the record instead."""
        assert "MEG" in CLARIFYING_NON_ANSWER
        record_notes((_meg(),))
        answer = _output_run(CLARIFYING_NON_ANSWER, NOTHING_QUERIED)["answer"]
        assert "the answer above is for" not in answer


class TestAStatementNobodyAnswered:
    """The shape every live refusal took, and the one a fixture would not have.

    The value **was** sent — so "did any statement carry it" passes — and the
    warehouse answered `{"ok": false}`. `cells_of`'s settled rule is that such
    a payload contributes nothing at all, which is the same sentence read one
    layer up: a statement nobody answered is not a result.
    """

    def test_a_failed_statement_is_not_evidence_of_an_answer(self) -> None:
        record_notes((_meg(),))
        answer = _output_run("I was unable to determine that.", STATEMENT_FAILED)["answer"]
        assert "the answer above is for" not in answer
        assert "No statement this run ran carried that value" in answer

    def test_the_fact_itself(self) -> None:
        assert values_no_statement_carried(
            {"tool_use": STATEMENT_FAILED}, ["Middle East Gulf (MEG)"]
        ) == frozenset({"Middle East Gulf (MEG)"})

    def test_a_failure_the_record_truncated_is_still_a_failure(self) -> None:
        """The live path. The first cut of this fix parsed the envelope, so it
        went green on a whole payload and did nothing at all on a real run."""
        assert values_no_statement_carried(
            {"tool_use": STATEMENT_TRUNCATED}, ["Middle East Gulf (MEG)"]
        ) == frozenset({"Middle East Gulf (MEG)"})

    def test_an_answered_statement_is_not_read_as_a_failure(self) -> None:
        assert statement_was_answered("[{'type': 'text', 'text': '{\"data\": {\"rows\": [1]}}'}]")
        assert not statement_was_answered("")


class TestTheOtherDirection:
    """`133`: a check that fires on correct work teaches people to bypass it."""

    def test_a_run_that_queried_keeps_the_sentence_127_wrote(self) -> None:
        record_notes((_meg(),))
        answer = _output_run("There are 68 ports.", MEG_QUERIED)["answer"]
        assert "the answer above is for Middle East Gulf (MEG)" in answer
        assert "No statement this run ran carried" not in answer

    def test_a_workflow_with_no_capabilities_is_never_accused(self) -> None:
        """A writer resolving a term and writing about it has no statement rail
        to be missing from, so there is nothing here to measure and `127`'s
        sentence stands."""
        record_notes((_meg(),))
        answer = _output_run("A note about the Middle East Gulf (MEG).", {"a1": {"bound": []}})[
            "answer"
        ]
        assert "the answer above is for Middle East Gulf (MEG)" in answer

    def test_a_run_with_no_record_at_all_is_never_accused(self) -> None:
        record_notes((_meg(),))
        answer = _output_run("There are 68 ports.")["answer"]
        assert "the answer above is for Middle East Gulf (MEG)" in answer


class TestTheFactItself:
    """Read off the run's record, with no model call and no prose matching."""

    def test_a_value_no_statement_carried(self) -> None:
        assert values_no_statement_carried(
            {"tool_use": NOTHING_QUERIED}, ["Middle East Gulf (MEG)"]
        ) == frozenset({"Middle East Gulf (MEG)"})

    def test_a_value_a_statement_carried(self) -> None:
        assert (
            values_no_statement_carried({"tool_use": MEG_QUERIED}, ["Middle East Gulf (MEG)"])
            == frozenset()
        )

    def test_one_axis_queried_and_another_not(self) -> None:
        """The case that makes this per value. One word, two axes, one query."""
        assert values_no_statement_carried(
            {"tool_use": MEG_QUERIED}, ["Middle East Gulf (MEG)", "persian-gulf-entry"]
        ) == frozenset({"persian-gulf-entry"})

    def test_a_run_with_no_statement_rail_is_not_spoken_about(self) -> None:
        assert values_no_statement_carried({}, ["Middle East Gulf (MEG)"]) == frozenset()
        assert (
            values_no_statement_carried({"tool_use": {"a1": {"bound": []}}}, ["Middle East Gulf (MEG)"])
            == frozenset()
        )

    def test_case_and_nothing_asked_about(self) -> None:
        assert (
            values_no_statement_carried({"tool_use": MEG_QUERIED}, ["middle east gulf (meg)"])
            == frozenset()
        )
        assert values_no_statement_carried({"tool_use": MEG_QUERIED}, []) == frozenset()
        assert values_no_statement_carried({}, ["   "]) == frozenset()
