"""What the machinery already says must reach the developer — ticket 39.

`LockedPromptSections` exists because of the original `RouterNode` bug: an
editable field pre-filled with the output contract, cleared by the first person
who wrote their own rules. The fix was to show the locked text read-only beside
the editable field. `GET /api/node-contracts` publishes it, and its docstring
promises *"the editor can show a developer what the machinery already says …
instead of letting them duplicate or contradict it."*

For `agent.llm` — the most-placed node in the product — it published nothing,
and the panel therefore rendered nothing, while 289 characters of honesty and
tool-discipline rules were prepended to every agent's prompt. Both of the two
fields it published (`preamble`, `contract`) are empty for an agent **by
design**: an agent legitimately answers free-form, so the base imposes no
output contract. Its non-editable layer is `PROMPT.default_rules`, which
appeared in no route and no MCP payload.

The one family whose locked content is exclusively `default_rules` was the one
family whose locked content the read-only surface could not show — and it is
the family where duplicating hurts most, since that block exists because an
agent with no rules answered a database question from parametric memory.

**A third section, not a widened definition of "locked".** `default_rules` is
replaceable — a developer can switch to replace mode — so labelling it "locked ·
runs first" would be untrue. It is published as its own field and labelled as a
default the developer's rules extend.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app

#: Every family the route claims to cover.
FAMILIES = ("agent.llm", "route.classifier", "route.grader", "orchestrate.supervisor")


@pytest.fixture(scope="module")
def contracts() -> dict:
    return TestClient(create_app()).get("/api/node-contracts").json()


class TestEveryFamilyPublishesWhatItLocks:
    def test_the_agent_publishes_its_default_rules(self, contracts: dict) -> None:
        agent = contracts["agent.llm"]

        assert agent["default_rules"].strip(), "the agent's only non-editable layer"
        # Still empty, and still correct: an agent answers free-form.
        assert agent["preamble"] == ""
        assert agent["contract"] == ""

    @pytest.mark.parametrize("family", FAMILIES)
    def test_no_family_publishes_three_empty_strings(self, contracts: dict, family: str) -> None:
        """The route's promise, stated as a test rather than as a docstring.

        A family with nothing in any of the three fields is one whose developer
        is typing beside a panel that renders nothing — which is the defect,
        whichever family it happens to.
        """
        sections = contracts[family]

        assert any(sections[key].strip() for key in ("preamble", "contract", "default_rules"))

    def test_what_it_publishes_is_what_the_class_holds(self, contracts: dict) -> None:
        """Served from the ladder classes, never restated here."""
        from openstategraph.abc.agent import BaseAgentNode
        from openstategraph.abc.router import BaseRouter

        assert contracts["agent.llm"]["default_rules"] == BaseAgentNode.PROMPT.default_rules
        assert contracts["route.classifier"]["preamble"] == BaseRouter.PROMPT.preamble
        assert contracts["route.classifier"]["default_rules"] == BaseRouter.PROMPT.default_rules


class TestTheMcpVocabularySaysTheSameThing:
    """`get_node_vocabulary` carries the same contract for a composing client,
    from the same classes — and carried the same hole, plus a sentence that was
    false because of it."""

    def test_it_carries_the_default_rules_too(self) -> None:
        from openstategraph.mcp_server import NodeVocabulary

        by_type = {n["type"]: n for n in NodeVocabulary().describe()["node_types"]}

        assert by_type["agent.llm"]["prompt_contract"]["default_rules"].strip()

    def test_it_no_longer_says_an_empty_contract_means_nothing_is_locked(self) -> None:
        """It said: *"An EMPTY preamble/contract means this node type locks
        nothing: its prompt is entirely yours."* For `agent.llm` both are empty
        and 289 characters are prepended anyway, so the sentence told a
        composing client the opposite of what the runtime does."""
        from openstategraph.mcp_server import NodeVocabulary

        by_type = {n["type"]: n for n in NodeVocabulary().describe()["node_types"]}
        editable = by_type["agent.llm"]["prompt_contract"]["editable"]

        assert "locks nothing" not in editable
        assert "default_rules" in editable
