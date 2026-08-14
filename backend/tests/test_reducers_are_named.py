"""Reducers are a named enum, which is the portability rule that was broken.

CLAUDE.md lists four guardrails that "cost nothing now and are expensive to
retrofit". The second is *"Reducers are a named enum, not arbitrary
functions"*, and it was the only one of the four not actually kept:
`merge_decisions`, `keep_max` and `keep_latest_nonempty` were plain functions
bound straight into `Annotated[...]`, with no enum, registry or name→function
map on either side — while `merge_decisions`' own docstring claimed to be "the
`merge` member" of an enum that did not exist (reviews-2026-08-14 ticket 07).

Why it matters more than tidiness: `workflow.json` is the vendor-neutral
layer, the only thing between this project and being a LangGraph front end. A
reducer written as a Python function is unserialisable and unportable in one
move. A name is data.
"""

from __future__ import annotations

import inspect

from openstategraph.compile.reducers import RESET, Reducer, reducer_for


class TestTheEnum:
    def test_a_member_serialises_as_its_own_name(self) -> None:
        # `str`-valued on purpose: this is a data contract, so a member has to
        # survive a JSON round trip with no encoder.
        assert Reducer.MERGE == "merge"
        assert Reducer.MERGE.value == "merge"

    def test_every_member_has_an_implementation(self) -> None:
        for member in Reducer:
            assert callable(reducer_for(member)), member

    def test_the_set_is_small_and_deliberate(self) -> None:
        # Adding a member is a contract change — a name a stored document may
        # carry and a second runtime must implement. The ceiling is the point.
        assert {member.value for member in Reducer} == {
            "merge",
            "max",
            "latest_nonempty",
            "add_messages",
        }


class TestTheImplementations:
    def test_merge_combines_and_clears_on_reset(self) -> None:
        merge = reducer_for(Reducer.MERGE)

        assert merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}
        assert merge({"a": 1}, {RESET: "", "b": 2}) == {"b": 2}

    def test_max_grows_and_zeroes_on_a_negative_write(self) -> None:
        keep_max = reducer_for(Reducer.MAX)

        assert keep_max(2, 1) == 2
        # The numeric spelling of RESET — this channel stays int end to end.
        assert keep_max(3, -1) == 0

    def test_latest_nonempty_refuses_an_empty_overwrite(self) -> None:
        latest = reducer_for(Reducer.LATEST_NONEMPTY)

        assert latest("kept", "") == "kept"
        assert latest("kept", "newer") == "newer"
        assert latest("kept", RESET) == ""


class TestNothingBindsAnAnonymousReducer:
    """The guard, and the reason this file is not just three unit tests.

    Fixing the three that existed is worth little if the fourth is written next
    month — which is exactly what happened to the docstring that described an
    enum nobody had built.
    """

    def test_run_state_declares_its_reducers_by_name(self) -> None:
        from openstategraph.compile import node_runtime

        source = inspect.getsource(node_runtime.RunState)

        # Every `Annotated[...]` in the state schema resolves through
        # `reducer_for`, so a stored document could name what it uses.
        for line in source.splitlines():
            if "Annotated[" not in line:
                continue
            assert "reducer_for(Reducer." in line, line.strip()
