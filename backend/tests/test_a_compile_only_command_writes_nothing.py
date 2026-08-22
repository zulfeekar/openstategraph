"""A command that compiles and never runs must leave the filesystem alone.

`organisms-first-class` 77. `openstategraph validate <pkg>` created a 24K
`.openstategraph/memory.sqlite` in the package's **parent** directory — not in
the package, not in the working directory — whether or not the document
configures memory at all. Running the package sweep from the repo root put one
inside `backend/openstategraph/templates/`, which is package data shipped in
the wheel, and turned `test_templates.py`'s directory listing red. The file is
gitignored, so `git status`, `scripts/session_guard.py` and `loop_gate.py` all
reported a clean tree while pytest failed: a local red no tree check can see.

**Everything here is a subprocess on purpose.** `conftest.py` sets
`OPENSTATEGRAPH_CHECKPOINT_PATH=memory` and `OPENSTATEGRAPH_MEMORY_PATH=memory`
at import so the suite itself leaves nothing behind — which is exactly the
defect's own hiding place. An in-process test of this would be green against a
completely unfixed `validate`. So each case runs the real command with those
two variables **removed**, snapshots the tree before and after, and diffs.

The inverses are the load-bearing half: a real `run` still opens both files,
and `OPENSTATEGRAPH_STATE_DIR` still decides where they go.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from openstategraph import cli

#: A document that compiles and runs with no model and no credential: the
#: text arrives at the formatter directly, so the `UnconfiguredProvider`
#: stand-in the loader builds is never called.
MODEL_FREE = {
    "version": 3,
    "name": "Quiet",
    "settings": {},
    "nodes": [
        {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 40, "y": 200}},
        {
            "id": "out1",
            "type": "output.formatted",
            "data": {},
            "position": {"x": 380, "y": 200},
        },
    ],
    "edges": [
        {
            "source": {"nodeId": "in1", "portId": "text"},
            "target": {"nodeId": "out1", "portId": "result"},
        }
    ],
}


def _tree(root: Path) -> dict[str, int]:
    """Every path under `root`, with the size of each file.

    Sizes and not just names: a command that reopened an existing sqlite file
    would leave the listing identical and the bytes different.
    """
    return {
        str(p.relative_to(root)): (p.stat().st_size if p.is_file() else -1)
        for p in sorted(root.rglob("*"))
    }


def _env(**overrides: str) -> dict[str, str]:
    """The real command's environment, with the suite's own opt-outs removed."""
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(cli.__file__).resolve().parents[1]),
    }
    env.pop("OPENSTATEGRAPH_CHECKPOINT_PATH", None)
    env.pop("OPENSTATEGRAPH_MEMORY_PATH", None)
    env.pop("OPENSTATEGRAPH_STATE_DIR", None)
    env.update(overrides)
    return env


def _run(argv: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "openstategraph.cli", *argv],
        cwd=cwd, env=env, capture_output=True, text=True,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A package in a directory that is nobody's checkout and nobody's root."""
    root = tmp_path / "somebody-elses-folder"
    package = root / "quiet"
    package.mkdir(parents=True)
    (package / "workflow.json").write_text(json.dumps(MODEL_FREE))
    return root


class TestACompileOnlyCommandLeavesTheTreeAsItFoundIt:
    @pytest.mark.parametrize("verb", ["validate", "graph"])
    def test_it_writes_nothing_anywhere_beneath_the_directory_it_was_pointed_at(
        self, project: Path, tmp_path: Path, verb: str
    ) -> None:
        elsewhere = tmp_path / "cwd"
        elsewhere.mkdir()
        before = _tree(project)

        done = _run([verb, str(project / "quiet")], cwd=elsewhere, env=_env())

        assert done.returncode == cli.EXIT_OK, done.stderr
        assert _tree(project) == before
        assert _tree(elsewhere) == {}


class TestARunStillGetsItsDurability:
    """The inverse. The fix must not buy a quiet `validate` with a `run` that
    forgets a `human.approval` pause across processes."""

    def test_a_real_run_opens_both_files_under_the_state_directory(
        self, project: Path, tmp_path: Path
    ) -> None:
        state = tmp_path / "state"

        done = _run(
            ["run", str(project / "quiet"), "hello"],
            cwd=tmp_path,
            env=_env(OPENSTATEGRAPH_STATE_DIR=str(state)),
        )

        assert done.returncode == cli.EXIT_OK, done.stderr
        assert (state / "memory.sqlite").is_file()
        assert (state / "checkpoints.sqlite").is_file()

    def test_the_state_directory_variable_still_decides_where_they_go(
        self, project: Path, tmp_path: Path
    ) -> None:
        """And nothing lands beside the package, which is the whole point of
        `OPENSTATEGRAPH_STATE_DIR` outranking both branches of `state_dir()`."""
        state = tmp_path / "elsewhere-entirely"
        before = _tree(project)

        done = _run(
            ["run", str(project / "quiet"), "hello"],
            cwd=tmp_path,
            env=_env(OPENSTATEGRAPH_STATE_DIR=str(state)),
        )

        assert done.returncode == cli.EXIT_OK, done.stderr
        assert sorted(p.name for p in state.iterdir()) == [
            "checkpoints.sqlite",
            "memory.sqlite",
        ]
        assert _tree(project) == before
