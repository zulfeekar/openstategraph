"""The tollbooth's ledger — install-experience ticket 17.

Built through `skills/atom-forge`, whose build checklist puts these tests
first. What they pin is the ledger itself: the namespace it occupies, the
retention it honours, the order it furnishes in, and — the half the interview
never asked for and the readiness card had to close before a line was written —
that its six failure conditions say six different things.

Nothing here reaches a model or a network. The Store is LangGraph's own
`InMemoryStore`, so every assertion is about our arithmetic rather than about
sqlite's.
"""

from __future__ import annotations

import pytest
from langgraph.store.memory import InMemoryStore

from openstategraph.memory_segment import (
    CEILING_REACHED,
    DEFAULT_RETENTION,
    NOTHING_CROSSED,
    NO_NAME,
    NO_STORE,
    READ_FAILED,
    SEGMENT_CEILING,
    SEGMENT_ROOT,
    WRITE_FAILED,
    MemorySegment,
    parse_retention,
)

SLUG = "tollbooth-demo"


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


def cross(segment: MemorySegment, store: object, text: str, node: str = "mem1"):
    return segment.cross(store, SLUG, text=text, node=node)


class TestTheLedgerIsNamedAndWorkflowScoped:
    """The interview's volunteered second half: identity is the *name*, so
    several tollbooths carrying one name are one ledger."""

    def test_the_namespace_is_the_workflow_and_the_segment_name(self) -> None:
        assert MemorySegment("notes").namespace(SLUG) == (SEGMENT_ROOT, SLUG, "notes")

    def test_two_positions_with_one_name_are_one_ledger(self, store: InMemoryStore) -> None:
        early = MemorySegment("notes")
        late = MemorySegment("notes")
        cross(early, store, "first", node="mem-early")
        crossing = cross(late, store, "second", node="mem-late")

        assert [entry.text for entry in crossing.entries] == ["first"]
        assert [entry.text for entry in late.entries(store, SLUG)[0]] == ["first", "second"]

    def test_two_names_are_two_ledgers(self, store: InMemoryStore) -> None:
        cross(MemorySegment("notes"), store, "a")
        cross(MemorySegment("other"), store, "b")

        assert [e.text for e in MemorySegment("notes").entries(store, SLUG)[0]] == ["a"]
        assert [e.text for e in MemorySegment("other").entries(store, SLUG)[0]] == ["b"]

    def test_a_different_workflow_slug_is_a_different_ledger(self, store: InMemoryStore) -> None:
        segment = MemorySegment("notes")
        segment.cross(store, "one-workflow", text="a", node="m")
        entries, _ = segment.entries(store, "another-workflow")
        assert entries == ()

    def test_it_stays_out_of_the_facts_namespace(self) -> None:
        """`save_memory` writes to `("workflow-memory", slug)` and searches it
        by prefix. A ledger of crossings sharing that root would be recalled
        as if each crossing were a fact somebody chose to remember."""
        from openstategraph.memory import MemoryScope

        assert SEGMENT_ROOT != "workflow-memory"
        assert MemorySegment("notes").namespace(SLUG)[0] != MemoryScope.WORKFLOW.value


class TestTheCrossingOrder:
    """Furnish what is there, *then* append. The other order hands a node its
    own input back inside the context block it is reading."""

    def test_the_first_crossing_furnishes_nothing_and_records(
        self, store: InMemoryStore
    ) -> None:
        crossing = cross(MemorySegment("notes"), store, "the report")

        assert crossing.entries == ()
        assert crossing.recorded is True
        assert "the report" in crossing.text

    def test_the_crossing_content_survives_verbatim(self, store: InMemoryStore) -> None:
        segment = MemorySegment("notes")
        cross(segment, store, "earlier")
        crossing = cross(segment, store, "the exact bytes")

        assert crossing.text.endswith("the exact bytes")

    def test_what_flows_onward_carries_the_ledger_above_the_crossing(
        self, store: InMemoryStore
    ) -> None:
        segment = MemorySegment("notes")
        cross(segment, store, "alpha")
        crossing = cross(segment, store, "beta")

        assert crossing.text.index("alpha") < crossing.text.index("beta")

    def test_entries_come_back_oldest_first(self, store: InMemoryStore) -> None:
        segment = MemorySegment("notes")
        for text in ("one", "two", "three"):
            cross(segment, store, text)
        entries, _ = segment.entries(store, SLUG)
        assert [entry.text for entry in entries] == ["one", "two", "three"]

    def test_an_entry_remembers_which_tollbooth_wrote_it(self, store: InMemoryStore) -> None:
        segment = MemorySegment("notes")
        cross(segment, store, "alpha", node="mem-early")
        entries, _ = segment.entries(store, SLUG)
        assert entries[0].node == "mem-early"


