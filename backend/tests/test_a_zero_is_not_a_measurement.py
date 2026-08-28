"""launch-readiness 166 — "0 dark vessels" over a table that stops in May.

`165` repaired *"1,454,449 dark vessels"* to *"6,119 dark vessels"* in one lap
and stayed `partially` for one reason: runs still answer **"0 dark vessels" as
though they looked.**

Measured against the live CPL warehouse on **2026-08-29**, through the same MCP
server the demo drives:

```
SELECT MIN(day), MAX(day), COUNT(*), COUNT(DISTINCT imo) FROM sm.area_counts_dark_v1r0
  -> 2026-01-01 .. 2026-05-12   2,208,572 rows   10,096 vessels
SELECT MIN(day), MAX(day), COUNT(*) FROM sm.area_counts_latest
  -> 2024-02-01 .. 2026-08-27     984,788 rows
```

So a *"last month"* filter over the dark table cannot match a row. The answer
*"none"* is right by accident and reads identically to one that looked — this
project's most expensive shape, and the whole of the ticket.

**The platform cannot know that without a declaration and must never guess
one.** These tests pin the two halves that follow from it:

- given a declaration, the check says which of the two a zero means;
- given none, it **fails safe** — it says the coverage is undeclared, on the
  reader's own rail, rather than letting silence stand for "I looked".

**Both directions.** `133` is the standing warning: a zero over a window the
table demonstrably *does* hold is a real answer, and a gate firing on it is a
gate people route around. That case is pinned as hard as the failing one.
"""

from __future__ import annotations

from datetime import date

from openstategraph.abc.tool_notes import (
    UncoveredWindow,
    UnverifiedAnswer,
    notes_for_reader,
)
from openstategraph.table_coverage import (
    COVERAGE_STATES,
    TableDeclaration,
    assess,
    check_zero_outside_coverage,
    declaration_in,
    declarations_in,
    declarations_in_result,
    nothing_claims_in,
    window_of,
)

DARK = "sm.area_counts_dark_v1r0"

#: What the lens must declare, in the wire shape a schema tool returns. Every
#: value here was measured, not chosen — see this module's docstring.
DARK_DECLARATION = {
    "table": DARK,
    "row_key": ["geofence", "day", "imo", "dt_last", "pos_last"],
    "coverage": {"column": "day", "min": "2026-01-01", "max": "2026-05-12"},
}

#: "Last month", as of the day this was written.
LAST_MONTH_SQL = (
    f"SELECT COUNT(*) AS dark FROM {DARK} "
    "WHERE dark = 1 AND day >= '2026-07-01' AND day < '2026-08-01'"
)

#: The same question over a period the table really holds.
COVERED_SQL = (
    f"SELECT COUNT(*) AS dark FROM {DARK} "
    "WHERE dark = 1 AND day >= '2026-03-01' AND day < '2026-04-01'"
)

ZERO_ANSWER = "There are no dark vessels departing Mongstad in that period."


def _state(sql: str, *, declared: bool) -> dict:
    """One agent lap: the statement it ran, and what its schema tool told it."""
    row: dict = {
        "bound": ["mcp_execute_sql"],
        "ran": ["mcp_execute_sql"],
        "queries": [{"sql": sql, "result": '{"ok": true, "data": {"sample_rows": [{"dark": 0}]}}'}],
    }
    if declared:
        row["declares"] = [DARK_DECLARATION]
    return {"messages": [], "tool_use": {"sql1": row}, "outputs": {}, "question": "dark vessels?"}


def _reader_rail(sql: str, *, declared: bool) -> str:
    """The sentence the output node would render, with the check run outside a run.

    `record_notes` is a no-op with no thread in play — deliberately, so a
    package's own `tests/` never detonate on one — so the notes are captured at
    the call rather than taken off the thread store. The graph-level test at the
    bottom of this file is the one that proves the rail itself carries them.
    """
    from unittest.mock import patch

    recorded: list = []

    def capture(notes, **kwargs):  # type: ignore[no-untyped-def]
        recorded.extend(notes)
        return True

    with patch("openstategraph.abc.tool_notes.record_notes", capture):
        assert check_zero_outside_coverage(ZERO_ANSWER, _state(sql, declared=declared), ()) == ""
    return notes_for_reader(recorded)


