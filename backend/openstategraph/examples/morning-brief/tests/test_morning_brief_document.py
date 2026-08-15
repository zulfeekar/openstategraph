"""Many sources, one report — three workers, three different tools.

Gallery example 20. What is settled here without a model:

- **One tool each.** This is the only fan-out whose workers carry tools, and
  the distinction that makes it worth building is that they carry *different*
  ones. A binding that drifted — two workers on one tool, or a worker with
  none — would still run and still produce three sections, so the shape has to
  be asserted rather than eyeballed.
- **The dispatch keys.** `archetype_key` slugifies the worker's **title**, so
  the titles are the dispatch vocabulary, and two workers whose titles slugify
  alike would shadow each other with only a plan warning to say so.
- **The one lever a worker has.** `role` never reaches the worker
  (gallery ticket 16) — it describes the worker to the *supervisor's* labelling
  call. The `skill` port is the only way to tell a worker how to answer, and
  this document uses one skill for all three.
- **The splitter.** The smoke question is a bare numbered list because
  `_NUMBERED` splits on `(?:^|\\n)` and would otherwise make a preamble line
  into subtask #1 (gallery ticket 15). That is pinned against the real regex.

The store's own contract is checked too: every topic reachable, every
cross-reference resolvable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph.abc.orchestrator import Orchestrator, archetype_key
from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.knowledge import PackageKnowledge
from openstategraph.package_testing import (
    assert_document_shape,
    load_document,
)

PACKAGE = Path(__file__).resolve().parents[1]

#: The recorded smoke question, verbatim — three numbered lines, no preamble.
SMOKE_QUESTION = (
    "1. What changed in the most recent Python release?\n"
    "2. What does our release checklist require before a tag?\n"
    "3. Which workflows exist on this platform?"
)


@pytest.fixture(scope="module")
def doc() -> dict:
    return load_document(PACKAGE)


@pytest.fixture(scope="module")
def plan(doc: dict):
    return WorkflowCompiler().plan(doc)


@pytest.fixture(scope="module")
def knowledge() -> PackageKnowledge:
    return PackageKnowledge(PACKAGE)


def test_the_baseline_every_package_shares(doc: dict) -> None:
    """Model pin, unique ids, no dangling edge, and a warning-free
    plan — `openstategraph.package_testing` owns the reasons."""
    assert_document_shape(doc)


def test_three_workers_fan_out_from_one_supervisor(plan) -> None:
    assert plan.fan_out == {
        "lead1": ["worker-web", "worker-handbook", "worker-platform"]
    }


def test_each_worker_holds_exactly_one_and_a_different_tool(plan) -> None:
    """The row's whole distinction from example 5, as an assertion."""
    assert plan.tool_bindings == {
        "worker-web": ["t-search"],
        "worker-handbook": ["t-knowledge"],
        "worker-platform": ["t-platform"],
    }
    bound = [tools[0] for tools in plan.tool_bindings.values()]
    assert len(set(bound)) == 3, "two workers ended up sharing a tool"


def test_the_three_tools_are_three_different_families(doc: dict) -> None:
    types = {n["id"]: n["type"] for n in doc["nodes"]}
    assert types["t-search"] == "tool.web-search"
    assert types["t-knowledge"] == "tool.knowledge-lookup"
    assert types["t-platform"] == "tool.platform-list-workflows"


def test_the_dispatch_keys_are_distinct(doc: dict) -> None:
    """`archetype_key` is the worker's slugified *title*, and a collision is
    resolved by first-writer-wins — one worker silently unreachable."""
    workers = [n for n in doc["nodes"] if n["type"] == "orchestrate.worker"]
    keys = [archetype_key(worker) for worker in workers]
    assert len(set(keys)) == len(keys) == 3
    assert all(key for key in keys)


def test_exactly_one_worker_is_the_default(doc: dict) -> None:
    """Where an unlabelled subtask goes. The web researcher takes it, because
    a question nobody could place is more likely to be about the world than
    about this team's rota."""
    workers = [n for n in doc["nodes"] if n["type"] == "orchestrate.worker"]
    defaults = [w["id"] for w in workers if w["data"].get("default")]
    assert defaults == ["worker-web"]


