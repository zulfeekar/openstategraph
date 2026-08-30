"""`resolve.vocabulary` — the prefetch step, lifted into a node type.

`launch-readiness/135`. The capability existed as one package's private
function (a private NL2SQL package's `functions/prefetch_context.py`) and
could not be
placed, configured or seen. What is lifted here is deliberately **vocabulary
only** — *"what is this word called here?"* — because the measurement that
scoped the ticket found the index's table coverage was 3 of 38 while its
glossary rows are language facts that port regardless of which store holds
the rows.

Two properties of the prior art are hard-won and pinned here so a rewrite
cannot lose them:

- **Rank, then cap** (`launch-readiness/130`). Merging by arrival meant the
  deciding entry reached the model only when its search won a thread race —
  the axis was chosen by thread scheduling before the model ran.
- **Concurrency preserved.** Ranking what lands is not a licence to
  serialise the searches.

And the constraint that made the ticket `L` rather than `M`:

> **A prefetch that finds nothing looks exactly like a term that is not
> ambiguous.**

So every test below that exercises a miss asserts what the node *said about
its coverage*, not merely that it found nothing.
"""

from __future__ import annotations

import threading

from openstategraph.abc.tool_notes import Substitution
from openstategraph.vocabulary import (
    DEFAULT_MAX_ENTRIES,
    derive_phrases,
    resolve_vocabulary,
)

MEG = {
    "id": "glossary:geography:meg",
    "term": "MEG",
    "axis": "load_shipping_region_v2",
    "canonical_value": "Middle East Gulf (MEG)",
    "aliases": ["MEG", "Middle East Gulf", "Arabian Gulf", "Persian Gulf"],
    "note": "The loading trade region.",
    "predicate": "WHERE load_shipping_region_v2 = 'Middle East Gulf (MEG)'",
}

HORMUZ = {
    "id": "glossary:geofence:hormuz",
    "term": "Hormuz",
    "axis": "geofence_id",
    "canonical_value": "persian-gulf-entry",
    "aliases": ["Hormuz", "Strait of Hormuz"],
    "note": "There is no literal 'Hormuz' value anywhere.",
}


def _source(rows_by_phrase: dict[str, list], *, declares=None, fails: set[str] | None = None):
    """A vocabulary source with the contract the node asks of one."""

    def source(phrase: str):
        if fails and phrase in fails:
            raise RuntimeError("index unreachable")
        return rows_by_phrase.get(phrase, [])

    if declares is not None:
        source.coverage = lambda: list(declares)  # type: ignore[attr-defined]
    return source


class TestRankThenCap:
    def test_every_searchs_best_entry_places_before_any_searchs_second(self) -> None:
        """Reciprocal rank fusion's defining property, and the fix for 130.

        `slow` returns the deciding entry at rank 1; `fast` returns two others.
        Merged by arrival, the entry that decides the axis is last and the cap
        can drop it. Merged by rank, a rank-1 hit outranks every rank-2.
        """
        a = {"id": "a", "term": "A", "axis": "x", "canonical_value": "A"}
        b = {"id": "b", "term": "B", "axis": "x", "canonical_value": "B"}
        source = _source({"one": [a, b], "two": [MEG]})

        resolution = resolve_vocabulary(
            "one two", source, phrases=("one", "two"), max_entries=DEFAULT_MAX_ENTRIES
        )

        ids = [entry.entry_id for entry in resolution.entries]
        assert ids.index("glossary:geography:meg") < ids.index("b")

    def test_the_cap_is_applied_after_the_ranking_never_before(self) -> None:
        many = [{"id": f"n{i}", "term": str(i), "axis": "x", "canonical_value": str(i)} for i in range(9)]
        source = _source({"one": many, "two": [MEG]})

        resolution = resolve_vocabulary(
            "one two", source, phrases=("one", "two"), max_entries=2
        )

        assert len(resolution.entries) == 2
        # MEG is the second search's rank-1, so a cap of two cannot drop it.
        assert "glossary:geography:meg" in [entry.entry_id for entry in resolution.entries]

    def test_the_order_does_not_depend_on_which_search_returned_first(self) -> None:
        """Determinism by construction: phrases are walked in sorted order."""
        released = threading.Event()

        def source(phrase: str):
            if phrase == "one":
                released.wait(timeout=2)
                return [{"id": "a", "term": "A", "axis": "x", "canonical_value": "A"}]
            released.set()
            return [MEG]

        first = resolve_vocabulary("q", source, phrases=("one", "two"), max_entries=8)
        released.clear()
        second = resolve_vocabulary("q", source, phrases=("one", "two"), max_entries=8)

        assert [e.entry_id for e in first.entries] == [e.entry_id for e in second.entries]


class TestConcurrencyIsPreserved:
    def test_the_searches_overlap_in_time(self) -> None:
        """A barrier that only trips if the calls are in flight together.

        `as_completed` in the prior art was never the bug — ranking what lands
        is the fix, and serialising the searches to get a deterministic order
        would have been the wrong one.
        """
        barrier = threading.Barrier(3, timeout=5)

        def source(phrase: str):
            barrier.wait()
            return [MEG]

        resolution = resolve_vocabulary(
            "q", source, phrases=("a", "b", "c"), max_entries=8
        )

        assert resolution.entries  # no BrokenBarrierError => all three overlapped


