"""A workflow's stated purpose had nothing keeping it honest.

`every-workflow-green` 03. `workflow-2026`'s `settings.purpose` claimed
"classify the ticket, answer it on the matching desk, grade the reply, and let
a person decide whether it is sent" — and the document has no classifier, no
grader and no gate. Every clause was false, and the sentence is shown to
somebody deciding whether to use the package.

The owner chose: **show the real shape beside the claim.** Nobody's sentence is
rewritten and nothing is guessed at; the reader sees what a package says about
itself and what it actually contains, and judges.

The mount card already did this — `compositionSurface` returns `census`
alongside `purpose`. `openstategraph examples list` did not: it printed the
claim alone.

The shape is counted from each node type's **family segment** — the part before
the first dot in `route.grader`. That is the same fallback the editor's census
documents for itself, and it deliberately duplicates no vocabulary table: the
family is already in the type id, so the two cannot drift.
"""

from __future__ import annotations

from openstategraph.examples import document_shape


class TestTheShapeIsCountedFromTheDocument:
    def test_it_counts_families_in_a_stable_order(self) -> None:
        document = {
            "nodes": [
                {"type": "input.text"},
                {"type": "agent.llm"},
                {"type": "tool.web-search"},
                {"type": "tool.web-fetch"},
                {"type": "output.formatted"},
            ]
        }
        assert document_shape(document) == "1 input · 1 agent · 2 tool · 1 output"

    def test_it_names_the_families_the_purpose_tends_to_claim(self) -> None:
        """"grade the reply, and let a person decide" — a reader must be able
        to see at a glance that neither is there."""
        document = {"nodes": [{"type": "route.grader"}, {"type": "human.approval"}]}
        shape = document_shape(document)
        assert "route" in shape and "human" in shape

    def test_a_document_with_no_nodes_says_nothing(self) -> None:
        assert document_shape({"nodes": []}) == ""
        assert document_shape({}) == ""

    def test_a_malformed_document_does_not_raise(self) -> None:
        assert document_shape({"nodes": [{"type": None}, "junk", {}]}) == ""

    def test_a_type_with_no_dot_is_counted_whole(self) -> None:
        assert document_shape({"nodes": [{"type": "custom"}]}) == "1 custom"


class TestTheExampleCarriesIt:
    def test_every_shipped_example_can_state_its_shape(self) -> None:
        from openstategraph import examples

        for example in examples.catalogue():
            assert example.shape, f"{example.slug} produced no shape"