# ------------------------------------------------------------------ #
# What a declaration is, and what it refuses to be
# ------------------------------------------------------------------ #


class TestReadingADeclaration:
    def test_the_measured_declaration_parses(self) -> None:
        declaration = declaration_in(DARK_DECLARATION)
        assert declaration is not None
        assert declaration.table == DARK
        assert declaration.row_key == ("geofence", "day", "imo", "dt_last", "pos_last")
        assert declaration.coverage_min == date(2026, 1, 1)
        assert declaration.coverage_max == date(2026, 5, 12)
        assert declaration.declares_coverage() is True
        assert declaration.a_row_is_not_one_thing() is True

    def test_a_payload_that_declares_nothing_is_not_a_declaration(self) -> None:
        """Strict in trusting: a table name on its own claims nothing."""
        assert declaration_in({"table": DARK, "columns": ["geofence", "day"]}) is None

    def test_a_declaration_with_no_table_belongs_to_no_table(self) -> None:
        assert declaration_in({"row_key": ["a", "b"], "coverage": {"min": "2026-01-01"}}) is None

    def test_half_a_window_is_not_a_window(self) -> None:
        declaration = declaration_in({"table": DARK, "coverage": {"min": "2026-01-01"}})
        assert declaration is None or declaration.declares_coverage() is False

    def test_a_window_that_ends_before_it_starts_is_dropped_not_reversed(self) -> None:
        declaration = declaration_in(
            {"table": DARK, "row_key": ["a"], "coverage": {"min": "2026-05-12", "max": "2026-01-01"}}
        )
        assert declaration is not None
        assert declaration.declares_coverage() is False

    def test_a_hand_written_row_key_may_be_a_comma_string(self) -> None:
        declaration = declaration_in({"table": DARK, "row_key": "geofence, day, imo"})
        assert declaration is not None
        assert declaration.row_key == ("geofence", "day", "imo")

    def test_the_flat_spelling_is_the_same_contract(self) -> None:
        declaration = declaration_in(
            {
                "canonical_table": DARK,
                "coverage_column": "day",
                "coverage_min": "2026-01-01",
                "coverage_max": "2026-05-12",
            }
        )
        assert declaration is not None
        assert declaration.coverage_max == date(2026, 5, 12)


