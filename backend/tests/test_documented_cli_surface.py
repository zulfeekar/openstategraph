"""The CLI reference in `docs/cli.md`, held against the real argparse.

Production-ready ticket 20, reopened, then moved by `launch-readiness/196`.
Ticket 20 closed on 2026-08-13 asserting every item done, and a sweep of the
same corpus three days later found a comparable list — so its own diagnosis
was upgraded from "a backlog to burn down" to "a rate". The conclusion drawn
there is the reason this file exists: **prefer a gate to a correction wherever
a claim is mechanically checkable.**

## What moved, and why the pin moved with it

The enumeration used to live in `docs/adoption.md` §"the rest of the
commands", and that page's job is *how to adopt this*, not *what does this
command do*. A reader looking up a flag had to read an adoption narrative to
find a table inside it. `docs/cli.md` is the reference — one section per
command, its flags, its exit codes, and a "which one do I want" table at the
top — and `docs/README.md` now names **it** as the single enumeration.

Moving the page without moving the pin would have been the drift this file was
written to stop, one directory over.

## What the drift looked like, the last time nothing was watching

- `openstategraph init` — the only command that creates a project, and the
  substitute for the one thing an install line cannot carry — had **no row at
  all**, while the page's own headline quickstart ran it.
- `examples copy --all` and `serve --workers` were undocumented. `--workers`
  matters more than its size: it exists only to be *refused*, and a reader who
  never learns it exists learns instead that we forgot about multi-worker
  deployment.
- The exit codes were right there and wrong in
  `docs/decisions/framework-packaging.md` §3.2, which had `1` and `2`
  transposed and invented a `5`. A CI script written from that document reads
  a usage error as a failed run.

## What is pinned, and what deliberately is not

**Pinned** — every command and subcommand appears; every `--flag` argparse
accepts is documented **in that command's own section**; every `--flag` a
section shows is one argparse accepts; the exit-code table names the real
constants.

The first of those is new here (`launch-readiness/196`). The old file checked
only that a *documented* flag was real — the direction that costs a reader a
failed paste. The other direction is the one that costs them a feature they
never find, and it is the direction a page drifts in on its own: a flag is
added to the parser in the same commit as the behaviour, and the document is a
separate act of will. Now it is not.

**Not pinned** — what each command *means*. That is prose, it is the useful
half, and a test demanding particular sentences would be a test of an author's
wording rather than of the software. The rule this file follows is the
repository's own: pin the checkable claim, leave the argument alone.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from openstategraph import cli

ROOT = Path(__file__).resolve().parents[2]

#: The reference. One document, deliberately — `docs/README.md` promises the
#: CLI's commands, flags and exit codes are enumerated in exactly one place,
#: and a second pinned copy would make that promise false while satisfying a
#: gate.
REFERENCE = ROOT / "docs" / "cli.md"

#: A long flag as a reader meets it: `--thread-id`, `--workers`, `--list-templates`.
FLAG_IN_PROSE = re.compile(r"--([a-z][a-z0-9-]*)")

#: Flags argparse supplies and no page should have to restate.
FREE = {"help", "version"}


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


def accepted(command: str) -> set[str]:
    """A group's own flags plus every leaf's — `runs list --json` is `runs`'."""
    flags = flags_of(command)
    for leaf in subcommand_tree()[command]:
        flags |= flags_of(command, leaf)
    return flags


def sections(page: str) -> dict[str, str]:
    """`### `init`` → the text under it, up to the next `###` or `##`.

    Keyed by the **first word** of the backticked heading, so `### `export
    plugin`` files under `export`, which is what argparse calls it.
    """
    found: dict[str, str] = {}
    current: str | None = None
    body: list[str] = []
    for line in page.splitlines():
        heading = re.match(r"^#{2,3} `([a-z][a-z-]*)", line)
        if line.startswith("## ") or line.startswith("### "):
            if current is not None:
                found[current] = "\n".join(body)
            current, body = (heading.group(1) if heading else None), []
            continue
        if current is not None:
            body.append(line)
    if current is not None:
        found[current] = "\n".join(body)
    return found


@pytest.fixture(scope="module")
def guide() -> str:
    return REFERENCE.read_text()


@pytest.fixture(scope="module")
def by_command(guide: str) -> dict[str, str]:
    return sections(guide)


