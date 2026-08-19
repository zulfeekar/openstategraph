"""The customer saw the machine's scaffolding.

`every-workflow-green` 15. `classifier-router-qa`, asked its own documented
question, answered:

    I'm not able to give the current time in Tokyo because I don't have a tool
    that can retrieve real-time information. {"nodeType": "tool.web-search",
    "attachTo": "agent-world", "port": "tools", ...}

The model emitted the suggestion without the ```suggestion fence, so
`split_suggestion` did not see it. `split_suggestion`'s own docstring promises
"a customer's answer therefore cannot contain one" — and it did. The developer
also lost the card, because nothing reached the developer channel.

The tolerance has to be narrow. This product prints JSON as prose all the time
— SQL results, and `workflow-architect` answers *with an entire workflow
document* — so only an object carrying the suggestion's own required keys may
be taken.
"""

from __future__ import annotations

import json

from openstategraph.developer_channel import split_suggestion

SUGGESTION = {
    "nodeType": "tool.web-search",
    "attachTo": "agent-world",
    "port": "tools",
    "label": "Web search for current time",
    "reason": "Need up-to-date time data",
}


class TestTheFencedFormIsUnchanged:
    def test_a_fenced_suggestion_still_splits(self) -> None:
        answer = "No tool for that.\n\n```suggestion\n" + json.dumps(SUGGESTION) + "\n```"
        prose, found = split_suggestion(answer)
        assert found == SUGGESTION
        assert "nodeType" not in prose

    def test_an_answer_with_no_suggestion_is_untouched(self) -> None:
        assert split_suggestion("Rock earns the most, $826.65.") == (
            "Rock earns the most, $826.65.",
            None,
        )


class TestTheUnfencedForm:
    def test_it_is_taken_out_of_the_prose(self) -> None:
        answer = (
            "I'm not able to give the current time in Tokyo because I don't have "
            "a tool that can retrieve real-time information. " + json.dumps(SUGGESTION)
        )
        prose, found = split_suggestion(answer)
        assert found == SUGGESTION
        assert "nodeType" not in prose
        assert "Tokyo" in prose

    def test_the_prose_survives_intact(self) -> None:
        answer = "Before. " + json.dumps(SUGGESTION) + " After."
        prose, found = split_suggestion(answer)
        assert found == SUGGESTION
        assert "Before." in prose and "After." in prose
        assert "nodeType" not in prose

    def test_an_answer_that_is_only_a_suggestion_still_says_something(self) -> None:
        prose, found = split_suggestion(json.dumps(SUGGESTION))
        assert found == SUGGESTION
        assert prose.strip()


class TestOrdinaryJsonIsNotEaten:
    """The narrowness is the safety, and it is the part most likely to regress."""

    def test_a_workflow_document_is_left_alone(self) -> None:
        """`workflow-architect` answers with one of these. It has no `attachTo`."""
        document = {
            "version": 2,
            "name": "Customer Complaint Handling",
            "nodes": [{"id": "in", "type": "input.text"}],
            "edges": [],
        }
        answer = "Here is the workflow:\n" + json.dumps(document)
        prose, found = split_suggestion(answer)
        assert found is None
        assert json.dumps(document) in prose

    def test_a_json_result_row_is_left_alone(self) -> None:
        answer = 'The top genre: {"Genre": "Rock", "Revenue": 826.65}'
        assert split_suggestion(answer) == (answer, None)

    def test_an_object_missing_attach_to_is_not_a_suggestion(self) -> None:
        partial = {"nodeType": "tool.web-search", "label": "Web search"}
        answer = "Consider " + json.dumps(partial)
        assert split_suggestion(answer) == (answer, None)
