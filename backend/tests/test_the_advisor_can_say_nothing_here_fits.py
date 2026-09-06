"""It offered an email tool to somebody asking for Slack.

`every-workflow-green` 29. On `classifier-router-qa`, asked to post to a Slack
channel, the developer channel produced:

    {"nodeType": "tool.email-send", "attachTo": "agent-howto",
     "label": "Send an email notification",
     "reason": "No Slack-send capability is available…"}

The `reason` field says there is no Slack capability, and it proposes the
nearest catalogue entry anyway — because `advisor_context` offers a catalogue
and no way to decline it. "Nothing here does this" was inexpressible, so the
model picked the closest thing.

A developer pressing **Add & re-run** then wires an email tool to an agent that
was asked to post to Slack. That is worse than no suggestion: a confident wrong
turn costing a node, an edge and a re-run to discover.

The catalogue stays exactly as strict — a suggestion still resolves against it,
which is what stops a hallucinated node type reaching the canvas. What changes
is that declining is now an answer the prompt allows and the parser recognises.
"""

from __future__ import annotations

from openstategraph.compile.node_runtime import advisor_context
from openstategraph.developer_channel import split_suggestion

CATALOG = "- tool.web-search — searches the web\n- tool.email-send — sends an email"


class TestThePromptAllowsDeclining:
    def test_it_says_none_is_an_allowed_answer(self) -> None:
        text = advisor_context("agent-1", CATALOG).lower()
        assert "none" in text

    def test_it_still_asks_for_the_plain_sentence_first(self) -> None:
        """Ticket 22's requirement — the block alone rendered as an empty reply."""
        assert "never the block alone" in advisor_context("agent-1", CATALOG)

    def test_no_catalogue_still_composes_nothing(self) -> None:
        assert advisor_context("agent-1", "") == ""

    def test_the_agents_own_id_is_still_prefilled(self) -> None:
        assert '"attachTo": "agent-1"' in advisor_context("agent-1", CATALOG)


class TestDecliningIsRecognised:
    """The parser half. A prompt that permits "none" and a splitter that only
    understands node types would be ticket 17 again — a format taught and not
    readable."""

    def test_a_declining_block_yields_no_suggestion(self) -> None:
        answer = (
            "I cannot post to Slack — this workflow has no Slack tool.\n\n"
            '```suggestion\n{"nodeType": "none", "attachTo": "agent-1", '
            '"port": "tools", "label": "", "reason": "Nothing in the catalogue posts to Slack"}\n```'
        )
        prose, suggestion = split_suggestion(answer)
        assert suggestion is None
        assert "Slack" in prose
        assert "nodeType" not in prose

    def test_a_real_suggestion_still_comes_through(self) -> None:
        """The regression net for ticket 15 — this must not get stricter."""
        answer = (
            "I need live data.\n\n"
            '```suggestion\n{"nodeType": "tool.web-search", "attachTo": "agent-1", '
            '"port": "tools", "label": "Web search", "reason": "live prices"}\n```'
        )
        _, suggestion = split_suggestion(answer)
        assert suggestion is not None
        assert suggestion["nodeType"] == "tool.web-search"

    def test_an_empty_node_type_declines_too(self) -> None:
        answer = (
            "Nothing here can do that.\n\n"
            '```suggestion\n{"nodeType": "", "attachTo": "agent-1", "port": "tools", '
            '"label": "", "reason": "no match"}\n```'
        )
        prose, suggestion = split_suggestion(answer)
        assert suggestion is None
        assert prose.strip()

    def test_declining_unfenced_is_recognised_too(self) -> None:
        """The unfenced path exists (ticket 15) and must not leak a decline."""
        answer = 'No tool for that. {"nodeType": "none", "attachTo": "agent-1"}'
        prose, suggestion = split_suggestion(answer)
        assert suggestion is None
        assert "nodeType" not in prose
