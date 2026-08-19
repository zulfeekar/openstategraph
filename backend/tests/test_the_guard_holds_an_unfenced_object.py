"""The streaming half of `every-workflow-green` 15.

`split_suggestion` learned to take an unfenced suggestion out of the settled
answer. `ProseGuard` did not, because it matches the ```suggestion marker and a
bare object carries none — so a customer's /chat pane still watched
`{"nodeType": "tool.web-search", "attachTo": …}` arrive token by token before
the settled answer was cleaned behind it.

The guard now also holds a `{` until it can tell what the object is:

- an object carrying **both** `nodeType` and `attachTo` is swallowed, exactly as
  a fenced one is;
- anything else is emitted whole, one chunk later than it would have been.

**The delay is the cost and it is bounded.** A token stream is a *preview*; the
settled answer is composed separately and cleaned by `split_suggestion`, so
text held here is never text the user loses — it is text they see a moment
later, or in the final answer. That is what makes a hold safe at all, and it is
why the cap below can simply give up and emit rather than needing a flush.
"""

from __future__ import annotations

import json

from openstategraph.developer_channel import ProseGuard

SUGGESTION = json.dumps(
    {
        "nodeType": "tool.web-search",
        "attachTo": "agent-world",
        "port": "tools",
        "label": "Web search",
        "reason": "no live data",
    }
)


def _stream(chunks: list[str]) -> str:
    guard = ProseGuard()
    return "".join(guard.feed(c) for c in chunks)


class TestTheFencedBehaviourIsUnchanged:
    def test_a_fence_split_across_chunks_is_still_swallowed(self) -> None:
        out = _stream(["Sorry. ", "```sugg", "estion\n", SUGGESTION, "\n```", " done"])
        assert "nodeType" not in out
        assert "Sorry." in out and "done" in out

    def test_plain_prose_passes_through_untouched(self) -> None:
        assert _stream(["Rock ", "earns ", "the most."]) == "Rock earns the most."


class TestAnUnfencedObject:
    def test_it_never_reaches_the_reader(self) -> None:
        out = _stream(["I cannot do that. ", SUGGESTION, " Sorry."])
        assert "nodeType" not in out
        assert "attachTo" not in out
        assert "I cannot do that." in out

    def test_it_is_caught_when_split_across_many_chunks(self) -> None:
        pieces = [SUGGESTION[i : i + 7] for i in range(0, len(SUGGESTION), 7)]
        out = _stream(["No tool. ", *pieces, " Done."])
        assert "nodeType" not in out
        assert "No tool." in out and "Done." in out


class TestOrdinaryJsonSurvives:
    """The narrowness is the safety — this product streams JSON as prose."""

    def test_a_result_row_is_emitted_whole(self) -> None:
        row = '{"Genre": "Rock", "Revenue": 826.65}'
        out = _stream(["Top: ", row, " end"])
        assert row in out
        assert out == "Top: " + row + " end"

    def test_a_workflow_document_survives(self) -> None:
        doc = json.dumps({"version": 2, "nodes": [{"id": "in", "type": "input.text"}]})
        out = _stream(["Here: ", doc])
        assert doc in out

    def test_an_object_with_only_one_key_is_not_a_suggestion(self) -> None:
        partial = '{"nodeType": "tool.web-search"}'
        assert partial in _stream(["Consider ", partial])

    def test_nested_braces_do_not_end_the_object_early(self) -> None:
        nested = '{"a": {"b": 1}, "c": 2}'
        assert nested in _stream([nested])


class TestItCannotSwallowTheAnswer:
    def test_an_object_that_never_closes_is_released(self) -> None:
        """A model that stops mid-object must not take the prose with it."""
        opened = '{"nodeType": "x", ' + "y" * 4000
        out = _stream(["Before ", opened])
        assert "Before " in out
        assert "y" * 100 in out