class TestEveryCommandIsDocumented:
    """A command absent from the reference is a command nobody finds."""

    @pytest.mark.parametrize("command", sorted(subcommand_tree()))
    def test_it_has_its_own_section(self, by_command: dict[str, str], command: str) -> None:
        assert command in by_command, (
            f"`openstategraph {command}` exists and docs/cli.md has no section for it. "
            "That page is the only enumeration of the CLI, per docs/README.md."
        )

    @pytest.mark.parametrize(
        ("group", "leaf"),
        sorted((group, leaf) for group, leaves in subcommand_tree().items() for leaf in leaves),
    )
    def test_each_subcommand_appears_in_its_section(
        self, by_command: dict[str, str], group: str, leaf: str
    ) -> None:
        assert f"{group} {leaf}" in by_command.get(group, ""), (
            f"`openstategraph {group} {leaf}` is a real command and the `{group}` "
            "section never spells it out"
        )


class TestEveryFlagIsDocumented:
    """The direction that costs a reader a feature they never learn exists.

    A flag reaches the parser in the same commit as the behaviour it turns on;
    documenting it is a separate act of will, which is the one that gets
    skipped. Scoped per section rather than per page, so a flag documented
    under the wrong command still fails.
    """

    @pytest.mark.parametrize("command", sorted(subcommand_tree()))
    def test_the_section_shows_every_flag_argparse_takes(
        self, by_command: dict[str, str], command: str
    ) -> None:
        documented = set(FLAG_IN_PROSE.findall(by_command.get(command, "")))
        missing = sorted(accepted(command) - documented - FREE)
        assert missing == [], (
            f"`openstategraph {command}` accepts {missing} and its section in "
            "docs/cli.md never names them"
        )


class TestNoDocumentedFlagIsInvented:
    """A flag that does not exist is a paste that exits 2 with `unrecognized
    arguments`, and the reader has no way to tell whether the document is
    wrong or their install is old."""

    @pytest.mark.parametrize("command", sorted(subcommand_tree()))
    def test_every_flag_in_the_section_is_real(
        self, by_command: dict[str, str], command: str
    ) -> None:
        documented = set(FLAG_IN_PROSE.findall(by_command.get(command, ""))) - FREE
        invented = sorted(documented - accepted(command))
        assert invented == [], (
            f"docs/cli.md's `{command}` section documents {invented}, which that "
            "parser does not accept"
        )

    def test_the_scan_actually_reaches_the_page(self, by_command: dict[str, str]) -> None:
        """Guards every assertion above from passing because it matched nothing.

        A heading pattern that stops matching is a green test that checks the
        empty set, which is the failure mode of every doc gate written this way.
        """
        assert set(subcommand_tree()) <= set(by_command), "the section scan found nothing"
        assert sum(len(body) for body in by_command.values()) > 5_000


class TestTheExitCodesAreTheOnesCIWillSee:
    """`docs/cli.md`: "Fixed and few, because they are what CI consumes".

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
        table = guide.split("## Exit codes")[1]
        for number, meaning in (
            ("0", "success"),
            ("1", "failed"),
            ("2", "usage"),
            ("3", "extra"),
        ):
            assert f"**{number}**" in table, f"exit {number} is not stated"
            assert meaning in table.lower(), f"exit {number}'s meaning is not stated"

    def test_there_is_no_fourth_code(self, guide: str) -> None:
        """`--strict` and its exit 4 were designed and deliberately dropped.

        `docs/decisions/framework-packaging.md` §3.2 described five codes for
        three days after the CLI shipped four; `gap-register.md` PK-10 records
        the drop. This is the assertion that keeps the invented ones out.
        """
        assert not hasattr(cli, "EXIT_STRICT")
        table = guide.split("## Exit codes")[1]
        assert "| **4**" not in table and "| **5**" not in table


class TestTheReferenceIsTheOnlyEnumeration:
    """`docs/README.md` promises one place, and a promise gets a test.

    The old table lived in `docs/adoption.md`; leaving it there beside the new
    page would have been two enumerations, which is exactly the state
    `docs/README.md`'s no-repetition rule exists to prevent — and the state in
    which one of them silently goes stale while a gate watches the other.
    """

    def test_the_index_names_the_reference(self) -> None:
        index = (ROOT / "docs" / "README.md").read_text()
        assert "(cli.md)" in index

    def test_adoption_points_here_rather_than_repeating(self) -> None:
        adoption = (ROOT / "docs" / "adoption.md").read_text()
        assert "cli.md" in adoption
        rows = [
            line
            for line in adoption.splitlines()
            if re.match(r"\| `openstategraph [a-z]", line)
        ]
        assert rows == [], f"docs/adoption.md is enumerating the CLI again: {rows[:3]}"


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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
