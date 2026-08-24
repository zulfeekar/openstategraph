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
