"""Two ways a failed run still reads like an ordinary one — workflow-gallery 44.

The ticket walked one uncredentialed install through both supported front
doors. `workflow-gallery/49` (`8bda508`) had already split `RunResult` into
`.warnings` (the whole health report) and `.failures` (the half a script may
gate on), so the *reason* is now on the verdict channel at both doors. Two
smaller things it did not touch, and this file pins:

1. **The CLI's prefix disagrees with its own exit code.** Every line was
   printed as `warning:`, including the one that ended the run and produced
   the `1`. A reader who greps for `error:` finds nothing on a failed run.

2. **A failed node's output is a sentinel that looks like content.** The
   failure lands in `outputs` as `'[summarise1 failed after retries: …]'` —
   which is correct, downstream nodes still read *something* — but a caller
   reading `outputs` rather than `warnings` has no way to tell that string
   from an answer. `redact_failure_markers` proves the machinery to tell them
   apart exists; it was reachable only from inside the compiler.

The third and largest question the ticket asks — whether `ask()` should raise,
or `RunResult`'s truthiness change — is a Tier 1 break and is handed back to
the owner (`docs-and-gaps/09`). Nothing here changes what `print(r)` does.
"""

from __future__ import annotations

import argparse

from openstategraph.compile.workflow_compiler import failure_marker
from openstategraph.results import RunResult

_REASON = 'Provider "anthropic" has no credential — set ANTHROPIC_API_KEY in .env'


class TestThePrefixMatchesTheExitCode:
    def test_a_failure_is_printed_as_an_error(self) -> None:
        from openstategraph.cli import run_report_lines

        result = RunResult("", outputs={}, warnings=[_REASON], failures=[_REASON])
        assert run_report_lines(result) == [f"error: {_REASON}"]

    def test_a_report_that_is_not_a_failure_is_still_a_warning(self) -> None:
        """A silent node is a report about how the answer was reached."""
        from openstategraph.cli import run_report_lines

        silent = 'Node "draft1" produced no output.'
        result = RunResult("an answer", outputs={}, warnings=[silent], failures=[])
        assert run_report_lines(result) == [f"warning: {silent}"]

    def test_both_appear_and_the_failure_is_not_demoted(self) -> None:
        from openstategraph.cli import run_report_lines

        silent = 'Node "draft1" produced no output.'
        result = RunResult("", outputs={}, warnings=[_REASON, silent], failures=[_REASON])
        assert run_report_lines(result) == [f"error: {_REASON}", f"warning: {silent}"]

    def test_the_command_itself_prints_the_error_prefix(self, monkeypatch, capsys) -> None:
        """Wired, not merely available — the defect was in `cmd_run`'s loop."""
        from openstategraph import cli

        outputs = {"summarise1": failure_marker("summarise1", _REASON)}
        result = RunResult("", outputs=outputs, warnings=[_REASON], failures=[_REASON])

        class _Workflow:
            slug = "chained-summarizer"

            def ask(self, *_args, **_kwargs) -> RunResult:
                return result

        monkeypatch.setattr(cli, "_load", lambda *_a, **_k: _Workflow())
        args = argparse.Namespace(
            package="chained-summarizer",
            question="Explain what a compiler is.",
            thread_id=None,
            json=False,
        )
        assert cli.cmd_run(args) == cli.EXIT_FAILURE
        err = capsys.readouterr().err
        assert f"error: {_REASON}" in err
        assert "warning:" not in err


class TestASentinelIsNotContent:
    def test_a_failed_node_is_named_with_its_reason(self) -> None:
        outputs = {
            "in1": "Explain what a compiler is.",
            "summarise1": failure_marker("summarise1", _REASON),
        }
        result = RunResult("", outputs=outputs)
        assert result.failed_nodes == {"summarise1": _REASON}

    def test_content_is_never_named(self) -> None:
        """The narrowness is the safety: this product prints brackets as prose."""
        outputs = {
            "a1": "a real answer",
            "a2": "[summarise1 failed after retries: …] is what a marker looks like",
            "a3": "",
        }
        assert RunResult("x", outputs=outputs).failed_nodes == {}

    def test_a_clean_run_says_so(self) -> None:
        assert RunResult("hi", outputs={"a1": "hi"}).failed_nodes == {}
