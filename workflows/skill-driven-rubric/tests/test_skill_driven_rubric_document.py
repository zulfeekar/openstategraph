"""One rules layer, two readers — the shape, not the prose.

Gallery example 14. The recorded expectation is "a message obeying the skill,
and unwiring the skill changes both nodes at once". What a test can settle
without a token is the structure that makes that true:

- one `input.skill` source, wired to *two* `skill` ports;
- both readers carrying an **empty** rules field of their own, so the skill is
  not one layer among several but the only one;
- `rulesMode: replace` on both, which is what
  `SystemPrompt.effective_rules()` reads to keep the topmost layer and drop
  the ones beneath;
- and the cycle closing on `feedback`, since a grader with no revise edge is a
  filter, not a loop.

Whether the model obeys the skill is a model question. The control run in
`AGENTS.md` is the evidence for that, and a stub answering it would be theatre.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.package_testing import (
    assert_document_shape,
    load_document,
)

PACKAGE = Path(__file__).resolve().parents[1]

#: The two nodes that read the skill. One agent, one grader — deliberately
#: different families, which is the point: `skill` is a port type, not an
#: agent field.
READERS = ("write1", "grader1")


@pytest.fixture(scope="module")
def doc() -> dict:
    return load_document(PACKAGE)


def by_id(doc: dict) -> dict[str, dict]:
    return {n["id"]: n for n in doc["nodes"]}


def test_the_baseline_every_package_shares(doc: dict) -> None:
    """Model pin, unique ids, no dangling edge, and a warning-free
    plan — `openstategraph.package_testing` owns the reasons."""
    assert_document_shape(doc)


def test_there_is_exactly_one_skill_source(doc: dict) -> None:
    sources = [n for n in doc["nodes"] if n["type"] == "input.skill"]
    assert [n["id"] for n in sources] == ["skill1"]


def test_the_one_source_feeds_both_readers(doc: dict) -> None:
    """`input.skill.skill` is an unlimited output; `agent.llm.skill` and
    `route.grader.skill` are `maxConnections: 1` inputs. One-to-many is the
    shape that proves the skill layer is a layer."""
    wired = {
        e["target"]["nodeId"]
        for e in doc["edges"]
        if e["source"]["nodeId"] == "skill1" and e["source"]["portId"] == "skill"
    }
    assert wired == set(READERS)
    for edge in doc["edges"]:
        if edge["source"]["nodeId"] == "skill1":
            assert edge["target"]["portId"] == "skill"


def test_neither_reader_types_its_rules_on_the_card(doc: dict) -> None:
    """The example's headline. `write1.systemPrompt` and `grader1.criteria` are
    both empty, so there is exactly one place the rules can be coming from."""
    nodes = by_id(doc)
    assert not nodes["write1"]["data"]["systemPrompt"].strip()
    assert not nodes["grader1"]["data"]["criteria"].strip()


def test_both_readers_replace_rather_than_extend(doc: dict) -> None:
    """`effective_rules()` keeps the topmost supplied layer — defaults, then
    the inline prompt, then the skill — so `replace` makes the skill the only
    rules the model sees. The locked preamble and output contract are
    untouched by the switch either way."""
    nodes = by_id(doc)
    for node_id in READERS:
        assert nodes[node_id]["data"]["rulesMode"] == "replace"


def test_the_skill_body_is_the_house_style_and_not_a_stub(doc: dict) -> None:
    skill = by_id(doc)["skill1"]["data"]
    assert skill["skillName"] == "commit-message"
    assert skill["skillDescription"].strip()
    body = skill["instruction"]
    # The rules the control run demonstrably broke without it.
    for token in ("Imperative mood", "Bullet points", "60 characters", "blank line"):
        assert token in body


def test_the_loop_closes_on_the_feedback_port(doc: dict) -> None:
    plan = WorkflowCompiler().plan(doc)
    assert plan.conditional["grader1"] == {"pass": "out1", "revise": "write1"}
    revise = [
        e
        for e in doc["edges"]
        if e["source"]["portId"] == "revise" and e["target"]["portId"] == "feedback"
    ]
    assert len(revise) == 1


def test_the_loop_is_bounded(doc: dict) -> None:
    """`maxAttempts` is a ceiling on the graph-wide `attempts` counter, not a
    per-grader budget (gallery ticket 21). One grader, so here they coincide."""
    assert int(by_id(doc)["grader1"]["data"]["maxAttempts"]) >= 2
