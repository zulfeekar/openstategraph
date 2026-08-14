"""The live-flow diagram, with the compiler's own words taken out.

Observed on `/chat` — the customer surface — before this existed:

    __start__   __default_error_handler__   in1   router1
    agent_general   grader_general   wf_music   out1

with edge labels `b-general` and `b-build`. A customer was reading LangGraph
node names, our `safe_name` of an author's node id, and a dunder error handler
that is not a step in anybody's workflow (reviews-2026-08-14 ticket 04).

The audience boundary already governs what a customer may read in a *frame*.
This is the same boundary applied to the picture, and it is a rendering
choice: the developer surface keeps the ids, because a developer debugging a
mount needs exactly the name the compiler used.
"""

from __future__ import annotations

from openstategraph.api.customer_graph import customer_mermaid

MERMAID = """---
config:
  flowchart:
    curve: linear
---
graph TD;
\t__start__(<p>__start__</p>)
\tagent_sql(agent_sql)
\tgrader_sql(grader_sql)
\tin1(in1)
\tout1(out1)
\trouter1(router1)
\t__default_error_handler__(<p>__default_error_handler__</p>)
\t__end__(<p>__end__</p>)
\t__start__ --> in1;
\tagent_sql --> grader_sql;
\tgrader_sql -. &nbsp;revise&nbsp; .-> agent_sql;
\tin1 --> router1;
\trouter1 -. &nbsp;b-data&nbsp; .-> agent_sql;
\tout1 --> __end__;
\tclassDef default fill:#f2f0ff,line-height:1.2
"""

DOCUMENT = {
    "nodes": [
        {"id": "in1", "type": "input.text", "title": "Question"},
        {"id": "out1", "type": "output.formatted", "title": "Answer"},
        {"id": "agent-sql", "type": "agent.llm", "title": "Data Analyst"},
        {"id": "grader-sql", "type": "route.grader", "title": "Verified?"},
        {
            "id": "router1",
            "type": "route.classifier",
            "title": "Intent",
            "data": {"branches": [{"id": "b-data", "name": "data_query"}]},
        },
    ],
    "edges": [],
}


class TestNoInternalsSurvive:
    def test_no_dunder_node_appears_at_all(self) -> None:
        out = customer_mermaid(MERMAID, DOCUMENT)

        for machinery in ("__start__", "__end__", "__default_error_handler__"):
            assert machinery not in out, machinery

    def test_an_edge_to_a_hidden_node_goes_with_it(self) -> None:
        # A dangling `--> __end__` would render as an arrow into nothing.
        out = customer_mermaid(MERMAID, DOCUMENT)

        assert "-->" in out  # real edges survive
        assert "__" not in out

    def test_a_node_reads_as_the_name_its_author_gave_it(self) -> None:
        out = customer_mermaid(MERMAID, DOCUMENT)

        assert "Data Analyst" in out
        assert "Question" in out
        assert "Verified?" in out

    def test_the_mermaid_identifiers_are_untouched(self) -> None:
        # Only the *label* changes. Rewriting identifiers would break every
        # edge line that references them, and the highlight code matches on
        # `safe_name` too.
        out = customer_mermaid(MERMAID, DOCUMENT)

        assert "agent_sql(" in out
        assert "router1(" in out

    def test_a_branch_reads_as_its_name_not_its_id(self) -> None:
        out = customer_mermaid(MERMAID, DOCUMENT)

        assert "data_query" in out
        assert "b-data" not in out

    def test_a_port_label_is_already_a_word_and_survives(self) -> None:
        # `revise` is the vocabulary, not an internal — it is the word the
        # revision loop is documented under.
        assert "revise" in customer_mermaid(MERMAID, DOCUMENT)

    def test_the_header_and_class_definitions_are_preserved(self) -> None:
        # The frontend re-tints `classDef default fill:#f2f0ff` for dark mode
        # by string replacement; dropping it would leave a light diagram in a
        # dark shell.
        out = customer_mermaid(MERMAID, DOCUMENT)

        assert out.startswith("---")
        assert "classDef default fill:#f2f0ff" in out
        assert "graph TD;" in out


class TestItDegradesQuietly:
    def test_a_node_with_no_title_keeps_a_usable_label(self) -> None:
        out = customer_mermaid(MERMAID, {"nodes": [{"id": "agent-sql", "type": "agent.llm"}]})

        # No invented name, and nothing removed — the diagram still renders.
        assert "agent_sql(" in out

    def test_an_empty_document_does_not_explode(self) -> None:
        out = customer_mermaid(MERMAID, {})

        assert "graph TD;" in out
        assert "__start__" not in out

    def test_text_that_is_not_a_diagram_is_returned_unharmed(self) -> None:
        assert customer_mermaid("", DOCUMENT) == ""