class TestRetention:
    """`int | None`, `None` meaning unbounded — honesty gate 3, which is why
    there is no number anywhere here standing in for infinity."""

    def test_the_default_is_the_last_twenty(self) -> None:
        assert DEFAULT_RETENTION == 20
        assert MemorySegment("notes").retention == 20

    def test_it_keeps_the_newest_and_drops_the_oldest(self, store: InMemoryStore) -> None:
        segment = MemorySegment("notes", retention=3)
        for text in ("one", "two", "three", "four", "five"):
            cross(segment, store, text)
        entries, _ = segment.entries(store, SLUG)
        assert [entry.text for entry in entries] == ["three", "four", "five"]

    def test_none_means_unbounded(self, store: InMemoryStore) -> None:
        segment = MemorySegment("notes", retention=None)
        for index in range(25):
            cross(segment, store, f"entry {index}")
        entries, _ = segment.entries(store, SLUG)
        assert len(entries) == 25

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("20", 20),
            (20, 20),
            ("  5 ", 5),
            ("", None),
            ("   ", None),
            (None, None),
            ("everything", None),
            ("0", None),
            (-3, None),
            (2.7, None),
            (True, None),
        ],
    )
    def test_what_the_card_can_write_becomes_int_or_none(
        self, raw: object, expected: int | None
    ) -> None:
        """A text field can hold anything a person types. Nothing it can hold
        may become a number that does not survive JSON, and nothing may become
        a silent zero — a ledger that keeps zero entries is a node whose whole
        card is a lie, so unparseable and non-positive both mean unbounded."""
        assert parse_retention(raw) == expected


class TestTheContextBlockIsMachinery:
    """Furnished as a Context section: generated, and with no field anywhere
    that lets a developer edit or delete it."""

    def test_it_names_the_segment_and_counts_what_it_holds(
        self, store: InMemoryStore
    ) -> None:
        segment = MemorySegment("notes")
        cross(segment, store, "alpha")
        cross(segment, store, "beta")
        crossing = cross(segment, store, "gamma")

        assert "notes" in crossing.text
        assert "2 entries" in crossing.text

    def test_one_entry_is_not_called_entries(self, store: InMemoryStore) -> None:
        segment = MemorySegment("notes")
        cross(segment, store, "alpha")
        crossing = cross(segment, store, "beta")
        assert "1 entry" in crossing.text
        assert "1 entries" not in crossing.text

    def test_an_empty_segment_reads_as_empty_and_not_as_broken(self) -> None:
        """The interview's own follow-up: an empty state that reads as an
        error trains people to ignore the card."""
        block = MemorySegment("notes").furnish(())
        assert "nothing has crossed yet" in block
        assert "error" not in block.lower()
        assert "fail" not in block.lower()

    def test_no_field_can_reach_it(self) -> None:
        """The `RouterNode` lesson, applied before the bug: the heading and the
        numbering are the machinery's, and the node has exactly two fields."""
        from openstategraph.compile.node_catalogue import load_catalogue

        keys = set(load_catalogue().field_keys["memory.segment"])
        assert {"segment", "retention"} <= keys
        assert not any("context" in key.lower() or "prompt" in key.lower() for key in keys)


