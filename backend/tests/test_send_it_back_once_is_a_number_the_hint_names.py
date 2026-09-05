"""The number a developer types for *send it back once*, held against the loop.

`osg-agent-experience/37`. The owner decided the grader "sends it back once".
The agent set `route.grader.maxAttempts: 1` — the natural reading of a field
labelled *Max attempts* — and got a grader that can never revise: the compiled
node computes

    judged = revisions + 1
    exhausted = judged >= cap

so a cap of 1 is exhausted on the first judgement and forces `pass`. The user
asked for one revision and got zero, silently. Found by reading the installed
source, not by any tool: `validate` and `graph` are both quiet about it,
because the document is entirely legal.

## Why the field is still called `maxAttempts`

The ticket offers a rename to `maxRevisions` and calls it the honest option. It
was measured before it was taken, and the measurement changed the answer. The
rename is not the descriptor plus a compatibility read; it is four things this
repository cannot pay for in one card:

- **`legacy_data_keys` is a tolerance list, not a migration.** It tells
  `document_checks.py` that a key no field declares is deliberate rather than a
  typo. Nothing renames a key and nothing rewrites a value — and here the value
  *must* move, because `maxAttempts: 2` and `maxRevisions: 2` are different
  numbers. A tolerance list would leave every saved document reading one more
  revision than its author wrote.
- **`guard.check` declares the same field with the same arithmetic**, as its
  own descriptor says in so many words ("same two ceilings as a grader"). A
  rename on one family and not the other is two spellings of one concept, which
  is the defect this ticket is about, one node type over.
- **`0 = never send back` cannot be expressed by the read that exists.** Both
  families read `int(data.get("maxAttempts") or self.services.max_attempts)`,
  and `0` is falsy, so the honest new floor would silently become the default.
- **Six shipped `workflows/*/workflow.json`, eight example packages and
  thirty-six test modules carry the key**, all with attempt semantics.

So the field keeps meaning *judgements*, and the descriptor is made to say the
arithmetic where a developer is standing when they choose the number.

## What this test actually pins

Not the wording — the **agreement**. It reads the number the shipped hint tells
a developer to type for one revision, out of `port_specs.json`, and then drives
the compiled grader at that number and counts the revisions. A hint that says
`1` and a runtime that revises zero times cannot both pass, and neither can a
hint that says nothing at all.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from openstategraph.compile.node_runtime import NodeRuntime
from openstategraph.compile.workflow_compiler import CompiledPlan

from conftest import drive_node

SPECS = Path(__file__).resolve().parents[1] / "openstategraph" / "compile" / "port_specs.json"

#: "2 = one revision", "type 2 to send it back once". The hint has to put a
#: bare number next to the phrase; anything looser would pass on prose that
#: merely mentions revisions, which is what the field already did.
ONE_REVISION = re.compile(
    r"\b(\d+)\b[^.]{0,80}?\b(?:one revision|sends? it back once|back once)\b"
    r"|\b(?:one revision|sends? it back once|back once)\b[^.]{0,80}?\b(\d+)\b",
    re.IGNORECASE,
)


def _field(node_type: str, key: str) -> dict[str, Any]:
    specs = json.loads(SPECS.read_text(encoding="utf-8"))
    node = next(entry for entry in specs["node_types"] if entry["type"] == node_type)
    return next(field for field in node["fields"] if field["key"] == key)


def _cap_for_one_revision(node_type: str) -> int:
    """The number this node type's own hint tells a developer to type."""
    hint = _field(node_type, "maxAttempts").get("hint") or ""
    match = ONE_REVISION.search(hint)
    assert match, (
        f"the {node_type} hint never says which number sends a candidate back exactly "
        f'once, so "send it back once" is a guess and the natural guess is wrong: {hint!r}'
    )
    return int(match.group(1) or match.group(2))


class _AlwaysRejects:
    """The only interesting judge for a budget: it never passes anything, so
    every `pass` in the transcript below is the ceiling and nothing else."""

    def grade(self, candidate: str, question: str = "") -> Any:  # noqa: ARG002
        class _Verdict:
            passed = False
            reason = "still not good enough"
            failed_check = ""
            feedback = "say more"

        return _Verdict()

    async def agrade(self, candidate: str, *, question: str = "") -> Any:
        return self.grade(candidate, question=question)


def _revisions_until_it_gives_up(monkeypatch: Any, *, cap: int, node_type: str) -> int:
    """Drive the compiled node from a standing start and count the send-backs.

    Not a simulation of the arithmetic — the arithmetic is what is on trial. The
    node is built by the real runtime and driven with the state LangGraph would
    hand it, one judgement at a time, exactly as the loop does.
    """
    runtime = NodeRuntime(model=None)
    monkeypatch.setattr(
        "openstategraph.compile.nodes.grader.Grader",
        lambda **_kwargs: _AlwaysRejects(),
    )
    node = {"id": "grader1", "type": node_type, "data": {"maxAttempts": str(cap)}}
    plan = CompiledPlan()
    plan.edges = [("agent1", "grader1")]
    plan.conditional = {"grader1": {"revise": "agent1", "pass": "out1"}}
    run = runtime._grader("grader1", node, plan)

    sent_back = 0
    for judged in range(cap + 3):
        state = {
            "question": "Which genre earns the most revenue?",
            "revisions": {"grader1": judged},
            "outputs": {"agent1": "Rock."},
        }
        result = drive_node(run, state)  # type: ignore[arg-type]
        if result["decisions"]["grader1"] != "revise":
            return sent_back
        sent_back += 1
    raise AssertionError("the grader never stopped revising")


class TestSendItBackOnce:
    def test_the_hint_names_a_number(self) -> None:
        """Red first: the shipped hint said *3 attempts allows 2 revisions* and
        left the developer to do the subtraction for the case they actually
        asked for."""
        assert _cap_for_one_revision("route.grader") >= 1

    def test_the_number_the_hint_names_revises_exactly_once(
        self, monkeypatch: Any
    ) -> None:
        """The ticket's own done-when. Configure the grader for one revision
        the way the editor tells you to, and count."""
        cap = _cap_for_one_revision("route.grader")
        assert _revisions_until_it_gives_up(monkeypatch, cap=cap, node_type="route.grader") == 1, (
            f"the hint says {cap} sends a candidate back once, and the compiled grader "
            "disagrees — which is the defect one layer up from where it was found"
        )

    def test_the_natural_reading_is_the_one_that_gets_it_wrong(
        self, monkeypatch: Any
    ) -> None:
        """Why the hint has to exist at all: `1` is what *send it back once*
        reads like, and `1` is a grader that never sends anything back. If this
        ever stops being true the hint is wrong and must be rewritten."""
        assert _revisions_until_it_gives_up(monkeypatch, cap=1, node_type="route.grader") == 0

    def test_the_guard_says_it_too(self) -> None:
        """`guard.check` carries the same field with the same arithmetic and
        says so in its own docstring. One family explaining itself and the
        other not is the same defect with a different node type."""
        assert _cap_for_one_revision("guard.check") == _cap_for_one_revision("route.grader")
