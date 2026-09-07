"""The pause said `threadId`; resume demanded `thread_id`.

`every-workflow-green` 24. A run paused at a gate and its terminal frame
published `{"node": "gate1", "candidate": …, "threadId": "run-…"}`. Copying
that field into the next documented call returned 422.

The product walks an adopter into exactly that call — `/api/runs` refuses a
paused workflow with a sentence naming the endpoint, the resume route and the
thread — so the one value that must travel between the two calls was spelled
one way on the way out and another on the way in.

The streaming frames are camelCase throughout (`activeNode`, `pathSlugs`,
`taskId`) and the request bodies are snake, so this is a convention boundary
rather than one bad field. The boundary stays where it is; what changes is that
the request **reads** the published spelling as well as its own. Tolerant in
reading, strict in trusting — `CLAUDE.md`.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from openstategraph.api.schemas import ResumeRequest

DOC = {"version": 2, "name": "x", "nodes": [], "edges": []}


class TestBothSpellingsAreAccepted:
    def test_the_documented_snake_case_still_works(self) -> None:
        req = ResumeRequest(thread_id="run-1", workflow=DOC, decision="approve")
        assert req.thread_id == "run-1"

    def test_the_spelling_the_pause_frame_publishes_works(self) -> None:
        req = ResumeRequest.model_validate(
            {"threadId": "run-1", "workflow": DOC, "decision": "approve"}
        )
        assert req.thread_id == "run-1"

    def test_both_together_agree_or_it_is_refused(self) -> None:
        """Two spellings of one value must not be allowed to disagree."""
        with pytest.raises(ValidationError):
            ResumeRequest.model_validate(
                {"thread_id": "a", "threadId": "b", "workflow": DOC, "decision": "approve"}
            )

    def test_a_matching_pair_is_fine(self) -> None:
        req = ResumeRequest.model_validate(
            {"thread_id": "run-1", "threadId": "run-1", "workflow": DOC, "decision": "approve"}
        )
        assert req.thread_id == "run-1"

    def test_neither_is_still_a_clear_error(self) -> None:
        with pytest.raises(ValidationError):
            ResumeRequest.model_validate({"workflow": DOC, "decision": "approve"})

    def test_an_unknown_field_is_still_refused(self) -> None:
        """`extra: forbid` is what caught this in the first place, and stays."""
        with pytest.raises(ValidationError):
            ResumeRequest.model_validate(
                {"thread_id": "run-1", "workflow": DOC, "decision": "approve", "nonsense": 1}
            )