class TestFindingADeclarationInsideAToolAnswer:
    def test_a_bulk_schema_dump_carries_one_per_table(self) -> None:
        result = (
            '{"ok": true, "data": {"tables": ['
            '{"table": "sm.area_counts_dark_v1r0", "row_key": ["geofence", "day", "imo"],'
            ' "coverage": {"column": "day", "min": "2026-01-01", "max": "2026-05-12"}},'
            '{"table": "sm.area_counts_latest",'
            ' "coverage": {"column": "day", "min": "2024-02-01", "max": "2026-08-27"}}]}}'
        )
        found = {d.table: d for d in declarations_in_result(result)}
        assert set(found) == {DARK, "sm.area_counts_latest"}
        assert found["sm.area_counts_latest"].coverage_max == date(2026, 8, 27)

    def test_an_answer_with_neither_marker_word_is_never_parsed(self) -> None:
        assert declarations_in_result('{"ok": true, "data": {"sample_rows": [{"n": 1}]}}') == []

    def test_the_measured_mcp_envelope_is_undone(self) -> None:
        """The three layers `165` measured: a Python repr, then JSON, then `data`."""
        inner = (
            '{"ok": true, "data": {"table": "sm.area_counts_dark_v1r0", '
            '"row_key": ["geofence", "day", "imo"], '
            '"coverage": {"column": "day", "min": "2026-01-01", "max": "2026-05-12"}}}'
        )
        blocks = repr([{"type": "text", "text": inner, "id": "x"}])
        found = declarations_in_result(blocks)
        assert [d.table for d in found] == [DARK]

    def test_the_live_date_columns_block_is_not_read_as_coverage(self) -> None:
        """The measured envelope's own `min`/`max` are about the rows returned.

        `sm.area_counts_dark_v1r0` answered a one-row `SELECT TOP 1 *` with
        `date_columns: [{"column": "day", "min": "2026-02-26", "max":
        "2026-02-26"}]` — the span of the **sample**, not of the table. Reading
        it as coverage would turn *"the row I fetched is from one day"* into
        *"this table holds one day"*, which is a confident wrong answer where
        the honest one is `undeclared`.
        """
        envelope = (
            '{"ok": true, "data": {"primary_table": "sm.area_counts_dark_v1r0", '
            '"date_columns": [{"column": "day", "min": "2026-02-26", "max": "2026-02-26"}], '
            '"row_count": 1}}'
        )
        assert declarations_in_result(envelope) == []

    def test_the_run_record_is_the_second_rail(self) -> None:
        """`_agent` returns no messages, so `tool_use[node]["declares"]` is it."""
        found = declarations_in(_state(LAST_MONTH_SQL, declared=True))
        assert found[DARK.casefold()].coverage_max == date(2026, 5, 12)

    def test_a_run_shown_nothing_holds_nothing(self) -> None:
        assert declarations_in(_state(LAST_MONTH_SQL, declared=False)) == {}

    def test_tool_report_is_what_puts_it_on_that_rail(self) -> None:
        """The plumbing, not only the reading.

        `165` had to build `tool_use[node]["queries"]` for exactly this reason:
        `_agent` returns no messages, so a gate behind an agent sees nothing an
        agent's loop was told. A declaration arrives on the same path.
        """
        from langchain_core.messages import ToolMessage

        from openstategraph.compile.node_runtime import tool_report

        payload = (
            '{"ok": true, "data": {"table": "sm.area_counts_dark_v1r0", '
            '"row_key": ["geofence", "day", "imo"], '
            '"coverage": {"column": "day", "min": "2026-01-01", "max": "2026-05-12"}}}'
        )
        messages = [ToolMessage(content=payload, tool_call_id="c1", name="mcp_describe_table")]
        row = tool_report("a1", messages, ["mcp_describe_table"])["tool_use"]["a1"]
        assert row["declares"][0]["table"] == DARK
        assert row["declares"][0]["coverage"]["max"] == "2026-05-12"

    def test_and_leaves_the_key_out_when_nothing_declared(self) -> None:
        """Absent rather than empty — the same claim `queried` and `queries` make."""
        from langchain_core.messages import ToolMessage

        from openstategraph.compile.node_runtime import tool_report

        messages = [ToolMessage(content='{"ok": true}', tool_call_id="c1", name="t")]
        assert "declares" not in tool_report("a1", messages, ["t"])["tool_use"]["a1"]


# ------------------------------------------------------------------ #
# The window a statement asked about
# ------------------------------------------------------------------ #


class TestTheWindowAStatementAsked:
    def test_last_month(self) -> None:
        assert window_of(LAST_MONTH_SQL) == (date(2026, 7, 1), date(2026, 8, 1))

    def test_one_literal_is_still_a_window(self) -> None:
        assert window_of(f"SELECT 1 FROM {DARK} WHERE day >= '2026-07-01'") == (
            date(2026, 7, 1),
            date(2026, 7, 1),
        )

    def test_a_statement_with_no_date_literal_has_an_unknown_window(self) -> None:
        assert window_of(f"SELECT COUNT(*) FROM {DARK}") == (None, None)

    def test_a_timestamp_literal_is_read_as_its_date(self) -> None:
        assert window_of(f"SELECT 1 FROM {DARK} WHERE dt_last > '2026-07-01T08:00:00'") == (
            date(2026, 7, 1),
            date(2026, 7, 1),
        )


