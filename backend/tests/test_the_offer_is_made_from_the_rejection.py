"""The offer, made from the fact rather than from the model's cooperation.

`every-workflow-green` 33. An agent called `web_fetch`, the runtime refused it
by name, `tool.web-fetch` was in the catalogue, and no card appeared — because
the card only ever came from a fence the model had to choose to write.

`suggestion_from_rejection` builds the same payload from what the run already
recorded. It is a **fallback**, never an override: a model that did emit a
suggestion knows more about its own situation than a name lookup does, and
ticket 15's card must keep winning.
"""

from __future__ import annotations

from openstategraph.api.registries import build_tool_registry
from openstategraph.compile.workflow_compiler import suggestion_from_rejection

REGISTRY = build_tool_registry(None, None)


class TestItBuildsAPlaceableSuggestion:
    def test_a_rejected_library_tool_becomes_an_offer(self) -> None:
        offer = suggestion_from_rejection({"agent-world": ["web_fetch"]}, REGISTRY)
        assert offer is not None
        assert offer["nodeType"] == "tool.web-fetch"
        assert offer["attachTo"] == "agent-world"
        assert offer["port"] == "tools"

    def test_it_says_why_in_the_users_terms(self) -> None:
        offer = suggestion_from_rejection({"agent-world": ["web_fetch"]}, REGISTRY)
        assert "web_fetch" in offer["reason"]

    def test_the_first_resolvable_name_wins(self) -> None:
        """One card, as the fence rule has always been — and the first name is
        the one the agent reached for first."""
        offer = suggestion_from_rejection({"a1": ["slack_post", "web_fetch"]}, REGISTRY)
        assert offer["nodeType"] == "tool.web-fetch"


class TestItDeclinesRatherThanGuesses:
    def test_a_name_no_tool_carries_offers_nothing(self) -> None:
        assert suggestion_from_rejection({"a1": ["slack_post"]}, REGISTRY) is None

    def test_no_rejections_offer_nothing(self) -> None:
        assert suggestion_from_rejection({}, REGISTRY) is None
        assert suggestion_from_rejection(None, REGISTRY) is None

    def test_a_malformed_record_is_not_a_crash(self) -> None:
        assert suggestion_from_rejection({"a1": "not a list"}, REGISTRY) is None
