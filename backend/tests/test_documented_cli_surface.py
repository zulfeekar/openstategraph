"""The CLI table in `docs/adoption.md`, held against the real argparse.

Production-ready ticket 20, reopened. That ticket closed on 2026-08-13
asserting every item done, and a sweep of the same corpus three days later
found a comparable list — so its own diagnosis was upgraded from "a backlog to
burn down" to "a rate". The conclusion drawn there is the reason this file
exists: **prefer a gate to a correction wherever a claim is mechanically
checkable.**

`docs/adoption.md` §"the rest of the commands" is the one place the CLI's
flags and exit codes are enumerated for a consumer — `docs/README.md` says so
in as many words, which makes that table the contract rather than a
convenience. It had drifted three ways at once:

- `openstategraph init` — the only command that creates a project, and the
  substitute for the one thing an install line cannot carry — had **no row at
  all**, while the page's own headline quickstart runs it on line 45.
- `examples copy --all` and `serve --workers` were undocumented. `--workers`
  matters more than its size: it exists only to be *refused*, and a reader who
  never learns it exists learns instead that we forgot about multi-worker
  deployment.
- The exit codes were right here and wrong in
  `docs/decisions/framework-packaging.md` §3.2, which had `1` and `2`
  transposed and invented a `5`. A CI script written from that document reads
  a usage error as a failed run.

What is pinned, and what deliberately is not:

**Pinned** — every subcommand exists in the table; every ``--flag`` the table
shows exists in that subcommand's parser; the exit-code paragraph names the
real constants. These are the assertions a reader acts on and can be checked
without reading prose.

**Not pinned** — what each command *means*. That is prose, it is the useful
half, and a test that demanded particular sentences would be a test of an
author's wording rather than of the software. The rule this file follows is
the repository's own: pin the checkable claim, leave the argument alone.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from openstategraph import cli

ROOT = Path(__file__).resolve().parents[2]

#: The consumer-facing enumeration. One document, deliberately — `docs/README.md`
#: promises the CLI's flags and exit codes are enumerated in exactly one place,
#: and a second pinned copy would make that promise false while satisfying a
#: gate.
ADOPTION = ROOT / "docs" / "adoption.md"

#: A long flag as a reader meets it: `--thread-id`, `--workers`, `--list-templates`.
FLAG_IN_PROSE = re.compile(r"`?--([a-z][a-z0-9-]*)")


def subcommand_tree() -> dict[str, set[str]]:
    """`{"run": set(), "threads": {"list", "show"}, …}` from the real parser.

    Built by walking `build_parser()` rather than by reading `cli.py` as text,
    because the thing a reader will type is what argparse accepts, not what a
    source file appears to say.
    """
    tree: dict[str, set[str]] = {}
    for action in cli.build_parser()._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, parser in action.choices.items():
            leaves: set[str] = set()
            for inner in parser._actions:
                if isinstance(inner, argparse._SubParsersAction):
                    leaves |= set(inner.choices)
            tree[name] = leaves
    return tree


def flags_of(command: str, leaf: str | None = None) -> set[str]:
    """Every long option string a subcommand accepts, minus `--help`."""
    parser = cli.build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            parser = action.choices[command]
            break
    if leaf:
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                parser = action.choices[leaf]
                break
    return {
        option.lstrip("-")
        for action in parser._actions
        for option in action.option_strings
        if option.startswith("--") and option != "--help"
    }


@pytest.fixture(scope="module")
def guide() -> str:
    return ADOPTION.read_text()


class TestEveryCommandIsDocumented:
    """A command absent from the table is a command nobody finds."""

    @pytest.mark.parametrize("command", sorted(subcommand_tree()))
    def test_it_appears_in_the_table(self, guide: str, command: str) -> None:
        assert f"`openstategraph {command}" in guide, (
            f"`openstategraph {command}` exists and docs/adoption.md never mentions it. "
            "That page is the only consumer-facing enumeration of the CLI, per docs/README.md."
        )

    @pytest.mark.parametrize(
        ("group", "leaf"),
        sorted((group, leaf) for group, leaves in subcommand_tree().items() for leaf in leaves),
    )
    def test_each_subcommand_appears_too(self, guide: str, group: str, leaf: str) -> None:
        """`threads list|show` and `examples copy` are separate commands.

        Written as `threads list|show` in the table, so the assertion is that
        the leaf appears somewhere in the same line as its group rather than
        that the full path appears verbatim.
        """
        lines = [line for line in guide.splitlines() if f"`openstategraph {group}" in line]
        assert any(leaf in line for line in lines), (
            f"`openstategraph {group} {leaf}` is a real command and no line documenting "
            f"`{group}` mentions it"
        )


class TestNoDocumentedFlagIsInvented:
    """The direction that costs a reader a failed command rather than a missed one.

    A missing flag is a gap; a flag that does not exist is a paste that exits
    2 with `unrecognized arguments`, and the reader has no way to tell whether
    the document is wrong or their install is old.
    """

    def test_every_flag_in_the_table_is_real(self, guide: str) -> None:
        """One row of the table, one command, and every `--flag` on that row.

        Scoped to the table rather than the whole page on purpose: a table row
        opens by naming its command, so which parser a flag belongs to is
        unambiguous there and only there. Body prose mentions a flag next to
        the *effect* it has, which is a different sentence shape and would need
        a different, guessier rule.
        """
        real = subcommand_tree()
        offenders: list[str] = []
        for number, line in enumerate(guide.splitlines(), start=1):
            row = re.match(r"\| `openstategraph ([a-z][a-z-]*)", line)
            if not row or row.group(1) not in real:
                continue
            command = row.group(1)
            accepted = flags_of(command)
            for leaf in real[command]:
                accepted |= flags_of(command, leaf)
            for flag in {f for f in FLAG_IN_PROSE.findall(line)} - {"help", "version"}:
                if flag not in accepted:
                    offenders.append(f"adoption.md:{number} `openstategraph {command}` --{flag}")
        assert offenders == [], (
            "documented flags that argparse does not accept — a reader pasting one gets "
            f"`unrecognized arguments` and cannot tell whose fault it is: {offenders}"
        )

    def test_the_scan_actually_reaches_the_table(self, guide: str) -> None:
        """Guards the test above from passing because it matched nothing.

        A regex that stops matching is a green test that checks the empty set,
        which is the failure mode of every doc gate written this way.
        """
        rows = [
            line for line in guide.splitlines() if re.match(r"\| `openstategraph [a-z]", line)
        ]
        assert len(rows) >= len(subcommand_tree()) - 2, (
            f"only {len(rows)} command rows matched; the table's shape changed and this "
            "file is now checking almost nothing"
        )


class TestTheExitCodesAreTheOnesCIWillSee:
    """`docs/adoption.md`: "Exit codes are fixed, because they are what CI consumes".

    Fixed is a promise, so it gets a test. The numbers are asserted against the
    constants rather than against a source line, because a constant renamed
    without changing its value must not fail this and a value changed must.
    """

    def test_the_constants_are_what_the_page_says(self) -> None:
        assert (cli.EXIT_OK, cli.EXIT_FAILURE, cli.EXIT_USAGE, cli.EXIT_MISSING_EXTRA) == (
            0,
            1,
            2,
            3,
        )

    def test_the_page_states_each_one(self, guide: str) -> None:
        paragraph = guide.split("Exit codes are fixed")[1][:600]
        for number, meaning in (
            ("0", "success"),
            ("1", "failure"),
            ("2", "usage"),
            ("3", "extra"),
        ):
            assert f"**{number}**" in paragraph, f"exit {number} is not stated"
            assert meaning in paragraph.lower(), f"exit {number}'s meaning is not stated"

    def test_there_is_no_fourth_code(self, guide: str) -> None:
        """`--strict` and its exit 4 were designed and deliberately dropped.

        `docs/decisions/framework-packaging.md` §3.2 described five codes for
        three days after the CLI shipped four; `gap-register.md` PK-10 records
        the drop. This is the assertion that keeps the invented ones out.
        """
        assert not hasattr(cli, "EXIT_STRICT")
        paragraph = guide.split("Exit codes are fixed")[1][:600]
        assert "**4**" not in paragraph and "**5**" not in paragraph


class TestTheEntryPointIsTheOneShipped:
    """A console script the documentation names and the wheel does not install.

    `framework-packaging.md` printed `openstategraph.cli:main`; the wheel
    declares `console_main`. Both exist and they are not the same function —
    `main` returns an exit code for a test to inspect, `console_main` is the
    one that hands it to the shell — so the wrong one in a third party's
    `pyproject.toml` produces a command that always succeeds.
    """

    def test_the_declared_console_script_resolves(self) -> None:
        import tomllib

        scripts = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text())["project"][
            "scripts"
        ]
        assert scripts == {"openstategraph": "openstategraph.cli:console_main"}
        assert callable(cli.console_main)
