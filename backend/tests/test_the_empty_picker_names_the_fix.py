"""launch-readiness/20 — the three-line onramp ends on an empty chat picker.

A fresh `init` then `serve` install has no published workflow. `/chat`'s
live-flow pane used to state the bare condition ("No workflows are published
yet") and stop, with no way out and no editor link on a surface that has no
editor in it (`docs/decisions/stranger-install-2026-08-23.md` §3). This pins
that the empty state now names the fix, in the words on the page itself
(say-it-on-the-surface/03: a fix explained only inside a panel a reader may
never open is not explained).
"""

from pathlib import Path

import openstategraph


def _chat_html() -> str:
    return (Path(openstategraph.__file__).parent / "api" / "static" / "chat.html").read_text(
        encoding="utf-8"
    )


class TestTheEmptyPickerNamesTheFix:
    def test_the_no_slug_flow_pane_still_states_the_condition(self) -> None:
        """Existing contract (test_the_demo_route_is_not_published.py) must survive."""
        body = _chat_html()
        no_slug_text = body.partition("if (!slug)")[2].partition("return")[0]
        assert "No workflows are published yet" in no_slug_text

    def test_the_empty_flow_pane_names_the_fix_and_a_way_out(self) -> None:
        body = _chat_html()
        no_slug_text = body.partition("if (!slug)")[2].partition("return")[0]

        # The instruction must be self-contained on this surface: what to do
        # (publish, from the Workflows panel) and where (the editor, linked).
        assert "open the editor" in no_slug_text
        assert "Workflows panel" in no_slug_text
        assert "Publish" in no_slug_text
        assert 'href="/"' in no_slug_text

    def test_the_fix_does_not_reintroduce_template_vocabulary(self) -> None:
        """CLAUDE.md vocabulary: "template" is the scaffold sense only; the
        reusable-definition surfaced here is a published workflow (package),
        never described here as a template."""
        body = _chat_html()
        no_slug_text = body.partition("if (!slug)")[2].partition("return")[0]
        assert "template" not in no_slug_text.lower()