class TestItProducesTicket127sTuple:
    def test_a_declared_alias_is_recorded_as_a_declared_synonym(self) -> None:
        source = _source({"Which ports in the Persian Gulf?": [MEG]})

        resolution = resolve_vocabulary(
            "Which ports in the Persian Gulf?",
            source,
            phrases=("Which ports in the Persian Gulf?",),
            max_entries=8,
        )

        assert len(resolution.substitutions) == 1
        note = resolution.substitutions[0]
        assert isinstance(note, Substitution)
        assert note.user_term.lower() == "persian gulf"
        assert note.axis == "load_shipping_region_v2"
        assert note.canonical_value == "Middle East Gulf (MEG)"
        assert note.how_matched == "declared_synonym"
        assert note.changed_the_question()

    def test_the_users_own_canonical_word_is_exact_not_a_synonym(self) -> None:
        source = _source({"q": [MEG]})

        resolution = resolve_vocabulary(
            "Volumes out of Middle East Gulf (MEG) please",
            source,
            phrases=("q",),
            max_entries=8,
        )

        assert [n.how_matched for n in resolution.substitutions] == ["exact"]
        assert not resolution.substitutions[0].changed_the_question()

    def test_it_never_claims_a_model_inferred_anything(self) -> None:
        """This node runs before the model and infers nothing.

        `model_inference` is a real state and a different one; a resolver that
        emitted it would be lying about who did the work.
        """
        source = _source({"q": [MEG, HORMUZ]})

        resolution = resolve_vocabulary(
            "persian gulf", source, phrases=("q",), max_entries=8
        )

        assert resolution.substitutions
        assert all(n.how_matched != "model_inference" for n in resolution.substitutions)

    def test_an_entry_with_no_axis_yields_no_substitution(self) -> None:
        """Tolerant in reading, strict in trusting: a row that cannot say
        which axis its value lives on cannot make the claim `127` renders."""
        source = _source({"q": [{"id": "x", "term": "MEG", "aliases": ["Persian Gulf"]}]})

        resolution = resolve_vocabulary(
            "persian gulf", source, phrases=("q",), max_entries=8
        )

        assert resolution.entries and not resolution.substitutions


class TestCoverageIsReportedNotOnlyHits:
    def test_a_miss_against_a_source_that_declares_its_inventory_is_conclusive(self) -> None:
        source = _source({}, declares=["meg", "nea", "hormuz"])

        report = resolve_vocabulary(
            "dwell time in Fujairah", source, phrases=("dwell time",), max_entries=8
        ).render()

        assert "3" in report  # what the source declares it holds
        assert "meg" in report and "hormuz" in report
        assert "not covered" in report.lower()

    def test_a_miss_against_a_silent_source_says_the_silence_proves_nothing(self) -> None:
        """The whole reason this ticket is `L`. Two states — *nothing names
        this term* and *this source cannot say* — must not render alike."""
        source = _source({})

        report = resolve_vocabulary(
            "dwell time", source, phrases=("dwell time",), max_entries=8
        ).render()

        lowered = report.lower()
        assert "does not declare" in lowered
        assert "unambiguous" in lowered

    def test_the_two_kinds_of_miss_do_not_render_alike(self) -> None:
        silent = resolve_vocabulary("t", _source({}), phrases=("t",), max_entries=8).render()
        declared = resolve_vocabulary(
            "t", _source({}, declares=["meg"]), phrases=("t",), max_entries=8
        ).render()

        assert silent != declared

    def test_a_hit_still_says_what_the_source_covers(self) -> None:
        source = _source({"q": [MEG]}, declares=["meg", "nea"])

        report = resolve_vocabulary("q", source, phrases=("q",), max_entries=8).render()

        assert "Middle East Gulf (MEG)" in report
        assert "2" in report

    def test_a_failed_search_is_reported_as_a_failure_not_as_a_miss(self) -> None:
        source = _source({}, fails={"boom"})

        resolution = resolve_vocabulary("q", source, phrases=("boom",), max_entries=8)
        report = resolution.render()

        assert resolution.errors
        assert "index unreachable" in report
        assert "not a miss" in report.lower()

    def test_the_configured_sentence_appears_only_when_nothing_was_covered(self) -> None:
        sentence = "Say nothing declared this term."
        missed = resolve_vocabulary(
            "q", _source({}), phrases=("q",), max_entries=8, when_uncovered=sentence
        ).render()
        hit = resolve_vocabulary(
            "q", _source({"q": [MEG]}), phrases=("q",), max_entries=8, when_uncovered=sentence
        ).render()

        assert sentence in missed
        assert sentence not in hit

    def test_it_names_every_phrase_it_searched(self) -> None:
        report = resolve_vocabulary(
            "q", _source({}), phrases=("alpha", "beta"), max_entries=8
        ).render()

        assert "alpha" in report and "beta" in report

    def test_a_row_it_could_not_read_is_counted_rather_than_dropped_in_silence(self) -> None:
        source = _source({"q": [MEG, 12345]})

        resolution = resolve_vocabulary("q", source, phrases=("q",), max_entries=8)

        assert resolution.unreadable == 1
        assert "1" in resolution.render()