class TestSixConditionsSaySixThings:
    """The dimension the interview never ran. Two failures that share a
    sentence are one failure — this is the test whose only job is to fail if
    anyone collapses two of them."""

    SENTENCES = (NO_STORE, NO_NAME, READ_FAILED, WRITE_FAILED, NOTHING_CROSSED, CEILING_REACHED)

    def test_every_condition_says_something_different(self) -> None:
        rendered = [
            template.format(name="notes", error="boom", ceiling=SEGMENT_CEILING)
            for template in self.SENTENCES
        ]
        assert len(set(rendered)) == len(self.SENTENCES)

    def test_no_store_says_the_gap_is_ours(self, store: InMemoryStore) -> None:
        crossing = MemorySegment("notes").cross(None, SLUG, text="alpha", node="mem1")
        assert crossing.recorded is False
        assert NO_STORE.format(name="notes") in crossing.text
        # The crossing still passes through: a tollbooth that swallowed the
        # flow because its ledger was unavailable would be an outage.
        assert crossing.text.endswith("alpha")

    def test_an_unnamed_segment_says_so_rather_than_inventing_a_ledger(
        self, store: InMemoryStore
    ) -> None:
        crossing = MemorySegment("  ").cross(store, SLUG, text="alpha", node="mem1")
        assert NO_NAME in crossing.text
        assert crossing.recorded is False
        assert store.search((SEGMENT_ROOT,), limit=10) == []

    def test_a_failed_read_is_never_reported_as_an_empty_segment(self) -> None:
        """The one that would otherwise be reported as success, and the reason
        this dimension exists. `search` raising must not furnish a block that
        tells a model the workflow has seen nothing."""

        class Unreadable(InMemoryStore):
            def search(self, *args: object, **kwargs: object) -> list:
                raise RuntimeError("store is unavailable")

        crossing = MemorySegment("notes").cross(Unreadable(), SLUG, text="alpha", node="mem1")
        assert READ_FAILED.format(name="notes", error="store is unavailable") in crossing.text
        assert "nothing has crossed yet" not in crossing.text

    def test_a_failed_write_says_it_read_and_did_not_append(self) -> None:
        class Unwritable(InMemoryStore):
            def put(self, *args: object, **kwargs: object) -> None:
                raise RuntimeError("disk is full")

        crossing = MemorySegment("notes").cross(Unwritable(), SLUG, text="alpha", node="mem1")
        assert WRITE_FAILED.format(name="notes", error="disk is full") in crossing.text
        assert crossing.recorded is False

    def test_nothing_crossing_appends_nothing(self, store: InMemoryStore) -> None:
        """A blank entry is not free: under retention it pushes a real one out."""
        segment = MemorySegment("notes")
        cross(segment, store, "alpha")
        crossing = cross(segment, store, "   ")

        assert NOTHING_CROSSED.format(name="notes") in crossing.text
        assert crossing.recorded is False
        assert len(segment.entries(store, SLUG)[0]) == 1

    def test_the_ceiling_says_the_reading_was_partial(self, store: InMemoryStore) -> None:
        segment = MemorySegment("notes", retention=None)
        for index in range(SEGMENT_CEILING + 1):
            segment.record(store, SLUG, text=f"entry {index}", node="mem1")
        _, note = segment.entries(store, SLUG)
        assert note == CEILING_REACHED.format(name="notes", ceiling=SEGMENT_CEILING)

    def test_a_healthy_crossing_says_nothing_at_all(self, store: InMemoryStore) -> None:
        """Every one of these sentences is an exception report. A run where
        the machinery worked must not carry any of them."""
        segment = MemorySegment("notes")
        cross(segment, store, "alpha")
        crossing = cross(segment, store, "beta")
        assert crossing.notes == ()
        assert "[memory:" not in crossing.text


class TestNoModelIsReachableFromHere:
    """Honesty gate 8, asserted rather than promised."""

    def test_the_module_imports_nothing_that_calls_a_model(self) -> None:
        import ast
        import inspect

        from openstategraph import memory_segment

        tree = ast.parse(inspect.getsource(memory_segment))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")

        assert not any(
            name.startswith(("langchain", "openai", "ollama", "anthropic"))
            for name in imported
        ), imported
