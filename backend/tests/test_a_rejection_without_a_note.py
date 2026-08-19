"""A reviewer who rejected in silence was quoted anyway.

`every-workflow-green` 11. `support-triage` paused at its gate on an
account-deletion ticket. The card said *"reject with a note saying what is
wrong"* and offered no field for one, so Reject was pressed with nothing
written. The held record then read:

    The draft was refused because the reviewer stated that identity
    verification and confirmation of the exact email address (or account ID)
    are required before proceeding.

The reviewer stated none of that. `_human_approval` wrote `feedback: ""` and
the downstream agent, handed an empty reason, supplied a plausible one and
attributed it to a person.

The editor now collects the note. This is the other half: a rejection with no
note must *say* it has no note, because an empty string is an invitation.
"""

from __future__ import annotations

from openstategraph.compile.node_runtime import rejection_feedback


class TestARejectionAlwaysCarriesAReason:
    def test_a_note_is_passed_through_untouched(self) -> None:
        assert rejection_feedback("Too formal, and it promises a date we cannot meet.") == (
            "Too formal, and it promises a date we cannot meet."
        )

    def test_silence_is_stated_rather_than_left_empty(self) -> None:
        reason = rejection_feedback("")
        assert reason
        assert "no reason" in reason.lower()

    def test_whitespace_is_silence(self) -> None:
        assert rejection_feedback("   \n ") == rejection_feedback("")

    def test_the_sentence_never_speaks_for_the_reviewer(self) -> None:
        """It reports the absence; it must not invent a position."""
        reason = rejection_feedback("").lower()
        assert "because" not in reason
        assert "stated" not in reason