def test_no_worker_carries_a_prompt_of_its_own(doc: dict) -> None:
    """`orchestrate.worker` declares no prompt field, and `role` reaches the
    supervisor's labeller rather than the worker (gallery ticket 16). A
    `systemPrompt` typed onto a worker would be silently inert, so this pins
    that none is there and that the skill port is wired instead."""
    workers = [n for n in doc["nodes"] if n["type"] == "orchestrate.worker"]
    assert not any("systemPrompt" in w["data"] for w in workers)
    skill_targets = {
        e["target"]["nodeId"] for e in doc["edges"] if e["target"]["portId"] == "skill"
    }
    assert skill_targets == {w["id"] for w in workers}


def test_one_skill_feeds_all_three(plan) -> None:
    assert plan.skill_bindings == {
        "worker-web": ["skill1"],
        "worker-handbook": ["skill1"],
        "worker-platform": ["skill1"],
    }


def test_the_skill_says_a_refusal_is_not_an_empty_result(doc: dict) -> None:
    """The sentence that made the recorded smoke run honest when the search
    tool was being rate-limited. Without it a worker has nothing at all
    telling it what to do with a tool failure."""
    instruction = next(n for n in doc["nodes"] if n["id"] == "skill1")["data"]["instruction"]
    assert "not a tool that found nothing" in instruction


class TestTheSplitterSurvivesTheSmokeQuestion:
    def test_it_splits_into_exactly_three(self) -> None:
        assert Orchestrator().split(SMOKE_QUESTION) == [
            "What changed in the most recent Python release?",
            "What does our release checklist require before a tag?",
            "Which workflows exist on this platform?",
        ]

    def test_a_preamble_line_would_have_cost_a_subtask(self, doc: dict) -> None:
        """Why the question is a bare list. `_NUMBERED` splits on `(?:^|\\n)`,
        so a summary line above the list becomes subtask #1 — and with
        `maxSubtasks` at the list's own length the last real item is then
        dropped without a word. Gallery ticket 15."""
        with_preamble = "Give me a three-source brief.\n" + SMOKE_QUESTION
        parts = Orchestrator().split(with_preamble)
        assert parts[0] == "Give me a three-source brief."
        cap = next(n for n in doc["nodes"] if n["id"] == "lead1")["data"]["maxSubtasks"]
        assert len(parts) > cap, "the preamble would have pushed item 3 past the cap"


class TestTheHandbookIsThePackage:
    def test_the_four_topics_are_on_disk(self, knowledge: PackageKnowledge) -> None:
        assert sorted(entry.name for entry in knowledge.topics()) == [
            "gallery",
            "on-call",
            "release-checklist",
            "support-desks",
        ]

    def test_every_topic_yields_an_index_hint(self, knowledge: PackageKnowledge) -> None:
        for entry in knowledge.topics():
            assert entry.hint.strip(), entry.name
            assert len(entry.hint) > 40, entry.name

    def test_the_smoke_answers_figures_come_from_one_topic(
        self, knowledge: PackageKnowledge
    ) -> None:
        """Seven lines and six days — the two figures the recorded brief
        quotes. Both are this handbook's own and neither is guessable."""
        body = knowledge.lookup("release-checklist")
        assert "six days" in body
        assert "| 7 |" in body

    def test_every_cross_referenced_topic_exists(self, knowledge: PackageKnowledge) -> None:
        import re

        names = {entry.name for entry in knowledge.topics()}
        found = 0
        for path in sorted((PACKAGE / "knowledge").glob("*.md")):
            for referenced in re.findall(r"\(`([a-z][a-z-]+)`\)", path.read_text()):
                found += 1
                assert referenced in names, f"{path.name} points at unknown topic {referenced!r}"
        assert found >= len(names), "the handbook stopped cross-referencing itself"
