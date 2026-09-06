"""`openstategraph resume` — finishing, from the terminal, a run started there.

`workflow-gallery` 24. `openstategraph run` was `ask()` and nothing else, and
`ask()` has no resume parameter, so a package holding a `human.approval` node
could be **started** from the CLI and never finished from it. The mechanism was
entirely present — `POST /api/runs/resume` continues a paused thread in a dozen
lines against the same durable checkpointer the CLI already opens — and the
only missing piece was a verb.

**These drive the command, not the seam it calls.** The target is a person at a
terminal finishing a run they started there, so every case here pauses a real
graph against a real sqlite checkpointer and then types the command, in-process
through `cli.main` (`test_cli.py`'s convention) with one subprocess case for the
promise an in-process call cannot show: it works from a directory that is not
this checkout.

**No model runs here, and that is deliberate rather than a limitation.** The
gallery's `approval-in-the-loop` reaches its gate through an `agent.llm`, and
this environment has no provider credential; wiring the input straight into the
gate's `candidate` port reaches the identical `interrupt()` — `_human_approval`
reads its candidate off the upstream edge either way — so the pause, the
refusals and both decisions are exercised with nothing to mock.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from openstategraph import cli


def _document(name: str = "Gate Demo") -> dict:
    """input.text ─▶ human.approval ─approved/rejected▶ output.formatted."""
    return {
        "version": 1,
        "name": name,
        "document": {
            "version": 3,
            "name": name,
            "nodes": [
                {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 0, "y": 0}},
                {
                    "id": "gate1",
                    "type": "human.approval",
                    "data": {"message": "This goes to a customer under your name."},
                    "position": {"x": 300, "y": 0},
                },
                {
                    "id": "out1",
                    "type": "output.formatted",
                    "data": {},
                    "position": {"x": 600, "y": 0},
                },
            ],
            "edges": [
                {
                    "source": {"nodeId": "in1", "portId": "text"},
                    "target": {"nodeId": "gate1", "portId": "candidate"},
                },
                {
                    "source": {"nodeId": "gate1", "portId": "approved"},
                    "target": {"nodeId": "out1", "portId": "result"},
                },
                {
                    "source": {"nodeId": "gate1", "portId": "rejected"},
                    "target": {"nodeId": "out1", "portId": "result"},
                },
            ],
        },
    }


def _straight_through(name: str = "Straight Through") -> dict:
    """input.text ─▶ output.formatted. Finishes; never pauses."""
    return {
        "version": 1,
        "name": name,
        "document": {
            "version": 3,
            "name": name,
            "nodes": [
                {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 0, "y": 0}},
                {
                    "id": "out1",
                    "type": "output.formatted",
                    "data": {},
                    "position": {"x": 300, "y": 0},
                },
            ],
            "edges": [
                {
                    "source": {"nodeId": "in1", "portId": "text"},
                    "target": {"nodeId": "out1", "portId": "result"},
                }
            ],
        },
    }


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A workflows root and a state directory outside the checkout.

    Both are needed together: the checkpointer the CLI opens lives under the
    state directory, and a run whose thread lands somewhere else is a thread
    the next command cannot find.
    """
    root = tmp_path / "workflows"
    for slug, document in (
        ("gate-demo", _document()),
        ("other-gate", _document("Other Gate")),
        ("straight", _straight_through()),
    ):
        (root / slug).mkdir(parents=True)
        (root / slug / "workflow.json").write_text(json.dumps(document))
    # `conftest` sets `OPENSTATEGRAPH_CHECKPOINT_PATH=memory` for the whole
    # suite, and an in-memory saver is per-process-per-load: the second command
    # would open a fresh one and find no thread at all. A resume is a claim
    # about a *durable* checkpoint, so these tests use the durable saver the
    # installed CLI uses, in a file of their own.
    monkeypatch.setenv("OPENSTATEGRAPH_CHECKPOINT_PATH", str(tmp_path / "checkpoints.sqlite"))
    monkeypatch.setenv("OPENSTATEGRAPH_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("OPENSTATEGRAPH_WORKFLOWS_ROOT", str(root))
    return root


def _pause(project: Path, thread: str, question: str = "Sorry your order was late.") -> int:
    """Start a run that stops at the gate. Returns the exit code it gave."""
    return cli.main(["run", str(project / "gate-demo"), question, "--thread-id", thread])


class TestRunNoLongerPretendsToHaveFinished:
    def test_a_paused_run_exits_non_zero_instead_of_reporting_success(
        self, project: Path, capsys
    ) -> None:
        code = _pause(project, "t-1")

        assert code == cli.EXIT_FAILURE
        assert capsys.readouterr().err  # it said something

    def test_it_prints_the_pause_payload_and_the_thread_id(self, project: Path, capsys) -> None:
        _pause(project, "t-2")

        err = capsys.readouterr().err
        assert "This goes to a customer under your name." in err
        assert "Sorry your order was late." in err
        assert "t-2" in err

    def test_it_names_the_command_that_finishes_the_run(self, project: Path, capsys) -> None:
        """The pause report is the only place a person learns the verb exists."""
        _pause(project, "t-3")

        err = capsys.readouterr().err
        assert "resume" in err
        assert "--approve" in err and "--reject" in err

    def test_json_carries_the_pause_so_a_script_can_see_it_too(
        self, project: Path, capsys
    ) -> None:
        code = cli.main(
            ["run", str(project / "gate-demo"), "Draft it.", "--thread-id", "t-4", "--json"]
        )

        payload = json.loads(capsys.readouterr().out)
        assert code == cli.EXIT_FAILURE
        assert payload["pause"]["candidate"] == "Draft it."
        assert payload["thread_id"] == "t-4"

    def test_a_run_that_finishes_still_exits_zero_with_no_pause(
        self, project: Path, capsys
    ) -> None:
        """The inverse: nothing here may make an ordinary run look unfinished."""
        code = cli.main(
            ["run", str(project / "straight"), "Hello", "--thread-id", "t-5", "--json"]
        )

        assert code == cli.EXIT_OK
        assert json.loads(capsys.readouterr().out)["pause"] is None


class TestTheVerbFinishesTheRun:
    def test_approve_completes_the_run_and_exits_zero(self, project: Path, capsys) -> None:
        _pause(project, "a-1")
        capsys.readouterr()

        code = cli.main(["resume", str(project / "gate-demo"), "a-1", "--approve"])

        out = capsys.readouterr().out
        assert code == cli.EXIT_OK
        assert "Sorry your order was late." in out

    def test_the_decision_reaches_the_graph_rather_than_only_the_exit_code(
        self, project: Path, capsys
    ) -> None:
        _pause(project, "a-2")
        capsys.readouterr()

        cli.main(["resume", str(project / "gate-demo"), "a-2", "--approve", "--json"])

        payload = json.loads(capsys.readouterr().out)
        assert payload["decisions"]["gate1"] == "approved"
        assert payload["thread_id"] == "a-2"

    def test_reject_is_recorded_as_the_other_decision(self, project: Path, capsys) -> None:
        _pause(project, "r-1")
        capsys.readouterr()

        cli.main(
            [
                "resume",
                str(project / "gate-demo"),
                "r-1",
                "--reject",
                "--feedback",
                "Too formal.",
                "--json",
            ]
        )

        assert json.loads(capsys.readouterr().out)["decisions"]["gate1"] == "rejected"

    def test_the_thread_is_finished_afterwards_and_cannot_be_resumed_twice(
        self, project: Path, capsys
    ) -> None:
        """A resume consumes the pause. Saying so is the whole reason the
        command warns before it acts."""
        _pause(project, "a-3")
        cli.main(["resume", str(project / "gate-demo"), "a-3", "--approve"])
        capsys.readouterr()

        code = cli.main(["resume", str(project / "gate-demo"), "a-3", "--approve"])

        assert code == cli.EXIT_FAILURE
        assert "not paused" in capsys.readouterr().err

    def test_it_says_what_it_is_about_to_do_before_it_does_it(
        self, project: Path, capsys
    ) -> None:
        """A resume runs the rest of the workflow against a durable checkpoint
        — tools, emails, everything downstream of the gate. It is announced on
        stderr, so `resume … > answer.txt` still gives only the answer."""
        _pause(project, "a-4")
        capsys.readouterr()

        cli.main(["resume", str(project / "gate-demo"), "a-4", "--approve"])

        err = capsys.readouterr().err
        assert "approve" in err
        assert "a-4" in err
        assert "This goes to a customer under your name." in err


class TestItRefusesRatherThanTracebacks:
    def test_a_thread_that_was_never_stored_is_a_sentence_not_a_stack(
        self, project: Path, capsys
    ) -> None:
        code = cli.main(["resume", str(project / "gate-demo"), "no-such-thread", "--approve"])

        captured = capsys.readouterr()
        assert code == cli.EXIT_FAILURE
        assert "no-such-thread" in captured.err
        assert "Traceback" not in captured.err

    def test_a_thread_that_is_not_paused_is_refused(self, project: Path, capsys) -> None:
        cli.main(["run", str(project / "straight"), "Hello", "--thread-id", "done-1"])
        capsys.readouterr()

        code = cli.main(["resume", str(project / "straight"), "done-1", "--approve"])

        assert code == cli.EXIT_FAILURE
        assert "not paused" in capsys.readouterr().err

    def test_a_thread_belonging_to_another_package_is_refused_by_name(
        self, project: Path, capsys
    ) -> None:
        """The checkpointer is shared, so the thread is *findable* from the
        wrong package — and resuming it there would run somebody else's
        document against this one's checkpoint."""
        _pause(project, "x-1")
        capsys.readouterr()

        code = cli.main(["resume", str(project / "other-gate"), "x-1", "--approve"])

        err = capsys.readouterr().err
        assert code == cli.EXIT_FAILURE
        assert "gate-demo" in err and "other-gate" in err

    def test_no_decision_at_all_is_a_usage_error_and_never_a_guess(
        self, project: Path
    ) -> None:
        """Exit 2, from argparse itself: a decision is a person's to give, and
        the one thing this command must never do is invent one."""
        _pause(project, "u-1")

        with pytest.raises(SystemExit) as exit_:
            cli.main(["resume", str(project / "gate-demo"), "u-1"])

        assert exit_.value.code == cli.EXIT_USAGE

    def test_both_decisions_at_once_is_a_usage_error(self, project: Path) -> None:
        with pytest.raises(SystemExit) as exit_:
            cli.main(["resume", str(project / "gate-demo"), "u-2", "--approve", "--reject"])

        assert exit_.value.code == cli.EXIT_USAGE

    def test_feedback_on_an_approval_is_refused_rather_than_dropped(
        self, project: Path, capsys
    ) -> None:
        """`_human_approval` reads `feedback` only when the decision is a
        rejection. Accepting the flag and discarding the words would be a
        silent loss of the one thing the person typed."""
        _pause(project, "u-3")
        capsys.readouterr()

        code = cli.main(
            ["resume", str(project / "gate-demo"), "u-3", "--approve", "--feedback", "hm"]
        )

        assert code == cli.EXIT_USAGE
        assert "--feedback" in capsys.readouterr().err

    def test_a_missing_provider_integration_still_exits_three_with_its_install_line(
        self, project: Path, capsys, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A rejection re-runs the drafting agent, so this command builds a
        model exactly as `run` does and inherits the same `3`. Raised at the
        load seam because this installation cannot produce the real gap."""

        def _no_integration(*_args, **_kwargs):
            raise ImportError("langchain-anthropic is required — pip install 'openstategraph[anthropic]'")

        monkeypatch.setattr(cli, "_load", _no_integration)

        code = cli.main(["resume", str(project / "gate-demo"), "any", "--approve"])

        assert code == cli.EXIT_MISSING_EXTRA
        assert "pip install" in capsys.readouterr().err


class TestFromAnyDirectory:
    def test_the_installed_command_resumes_from_outside_the_checkout(
        self, project: Path, tmp_path: Path
    ) -> None:
        """The CLI's standing promise, and the one an in-process call cannot
        show: paths come from the arguments, nothing is relative to a
        checkout."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        env = {
            **os.environ,
            "PYTHONPATH": str(Path(cli.__file__).resolve().parents[1]),
            "OPENSTATEGRAPH_CHECKPOINT_PATH": str(tmp_path / "checkpoints.sqlite"),
            "OPENSTATEGRAPH_STATE_DIR": str(tmp_path / "state"),
            "OPENSTATEGRAPH_WORKFLOWS_ROOT": str(project),
        }
        package = str(project / "gate-demo")

        started = subprocess.run(
            [sys.executable, "-m", "openstategraph.cli", "run", package, "Draft it.",
             "--thread-id", "sub-1"],
            cwd=elsewhere, env=env, capture_output=True, text=True,
        )
        finished = subprocess.run(
            [sys.executable, "-m", "openstategraph.cli", "resume", package, "sub-1", "--approve"],
            cwd=elsewhere, env=env, capture_output=True, text=True,
        )

        assert started.returncode == cli.EXIT_FAILURE, started.stderr
        assert "sub-1" in started.stderr
        assert finished.returncode == cli.EXIT_OK, finished.stderr
        assert "Draft it." in finished.stdout
