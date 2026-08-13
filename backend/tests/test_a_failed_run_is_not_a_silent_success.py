"""A run that produced nothing exited 0 and said nothing.

Found by building the wheel and *using* it, which is the only way this was ever
going to surface: a new user's literal first `run` after `new` has no provider
credential, and got back an empty line and a success exit code.

    $ openstategraph new t --template loop
    $ openstategraph run workflows/t "what is 2+2?"
    $ echo $?
    0

The diagnosis existed the whole time — it was in `outputs`, wrapped in
`[agent1 failed after retries: Provider "ollama" has no credential — set
OLLAMA_API_KEY or OLLAMA_HOST in .env]` — and only `--json` showed it.

This is the same defect as providers-and-credentials ticket 04, on the door
that ticket missed. That one promoted node failures onto the developer channel
for `/api/runs` and `/api/runs/stream`. `load_workflow` — the Tier 1 seam an
adopter actually embeds, and the one the CLI uses — was the third door.
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.workflow_compiler import failure_marker
from openstategraph.results import RunResult


class TestTheFailureReachesTheCaller:
    def test_a_failed_node_becomes_a_warning_on_the_result(self) -> None:
        """`RunResult.warnings` is what the CLI prints and an adopter reads."""
        from openstategraph.loader import _warnings_with_node_failures

        outputs = {"agent1": failure_marker("agent1", 'Provider "ollama" has no credential')}
        warnings = _warnings_with_node_failures(["a pre-existing warning"], outputs)

        assert "a pre-existing warning" in warnings
        assert any("agent1" in warning for warning in warnings)
        assert any("ollama" in warning for warning in warnings)

    def test_a_clean_run_gains_nothing(self) -> None:
        from openstategraph.loader import _warnings_with_node_failures

        assert _warnings_with_node_failures(["only mine"], {"agent1": "a real answer"}) == [
            "only mine"
        ]

    def test_the_order_puts_the_run_s_own_failures_last(self) -> None:
        """Compile-time findings first, then what happened when it ran."""
        from openstategraph.loader import _warnings_with_node_failures

        warnings = _warnings_with_node_failures(
            ["compiled with a missing tool"], {"a1": failure_marker("a1", "boom")}
        )
        assert warnings[0] == "compiled with a missing tool"


class TestTheCliStopsCallingItSuccess:
    def _result(self, answer: str, outputs: dict[str, Any]) -> RunResult:
        return RunResult(answer, decisions={}, outputs=outputs, warnings=[], attempts=0)

    def test_a_run_that_produced_nothing_and_failed_is_a_failure(self) -> None:
        from openstategraph.cli import EXIT_FAILURE, run_exit_code

        failed = self._result("", {"a1": failure_marker("a1", "no credential")})
        assert run_exit_code(failed) == EXIT_FAILURE

    def test_an_answer_is_a_success_even_if_one_step_degraded(self) -> None:
        """"Degrade loud, never silent" — loud, but still a degrade.

        A workflow whose optional tool was missing still answered; failing the
        exit code there would make every partial run look like a crash.
        """
        from openstategraph.cli import EXIT_OK, run_exit_code

        degraded = self._result("Rock earns the most.", {"a1": failure_marker("a1", "no tool")})
        assert run_exit_code(degraded) == EXIT_OK

    def test_an_empty_answer_with_no_failure_stays_a_success(self) -> None:
        """A workflow may legitimately answer with nothing at all."""
        from openstategraph.cli import EXIT_OK, run_exit_code

        assert run_exit_code(self._result("", {"out1": ""})) == EXIT_OK