class TestPhraseDerivation:
    def test_the_whole_question_is_always_searched(self) -> None:
        assert derive_phrases("ports in the persian gulf")[0] == "ports in the persian gulf"

    def test_a_grammatical_capital_is_not_mistaken_for_a_name(self) -> None:
        """`launch-readiness/130`: "Can you find the ports…" spent a phrase
        slot searching for the word "Can"."""
        assert "Can" not in derive_phrases("Can you find the VLCCs in Fujairah?")

    def test_a_genuine_name_after_a_grammatical_capital_survives(self) -> None:
        assert "VLCCs" in derive_phrases("Which VLCCs loaded there?")

    def test_a_quoted_term_is_searched_on_its_own(self) -> None:
        phrases = derive_phrases('ports in "Persian Gulf" please')
        assert "Persian Gulf" in phrases

    def test_the_phrase_count_is_capped(self) -> None:
        question = " ".join(f"Alpha{i}" for i in range(20))
        assert len(derive_phrases(question)) <= 5


class TestTheNodeType:
    """The drawn half: a `resolve.vocabulary` node, compiled and run."""

    @staticmethod
    def _document(data: dict) -> dict:
        return {
            "version": 2,
            "name": "resolver-test",
            "nodes": [
                {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
                {
                    "id": "r1",
                    "type": "resolve.vocabulary",
                    "position": {"x": 200, "y": 0},
                    "data": data,
                },
                {
                    "id": "out1",
                    "type": "output.formatted",
                    "position": {"x": 400, "y": 0},
                    "data": {},
                },
            ],
            "edges": [
                {
                    "source": {"nodeId": "in1", "portId": "text"},
                    "target": {"nodeId": "r1", "portId": "question"},
                },
                {
                    "source": {"nodeId": "r1", "portId": "result"},
                    "target": {"nodeId": "out1", "portId": "result"},
                },
            ],
        }

    def _run(self, data: dict, question: str, functions: dict):
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        document = self._document(data)
        runtime = NodeRuntime(functions=functions)
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        final = graph.invoke({"question": question})
        return runtime, final

    def test_it_compiles_and_hands_the_resolution_downstream(self) -> None:
        _, final = self._run(
            {"source": "glossary"},
            "ports in the Persian Gulf",
            {"function.glossary": _source({"ports in the Persian Gulf": [MEG]})},
        )

        answer = final["outputs"]["r1"]
        assert "ports in the Persian Gulf" in answer  # the question survives
        assert "Middle East Gulf (MEG)" in answer
        assert "Coverage" in answer

    def test_an_unresolved_source_is_reported_never_passed_through(self) -> None:
        """The one thing this node must be unable to do quietly.

        A resolver that forwarded the question would leave the run in exactly
        the state the whole node exists to prevent: no vocabulary consulted,
        and nothing saying so.
        """
        from openstategraph.compile.diagnostics import Finding

        runtime, final = self._run({"source": "missing"}, "persian gulf", {})

        assert ("resolve.vocabulary:missing",) in runtime.diagnostics.subjects(
            Finding.UNRESOLVED_FUNCTION
        )
        answer = final["outputs"]["r1"]
        assert "nothing was consulted" in answer.lower()

    def test_the_card_caps_how_many_entries_reach_the_model(self) -> None:
        rows = [
            {"id": f"n{i}", "term": str(i), "axis": "x", "canonical_value": str(i)}
            for i in range(6)
        ]
        _, final = self._run(
            {"source": "glossary", "maxEntries": 2},
            "anything",
            {"function.glossary": _source({"anything": rows})},
        )

        listed = [line for line in final["outputs"]["r1"].splitlines() if line.startswith("- ")]
        # Two entries, plus the coverage bullets — the entries themselves are
        # the ones under the "What this vocabulary names" heading.
        block = final["outputs"]["r1"].split("### What this vocabulary names")[1]
        assert len([l for l in block.split("### Coverage")[0].splitlines() if l.startswith("- ")]) == 2
        assert listed

    def test_the_substitution_reaches_the_reader_without_the_model(self) -> None:
        """`launch-readiness/127`'s reader rail, produced by this node.

        The disclosure is not the model's to forget: the resolver records it
        against the run and the output node renders it.
        """
        from openstategraph.abc.tool_notes import notes_for_reader
        from openstategraph.vocabulary import resolve_vocabulary as _resolve

        resolution = _resolve(
            "ports in the Persian Gulf",
            _source({"ports in the Persian Gulf": [MEG]}),
            phrases=("ports in the Persian Gulf",),
            max_entries=8,
        )

        rendered = notes_for_reader(resolution.substitutions)
        assert "Persian Gulf" in rendered
        assert "Middle East Gulf (MEG)" in rendered
        assert "synonym this data declares" in rendered
