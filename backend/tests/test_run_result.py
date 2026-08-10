"""`RunResult` — the answer, which *is* a string, plus what the run produced.

**The whole test module is about one decision**: `.ask()` shipped in 0.3.0
returning a plain `str`, and `docs/adoption.md` publishes
`print(workflow.ask("..."))`. A plain dataclass with `__str__` would cover
`print()` and f-strings and silently break `.strip()`, `+`, `json.dumps`,
`re.search` and `isinstance(x, str)` — breakages that appear at run time in
somebody else's service, months later, not at import.

So every test below that asserts a `str` behaviour is a back-compat test, and
each one of them **fails for a non-`str` object**. That is the point: this file
is the evidence for the subclass-`str` trade-off recorded in
`docs/decisions/framework-packaging.md` §3.2(b).
"""

from __future__ import annotations

import copy
import json
import pickle
import re

from openstategraph import RunResult


def result(answer: str = "42 invoices") -> RunResult:
    return RunResult(
        answer,
        decisions={"router1": "billing"},
        outputs={"agent1": "42 invoices"},
        warnings=["tool.nowhere is unresolved"],
        attempts=2,
    )


class TestItIsAString:
    """Each of these fails for a bare object with `__str__`."""

    def test_isinstance_str(self) -> None:
        assert isinstance(result(), str)

    def test_equality_with_a_plain_string(self) -> None:
        assert result() == "42 invoices"

    def test_string_methods(self) -> None:
        assert RunResult("  padded  ").strip() == "padded"
        assert result().upper() == "42 INVOICES"

    def test_concatenation(self) -> None:
        assert "answer: " + result() == "answer: 42 invoices"

    def test_json_dumps(self) -> None:
        assert json.dumps({"a": result()}) == '{"a": "42 invoices"}'

    def test_regex(self) -> None:
        assert re.search(r"\d+", result()).group() == "42"

    def test_len_and_slicing(self) -> None:
        assert len(result()) == len("42 invoices")
        assert result()[:2] == "42"

    def test_it_is_falsy_when_empty(self) -> None:
        """`if not workflow.ask(q):` is how a caller checks for no answer."""
        assert not RunResult("")


class TestItCarriesTheRun:
    def test_answer_is_the_string_itself(self) -> None:
        assert result().answer == "42 invoices"
        assert result().answer == str(result())

    def test_decisions_outputs_warnings_attempts(self) -> None:
        run = result()

        assert run.decisions == {"router1": "billing"}
        assert run.outputs == {"agent1": "42 invoices"}
        assert run.warnings == ["tool.nowhere is unresolved"]
        assert run.attempts == 2

    def test_the_defaults_are_empty_not_none(self) -> None:
        """A caller iterating `.warnings` must never meet `None`."""
        bare = RunResult("hi")

        assert bare.decisions == {} and bare.outputs == {}
        assert bare.warnings == [] and bare.attempts == 0

    def test_repr_shows_the_answer_and_the_extras(self) -> None:
        assert "42 invoices" in repr(result())
        assert "attempts" in repr(result())


class TestItSurvivesCopyingAndPickling:
    """A `str` subclass with attributes needs `__reduce__` or the attributes
    silently vanish — which is worse than crashing, because the object still
    looks right."""

    def test_pickle_round_trip(self) -> None:
        restored = pickle.loads(pickle.dumps(result()))

        assert restored == "42 invoices"
        assert restored.decisions == {"router1": "billing"}
        assert restored.attempts == 2

    def test_deepcopy_round_trip(self) -> None:
        restored = copy.deepcopy(result())

        assert restored.outputs == {"agent1": "42 invoices"}
        assert restored.warnings == ["tool.nowhere is unresolved"]
