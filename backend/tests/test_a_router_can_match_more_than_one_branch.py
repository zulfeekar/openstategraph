"""A question that matches two desks lost one.

`every-workflow-green` 27. Asked *"what do you know about music? what is your
skill? do you have a name?"* — three questions in one message, which is how
people write — `ops-desk` ran one desk and dropped the rest, silently.

The runtime has always supported this: LangGraph's own docs say a conditional
edge may return a list and that "all of those destination nodes will be
executed in parallel as part of the next superstep", and ship a recipe of
exactly this shape. Only this compiler insisted on one.

**Opt-in, never the default.** Routing one ticket to one desk is a real pattern
that `support-triage` depends on, and broadcasting would multiply model cost by
the branch count. `match_mode="best"` is the default and every shipped workflow
keeps behaving exactly as it does today.
"""

from __future__ import annotations

from openstategraph.abc.router import Branch, Router

BRANCHES = [
    Branch(id="b-data", name="data"),
    Branch(id="b-policy", name="policy"),
    Branch(id="b-reply", name="reply"),
]


def _router(match_mode: str = "best") -> Router:
    return Router(branches=BRANCHES, fallback="policy", rules="", match_mode=match_mode)


class TestBestModeIsUnchanged:
    """The regression net for every workflow that ships today."""

    def test_one_clean_match_is_that_branch(self) -> None:
        assert _router().normalise("data").branch == "data"

    def test_two_matches_still_fall_back(self) -> None:
        verdict = _router().normalise("this is about data and policy")
        assert verdict.branch == "policy"
        assert verdict.fell_back is True

    def test_the_default_is_best_behaviour(self) -> None:
        """Asserted through behaviour, not an attribute: the mode is private,
        because a public one would grow this class's surface for configuration
        only `normalise` reads."""
        plain = Router(branches=BRANCHES, fallback="policy", rules="")
        assert plain.normalise("data and policy").fell_back is True

    def test_best_mode_reports_a_single_branch_list(self) -> None:
        """`branches` is always populated, so readers need no mode check."""
        assert _router().normalise("data").branches == ["data"]


class TestAllModeKeepsEveryMatch:
    def test_two_matches_are_both_returned(self) -> None:
        verdict = _router("all").normalise("this is about data and policy")
        assert set(verdict.branches) == {"data", "policy"}
        assert verdict.fell_back is False

    def test_the_primary_branch_is_one_of_them(self) -> None:
        """`decisions[node]` keeps naming a single branch — the compiler routes
        on that exact label, and ticket 09 is why it must not be widened."""
        verdict = _router("all").normalise("data and policy")
        assert verdict.branch in verdict.branches

    def test_one_match_behaves_exactly_as_best_does(self) -> None:
        verdict = _router("all").normalise("data")
        assert verdict.branch == "data"
        assert verdict.branches == ["data"]

    def test_the_order_follows_the_declared_branches(self) -> None:
        """Not the order the model happened to mention them in — the document's
        order is the one a reader can predict."""
        verdict = _router("all").normalise("policy and data")
        assert verdict.branches == ["data", "policy"]


class TestToleranceIsNotTrust:
    def test_an_invented_branch_still_falls_back_in_both_modes(self) -> None:
        for mode in ("best", "all"):
            verdict = _router(mode).normalise("astronomy")
            assert verdict.branch == "policy"
            assert verdict.fell_back is True
            assert verdict.branches == ["policy"]

    def test_an_empty_answer_still_falls_back_in_both_modes(self) -> None:
        for mode in ("best", "all"):
            assert _router(mode).normalise("   ").fell_back is True


class TestThePromptAsksForWhatTheModeCanUse:
    """A parser that accepts several names is useless if the prompt demands one.

    `every-workflow-green` 17 is the record of getting this backwards: the
    orchestrator's prompt taught the model a format its own parser could not
    read. The two must agree, so the mode has to reach the prompt.
    """

    def test_best_mode_still_asks_for_exactly_one(self) -> None:
        prompt = _router().resolve_system_prompt().lower()
        assert "exactly one branch name" in prompt

    def test_all_mode_invites_more_than_one(self) -> None:
        prompt = _router("all").resolve_system_prompt().lower()
        assert "exactly one branch name" not in prompt
        assert "every branch" in prompt

    def test_all_mode_still_forbids_prose(self) -> None:
        """Tolerant reading does not license a chatty contract — the parser
        still matches names, and a sentence is still the harder case."""
        prompt = _router("all").resolve_system_prompt().lower()
        assert "no explanation" in prompt

    def test_the_branch_list_is_present_in_both(self) -> None:
        for mode in ("best", "all"):
            prompt = _router(mode).resolve_system_prompt()
            assert "data" in prompt and "policy" in prompt and "reply" in prompt

