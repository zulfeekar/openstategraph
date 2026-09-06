"""`threads list`/`threads show` name how to answer a paused thread.

`workflow-gallery` 76. `openstategraph resume` (`workflow-gallery` 24,
`07ffbc3`) taught `run` to print the pause and the exact command that
finishes it — but that line only ever existed in the terminal that started
the run. `threads list` printed the word `paused` and no next step; `threads
show` printed every checkpoint value except the pause payload, so the one
surface built to read a thread back could not show what it was waiting for.

Measured on a real paused thread before this fix (`gate-demo`,
`human.approval`, wired straight to `candidate` with no model — the fixture
`test_cli_resume.py` already built for the identical `interrupt()`):

    $ openstategraph threads show demo-1
    thread demo-1 — paused
      workflow: gate-demo
      ...
    step 1 (loop) ...
      question: hello there

No `message`, no `candidate`, no `resume` line anywhere in that output.
"""

from __future__ import annotations

import json
from pathlib import Path

from openstategraph import cli

from test_cli_resume import project, _document, _straight_through  # noqa: F401 (fixture)


def _pause(project: Path, thread: str, question: str = "Sorry your order was late.") -> None:
    cli.main(["run", str(project / "gate-demo"), question, "--thread-id", thread])


class TestThreadsShowPrintsThePausePayload:
    def test_it_prints_the_gate_message_and_the_candidate(
        self, project: Path, capsys
    ) -> None:
        _pause(project, "show-1")
        capsys.readouterr()

        code = cli.main(["threads", "show", "show-1", "--workflows-root", str(project)])

        out = capsys.readouterr().out
        assert code == cli.EXIT_OK
        assert "This goes to a customer under your name." in out
        assert "Sorry your order was late." in out

    def test_it_prints_a_copy_pasteable_resume_line_naming_the_package(
        self, project: Path, capsys
    ) -> None:
        _pause(project, "show-2")
        capsys.readouterr()

        cli.main(["threads", "show", "show-2", "--workflows-root", str(project)])

        out = capsys.readouterr().out
        assert "openstategraph resume" in out
        assert str(project / "gate-demo") in out
        assert "show-2" in out
        assert "--approve" in out and "--reject" in out

    def test_the_resume_line_actually_finishes_the_run_when_typed(
        self, project: Path, capsys
    ) -> None:
        """Not just present — correct. Extract it and run it."""
        _pause(project, "show-3")
        capsys.readouterr()
        cli.main(["threads", "show", "show-3", "--workflows-root", str(project)])
        out = capsys.readouterr().out
        line = next(line for line in out.splitlines() if "finish it:" in line)
        command = line.split("finish it:", 1)[1].strip()
        # The printed line offers a choice ("--approve | --reject ..."); take
        # the approve branch, the same way a person reading it would.
        args = command.replace("--approve | --reject --feedback '…'", "--approve").split()
        assert args[:2] == ["openstategraph", "resume"]

        code = cli.main(args[1:])

        assert code == cli.EXIT_OK
        assert "Sorry your order was late." in capsys.readouterr().out

    def test_json_carries_the_pause_payload_too(self, project: Path, capsys) -> None:
        _pause(project, "show-4")
        capsys.readouterr()

        cli.main(["threads", "show", "show-4", "--workflows-root", str(project), "--json"])

        payload = json.loads(capsys.readouterr().out)
        assert payload["thread"]["pause"]["candidate"] == "Sorry your order was late."
        assert "customer" in payload["thread"]["pause"]["message"]


class TestAnUnpausedThreadIsUnchanged:
    def test_a_finished_thread_shows_no_pause_lines_at_all(
        self, project: Path, capsys
    ) -> None:
        cli.main(["run", str(project / "straight"), "Hello", "--thread-id", "done-show-1"])
        capsys.readouterr()

        cli.main(["threads", "show", "done-show-1", "--workflows-root", str(project)])

        out = capsys.readouterr().out
        assert "waiting:" not in out
        assert "finish it:" not in out
        assert "resume" not in out

    def test_a_finished_thread_s_json_pause_is_null(self, project: Path, capsys) -> None:
        cli.main(
            ["run", str(project / "straight"), "Hello", "--thread-id", "done-show-2", "--json"]
        )
        capsys.readouterr()

        cli.main(
            ["threads", "show", "done-show-2", "--workflows-root", str(project), "--json"]
        )

        payload = json.loads(capsys.readouterr().out)
        assert payload["thread"]["pause"] is None


class TestThreadsListStaysScannableButSaysSomethingIsWaiting:
    def test_a_paused_row_gets_a_footer_not_a_wall_of_text(
        self, project: Path, capsys
    ) -> None:
        _pause(project, "list-1")
        capsys.readouterr()

        code = cli.main(["threads", "list", "--workflows-root", str(project)])

        out = capsys.readouterr().out
        rows = [line for line in out.splitlines() if line.startswith("list-1")]
        assert code == cli.EXIT_OK
        assert len(rows) == 1  # one row per thread, still
        # the row itself stays terse — no full sentence crammed onto it
        assert "openstategraph resume" not in rows[0]
        assert "threads show" in out  # the footer names the next step

    def test_no_footer_when_nothing_is_paused(self, project: Path, capsys) -> None:
        cli.main(["run", str(project / "straight"), "Hello", "--thread-id", "list-2"])
        capsys.readouterr()

        cli.main(["threads", "list", "--workflows-root", str(project)])

        out = capsys.readouterr().out
        assert "paused" not in out.split("\n")[0]
        assert "threads show" not in out