class TestAJoinIsJudgedByItsWeakestSide:
    """Found live on 2026-08-29 and by nothing else.

    The model answered the dark half with `FROM sm.cargoflow_latest ... EXISTS
    (SELECT 1 FROM sm.area_counts_dark_v1r0 ...)`, so the table whose coverage
    is in question was named **second**. A check reading only the first `FROM`
    would have cleared the statement on the strength of the wrong table.
    """

    JOINED = (
        "SELECT * FROM sm.cargoflow_latest c WHERE c.load_date >= '2026-07-01' "
        "AND c.load_date < '2026-08-01' AND EXISTS (SELECT 1 FROM "
        "sm.area_counts_dark_v1r0 d WHERE d.imo = c.vessel_imo AND d.dark = 1)"
    )

    def _state(self, declarations: list[dict]) -> dict:
        return {
            "messages": [],
            "outputs": {},
            "tool_use": {
                "sql1": {
                    "bound": [],
                    "ran": [],
                    "queries": [{"sql": self.JOINED, "result": '{"ok": true}'}],
                    "declares": declarations,
                }
            },
        }

    def test_both_tables_are_named(self) -> None:
        from openstategraph.counted_rows import tables_in

        assert tables_in(self.JOINED) == ["sm.cargoflow_latest", "sm.area_counts_dark_v1r0"]

    def test_the_covered_first_table_does_not_clear_the_uncovered_second(self) -> None:
        covered = {
            "table": "sm.cargoflow_latest",
            "coverage": {"column": "load_date", "min": "2024-01-01", "max": "2026-08-27"},
        }
        reason = check_zero_outside_coverage(
            ZERO_ANSWER, self._state([covered, DARK_DECLARATION]), ()
        )
        assert "2026-05-12" in reason and DARK in reason

    def test_and_a_join_of_two_covered_tables_is_still_silent(self) -> None:
        covered = {
            "table": "sm.cargoflow_latest",
            "coverage": {"column": "load_date", "min": "2024-01-01", "max": "2026-08-27"},
        }
        wide = {
            "table": DARK,
            "coverage": {"column": "day", "min": "2024-01-01", "max": "2026-08-27"},
        }
        assert check_zero_outside_coverage(ZERO_ANSWER, self._state([covered, wide]), ()) == ""


class TestTheFourStates:
    DECLARED = TableDeclaration(
        table=DARK,
        row_key=("geofence", "day", "imo"),
        coverage_column="day",
        coverage_min=date(2026, 1, 1),
        coverage_max=date(2026, 5, 12),
    )

    def test_last_month_is_entirely_outside(self) -> None:
        assert assess(window_of(LAST_MONTH_SQL), self.DECLARED) == "outside"

    def test_march_is_covered(self) -> None:
        assert assess(window_of(COVERED_SQL), self.DECLARED) == "covered"

    def test_a_window_running_past_the_end_is_partial(self) -> None:
        assert assess((date(2026, 5, 1), date(2026, 6, 1)), self.DECLARED) == "partial"

    def test_no_declaration_is_undeclared(self) -> None:
        assert assess(window_of(LAST_MONTH_SQL), None) == "undeclared"

    def test_no_window_is_not_a_state_at_all(self) -> None:
        """A statement that asked about no period is evidence of nothing."""
        assert assess((None, None), self.DECLARED) == ""
        assert assess((None, None), None) == ""

    def test_the_set_is_closed(self) -> None:
        assert set(COVERAGE_STATES) == {"covered", "partial", "outside", "undeclared"}


# ------------------------------------------------------------------ #
# What the answer has to say for this to be anybody's business
# ------------------------------------------------------------------ #


class TestWhatCountsAsReportingNone:
    def test_the_published_sentence(self) -> None:
        assert nothing_claims_in(ZERO_ANSWER) == ["vessels"]

    def test_a_digit_zero_says_the_same_thing(self) -> None:
        assert nothing_claims_in("I found 0 dark vessels last month.") == ["vessels"]

    def test_a_word_about_the_record_is_not_a_word_about_the_world(self) -> None:
        """The same rule `165` applies to the opposite claim."""
        assert nothing_claims_in("The query returned no rows.") == []
        assert nothing_claims_in("There were no results.") == []

    def test_a_number_with_no_noun_is_not_a_claim(self) -> None:
        assert nothing_claims_in("The total was 0.") == []

    def test_a_country_code_is_not_the_word_no(self) -> None:
        """Found on the first live run, 2026-08-29, and by nothing else.

        The owner's own question produced a correct breakdown reading
        *"32,759 barrels to Floro [NO]"* three times over — `[NO]` is Norway —
        and the disclosure came out as *"no barrels and instances"*: a sentence
        about nothing, attached to an answer that was right. `133` in person,
        one live run to find and no fixture that would have caught it.
        """
        prose = (
            "Biodiesel: 32,759 barrels to Floro [NO]. Diesel/Gasoil: 109,724 barrels "
            "to Alesund [NO]. Regarding dark vessels, there were no recorded instances "
            "of dark vessels departing from Mongstad during this period."
        )
        assert nothing_claims_in(prose) == ["vessels"]

    def test_it_walks_past_the_word_that_is_not_the_subject(self) -> None:
        """*"no recorded instances of dark vessels"* is about vessels."""
        assert nothing_claims_in("There were no recorded instances of dark vessels.") == [
            "vessels"
        ]


