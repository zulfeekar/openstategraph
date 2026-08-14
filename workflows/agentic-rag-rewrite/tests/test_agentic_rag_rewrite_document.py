"""The revise edge that reshapes the question instead of the answer.

Gallery example 8, and the package that answers organisms-first-class 37 in the
affirmative — see AGENTS.md for the run that answers it. What is mechanical
here: the rewriter sits upstream of the retriever (because `agent.prompt` takes
one edge), the cycle closes on the rewriter, and the knowledge store contains
figures that exist nowhere but in it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]

TOPICS = {
    "escalation-paths",
    "incident-response",
    "oncall-rotation",
    "release-train",
    "support-tiers",
}


@pytest.fixture(scope="module")
def document() -> dict:
    envelope = json.loads((PACKAGE / "workflow.json").read_text())
    assert envelope["version"] == 1
    document = envelope["document"]
    assert document["version"] == 3
    return document


def _node(document: dict, node_id: str) -> dict:
    return next(n for n in document["nodes"] if n["id"] == node_id)


def _edges(document: dict) -> set[tuple[str, str, str, str]]:
    return {
        (e["source"]["nodeId"], e["source"]["portId"], e["target"]["nodeId"], e["target"]["portId"])
        for e in document["edges"]
    }


def test_the_model_is_pinned_to_ollama_cloud(document: dict) -> None:
    assert document["settings"]["model"] == "ollama:gpt-oss:120b-cloud"


def test_the_cycle_re_enters_retrieval_not_generation(document: dict) -> None:
    assert _edges(document) == {
        ("in1", "text", "rewrite1", "prompt"),
        ("rewrite1", "result", "retrieve1", "prompt"),
        ("know1", "tool", "retrieve1", "tools"),
        ("retrieve1", "result", "grader1", "candidate"),
        ("grader1", "revise", "rewrite1", "feedback"),
        ("grader1", "pass", "out1", "result"),
    }


def test_the_revise_edge_lands_on_a_node_that_is_not_the_candidates_producer(
    document: dict,
) -> None:
    """The whole point of the example. `retrieve1` produces the candidate;
    `rewrite1` receives the feedback."""
    revise = next(e for e in document["edges"] if e["source"]["portId"] == "revise")
    candidate = next(e for e in document["edges"] if e["target"]["portId"] == "candidate")
    assert revise["target"]["nodeId"] == "rewrite1"
    assert candidate["source"]["nodeId"] == "retrieve1"
    assert revise["target"]["nodeId"] != candidate["source"]["nodeId"]


def test_the_rewriter_is_upstream_of_the_retriever(document: dict) -> None:
    """`agent.prompt` is `maxConnections: 1`, so the retriever's prompt IS the
    rewritten question. A rewriter beside the retriever could hand it nothing."""
    assert ("rewrite1", "result", "retrieve1", "prompt") in _edges(document)


def test_the_rewriter_is_told_to_translate_answer_feedback_into_a_question(
    document: dict,
) -> None:
    """The condition attached to organisms-37's 'yes': a grader writes about an
    answer, and a node on a `feedback` port must be told to turn that into a
    different question. Without this the edge is legal and mismatched."""
    prompt = _node(document, "rewrite1")["data"]["systemPrompt"].lower()
    assert "ask a different question" in prompt


def test_the_knowledge_store_holds_exactly_the_topics_both_prompts_name(
    document: dict,
) -> None:
    on_disk = {p.stem for p in (PACKAGE / "knowledge").glob("*.md")}
    assert on_disk == TOPICS
    for node_id in ("rewrite1", "retrieve1"):
        body = _node(document, node_id)["data"]["systemPrompt"]
        for topic in TOPICS:
            assert topic in body, f"{node_id} does not name {topic}"


def test_every_topic_doc_leads_with_its_index_hint(document: dict) -> None:
    """`BaseKnowledge.extract_hint` takes the first meaningful line, and that
    line is the whole free index tier — a doc opening with a heading or a blank
    gives the model a topic with no reason to pick it."""
    def squash(text: str) -> str:
        return "".join(c for c in text.lower() if c.isalnum())

    for path in sorted((PACKAGE / "knowledge").glob("*.md")):
        first = path.read_text().splitlines()[0].strip()
        assert first and not first.startswith(("#", "<!--")), path.name
        # The hint must name its own topic — compared with punctuation and
        # hyphens squashed out, because the doc spells it as English
        # ("On-call rotation") and the topic key is the file stem
        # (`oncall-rotation`); `BaseKnowledge.normalize` draws the same
        # distinction one layer down.
        assert squash(path.stem) in squash(first), path.name


def test_the_retriever_is_forbidden_from_answering_from_memory(document: dict) -> None:
    """Northwind Robotics is fictional, so a plausible answer with no quoted
    figure is an invented one. This is the sentence that makes the grader's
    grounding rule enforceable rather than hopeful."""
    prompt = _node(document, "retrieve1")["data"]["systemPrompt"].lower()
    assert "you have no memory of it" in prompt
    assert "the handbook does not say" in prompt


def test_the_grader_treats_a_non_answer_as_a_failure(document: dict) -> None:
    criteria = _node(document, "grader1")["data"]["criteria"].lower()
    assert "'the handbook does not say' is a failure" in criteria
    assert _node(document, "grader1")["data"]["rulesMode"] == "extend"


def test_the_budget_buys_whole_laps(document: dict) -> None:
    """Both agents increment the one graph-wide `attempts` counter, so a lap
    here costs two. An odd ceiling would strand half a lap. Gallery ticket 21."""
    cap = int(_node(document, "grader1")["data"]["maxAttempts"])
    assert cap >= 4 and cap % 2 == 0
