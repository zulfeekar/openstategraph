"""`/chat` described two different products at once (production-ready 55.7).

The empty state said *"I'll route it to the right workflow"* — a concierge that
chooses for you — while the composer, two inches below it, said *"Ask the
selected workflow…"* next to an explicit picker in the header.

Both sentences are true of this page, and neither is true all the time. **Auto
— let OpenStateGraph route** is the picker's first entry *only where the
`concierge` package is installed* (`state.hasAuto`, read off the
`X-Auto-Available` header on the same `?surface=chat` request rather than a
second probe — launch-readiness 34), and then it is the default; on every
other install the picker is the whole story. The defect was
that both lines were unconditional, so exactly one of them was lying at any
moment, and which one depended on something the reader could not see.

So the copy follows the selection. Pinned here rather than merely fixed,
because the sentence had a second copy inside the "New conversation" handler —
invisible until somebody pressed it, which is how the two came to disagree.

Source assertions, for the reason `test_terminal_frame.py` records: `chat.html`
is a dependency-free page with no JS test harness in this repository, and the
alternative to pinning it here is pinning it nowhere.
"""

from __future__ import annotations


def _page() -> str:
    from openstategraph.api.chat_page import chat_page_html

    return chat_page_html()


class TestTheCopyFollowsThePicker:
    def test_both_readings_exist(self) -> None:
        page = _page()

        assert "route it to the right workflow" in page
        assert "the workflow selected above" in page

    def test_which_one_shows_is_decided_by_the_selection(self) -> None:
        """`routing()` is the whole condition: Auto is offered, and chosen."""
        page = _page()

        assert "const routing = () => state.hasAuto && state.workflow ===" in page
        assert "routing() ? ROUTED_LINE : SELECTED_LINE" in page

    def test_the_composer_is_re_said_with_it(self) -> None:
        """The composer's placeholder was the other half of the contradiction,
        so it is re-said by the same function rather than left fixed."""
        page = _page()

        assert 'routing() ? "Ask anything' in page
        assert '"Ask the selected workflow' in page

    def test_the_selection_is_described_on_load_and_on_change(self) -> None:
        page = _page()

        # Once for the definition, once after the first render, once on change.
        assert page.count("describeSelection()") >= 3

    def test_the_default_wording_exists_once(self) -> None:
        """`New conversation` rebuilds the empty state from the same function
        the first paint uses, so there is one sentence to keep true, not two."""
        page = _page()

        assert page.count("the workflow selected above") == 1
        assert 'SELECTED_LINE = $("empty").querySelector("p").innerHTML' in page
        assert 'innerHTML = emptyHtml()' in page
