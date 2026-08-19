"""A hallucinated tool name silenced the offer it should have triggered.

`every-workflow-green` 30. In the editor, asked "What is the current price of
Bitcoin right now?", the agent called `web_search` — a name it invented — and
the runtime answered:

    Error: web_search is not a valid tool, try one of
           [save_memory, search_memory, forget_memory].

No suggestion card appeared. `advisor_context` carries a clause from
`the-agent-asks-for-what-it-cannot-get` 01:

    "A tool that ran and returned an error is NOT a missing capability: you
     have it… never suggest adding a tool you were already given."

Right for its own case — an Email Send answering "No recipient configured" was
reported three times as a missing email capability. Wrong here: the premise
*you have it* is false, and the instruction still fires.

An invented tool name is the **clearest** signal of a missing capability, and
it was the one thing guaranteed to hide one.

Only visible in the editor: `curl` suggests correctly 5 runs in 5, because
without ambient memory tools bound the agent has none and never guesses.
"""

from __future__ import annotations

from openstategraph.compile.node_runtime import advisor_context

CATALOG = "- tool.web-search — searches the web"


class TestTheTwoErrorsAreDistinguished:
    def test_a_real_tool_error_is_still_not_a_missing_capability(self) -> None:
        """The regression net. This clause exists because an agent reported a
        misconfigured Email Send as a missing email capability, three times."""
        text = advisor_context("agent-1", CATALOG)
        assert "ran and returned an error is NOT a missing capability" in text

    def test_a_name_the_runtime_rejected_is_a_missing_capability(self) -> None:
        text = advisor_context("agent-1", CATALOG).lower()
        assert "is not a valid tool" in text
        assert "missing capability" in text

    def test_the_two_are_not_the_same_sentence(self) -> None:
        """They mean opposite things and must not be collapsed by an edit."""
        text = advisor_context("agent-1", CATALOG)
        assert text.count("missing capability") >= 2

    def test_nothing_is_composed_without_a_catalogue(self) -> None:
        assert advisor_context("agent-1", "") == ""

    def test_declining_is_still_available(self) -> None:
        """Ticket 29's clause must survive — the two were written together."""
        assert '"none"' in advisor_context("agent-1", CATALOG)


class TestItNeverOverridesAnAnswerYouAlreadyHave:
    """The regression this ticket caused, caught by the owner in one chat.

    After `tool.web-search` was added it **worked** — six live results with
    real prices. The agent then called `web_fetch`, a name it does not have,
    got "not a valid tool", and answered:

        "I'm not able to give the current Bitcoin price because this workflow
         doesn't have a capability to fetch live web data."

    It had the data. The sentence added above was strong enough to override
    "only suggest when genuinely blocked", so a failed *second* call erased a
    successful *first* one. A missing capability only matters when it leaves
    you unable to answer.
    """

    def test_the_invalid_name_clause_is_conditional_on_being_blocked(self) -> None:
        text = advisor_context("agent-1", CATALOG).lower()
        assert "still cannot answer" in text

    def test_it_says_to_answer_when_another_tool_already_worked(self) -> None:
        text = advisor_context("agent-1", CATALOG).lower()
        assert "already" in text and "answer" in text

    def test_only_suggest_when_blocked_survives(self) -> None:
        assert "never when you can already answer" in advisor_context("agent-1", CATALOG)

    def test_a_tool_result_counts_as_something_you_know(self) -> None:
        """The observed failure, twice, on two different questions.

        Trace: web_search → HTTP 202, web_fetch → not a valid tool, web_search
        → **succeeded**, returning the Python 3.13 release notes. The answer:
        "I don't have the ability to look up current release notes."

        The success was the *last* event, so this is not a later failure
        erasing an earlier one — the agent simply did not treat a returned
        result as knowledge. Saying so explicitly is the only lever here.
        """
        text = advisor_context("agent-1", CATALOG).lower()
        assert "a tool returned" in text
        assert "never say you cannot look something up" in text

