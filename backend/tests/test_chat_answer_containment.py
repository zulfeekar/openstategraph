"""An answer stays inside its card, however long one word in it is.

Ticket 27. Asked `/chat` for a URL, the customer got:

    The official documentation for LangGraph is hosted on
    the LangChain docs site at:

    https://python.langchain.com/docs/oss/python/langgra▏  <- the card edge

— clipped mid-word, with `/langgraph/overview` unreachable: the card does not
scroll horizontally at that point and the token does not wrap. The prose
around it wrapped correctly, so this is specifically the long unbroken token.

`.answer` declared neither `overflow-wrap` nor `word-break` — the editor's
`.ask__answer` does, and the two pages had simply drifted. A URL is a normal
thing for the Web Researcher branch to answer with, and so is a file path, a
long identifier or a base64 blob.

Source assertions on the page text, following
`test_terminal_frame.TestTheCustomerSurfaceHonoursTheContract`: `chat.html`
is a dependency-free page with no JS/CSS test harness in this repo, and the
alternative to pinning it here is pinning it nowhere.
"""

from __future__ import annotations

import re

import pytest


@pytest.fixture(scope="module")
def page() -> str:
    from openstategraph.api.chat_page import chat_page_html

    return chat_page_html()


def _rule(page: str, selector: str) -> str:
    """The declaration block of one CSS rule, by exact selector."""
    # Anchored at the start of a line, so `.answer pre` matches its own rule
    # rather than the tail of the shared `.answer code, .answer pre` one.
    match = re.search(r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", page)
    assert match, f"no `{selector}` rule on the page at all"
    return match.group(1)


class TestTheAnswerCardContainsItsAnswer:
    def test_a_long_unbroken_token_is_allowed_to_break(self, page: str) -> None:
        """`overflow-wrap: anywhere`, not only the legacy `word-break` alias.

        Both are declared: `word-break: break-word` is what `.ask__answer`
        already says and is the one older engines honour, `overflow-wrap:
        anywhere` is the specified behaviour and the one that also lets a
        long token shrink the line box it is in.
        """
        rule = _rule(page, ".answer")
        assert "overflow-wrap: anywhere" in rule
        assert "word-break: break-word" in rule

    def test_the_card_can_still_scroll_what_it_cannot_break(self, page: str) -> None:
        """A wide table has no break opportunity; the card must not clip it."""
        assert "overflow-x: auto" in _rule(page, ".answer")

    def test_a_code_block_wraps_rather_than_hiding_its_tail(self, page: str) -> None:
        """The ticket's lower-severity half, and the same defect.

        The fenced SQL in the Chinook answers was wider than the card and
        scrolled — with no visible scrollbar, so nothing told the reader the
        rest of the query was there. Unreadable-but-present is the same
        outcome as absent. A wrapped `SELECT` is uglier than a scrolled one
        and is the only one of the two a customer can finish reading.
        """
        rule = _rule(page, ".answer pre")
        assert "white-space: pre-wrap" in rule
        assert "overflow-wrap: anywhere" in rule

    def test_the_live_preview_wraps_too(self, page: str) -> None:
        """`.thinking` renders the same prose a few hundred milliseconds
        earlier, so a fix that stopped at the settled card would let the URL
        overflow for the whole run and then tidy itself up at the end."""
        assert "overflow-wrap: anywhere" in _rule(page, ".thinking")

    def test_the_question_bubble_contains_the_question(self, page: str) -> None:
        """Found in the screenshot that verified the fix, not in the ticket.

        A question containing a URL ran off the right edge of its own bubble
        while the answer beneath it wrapped correctly — the customer's own
        words, clipped.
        """
        assert "overflow-wrap: anywhere" in _rule(page, ".q")

    def test_the_page_never_scrolls_sideways_as_a_whole(self, page: str) -> None:
        """Containment means the overflow stays in the card that owns it."""
        assert "max-width: 100%" in _rule(page, ".answer")
