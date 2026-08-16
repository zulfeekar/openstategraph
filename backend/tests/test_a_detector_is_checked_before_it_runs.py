"""A custom detector is compiled when the graph is, not when a user is waiting.

Guardrails ticket 05. `GuardrailRule.detector` is a regex a developer types on
the card, and until now nothing looked at it until `screen()` reached it —
inside a run, with a person waiting for an answer. A missing `)` raised a bare
`re.error` out of the middle of the graph: not a sentence, not a diagnostic, and
not caught by the `try` around `screen`, which named `PIIDetectionError` and
`ValueError` only.

That is exactly the failure `BaseGuardrail.resolved` already refuses to have for
its *other* two mistakes — an unimplemented strategy and a custom entity with no
pattern both raise there, deliberately, because "a card that claims a protection
which does not exist" must be loud. The third mistake had no check at all.

**What is checked, and what is honestly not.** `re.compile` establishes that a
pattern is a pattern. It does not, and cannot here, establish that matching it
terminates in reasonable time — see `detector_problem`'s docstring for why that
class is refused rather than half-mitigated with a heuristic.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from openstategraph.abc.guardrail import (
    DETECTOR_MAX_LENGTH,
    Guardrail,
    GuardrailRule,
    detector_problem,
)

ROOT = Path(__file__).resolve().parents[2]
FIELD_SET = ROOT / "src" / "nodes" / "guard" / "GuardrailNode.ts"
DETECTOR_TS = ROOT / "src" / "nodes" / "guard" / "detectorPattern.ts"


class TestWhatCountsAsInvalid:
    def test_a_pattern_that_compiles_has_no_problem(self) -> None:
        """The shipped one, from `examples/guarded-lookup/workflow.json`."""
        assert detector_problem(r"\+\d[\d\s()\-]{6,}\d") == ""

    def test_an_empty_pattern_has_no_problem(self) -> None:
        """Blank is how every builtin entity is spelled — the library brings
        the detector. Whether a *custom* entity may be blank is `resolved`'s
        question, not this one."""
        assert detector_problem("") == ""

    def test_a_pattern_that_does_not_compile_is_named_with_its_reason(self) -> None:
        problem = detector_problem("(unclosed")

        assert "(unclosed" in problem
        assert "missing )" in problem

    def test_a_pattern_past_the_cap_is_refused_by_length(self) -> None:
        problem = detector_problem("a" * (DETECTOR_MAX_LENGTH + 1))

        assert str(DETECTOR_MAX_LENGTH) in problem

    def test_the_cap_is_not_a_backtracking_defence_and_does_not_claim_to_be(
        self,
    ) -> None:
        """`(a+)+$` is eleven characters. If the cap were sold as protection
        against a pathological pattern it would be selling a story."""
        assert detector_problem("(a+)+$") == ""
        assert "backtrack" not in detector_problem("a" * (DETECTOR_MAX_LENGTH + 1))


class TestTheLadderRefusesItTheWayItRefusesTheOtherTwo:
    def test_resolving_raises_value_error(self) -> None:
        guard = Guardrail(rules=[GuardrailRule(entity="ticket", detector="(unclosed")])

        with pytest.raises(ValueError, match="ticket"):
            guard.resolved()

    def test_screening_no_longer_leaks_a_re_error(self) -> None:
        """The live defect. `re.error` is not a `ValueError`, so the compiler's
        own `except ValueError` around `screen` never saw it and the run died
        with a traceback out of the standard library."""
        guard = Guardrail(rules=[GuardrailRule(entity="ticket", detector="(unclosed")])

        with pytest.raises(ValueError) as raised:
            guard.screen("anything at all")

        assert not isinstance(raised.value, re.error)

    def test_a_good_table_still_resolves(self) -> None:
        """The control: a check that refused everything would pass every
        assertion above."""
        guard = Guardrail(rules=[GuardrailRule(entity="email", strategy="redact")])

        assert len(guard.resolved()) == 1


class TestTheCompilerSaysSoBeforeTheRun:
    @staticmethod
    def _document(detector: str) -> dict[str, object]:
        return {
            "nodes": [
                {
                    "id": "guard1",
                    "type": "guard.policy",
                    "data": {
                        "policy": [
                            {
                                "entity": "ticket",
                                "strategy": "redact",
                                "detector": detector,
                            }
                        ]
                    },
                }
            ],
            "edges": [],
        }

    def _warnings(self, detector: str) -> list[str]:
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        document = self._document(detector)
        runtime = NodeRuntime()
        WorkflowCompiler().build(document, RunState, runtime.factory(document))
        return runtime.diagnostics.warnings()

    def test_a_broken_pattern_is_a_compile_finding(self) -> None:
        found = self._warnings("(unclosed")

        assert any("guard1" in line and "(unclosed" in line for line in found), found

    def test_the_finding_says_the_row_is_not_protecting_anything(self) -> None:
        found = " ".join(self._warnings("(unclosed"))

        assert "ticket" in found

    def test_a_good_pattern_says_nothing(self) -> None:
        assert self._warnings(r"\d{3}") == []


class TestTheCardAndTheLadderAgreeOnInvalid:
    """The cross-language pin, in the style `test_guardrail_field_contract.py`
    uses for this card's other two vocabularies."""

    def test_the_card_carries_the_same_cap(self) -> None:
        source = DETECTOR_TS.read_text()
        found = re.search(r"DETECTOR_MAX_LENGTH = (\d+)", source)

        assert found, "detectorPattern.ts no longer declares DETECTOR_MAX_LENGTH"
        assert int(found.group(1)) == DETECTOR_MAX_LENGTH

    def test_the_pattern_field_refuses_a_value_before_it_is_saved(self) -> None:
        source = FIELD_SET.read_text()
        block = source.split("key: 'detector'")[1].split("},")[0]

        assert "validate: validateDetector" in block

    def test_the_extractor_can_actually_fail(self) -> None:
        source = FIELD_SET.read_text()

        assert "key: 'detector'" in source
        assert "validateDetector" in DETECTOR_TS.read_text()