# ------------------------------------------------------------------ #
# The check — both directions
# ------------------------------------------------------------------ #


class TestItRefusesTheZeroThatCouldNotHaveBeenAnythingElse:
    def test_the_reason_names_the_last_date_the_data_holds(self) -> None:
        reason = check_zero_outside_coverage(ZERO_ANSWER, _state(LAST_MONTH_SQL, declared=True), ())
        assert reason
        assert "2026-05-12" in reason
        assert DARK in reason
        assert "not a measurement" in reason

    def test_it_asks_for_the_distinction_rather_than_a_different_number(self) -> None:
        reason = check_zero_outside_coverage(ZERO_ANSWER, _state(LAST_MONTH_SQL, declared=True), ())
        assert "nothing was found" in reason and "does not reach the period" in reason

    def test_hedging_is_not_saying_it(self) -> None:
        """The exit below is one literal, not a tone. A sentence that gestures at
        doubt without naming the date leaves the reader exactly where they were."""
        candidate = "There are no dark vessels, though I cannot vouch for the period."
        assert check_zero_outside_coverage(candidate, _state(LAST_MONTH_SQL, declared=True), ())


class TestTheCheckCanSeeItsOwnRepair:
    """Found live on 2026-08-29, after the fix, and by nothing else.

    The model complied **completely** — *"The data for the dark fleet only goes
    up to May 12, 2026. Therefore, there were no distinct dark vessels recorded
    from July 1, 2026, to August 1, 2026, because this period is beyond the
    available data coverage."* — and the guard rejected it again, exhausted, and
    the reader was told the answer was unverified. A gate that cannot recognise
    its own repair is `167` built on purpose, and `133`'s failure exactly: it
    fired on work that was correct.

    The exit is one literal the check itself supplied — the last date the
    declaration states — and not a judgement about how the model phrased itself.
    """

    COMPLIANT = (
        "The data for the dark fleet only goes up to May 12, 2026. Therefore, there were "
        "no distinct dark vessels recorded from July 1, 2026 to August 1, 2026, because "
        "this period is beyond the available data coverage."
    )

    def test_the_sentence_the_live_model_wrote(self) -> None:
        assert check_zero_outside_coverage(self.COMPLIANT, _state(LAST_MONTH_SQL, declared=True), ()) == ""

    def test_the_iso_spelling_too(self) -> None:
        candidate = "No dark vessels: this data stops on 2026-05-12."
        assert check_zero_outside_coverage(candidate, _state(LAST_MONTH_SQL, declared=True), ()) == ""

    def test_a_different_date_is_not_the_date(self) -> None:
        """Strict in trusting: the exit is the declared end and nothing near it."""
        candidate = "No dark vessels. This data stops on May 11, 2026."
        assert check_zero_outside_coverage(candidate, _state(LAST_MONTH_SQL, declared=True), ())

    def test_the_spellings_it_reads(self) -> None:
        from datetime import date as _date

        from openstategraph.table_coverage import states_the_date

        day = _date(2026, 5, 12)
        for spelling in ("2026-05-12", "May 12, 2026", "12 May 2026", "may 12 2026"):
            assert states_the_date(f"the data stops on {spelling}.", day), spelling

    def test_an_ambiguous_numeric_spelling_is_not_read(self) -> None:
        """Two readings of one string is the defect this map is named for."""
        from datetime import date as _date

        from openstategraph.table_coverage import states_the_date

        assert not states_the_date("the data stops on 12/05/2026.", _date(2026, 5, 12))


