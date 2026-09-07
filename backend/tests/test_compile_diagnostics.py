"""Compile-time findings are a collaborator, not seven fields on the runtime.

`NodeRuntime` carried seven warning buckets — 7 of its 23 attributes — and
`api/registries.runtime_warnings()` reached across into all seven to turn them
into sentences, three of them through `getattr(runtime, name, [])`. The
defensive access is the tell: the contract between the two was never firm
enough for either side to depend on it (reviews-2026-08-14 ticket 07).

So the data and its only reader move in together. What that buys, beyond the
member count:

- **Dedup happens once.** Five call sites open-coded `if x not in bucket`.
  One forgot (`unenforced_outcomes`), and nothing noticed.
- **A finding is registered, not coded.** The sentence table is keyed by the
  enum, so a new kind of finding is a table entry rather than another `for`
  loop in `runtime_warnings` and another field on `NodeRuntime`.
- **Order is declared.** Report order is enum declaration order, which is a
  property you can read, rather than the order somebody happened to write the
  loops in.

The `Reducer` enum earlier in this same ticket is the precedent: a `str`-valued
enum, so a member survives a JSON round trip, and one place where a name
becomes behaviour.
"""

from __future__ import annotations

import pytest

from openstategraph.compile.diagnostics import CompileDiagnostics, Finding


class TestRecording:
    def test_a_recorded_finding_produces_its_sentence(self) -> None:
        diagnostics = CompileDiagnostics()

        diagnostics.record(Finding.UNRESOLVED_TOOL, "tool.reddit")

        assert len(diagnostics.warnings()) == 1
        assert "tool.reddit" in diagnostics.warnings()[0]

    def test_nothing_recorded_is_nothing_reported(self) -> None:
        assert CompileDiagnostics().warnings() == []

    def test_the_same_finding_twice_is_reported_once(self) -> None:
        """Dedup used to be open-coded at each call site, and one of the seven
        did not do it — two Team mounts of the same broken child reported the
        outcome twice."""
        diagnostics = CompileDiagnostics()

        diagnostics.record(Finding.UNRESOLVED_TOOL, "tool.reddit")
        diagnostics.record(Finding.UNRESOLVED_TOOL, "tool.reddit")

        assert len(diagnostics.warnings()) == 1

    def test_two_different_subjects_are_two_findings(self) -> None:
        diagnostics = CompileDiagnostics()

        diagnostics.record(Finding.UNRESOLVED_TOOL, "tool.reddit")
        diagnostics.record(Finding.UNRESOLVED_TOOL, "tool.chinook")

        assert len(diagnostics.warnings()) == 2

    def test_a_finding_carrying_two_subjects_uses_both(self) -> None:
        diagnostics = CompileDiagnostics()

        diagnostics.record(Finding.UNENFORCED_OUTCOME, "team-1", "billing")

        sentence = diagnostics.warnings()[0]
        assert "team-1" in sentence and "billing" in sentence

    def test_the_wrong_number_of_subjects_is_an_error_not_a_bad_sentence(self) -> None:
        # A template with an unfilled slot would ship "{1}" to a user.
        with pytest.raises(ValueError):
            CompileDiagnostics().record(Finding.UNENFORCED_OUTCOME, "team-1")


class TestReading:
    def test_subjects_come_back_for_the_kind_asked_for(self) -> None:
        diagnostics = CompileDiagnostics()
        diagnostics.record(Finding.UNRESOLVED_TOOL, "tool.reddit")
        diagnostics.record(Finding.UNRESOLVED_SUBGRAPH, "billing")

        assert diagnostics.subjects(Finding.UNRESOLVED_TOOL) == [("tool.reddit",)]
        assert diagnostics.subjects(Finding.UNRESOLVED_SUBGRAPH) == [("billing",)]

    def test_a_kind_never_recorded_reads_as_empty_not_as_missing(self) -> None:
        # `runtime_warnings` used `getattr(runtime, name, [])` for three of the
        # seven, because it could not rely on the attribute being there.
        assert CompileDiagnostics().subjects(Finding.UNKNOWN_NODE_TYPE) == []

    def test_it_knows_whether_it_has_anything_to_say(self) -> None:
        diagnostics = CompileDiagnostics()
        assert not diagnostics.any(Finding.UNRESOLVED_FUNCTION)

        diagnostics.record(Finding.UNRESOLVED_FUNCTION, "function.slugify")

        assert diagnostics.any(Finding.UNRESOLVED_FUNCTION)


class TestTheReport:
    def test_every_finding_kind_has_a_sentence(self) -> None:
        """A kind with no template would raise at the moment a user hit it —
        which is the moment least able to afford it."""
        for finding in Finding:
            assert CompileDiagnostics.sentence_for(finding)

    def test_no_sentence_leaks_an_unfilled_slot(self) -> None:
        diagnostics = CompileDiagnostics()
        for finding in Finding:
            slots = CompileDiagnostics.sentence_for(finding).count("{")
            diagnostics.record(finding, *[f"s{n}" for n in range(slots)])

        for sentence in diagnostics.warnings():
            assert "{" not in sentence and "}" not in sentence

    def test_report_order_is_enum_declaration_order(self) -> None:
        """The order the seven loops happened to be written in is now a
        property you can read off the enum."""
        diagnostics = CompileDiagnostics()
        # Recorded back to front.
        diagnostics.record(Finding.CAPABILITY_FAILED, "capability")
        diagnostics.record(Finding.UNRESOLVED_TOOL, "tool.reddit")

        first, second = diagnostics.warnings()
        assert "tool.reddit" in first
        assert "capability" in second

    def test_a_finding_is_json_safe_because_the_enum_is_str_valued(self) -> None:
        import json

        assert json.dumps(Finding.UNRESOLVED_TOOL) == '"unresolved_tool"'
