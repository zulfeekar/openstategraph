"""The two commands that *create* packages ask the resolver like everyone else.

install-experience T5. `workflows_root()` already implements the project-wide
precedence — explicit argument > `OPENSTATEGRAPH_WORKFLOWS_ROOT` >
`workflows_dir:` > checkout > `./workflows` — and resolves it per call. The two
commands that write new packages bypassed it entirely, each spelling

    Path(args.root)… if args.root else Path.cwd() / "workflows"

So in a project with `workflows_dir: flows`, or with the environment variable
set, `openstategraph new my-thing` wrote to `./workflows/my-thing` and
`openstategraph serve` then showed an empty project: the *"No workflows exist
yet."* failure `workflows_root.py`'s own docstring was written to end,
reintroduced by the two commands a new adopter reaches for first.

What is pinned here is agreement rather than any one answer: **whatever
`serve` would read, `new` and `examples copy` write into**, under every source
of the precedence rule.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from openstategraph import cli
from openstategraph.config_file import reset_active_config
from openstategraph.providers import reset_provider_catalogue
from openstategraph.workflows_root import WORKFLOWS_ROOT_ENV, workflows_root


def _use_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    path = tmp_path / "openstategraph.yaml"
    path.write_text(text)
    monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(path))
    reset_provider_catalogue()
    reset_active_config()


class TestBothWritersAskTheResolver:
    """Every source, both commands, captured rather than written.

    The root each command *chose* is captured by replacing the scaffold
    function, so the checkout and cwd sources can be covered without either
    writing a package into this repository or leaving the four cases untested
    because two of them are awkward.
    """

    def _root_chosen(
        self, monkeypatch: pytest.MonkeyPatch, argv: list[str], target: str
    ) -> Path:
        seen: dict[str, Path] = {}

        def capture(root: Path, *args: Any, **kwargs: Any) -> Any:
            seen["root"] = Path(root)
            written = Path(root) / "captured"
            # `new_package` answers with the package it created; `copy_example`
            # answers with every path it wrote, the mount closure included,
            # plus which of them were already there unchanged (`.kept`).
            if target == "copy_example":
                from openstategraph.scaffold import CopyResult

                return CopyResult((written,), frozenset())
            return written

        monkeypatch.setattr(f"openstategraph.scaffold.{target}", capture)
        assert cli.main(argv) == cli.EXIT_OK
        return seen["root"]

    @pytest.mark.parametrize(
        ("command", "target"),
        [
            (["new", "my-flow"], "new_package"),
            (["examples", "copy", "chained-summarizer"], "copy_example"),
        ],
    )
    def test_the_checkout_is_used_when_nothing_else_says_otherwise(
        self, monkeypatch: pytest.MonkeyPatch, command: list[str], target: str
    ) -> None:
        """The source that used to be silently wrong in a checkout too.

        `Path.cwd() / "workflows"` happened to agree here only when the
        command was run from the repository root.
        """
        monkeypatch.delenv(WORKFLOWS_ROOT_ENV, raising=False)
        assert self._root_chosen(monkeypatch, command, target) == workflows_root()

    @pytest.mark.parametrize(
        ("command", "target"),
        [
            (["new", "my-flow"], "new_package"),
            (["examples", "copy", "chained-summarizer"], "copy_example"),
        ],
    )
    def test_the_environment_variable_is_honoured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: list[str], target: str
    ) -> None:
        monkeypatch.setenv(WORKFLOWS_ROOT_ENV, str(tmp_path / "deployment"))
        assert self._root_chosen(monkeypatch, command, target) == tmp_path / "deployment"
        assert workflows_root() == tmp_path / "deployment"

    @pytest.mark.parametrize(
        ("command", "target"),
        [
            (["new", "my-flow"], "new_package"),
            (["examples", "copy", "chained-summarizer"], "copy_example"),
        ],
    )
    def test_the_config_files_workflows_dir_is_honoured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: list[str], target: str
    ) -> None:
        """The case that produced *"No workflows exist yet."* with a full project."""
        monkeypatch.delenv(WORKFLOWS_ROOT_ENV, raising=False)
        _use_config(tmp_path, monkeypatch, "version: 1\nworkflows_dir: flows\n")

        assert self._root_chosen(monkeypatch, command, target) == workflows_root()
        assert workflows_root() == tmp_path / "flows"

    @pytest.mark.parametrize(
        ("command", "target"),
        [
            (["new", "my-flow"], "new_package"),
            (["examples", "copy", "chained-summarizer"], "copy_example"),
        ],
    )
    def test_an_explicit_root_still_wins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: list[str], target: str
    ) -> None:
        """`--root` is the explicit argument the precedence rule puts on top."""
        monkeypatch.setenv(WORKFLOWS_ROOT_ENV, str(tmp_path / "deployment"))
        _use_config(tmp_path, monkeypatch, "version: 1\nworkflows_dir: flows\n")

        chosen = self._root_chosen(
            monkeypatch, [*command, "--root", str(tmp_path / "by_hand")], target
        )
        assert chosen == tmp_path / "by_hand"


class TestTheyAgreeOnDisk:
    """The same property once more, written and then read back.

    The capture tests above prove which directory was chosen; this proves the
    package a reader can actually see is in the directory `serve` reports.
    """

    def test_new_lands_where_serve_says_it_looks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(WORKFLOWS_ROOT_ENV, str(tmp_path / "flows"))

        assert cli.main(["new", "my-flow"]) == cli.EXIT_OK

        assert (tmp_path / "flows" / "my-flow" / "workflow.json").is_file()
        assert f"workflows      {tmp_path / 'flows'}" in cli.startup_facts()
        assert not (Path.cwd() / "workflows" / "my-flow").exists()

    def test_examples_copy_lands_there_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(WORKFLOWS_ROOT_ENV, str(tmp_path / "flows"))

        assert cli.main(["examples", "copy", "chained-summarizer"]) == cli.EXIT_OK

        assert (tmp_path / "flows" / "chained-summarizer" / "workflow.json").is_file()
        assert not (Path.cwd() / "workflows" / "chained-summarizer").exists()