class TestItIsSilentOnCorrectWork:
    """`133`: a check that fires on a right answer is a check people route around."""

    def test_a_zero_over_a_period_the_table_holds_is_a_real_answer(self) -> None:
        state = _state(COVERED_SQL, declared=True)
        assert check_zero_outside_coverage(ZERO_ANSWER, state, ()) == ""

    def test_and_it_says_nothing_to_the_reader_either(self) -> None:
        """Silent on both rails, not merely on the one that routes."""
        assert _reader_rail(COVERED_SQL, declared=True) == ""

    def test_an_answer_reporting_something_is_not_this_checks_business(self) -> None:
        answer = "6,119 dark vessels were seen."
        assert check_zero_outside_coverage(answer, _state(LAST_MONTH_SQL, declared=True), ()) == ""

    def test_a_run_that_filtered_on_no_period_is_not_reported(self) -> None:
        state = _state(f"SELECT COUNT(DISTINCT imo) FROM {DARK} WHERE dark = 1", declared=True)
        assert check_zero_outside_coverage(ZERO_ANSWER, state, ()) == ""

    def test_a_run_that_ran_nothing_is_not_reported(self) -> None:
        empty: dict = {"messages": [], "tool_use": {}, "outputs": {}}
        assert check_zero_outside_coverage(ZERO_ANSWER, empty, ()) == ""


# ------------------------------------------------------------------ #
# The fail-safe — the half that is live before any lens declares anything
# ------------------------------------------------------------------ #


class TestAnUndeclaredTableFailsSafe:
    """The declaration does not exist yet, and this is what happens until it does.

    Not a revise: no revision lap makes a table declare a window, so routing
    this to `revise` would build a guard that objects forever and then
    publishes anyway — `launch-readiness/167` in person. It travels the reader
    rail instead, which renders whether or not the model mentions it.
    """

    def _note(self, sql: str = LAST_MONTH_SQL) -> str:
        return _reader_rail(sql, declared=False)

    def test_it_passes_rather_than_revising(self) -> None:
        assert check_zero_outside_coverage(ZERO_ANSWER, _state(LAST_MONTH_SQL, declared=False), ()) == ""

    def test_the_reader_is_told_the_two_cannot_be_told_apart(self) -> None:
        sentence = self._note()
        assert "cannot be told apart" in sentence
        assert "does not state which period it covers" in sentence

    def test_it_names_no_table_and_no_statement(self) -> None:
        """`abc/narration.py`'s rule: the machinery is never named aloud."""
        sentence = self._note()
        assert DARK not in sentence
        assert "SELECT" not in sentence.upper()

    def test_a_window_running_past_a_declared_end_names_the_last_date(self) -> None:
        note = UncoveredWindow(subject="vessels", table=DARK, declared_max="2026-05-12")
        sentence = notes_for_reader([note])
        assert "2026-05-12" in sentence
        assert "could not have appeared" in sentence
        assert DARK not in sentence

    def test_the_two_sentences_are_different(self) -> None:
        declared = notes_for_reader([UncoveredWindow(subject="vessels", declared_max="2026-05-12")])
        undeclared = notes_for_reader([UncoveredWindow(subject="vessels")])
        assert declared and undeclared and declared != undeclared


# ------------------------------------------------------------------ #
# `row_key` — what `165` could not say, and can now
# ------------------------------------------------------------------ #


class TestRowKeyTurnsADoubtIntoAFact:
    COUNT_SQL = f"SELECT COUNT(*) AS n FROM {DARK} WHERE dark = 1"
    PUBLISHED = "There are 1,454,449 dark vessels."

    def _state(self, *, declared: bool) -> dict:
        row: dict = {
            "bound": ["mcp_execute_sql"],
            "ran": ["mcp_execute_sql"],
            "queries": [
                {
                    "sql": self.COUNT_SQL,
                    "result": '{"ok": true, "data": {"sample_rows": [{"n": 1454449}]}}',
                }
            ],
        }
        if declared:
            row["declares"] = [DARK_DECLARATION]
        return {"messages": [], "tool_use": {"sql1": row}, "outputs": {}}

    def test_without_a_declaration_it_still_says_only_what_it_knows(self) -> None:
        from openstategraph.counted_rows import check_row_counts_in_prose

        reason = check_row_counts_in_prose(self.PUBLISHED, self._state(declared=False), ())
        assert "never established that" in reason
        assert "declares its row key" not in reason

    def test_with_one_it_states_the_figure_is_a_count_of_rows(self) -> None:
        from openstategraph.counted_rows import check_row_counts_in_prose

        reason = check_row_counts_in_prose(self.PUBLISHED, self._state(declared=True), ())
        assert "declares its row key as (geofence, day, imo, dt_last, pos_last)" in reason
        assert "not one vessel" in reason
        assert "never established that" not in reason

    def test_a_declared_one_row_per_entity_table_keeps_the_softer_sentence(self) -> None:
        """A key of one column says a row **is** one of something.

        `165`'s known cost — `sm.dim_vessel_latest` reported too — is bounded by
        exactly this: the declaration that would make the harder sentence true
        is also the declaration that withholds it.
        """
        from openstategraph.counted_rows import check_row_counts_in_prose

        state = self._state(declared=True)
        state["tool_use"]["sql1"]["declares"] = [{"table": DARK, "row_key": ["imo"]}]
        reason = check_row_counts_in_prose(self.PUBLISHED, state, ())
        assert "declares its row key" not in reason
        assert "never established that" in reason


