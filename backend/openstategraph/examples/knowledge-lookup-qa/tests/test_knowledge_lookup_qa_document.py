"""Retrieval, wired and reachable — checked without calling a model.

Gallery example 15. Two things are settled here:

- **The binding.** One `tool.knowledge-lookup`, on one agent's `tools` bus,
  and no loop or router to confuse the picture. `tool.knowledge-lookup` is the
  only node type with `maxInstances: 1` (`src/nodes/tools/PlatformToolsNode.ts`)
  — a second one would be a second name for one store — and the document-level
  version of that rule is asserted here.
- **The store.** The package's own `knowledge/` really holds the topics the
  smoke answer cites, every doc yields an index hint, and every topic the docs
  cross-reference exists. That last one is the store's own contract:
  progressive disclosure only works if a topic named inside one doc can be
  fetched next.

Whether the model reads what it fetched is what the smoke run and its
`threads show` recording are for.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.knowledge import PackageKnowledge
from openstategraph.package_testing import (
    assert_document_shape,
    load_document,
)

PACKAGE = Path(__file__).resolve().parents[1]

#: The two figures the recorded smoke answer quotes. Fictional on purpose:
#: they are either in these files or invented, with no third possibility.
SMOKE_FACTS = ("every 20 years", "below 70 %")


@pytest.fixture(scope="module")
def doc() -> dict:
    return load_document(PACKAGE)


@pytest.fixture(scope="module")
def knowledge() -> PackageKnowledge:
    # The convention form: `<package>/knowledge` is what every canvas-authored
    # workflow uses, and it is the one the runtime binds.
    return PackageKnowledge(PACKAGE)


def test_the_baseline_every_package_shares(doc: dict) -> None:
    """Model pin, unique ids, no dangling edge, and a warning-free
    plan — `openstategraph.package_testing` owns the reasons."""
    assert_document_shape(doc)


def test_it_is_four_nodes_no_loop_no_router(doc: dict) -> None:
    assert [n["type"] for n in doc["nodes"]] == [
        "input.text",
        "tool.knowledge-lookup",
        "agent.llm",
        "output.formatted",
    ]
    assert not any(e["target"]["portId"] == "feedback" for e in doc["edges"])


def test_the_store_is_bound_to_the_agent(doc: dict) -> None:
    plan = WorkflowCompiler().plan(doc)
    assert plan.tool_bindings == {"answer1": ["t-knowledge"]}


def test_there_is_exactly_one_knowledge_node(doc: dict) -> None:
    """`maxInstances: 1`, as a document can state it."""
    knowledge_nodes = [n for n in doc["nodes"] if n["type"] == "tool.knowledge-lookup"]
    assert len(knowledge_nodes) == 1


class TestTheStoreIsThePackage:
    def test_the_five_topics_are_on_disk(self, knowledge: PackageKnowledge) -> None:
        assert sorted(entry.name for entry in knowledge.topics()) == [
            "accessions",
            "duplication",
            "storage-tiers",
            "viability-testing",
            "withdrawals",
        ]

    def test_every_topic_yields_an_index_hint(self, knowledge: PackageKnowledge) -> None:
        """The free index tier is self-assembling: the hint IS the doc's first
        meaningful line. A doc that opens with a heading has no hint and the
        model gets a bare name to choose from."""
        for entry in knowledge.topics():
            assert entry.hint.strip(), entry.name
            assert len(entry.hint) > 40, entry.name

    def test_the_smoke_answers_figures_come_from_one_topic(
        self, knowledge: PackageKnowledge
    ) -> None:
        body = knowledge.lookup("viability-testing")
        assert "20 years" in body
        assert "below 70 %" in body

    def test_every_cross_referenced_topic_exists(self, knowledge: PackageKnowledge) -> None:
        """Progressive disclosure only pays off if the next hop is fetchable.

        The docs point at each other in one fixed form — a parenthesised
        backticked topic name, `(`storage-tiers`)` — so this reads
        cross-references and not every backticked word. Each one must resolve,
        or the model follows a reference into an error.
        """
        names = {entry.name for entry in knowledge.topics()}
        found = 0
        for path in sorted((PACKAGE / "knowledge").glob("*.md")):
            for referenced in re.findall(r"\(`([a-z][a-z-]+)`\)", path.read_text()):
                found += 1
                assert referenced in names, f"{path.name} points at unknown topic {referenced!r}"
        assert found >= len(names), "the store stopped cross-referencing itself"
