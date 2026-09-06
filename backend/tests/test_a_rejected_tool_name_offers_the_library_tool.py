"""It asked for `web_fetch`. `tool.web-fetch` was in the library. Nothing offered it.

`every-workflow-green` 33. The transcript, in full:

    web_search  → six results, one carrying the price
    web_fetch   → Error: web_fetch is not a valid tool, try one of [...]
    answer      → Error: web_fetch is not a valid tool, try one of [...]

That is the exact case the capability rule names: **the data exists, the tool
is not on the canvas, and it is in the library.** The expected behaviour is an
offer to add `tool.web-fetch`.

Two rounds were spent instead on prompt wording, trying to persuade the model
to announce a gap it was already announcing — by *name*, in our own error
string, for a tool we ship. A prompt is the last resort. When the fix can be a
lookup, it should be a lookup: this runs whether or not the model cooperates,
and it cannot regress the way a sentence can.
"""

from __future__ import annotations

from openstategraph.api.registries import build_tool_registry
from openstategraph.compile.workflow_compiler import rejected_tool_names, suggestible_node_type

REGISTRY = build_tool_registry(None, None)


class TestReadingTheNameOutOfOurOwnError:
    def test_it_finds_the_name_the_runtime_rejected(self) -> None:
        text = "Error: web_fetch is not a valid tool, try one of [web_search, save_memory]."
        assert rejected_tool_names(text) == ["web_fetch"]

    def test_several_rejections_are_all_found(self) -> None:
        text = (
            "Error: web_fetch is not a valid tool, try one of [a].\n"
            "Error: slack_post is not a valid tool, try one of [a]."
        )
        assert rejected_tool_names(text) == ["web_fetch", "slack_post"]

    def test_the_same_name_twice_is_reported_once(self) -> None:
        text = "Error: web_fetch is not a valid tool. Error: web_fetch is not a valid tool."
        assert rejected_tool_names(text) == ["web_fetch"]

    def test_an_ordinary_tool_error_is_not_a_rejection(self) -> None:
        """A tool that ran and failed is a different thing entirely — it is
        wired, and suggesting it again is what
        `the-agent-asks-for-what-it-cannot-get` 01 exists to stop."""
        assert rejected_tool_names("Error: No recipient configured for email_send.") == []

    def test_prose_mentioning_a_tool_is_not_a_rejection(self) -> None:
        assert rejected_tool_names("I could use web_fetch here if it existed.") == []

    def test_nothing_is_not_a_crash(self) -> None:
        assert rejected_tool_names("") == []
        assert rejected_tool_names(None) == []


class TestMappingTheNameToSomethingPlaceable:
    def test_a_library_tool_resolves_to_its_node_type(self) -> None:
        assert suggestible_node_type("web_fetch", REGISTRY) == "tool.web-fetch"

    def test_another_one_resolves_too(self) -> None:
        assert suggestible_node_type("web_search", REGISTRY) == "tool.web-search"

    def test_a_name_no_tool_carries_resolves_to_nothing(self) -> None:
        """Slack has no tool. Offering the nearest entry is what ticket 29 just
        stopped; resolving to None is how this path declines."""
        assert suggestible_node_type("slack_post", REGISTRY) is None

    def test_an_empty_name_resolves_to_nothing(self) -> None:
        assert suggestible_node_type("", REGISTRY) is None

    def test_an_unsuggestible_tool_is_not_offered(self) -> None:
        """`SUGGESTIBLE_TOOL_PREFIXES` decides what may be placed by a card, and
        this path must obey the same gate the catalogue does."""
        assert suggestible_node_type("session_identity", {}) is None
