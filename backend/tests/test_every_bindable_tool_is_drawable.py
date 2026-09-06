"""A tool the runtime can bind must be drawable, or must say why not.

`every-workflow-green` — the gate the owner asked for, replacing a habit.

`tool.session-identity` was the **fifth** tool shipped with no editor card.
production-ready 61 fixed four, and the test it left behind
(`src/nodes/tools/cardlessTools.test.ts`) names those four in a literal list.
That list proves the four are drawable and says nothing at all when a fifth
appears — which is how a fifth appeared. A list is not a gate.

This is the gate. It asks the running process the same question the palette
warning asks a user, and fails the build rather than printing a sentence
somebody may or may not read.

**Adding a tool with no card is not forbidden — it is forbidden to do it
silently.** A deliberate exception goes in `WITHOUT_A_CARD` with the argument
for it written beside it, which is the same shape `CLAUDE.md` requires of every
other number it pins: an exception with no recorded reason is a story.
"""

from __future__ import annotations

from openstategraph.api.plugin_capabilities import (
    bindable_tool_types,
    editor_renderable_types,
)

#: Bindable tool types that deliberately ship without an editor card.
#:
#: Empty, and that is the point: every tool this runtime can bind can be drawn
#: on a canvas. Add an entry only with the reason on the same line, and only
#: when the tool genuinely cannot be placed by hand — not merely because
#: writing the card is work.
WITHOUT_A_CARD: dict[str, str] = {}


def _missing() -> set[str]:
    renderable = editor_renderable_types()
    return {t for t in bindable_tool_types() if t and t not in renderable}


class TestNoToolIsUndrawableByAccident:
    def test_every_bindable_tool_has_an_editor_card(self) -> None:
        undeclared = _missing() - set(WITHOUT_A_CARD)
        assert not undeclared, (
            f"These tools can be bound at runtime but cannot be drawn: "
            f"{sorted(undeclared)}. Add a node definition in src/nodes/tools/ and run "
            f"`npm run generate:ports`, or record it in WITHOUT_A_CARD with the reason."
        )

    def test_the_exception_list_has_no_stale_entries(self) -> None:
        """An exception that is no longer true is worse than none.

        A tool that gained a card must leave this list, or the next reader
        believes a gap exists that does not.
        """
        stale = set(WITHOUT_A_CARD) - _missing()
        assert not stale, f"These have cards now and should leave WITHOUT_A_CARD: {sorted(stale)}"

    def test_every_exception_carries_an_argument(self) -> None:
        for tool_type, reason in WITHOUT_A_CARD.items():
            assert reason.strip(), f"{tool_type} is excepted with no reason given"