# ------------------------------------------------------------------ #
# Through a compiled graph — the layer the defect lives at
# ------------------------------------------------------------------ #


class TestTheDisclosureReachesTheAnswer:
    """Five defects this week were invisible to a green suite because the test
    sat one layer up. So this one runs the graph: a guard wired to the check, an
    output node behind it, and the sentence read off `answer`."""

    def _document(self) -> dict:
        wire = lambda s, sp, t, tp: {  # noqa: E731
            "source": {"nodeId": s, "portId": sp},
            "target": {"nodeId": t, "portId": tp},
        }
        # **No `input.text`, and that is not a shortcut.** `_input` resets
        # `tool_use` for a fresh turn — correct, and it means a record seeded
        # into the initial state would be wiped before the agent ran. The
        # record here stands for what an agent's own loop writes through
        # `tool_report`, which is the rail `165` had to build to make any gate
        # behind an agent able to see anything at all.
        return {
            "nodes": [
                {"id": "a1", "type": "agent.llm", "data": {}},
                {
                    "id": "guard1",
                    "type": "guard.check",
                    "data": {"check": "zero_outside_coverage", "maxAttempts": 2},
                },
                {"id": "out1", "type": "output.formatted", "data": {}},
            ],
            "edges": [
                wire("a1", "result", "guard1", "candidate"),
                wire("guard1", "revise", "a1", "feedback"),
                wire("guard1", "pass", "out1", "result"),
            ],
        }

    def _answer(self, *, declared: bool) -> str:
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        from conftest import RespondingModel

        model = RespondingModel([], default=ZERO_ANSWER)
        runtime = NodeRuntime(model=model)
        graph = WorkflowCompiler().build(
            self._document(), RunState, runtime.factory(self._document())
        )
        seed = _state(LAST_MONTH_SQL, declared=declared)
        final = graph.invoke(
            {
                "question": "Any dark vessels last month?",
                "attempts": 0,
                "decisions": {},
                "outputs": {},
                "tool_use": seed["tool_use"],
            },
            {"recursion_limit": 30, "configurable": {"thread_id": "coverage-166"}},
        )
        return str(final.get("answer") or "")

    def test_an_undeclared_table_says_so_in_the_answer_itself(self) -> None:
        answer = self._answer(declared=False)
        assert ZERO_ANSWER in answer
        assert "cannot be told apart" in answer, answer

    def test_and_a_declared_covered_run_adds_nothing(self) -> None:
        """The other direction, through the same graph."""
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        from conftest import RespondingModel

        model = RespondingModel([], default=ZERO_ANSWER)
        runtime = NodeRuntime(model=model)
        graph = WorkflowCompiler().build(
            self._document(), RunState, runtime.factory(self._document())
        )
        final = graph.invoke(
            {
                "question": "Any dark vessels in March?",
                "attempts": 0,
                "decisions": {},
                "outputs": {},
                "tool_use": _state(COVERED_SQL, declared=True)["tool_use"],
            },
            {"recursion_limit": 30, "configurable": {"thread_id": "coverage-166-ok"}},
        )
        assert str(final.get("answer") or "").strip() == ZERO_ANSWER


class TestTheCheckIsNameableAndDiscoverable:
    def test_it_is_a_built_in(self) -> None:
        from openstategraph.compile.node_runtime import _BUILT_IN_CHECKS

        assert _BUILT_IN_CHECKS["zero_outside_coverage"] is check_zero_outside_coverage

    def test_the_note_kinds_are_on_the_carrier(self) -> None:
        from openstategraph.abc.tool_notes import ToolNote

        assert UncoveredWindow in ToolNote.__args__  # type: ignore[attr-defined]
        assert UnverifiedAnswer in ToolNote.__args__  # type: ignore[attr-defined]
