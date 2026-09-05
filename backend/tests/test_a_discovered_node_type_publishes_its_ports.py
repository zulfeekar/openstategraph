"""A `function.<name>` node's ports, said out loud (`osg-agent-experience/46`).

A discovered function node is minted per workflow package, so no static
catalogue can list the *types* — and until this ticket nothing published their
**shape** either. The ids existed only through `default_port_resolver`'s
unknown-type fallback, which accepts any in-port id and treats `result` alone
as the way out, so a document naming a port the editor cannot draw compiled
clean. The try-folder session found the ids by reading the compiler's source.

The shape is fixed by one factory per prefix, so it is probed and emitted with
the rest of the generated catalogue rather than typed a second time in Python.
These assertions are the three doors a composing agent actually stands at: the
generated artifact, `get_node_vocabulary`, and `openstategraph nodes`.
"""

from __future__ import annotations

from openstategraph.compile.node_catalogue import CATALOGUE


def _function_prefix() -> dict:
    entry = next(p for p in CATALOGUE.type_prefixes if p["prefix"] == "function.")
    return entry


class TestTheGeneratedCatalogueCarriesTheShape:
    def test_the_function_prefix_declares_both_ports(self) -> None:
        ports = {port["id"]: port for port in _function_prefix()["ports"]}
        assert set(ports) == {"text", "result"}
        assert ports["text"]["direction"] == "in"
        assert ports["text"]["max_connections"] == 1
        assert ports["result"]["direction"] == "out"

    def test_the_tool_prefix_declares_its_binding_port(self) -> None:
        entry = next(p for p in CATALOGUE.type_prefixes if p["prefix"] == "tool.")
        ports = {port["id"]: port for port in entry["ports"]}
        assert ports["tool"]["direction"] == "out"
        assert ports["tool"]["type"] == "tool"


class TestTheVocabularyPublishesThem:
    def test_get_node_vocabulary_carries_the_ports_not_only_a_sentence(self) -> None:
        from openstategraph.mcp_server import NodeVocabulary

        prefixes = NodeVocabulary().describe()["dynamic_type_prefixes"]
        entry = prefixes["function."]
        assert entry["hint"]
        assert [port["id"] for port in entry["ports"]] == ["text", "result"]


class TestTheTerminalDoorAnswersToo:
    def test_nodes_function_anything_prints_its_ports(self, capsys) -> None:
        from openstategraph.cli import main

        assert main(["nodes", "function.summarise"]) == 0
        out = capsys.readouterr().out
        assert "text" in out and "result" in out
        assert "functions/" in out


class TestThePageSaysIt:
    """Derived from the catalogue, never typed twice.

    `docs/ports-and-edges.md`'s static tables are already checked for coverage
    against the generated artifact (`test_the_ports_page_matches_the_catalogue`);
    these two namespaces were the part of the type system that page did not
    mention at all.
    """

    def test_ports_and_edges_names_every_prefix_and_its_ports(self) -> None:
        from pathlib import Path

        page = (
            Path(__file__).resolve().parents[2] / "docs" / "ports-and-edges.md"
        ).read_text(encoding="utf-8")
        for entry in CATALOGUE.type_prefixes:
            spelling = f"`{entry['prefix']}<name>`"
            assert spelling in page, spelling
            for port in entry["ports"]:
                assert f"`{port['id']}`" in page, (spelling, port["id"])


class TestAnOutputPrintsWhatReachesIt:
    """The other half of `osg-agent-experience/46`, decided the other way.

    The ticket offered a choice: give `output.formatted` an optional `text`
    field, or say in the docs that an Output prints what reaches it. The field
    was **not** taken, and the reason is the case that asked for it. An
    ask-back branch carries the user's own question into the Output, so a
    `text` that loses to arriving content would not have produced the sentence
    the try-folder session needed — and a `text` that wins would let a typed
    field silently discard a run's answer at the one node where "the run's
    answer" is defined. That is a design decision rather than a gap, so it is
    filed (`osg-agent-experience/55`) and the docs say what is true today.
    """

    def test_the_output_declares_no_text_field(self) -> None:
        record = next(
            node for node in CATALOGUE.nodes if node["type"] == "output.formatted"
        )
        # `maxRetries`/`timeoutSeconds`/`cacheTtlSeconds` are the graph-assembly
        # parameters every node carries; `format` is the node's own. Neither is
        # a place to type a sentence.
        assert "text" not in {field["key"] for field in record["fields"]}
        assert "format" in {field["key"] for field in record["fields"]}

    def test_the_page_says_where_a_sentence_comes_from(self) -> None:
        from pathlib import Path

        page = (
            Path(__file__).resolve().parents[2] / "docs" / "on-the-canvas.md"
        ).read_text(encoding="utf-8")
        assert "An Output prints what reaches it" in page
        assert "has no text field" in page
