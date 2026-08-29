"""`Enter` did not send in `/chat`'s composer (launch-readiness/36).

Reproduced with a real keydown, not a screenshot: dispatching a Return
keypress that mirrors what some real input paths actually deliver — a
keydown whose `key`/`code` are never populated, carrying only
`keyCode === 13` (verified live in the browser tool used for this session's
diagnosis: `event.key === ""`, `event.keyCode === 0` on the automation's own
synthetic press for comparison, while a genuine Return from Chrome's DOM
carries `keyCode === 13`) — showed the text sitting untouched in the box and
no `POST /api/runs/stream`, exactly as the ticket describes. The handler
checked `e.key === "Enter"` only, so any Return whose `key` is not populated
was silently dropped.

Source assertions, for the reason `test_chat_picker_disambiguates.py`
records: `chat.html` is a dependency-free page with no JS test harness in
this repository, and the alternative to pinning it here is pinning it
nowhere.
"""

from __future__ import annotations


def _page() -> str:
    from openstategraph.api.chat_page import chat_page_html

    return chat_page_html()


def _keydown_handler() -> str:
    page = _page()
    start = page.index('$("msg").addEventListener("keydown"')
    return page[start : page.index("});", start) + 3]


class TestEnterSendsInTheComposer:
    def test_the_enter_check_tolerates_an_unpopulated_key(self) -> None:
        body = _keydown_handler()

        # `e.key` alone is not enough: accept the keyCode fallback too, so a
        # Return whose `key`/`code` never got populated still sends.
        assert 'e.key === "Enter" || e.keyCode === 13' in body
        assert "!e.shiftKey" in body
        assert "e.preventDefault();" in body

    def test_shift_enter_is_still_excluded(self) -> None:
        body = _keydown_handler()

        assert "&& !e.shiftKey" in body


class TestTheComposerSaysWhichKeySends:
    """`/chat` bound Enter and never said so; the Ask panel says so and does.

    launch-readiness/173 re-filed 36 after a second stranger run, and the
    binding turned out to be intact on both surfaces — the report was an
    artifact of the automation's `Return` key name, which arrives with no
    identity at all (`key: ""`, `code: ""`, `keyCode: 0`), while its `Enter`
    name arrives populated and sends. What survived the investigation is the
    one thing 173's "Done when" asks for that was genuinely missing: an
    invisible convention. The editor's Ask panel tells a developer *"Type a
    question above, then press Send or Enter"* on its Send control; `/chat`,
    the surface a non-developer meets first, said nothing on either control.

    An inconsistency between the two surfaces is worse than either
    behaviour, so the customer surface gets the sentence too.
    """

    def _send_button(self) -> str:
        page = _page()
        start = page.index('<button id="send"')
        return page[start : page.index(">", start) + 1]

    def test_the_send_control_names_the_key_that_sends(self) -> None:
        assert "Enter" in self._send_button()

    def test_it_names_the_key_that_does_not(self) -> None:
        # Shift+Enter is the half a multi-line composer needs stated: a
        # reader told only "Enter sends" has been told their newline is
        # unreachable.
        assert "Shift" in self._send_button()
