"""Nothing in the library does it, and the user is left at a dead end.

`every-workflow-green` 34. As a user, in the editor:

> How many open pull requests are in our GitHub repo right now?

    card:   none
    answer: "I'm not able to tell you… because this workflow doesn't include a
             tool for querying the GitHub repository."

Honest, and a dead end. The rule says this is case B — **not in the library** —
and the developer should be offered a new module, interviewed, and given
something workflow-specific under `workflows/<slug>/tools/`.

The deterministic route that fixed case B's sibling (ticket 33, reading a name
the runtime refused) does not exist here: the agent never called anything, so
there is nothing recorded. Only the model knows what the user wanted, so the
block it was told to emit has to actually be emitted — "none" was optional in
practice and it simply skipped it.

So the prompt requires the block **whenever blocked**, either shape, and the
handling of it stays deterministic.
"""

from __future__ import annotations

from openstategraph.compile.node_runtime import advisor_context
from openstategraph.developer_channel import capability_gap, split_suggestion

CATALOG = "- tool.web-search — searches the web"


class TestThePromptRequiresTheBlockEvenWhenDeclining:
    def test_the_block_is_not_optional_when_blocked(self) -> None:
        text = advisor_context("agent-1", CATALOG).lower()
        assert "always emit" in text or "must emit" in text

    def test_declining_is_still_a_shape_of_that_block(self) -> None:
        assert '"none"' in advisor_context("agent-1", CATALOG)


class TestReadingTheGapOutOfADecline:
    def _decline(self, reason: str) -> str:
        return (
            "I can't query GitHub.\n\n"
            '```suggestion\n{"nodeType": "none", "attachTo": "agent-1", "port": "tools", '
            f'"label": "", "reason": "{reason}"}}\n```'
        )

    def test_the_reason_is_what_is_missing(self) -> None:
        gap = capability_gap(self._decline("Needs a tool that can query the GitHub API"))
        assert gap == "Needs a tool that can query the GitHub API"

    def test_a_real_suggestion_is_not_a_gap(self) -> None:
        """A catalogue entry fits, so there is nothing to build."""
        answer = (
            "No live data.\n\n"
            '```suggestion\n{"nodeType": "tool.web-search", "attachTo": "a1", '
            '"port": "tools", "label": "Web", "reason": "live data"}\n```'
        )
        assert capability_gap(answer) is None

    def test_no_block_is_no_gap(self) -> None:
        assert capability_gap("I cannot do that.") is None
        assert capability_gap("") is None

    def test_a_decline_with_no_reason_is_still_a_gap(self) -> None:
        """A developer must be offered the door even if the model was terse."""
        assert capability_gap(self._decline("")) == ""

    def test_the_prose_is_still_clean(self) -> None:
        prose, suggestion = split_suggestion(self._decline("Needs GitHub"))
        assert suggestion is None
        assert "nodeType" not in prose
        assert "GitHub" in prose
