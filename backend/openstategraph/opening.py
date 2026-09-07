"""What `openstategraph open` decides, before a socket is bound.

**Tier 2, provisional.** The *command* is the contract; this module is where
its decisions live so that `cli.py` stays argument handling plus a call, which
is rule 1 at the top of that file.

The verb exists because of a comparison the owner drew: a standalone graph
tool installed once and run as `<tool> .` — one verb, point it at a folder, it
works. Four things stood between this CLI and that shape, and only the last was
a missing feature:

1. the workflows directory was resolved by **where you were standing**, and
   nothing said which directory that was or what chose it;
2. nothing reviewed the packages already in it before serving them;
3. nothing said what to do when the directory was not a project at all;
4. nothing opened a browser.

Three of those are things the command already knew and did not say, which is
why this module produces **lines and a refusal** rather than doing anything.
It creates no directory, writes no config, opens no socket and calls no
`chdir`; the command does all four, so every decision here is testable without
a filesystem side effect or a bound port.

**`open` is not `serve`, and this module is the argument for the split.**
`serve` is what a deployment runs: documented flags, no questions, no browser,
no directory argument. A verb that opens a browser, prompts, and can create a
directory is not the verb a container runs — and growing `serve` an argument
would have made it both, with the interactive half reachable by accident from
a Dockerfile.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from pathlib import Path

from openstategraph.workflows_root import RootChoice, resolve_workflows_root

if TYPE_CHECKING:  # pragma: no cover - typing only
    from openstategraph.scaffold import FoundPackage

#: A directory holding this file is a workflow package, not a project root.
PACKAGE_MARKER = "workflow.json"


@dataclass(frozen=True)
class Opening:
    """The whole decision, as data.

    `refusal` and `consent_needed` are mutually exclusive by construction:
    a refusal has already said what to do instead, and a question that follows
    a refusal is a question nobody gets to answer.
    """

    #: The directory named on the command line, resolved.
    project: Path
    #: Where packages will be read from — `RootChoice.path`.
    workflows_root: Path
    #: What chose it, for the report and for a test to assert on.
    choice: RootChoice | None = None
    #: The report, printed in order when there is no refusal.
    lines: tuple[str, ...] = ()
    #: Print to stderr and exit 2. Nothing was done.
    refusal: str | None = None
    #: Ask before creating the workflows root. Only ever true on a terminal.
    consent_needed: bool = False
    #: Create the workflows root without asking — `--create` was given.
    will_create: bool = False
    #: What the review found, so a caller can count it.
    review: tuple["FoundPackage", ...] = ()


def plan(target: Path | str, *, create: bool, can_ask: bool) -> Opening:
    """What `open <target>` should say and ask. Touches nothing.

    `can_ask` is the terminal, not a preference: a prompt in CI is a hang, and
    exit codes are this CLI's API for CI (`scale-and-adopt/13`, which settled
    the same question for `init`). The difference here is that `open` is the
    verb a developer types at a prompt, so the question is asked when there is
    somebody to answer it and becomes a refusal naming a flag when there is
    not — one behaviour, two spellings, rather than two behaviours.

    The precedence chain is **not re-implemented**. The command changes where
    the process is standing and then `resolve_workflows_root()` answers,
    exactly as it answers for every other reader; this reports the answer and
    the reason. A second chain here is the defect `workflows_root` was written
    to have already fixed once.
    """
    project = Path(target).expanduser().resolve()

    if not project.is_dir():
        return Opening(project, project, refusal=f"{project} is not a directory.")

    package = _package_refusal(project)
    if package is not None:
        return Opening(project, project, refusal=package)

    choice = resolve_workflows_root()
    root = choice.path
    # Only what is about the *argument*. The resolved root and the reason for
    # it are `cli.startup_facts()`, which every serving path already prints —
    # printing them here too would be one directory said twice, three lines
    # apart, which is the shape this codebase calls a second copy.
    lines = [f"project      {project}"]

    # The failure this verb was filed over, said out loud. A root outside the
    # directory somebody just named is the silent case: the argument looked
    # like it decided something and it did not.
    if not _inside(root, project):
        lines.append(f"workflows    {root}")
        lines.append(f"note: {choice.why} — not the path you gave.")

    if not root.is_dir():
        offer = _no_root_offer(project, root, create=create, can_ask=can_ask)
        if offer.refusal is not None:
            return Opening(project, root, choice=choice, refusal=offer.refusal)
        return Opening(
            project,
            root,
            choice=choice,
            lines=tuple(lines + offer.lines),
            consent_needed=offer.consent_needed,
            will_create=offer.will_create,
        )

    from openstategraph.scaffold import review_lines, review_workflows_root

    review = review_workflows_root(root)
    lines.append("")
    lines.extend(review_lines(review))
    lines.extend(_configuration_note(project, choice))
    return Opening(project, root, choice=choice, lines=tuple(lines), review=review)


def _inside(root: Path, project: Path) -> bool:
    return root == project or project in root.parents


def _package_refusal(project: Path) -> str | None:
    """The case the owner named: a directory that *is* a workflow package.

    Refused rather than redirected. Treating it as a root would create a
    nested `workflows/workflows/`, and quietly meaning the parent instead is
    the same silent-substitution defect this verb exists to end — so the
    parent is *named*, as a command to run, and not taken.
    """
    if not (project / PACKAGE_MARKER).is_file():
        return None
    # `<root>/<slug>/workflow.json`, so the project is two levels up — when
    # the middle directory is really a workflows root. When it is not, the
    # parent is still the most useful thing to name.
    holder = project.parent
    suggested = holder.parent if holder.name in {"workflows", "flows"} else holder
    return (
        f"{project} is a workflow package, not a project root — it holds a "
        f"{PACKAGE_MARKER}.\n"
        f"Opening it as a project would put a workflows/ directory inside a "
        f"package. Nothing was done.\n"
        f"  the project it lives in:  openstategraph open {suggested}\n"
        f"  or run it as it is:       openstategraph run {project} \"hello\""
    )


@dataclass(frozen=True)
class _Offer:
    lines: list[str] = field(default_factory=list)
    refusal: str | None = None
    consent_needed: bool = False
    will_create: bool = False


def _no_root_offer(project: Path, root: Path, *, create: bool, can_ask: bool) -> _Offer:
    """`workflows/` is not there. Say so, and offer — never scaffold.

    The owner's line, and it is the rule rather than a preference: *a verb
    that quietly scaffolds is a verb people stop trusting to be read-only.*
    `init` is the scaffolding verb and already exists, so this offers the
    smallest thing that is not `init` — one empty directory — and names `init`
    for everything else.
    """
    if create:
        return _Offer(lines=["", f"{root} does not exist — creating it (--create)."], will_create=True)
    if can_ask:
        return _Offer(lines=["", f"{root} does not exist."], consent_needed=True)
    return _Offer(
        refusal=(
            f"{root} does not exist, and {project} holds no OpenStateGraph "
            f"configuration.\nNothing was written.\n"
            f"  scaffold a project:  openstategraph init {project}\n"
            f"  or just the folder:  openstategraph open {project} --create\n"
            f"You are not being asked because this is not a terminal — a prompt in "
            f"CI is a hang."
        )
    )


def _configuration_note(project: Path, choice: RootChoice) -> list[str]:
    """One line when the packages resolve by convention and nothing is committed.

    Not a refusal: `./workflows` is the convention every reader in this
    codebase already resolves, so this works. What it does not have is a
    committed answer, which is the thing that stops meaning the same directory
    the moment somebody starts the process from somewhere else.
    """
    if choice.source != "convention":
        return []
    return [
        "",
        f"no configuration file — {project.name}/ resolves workflows by convention.",
        f"  commit that answer:  openstategraph init {project}",
    ]


def prompt_line(root: Path) -> str:
    """The question, in one place, so the test and the terminal agree."""
    return f"Create {root}{os.sep} and open the editor on it? [y/N] "


__all__ = ["Opening", "PACKAGE_MARKER", "plan", "prompt_line"]
