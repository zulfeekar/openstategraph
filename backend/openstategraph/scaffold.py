"""Creating a conforming workflow package — the one copy of the scaffold.

**Tier 2, provisional** (`docs/stability.md`): importable and documented, may
change in a minor release with a changelog note.

This used to live in `scripts/new_workflow.py` and `scripts/new_team.py`, which
worked exactly as long as you had a checkout. `scripts/` is not in the wheel, so
`openstategraph new` could not have called it — and the alternative, a second
copy of the document literal inside the CLI, is precisely the duplicated
*knowledge* CLAUDE.md names as the defect: the two copies would agree on the day
they were written and diverge on the first port rename.

So the scaffold moved **here**, and both entry points are thin:

- `scripts/new_workflow.py` / `scripts/new_team.py` keep their exact
  command lines and now call these functions;
- `openstategraph new <slug> [--template …]` calls the same functions.

**The documents themselves moved on again** (scale-and-adopt ticket 04): they
are data files under `openstategraph/templates/`, read through
`openstategraph.templates`. This module knows how to *make a package* — the
slug rule, the conventional directories, the storage envelope, the refusal to
overwrite — and no longer knows what any particular starting point looks like.
The two concerns changed for different reasons, and adding a third document
literal here is what would have made this file a catalogue by accident.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openstategraph import agent_brief, templates
from openstategraph.agent_config import AgentFileAction

#: A package's directory name is its frozen identity, and it is what scopes
#: tool, function, skill and knowledge discovery. Same rule as `slugify`.
SLUG_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*")

#: Discovered by convention, so a scaffold that omits them is a scaffold whose
#: conventions are invisible until someone reads the docs. Kept as names for
#: the callers that already import them; the authority is each template's own
#: `directories` in `templates/index.json`.
WORKFLOW_DIRECTORIES = ("tools", "functions", "middlewares", "skills", "tests", "data")
TEAM_DIRECTORIES = ("tools", "functions", "middlewares", "tests")


class ScaffoldError(ValueError):
    """A slug that cannot name a package, or a directory already there."""


def _prepare(root: Path | str, slug: str, subdirectories: tuple[str, ...]) -> Path:
    if not SLUG_PATTERN.fullmatch(slug):
        raise ScaffoldError(f"slug {slug!r} must be lowercase letters, digits and hyphens")
    target = Path(root) / slug
    if target.exists():
        raise ScaffoldError(f"{target} already exists")
    target.mkdir(parents=True)
    for name in subdirectories:
        (target / name).mkdir()
    return target


def _envelope(name: str, document: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "name": name,
        # Ticket 04: scaffolded workflows are DRAFTS. Publish via
        # POST /api/workflows/<slug>/publish (or the editor's Workflows panel)
        # to appear on the customer /chat surface.
        "published": False,
        "savedAt": datetime.now(timezone.utc).isoformat(),
        "document": document,
    }


def new_package(
    root: Path | str,
    slug: str,
    *,
    template: str = templates.DEFAULT_TEMPLATE,
    name: str | None = None,
    outcome: str | None = None,
) -> Path:
    """Create `<root>/<slug>/` from a named template. Returns the directory,
    which is exactly what `load_workflow` takes.

    Raises `templates.UnknownTemplateError` for a name not in the catalogue and
    `ScaffoldError` for a slug that cannot name a package or a directory that
    already exists. The template is resolved **before** anything is written, so
    a bad name never leaves a half-made package behind.
    """
    chosen = templates.get(template)
    display = name or slug.replace("-", " ").title()
    target = _prepare(root, slug, chosen.directories)
    try:
        document = chosen.document(display, outcome=outcome)
        (target / "workflow.json").write_text(
            json.dumps(_envelope(display, document), indent=2) + "\n"
        )
        (target / "AGENTS.md").write_text(chosen.agents_md(display, slug, outcome=outcome))
        test_shape = chosen.test_shape_py(display, slug, outcome=outcome)
        if test_shape is not None:
            (target / "tests" / "test_shape.py").write_text(test_shape)
    except Exception:
        # A package with directories and no document is not a package; it is
        # debris the next `new` run would then refuse to overwrite.
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target


def starter_document(name: str) -> dict[str, Any]:
    """input → agent → output. The smallest document that compiles and runs."""
    return templates.get("minimal").document(name)


def team_document(name: str, outcome: str) -> dict[str, Any]:
    """The prebuilt minimum-viable Team (ticket 52): supervisor + worker + grader.

    The grader's criteria ARE the team's outcome contract — the first thing a
    developer edits — and the `revise` edge back to the supervisor is what
    makes the loop a loop. A cycle needs a conditional edge to terminate, and
    the grader is it.
    """
    return templates.get("team").document(name, outcome=outcome)


def new_workflow(root: Path | str, slug: str, name: str | None = None) -> Path:
    """Create `<root>/<slug>/` from the default template. Kept for the callers
    that predate templates; `new_package` is the general form."""
    return new_package(root, slug, template=templates.DEFAULT_TEMPLATE, name=name)


def new_team(root: Path | str, slug: str, outcome: str | None = None) -> Path:
    """Create `<root>/<slug>/` as a Team package. Returns the directory."""
    return new_package(root, slug, template="team", outcome=outcome)


def _package_digest(directory: Path) -> dict[str, str]:
    """Every file under `directory`, keyed by its path relative to it, hashed.

    The comparison install-experience 20b needed a defensible definition for.
    Included: `workflow.json`, `AGENTS.md`, `tools/`, `tests/`, `knowledge/`,
    `data/` — everything a package actually ships, because a difference in any
    of them is a difference a `requires()`-er would inherit. Excluded:
    `__pycache__` and `*.pyc` (bytecode, never shipped — `copy_example` itself
    already strips them on the way out) and `.DS_Store` (Finder noise, not
    package content). File **mtimes are never read** — only bytes — so two
    copies made minutes apart still compare identical.
    """
    digests: dict[str, str] = {}
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc" or path.name == ".DS_Store":
            continue
        digests[str(path.relative_to(directory))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def _is_unedited(existing: Path, shipped: Path) -> bool:
    """Whether `existing` (already on disk) is byte-identical to `shipped`
    (what the gallery would copy). See `_package_digest` for what counts."""
    return _package_digest(existing) == _package_digest(shipped)


class CopyResult(tuple[Path, ...]):
    """`tuple[Path, ...]` — every existing caller keeps working unchanged —
    plus which of those paths were already there, byte-identical to what
    ships, and so were left alone rather than overwritten.

    A plain tuple subclass rather than a dataclass: `copy_example` has always
    returned "the paths now present", and that contract does not change here
    — this only adds a way to ask which of them `copy_example` did not
    actually touch.
    """

    kept: frozenset[Path]

    def __new__(cls, paths: tuple[Path, ...], kept: frozenset[Path]) -> "CopyResult":
        result = super().__new__(cls, paths)
        result.kept = kept
        return result


def copy_example(root: Path | str, slug: str) -> CopyResult:
    """Copy a shipped example, and everything it mounts, into `root`.

    Gallery ticket 07. The counterpart to `new_package`: a template is
    *rendered* into a new package, an example is **copied** verbatim into one.
    Returns the directories written, the requested example first.

    Three things this does not do, each on purpose:

    - **No rename.** A package's directory name is its frozen identity and a
      mounting document addresses it by that name, so `nested-mounts` copied as
      `my-mounts` would still be looking for `nested-mounts-mid`. The slug
      travels with the package.
    - **No substitution.** An example has no placeholders; it is the document
      that was actually smoke-run, and rewriting it would break the claim its
      `AGENTS.md` makes.
    - **No edit of the envelope.** `published: false` is copied through, and in
      the user's own root it finally means what it says: this is your draft,
      publish it when you choose.

    Raises `examples.UnknownExampleError` for a slug that is not in the
    gallery, and `ScaffoldError` when any directory it would write already
    exists **and differs** from what would be copied — checked for the *whole*
    set before the first byte is written, so a refusal never leaves half a
    dependency chain behind.

    install-experience 20b: a *transitive* requirement already on disk is not
    automatically a clash — only the package `slug` itself names directly. A
    dependency that is byte-identical to the shipped copy (`_is_unedited`) is
    already satisfied — skipped rather than refused, named in the result's
    `.kept`. The requested slug itself keeps the old, stricter behaviour:
    asking to copy `chained-summarizer` a second time still refuses, even
    byte-identical, because a repeated direct request is a question the caller
    gets to ask again rather than a transitive detail this call is entitled to
    silently satisfy on its behalf. This stays all-or-nothing: the moment
    *any* dependency actually differs, the whole copy is refused exactly as
    before, identical ones included, because "copy the rest" is only safe when
    nothing on the set differs. Ticket 08's protection is unchanged — an
    *edited* dependency still refuses, same message, nothing written.
    """
    from openstategraph import examples

    needed = examples.get(slug).requires()
    root = Path(root)
    targets = [(name, root / name) for name in needed]

    clashes: list[str] = []
    kept: set[Path] = set()
    for name, path in targets:
        if not path.exists():
            continue
        if name != slug and _is_unedited(path, examples.get(name).directory):
            kept.add(path)
        else:
            clashes.append(str(path))
    if clashes:
        raise ScaffoldError(
            f"{', '.join(clashes)} already exists — "
            f"copying {slug} would overwrite it, so nothing was written"
        )

    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    newly_written: list[Path] = []
    try:
        for name, path in targets:
            if path in kept:
                written.append(path)
                continue
            shutil.copytree(
                examples.get(name).directory,
                path,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            written.append(path)
            newly_written.append(path)
    except Exception:
        for path in newly_written:
            shutil.rmtree(path, ignore_errors=True)
        raise
    return CopyResult(tuple(written), frozenset(kept))


@dataclass(frozen=True)
class GalleryFootprint:
    """What taking the whole gallery costs, measured before it is taken.

    install-experience T8. The size is announced rather than discovered:
    `sql-qa` ships a 1 MB sqlite database, and a megabyte landing in somebody's
    repository unannounced is the kind of surprise this project refuses
    everywhere else.
    """

    #: How many packages `copy_all_examples` would write.
    packages: int
    #: Their total size on disk.
    bytes: int
    #: The single largest file, relative to the gallery root — derived, so the
    #: day it stops being the Chinook database this still tells the truth.
    largest_name: str
    largest_bytes: int

    @property
    def human(self) -> str:
        """`1.2 MB`. Decimal, because that is what a filesystem reports."""
        return _human_bytes(self.bytes)

    @property
    def largest_human(self) -> str:
        return _human_bytes(self.largest_bytes)


def _human_bytes(count: int) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f} MB"
    if count >= 1_000:
        return f"{count / 1_000:.0f} KB"
    return f"{count} bytes"


def gallery_footprint() -> GalleryFootprint:
    """Measure the shipped gallery. Reads sizes, opens nothing."""
    from openstategraph import examples

    total = 0
    largest: tuple[str, int] = ("", 0)
    for path in examples.DATA.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        size = path.stat().st_size
        total += size
        if size > largest[1]:
            largest = (str(path.relative_to(examples.DATA)), size)
    return GalleryFootprint(
        packages=len(examples.slugs()),
        bytes=total,
        largest_name=largest[0],
        largest_bytes=largest[1],
    )


def copy_all_examples(root: Path | str) -> tuple[Path, ...]:
    """Copy every shipped example into `root`. install-experience T8.

    The plural of `copy_example`, and it inherits every one of that function's
    rules rather than inventing new ones: no rename, no substitution, no
    envelope edit, and **all-or-nothing over the whole set** — one clash
    anywhere and not a byte is written, because a half-copied gallery is a
    directory the next attempt then refuses to touch.

    The transitive closure is already handled: a mounted package is in the
    catalogue too, so copying the catalogue copies every mount by definition.
    """
    from openstategraph import examples

    root = Path(root)
    targets = [(slug, root / slug) for slug in examples.slugs()]
    clashes = [str(path) for _, path in targets if path.exists()]
    if clashes:
        raise ScaffoldError(
            f"{', '.join(clashes)} already exists — "
            f"copying every example would overwrite it, so nothing was written"
        )

    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    try:
        for slug, path in targets:
            shutil.copytree(
                examples.get(slug).directory,
                path,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            written.append(path)
    except Exception:
        for path in written:
            shutil.rmtree(path, ignore_errors=True)
        raise
    return tuple(written)


# --------------------------------------------------------------------- #
# The project — install-experience T6
# --------------------------------------------------------------------- #

#: The one package `init` writes, and the name is the same word the editor's
#: `assembly.starter` palette item and `starter_document()` already use. They
#: agree in substance — all three are input → agent → output — so this is a
#: convergence rather than a third meaning (design collision C9).
STARTER_SLUG = "starter"

#: The last line `init` prints. `osg-agent-experience/25`: everything above it
#: is a list of files, and a reader who has just been told their agent is
#: configured still needs the sentence that addresses it. One copy, here,
#: because the CLI is not the only door that will want to print it.
NEXT_SENTENCE = (
    'next: open your coding agent here and say "use OpenStateGraph" and'
    " describe the workflow you want."
)


#: `osg-agent-experience/24`. Every file `init` writes for a coding agent —
#: the four MCP configs, both skill roots, `AGENTS.md` — is read when that
#: agent starts, and `init` is very often typed *inside* the session that will
#: use them. So the agent that just ran it has seen none of them, and the
#: sentence above this one tells the developer to address it. One copy, here,
#: beside `NEXT_SENTENCE`, which has the same reason.
RESTART_SENTENCE = (
    "restart your coding agent so it re-scans this directory — it reads the"
    " files above only at start-up."
)


@dataclass(frozen=True)
class InitResult:
    """What `init_project` made, and what it found already there.

    Both halves, because `--force` **adds**: it never deletes and never
    overwrites a file it did not write, so "created" and "left alone" are
    different sentences the command has to be able to print truthfully.
    """

    #: The project directory — the thing the user named.
    directory: Path
    #: `<directory>/openstategraph.yaml`.
    config: Path
    #: `<directory>/.gitignore`.
    gitignore: Path
    #: `<directory>/AGENTS.md` — the brief a coding agent reads
    #: (install-experience/25).
    agents_md: Path
    #: Which of `created` / `added` / `refreshed` / `current` happened to the
    #: marked block in it. Four states rather than a boolean, because "we
    #: wrote the file", "we added a block to yours" and "it was already right"
    #: are three different sentences and `init` prints one of them.
    agents_md_action: str
    #: The workflows root inside it — `workflows/` unless renamed.
    workflows: Path
    #: `<workflows>/starter`, or `None` when the starter was not asked for.
    starter: Path | None
    #: Exactly the paths this call wrote. Anything above and not in here was
    #: already on disk and was left untouched.
    created: frozenset[Path]
    #: Whether the directory existed and was empty — case two, which is a
    #: success with a sentence rather than a refusal.
    reused_empty: bool
    #: launch-readiness/32: set when the directory was non-empty and not
    #: already ours — a warning that proceeds, never a refusal. `None` when
    #: there was nothing to say.
    existing_project_warning: str | None
    #: launch-readiness/191: which of the ignore rules this project needs an
    #: *existing* `.gitignore` does not carry. Empty when we wrote the file
    #: ourselves, and empty when theirs already covers both — so the caller
    #: can only say "already covers it" in the case where it does. Never a
    #: reason to write: the fix was the sentence, not the file.
    gitignore_gaps: tuple[str, ...]
    #: The packages already in the workflows root when `--adopt` took it over.
    #: Empty whenever there was nothing to adopt, which is what makes
    #: `--adopt` inert in a fresh directory rather than a second, quieter
    #: `init` that skips the starter.
    adopted: tuple[FoundPackage, ...] = ()
    #: `{(root, skill_name): state}` for `ticket-forge`/`kanban-patrol` —
    #: kanban-patrol/24. Carried so `init`'s printed report can say what
    #: happened per file, same as it does for `AGENTS.md`.
    skills_installed: dict[tuple[str, str], str] = field(default_factory=dict)
    #: One per agent config file — `.mcp.json`, `.vscode/mcp.json`,
    #: `.cursor/mcp.json`, `.codex/config.toml` — with which of created /
    #: merged / current / kept happened to it (`osg-agent-experience/25`).
    #: Same reason as `agents_md_action`: `init` prints a sentence per file
    #: and two of those four sentences say it wrote nothing.
    agent_files: tuple[AgentFileAction, ...] = ()


def agent_surface_changed(result: InitResult) -> bool:
    """Did this run put anything in front of a coding agent that it has not read?

    `osg-agent-experience/24`. The predicate for `RESTART_SENTENCE`, derived
    from the three states `init` already prints rather than from a flag set at
    the write: a second `init --force` that reports `current` down the whole
    block changed nothing an agent could re-scan, and telling a developer to
    restart for that is advice that teaches them to skip the next one.
    """
    from openstategraph.agent_config import AgentFileState

    return (
        result.agents_md_action != agent_brief.CURRENT
        or any(state != agent_brief.CURRENT for state in result.skills_installed.values())
        or any(
            action.state not in (AgentFileState.CURRENT, AgentFileState.KEPT)
            for action in result.agent_files
        )
    )


def _existing_directory_refusal(target: Path, label: str) -> str | None:
    """The remaining hard-stop cases, or `None` to proceed.

    launch-readiness/32: the "directory is not empty" case used to live here
    too, as a third refusal. It never protected anything — `init` writes
    `openstategraph.yaml` only `if not config.exists()`, never writes `.env`,
    and a non-empty directory is exactly what following the README's own
    install steps produces (a `venv/`, a `.env`). Refusing it taught a reader
    to go and pick a different, wrong directory instead. It is now
    `_existing_directory_warning`, below: same observation, no exit.

    One refusal is left, and it stays a refusal on purpose: an existing
    OpenStateGraph project sends the reader to `serve` rather than letting a
    second `init` silently re-adopt it. `--force` still waives it.

    The confirmation is `--force`, a flag, and it appears **inside** the
    refusal so it is never something to go and look up. Not a prompt: exit
    codes are this CLI's API for CI, and a command that blocks on stdin hangs
    a CI job.
    """
    if not target.exists():
        return None
    if not target.is_dir():
        return f"{label} exists and is not a directory. Nothing was written."

    from openstategraph.config_file import CONFIG_FILENAMES

    for name in CONFIG_FILENAMES:
        if (target / name).is_file():
            return (
                f"{label}/{name} is already there — this is already an\n"
                f"OpenStateGraph project, and nothing was written.\n"
                f"  open it:      cd {label} && openstategraph serve\n"
                f"  start again:  openstategraph init {label} --force"
            )
    return None


def _existing_directory_warning(target: Path, label: str, workflows_dir: str) -> str | None:
    """A non-empty directory that is not already ours — a warning, not a
    refusal (launch-readiness/32, owner decision 2026-08-24: warn, then
    proceed).

    Runs regardless of `--force`, because there is nothing left for `--force`
    to waive here: the command never overwrites or deletes anything this case
    could be protecting. Says what is actually happening — `workflows/` and
    `openstategraph.yaml` are being added to what looks like an existing
    project — rather than implying a collision that cannot happen. The
    "already ours" case is handled by `_existing_directory_refusal` and never
    reaches here.
    """
    if not target.is_dir() or _looks_like_our_project(target):
        return None
    entries = list(target.iterdir())
    if not entries:
        return None
    count = len(entries)
    noun = "file" if count == 1 else "files"
    return (
        f"{label}/ already has {count} {noun} in it — this looks like an existing\n"
        f"project. Adding {workflows_dir}/ and openstategraph.yaml to it now."
    )


def _looks_like_our_project(target: Path) -> bool:
    """Whether `target` carries an OpenStateGraph config file.

    The same marker `_existing_directory_refusal` uses for case two, reused
    here for a different question: whose `workflows/` is that? A directory
    with our config file is ours and so is its workflows root, which is what
    keeps `init x --force` idempotent on a project we made.
    """
    from openstategraph.config_file import CONFIG_FILENAMES

    return any((target / name).is_file() for name in CONFIG_FILENAMES)


@dataclass(frozen=True)
class FoundPackage:
    """One directory inside a workflows root somebody else wrote.

    `error` rather than an omission, which is the catalogue's rule for the
    same reason: a review that silently drops the one package that will not
    parse hides exactly what a reader most needs before adopting a directory.
    """

    #: The folder name — the slug this package would be addressed by.
    slug: str
    #: `name` from its document, or the slug when the document does not say.
    name: str
    #: How many nodes it draws. Zero when the document could not be read.
    node_count: int
    #: Why it could not be read, or `None`.
    error: str | None


def review_workflows_root(root: Path) -> tuple[FoundPackage, ...]:
    """What is already in a workflows root, read without compiling anything.

    **The reading is `WorkflowStore.list`'s, not a second one.** The envelope
    a `workflow.json` carries — `document.nodes`, a `published` flag, a
    `savedAt` — is knowledge that already has one owner, and a hand-rolled
    `json.loads` here would be a second copy of it that drifts silently. The
    first draft of this function was exactly that, and it reported a real
    seven-node package as *"0 nodes"* because it read `nodes` off the
    envelope instead of off the document inside it.

    Cheap by construction rather than by promise: that method reads one
    `workflow.json` per package and imports no runtime, builds no model and
    executes nobody's `tools/*.py` — which matters more here than anywhere
    else, because this runs against a directory that is not ours and before a
    project exists at all.

    `include_broken=True`, and hidden packages included: this answers "what am
    I about to adopt", and the honest answer names everything the root holds.
    """
    from openstategraph.api.workflow_store import WorkflowStore

    if not root.is_dir():
        return ()
    rows = WorkflowStore(root).list(include_broken=True, include_hidden=True)
    return tuple(
        FoundPackage(
            slug=row.slug,
            name=row.name or row.slug,
            node_count=row.node_count,
            error=row.error or None,
        )
        for row in sorted(rows, key=lambda row: row.slug)
    )


def review_lines(found: tuple[FoundPackage, ...]) -> list[str]:
    """The review, as the refusal and the adoption report both print it."""
    if not found:
        return ["  (no packages in it yet)"]
    width = max(len(row.slug) for row in found)
    lines = []
    for row in found:
        if row.error is not None:
            lines.append(f"  {row.slug.ljust(width)}  will not parse — {row.error}")
        else:
            plural = "" if row.node_count == 1 else "s"
            lines.append(f"  {row.slug.ljust(width)}  {row.name} — {row.node_count} node{plural}")
    return lines


def _shared_workflows_root_refusal(target: Path, workflows_dir: str, label: str) -> str | None:
    """production-ready/68 — the one directory `init` was most likely to
    collide over, and the only one it said nothing about.

    `WorkflowStore.list` scans this root for packages, so moving in beside
    somebody else's `workflows/` makes two things share it. Nothing is
    destroyed; the defect is that the user was never told.

    **This refusal is deliberately not waived by `--force`.** It cannot be:
    a non-empty target is already refused by
    `_existing_directory_refusal`, and a target that does not exist cannot
    contain a `workflows/`, so `--force` is the *only* way to reach this
    check. A flag that both reaches a check and waives it is a check that
    never runs. The module already draws this line once — `--force` is
    consent to use a directory that has things in it — and this is the same
    line one level down: it is not consent to share the workflows root.

    The waiver is the project marker instead, which is a fact rather than a
    guess about what the folder holds.
    """
    root = target / workflows_dir
    if not root.exists() or _looks_like_our_project(target):
        return None
    if not root.is_dir():
        return f"{label}/{workflows_dir} exists and is not a directory. Nothing was written."
    # Never suggest the name that just collided — a suggestion that repeats
    # the failing input is a loop rather than an exit. Ordinals, the same
    # spelling case four uses for the project directory.
    ordinal = 2
    while (target / f"{workflows_dir}_{ordinal}").exists():
        ordinal += 1
    review = "\n".join(review_lines(review_workflows_root(root)))
    return (
        f"{label}/{workflows_dir}/ already exists and is not ours. Nothing was written.\n"
        f"Here is what is in it:\n"
        f"{review}\n"
        f"  adopt it:           openstategraph init {label} --force --adopt\n"
        f"  pick another root:  openstategraph init {label} --force"
        f" --workflows-dir {workflows_dir}_{ordinal}\n"
        f"  or move theirs:     mv {label}/{workflows_dir} {label}/{workflows_dir}_old\n"
        f"--force is consent to use a directory with things in it, not consent to share\n"
        f"the workflows root: OpenStateGraph scans {workflows_dir}/ for packages, so from\n"
        f"then on it would be reading directories it did not write. `--adopt` is that\n"
        f"second consent, and it is the right answer when those packages are yours —\n"
        f"a service that already ships workflows and now wants the canvas over them."
    )


def init_project(
    directory: Path | str,
    *,
    label: str | None = None,
    workflows_dir: str = "workflows",
    force: bool = False,
    starter: bool = True,
    adopt: bool = False,
) -> InitResult:
    """Make `directory` an OpenStateGraph project. The third writer here.

    install-experience T6, and the honest substitute for a syntax pip cannot
    parse: an extra is a bare identifier, so `openstategraph[directory:'x']`
    does not parse, and `openstategraph[x]` installs successfully while doing
    nothing at all. The directory a user wants to name is named by a command.

    Writes a commented `openstategraph.yaml`, a `.gitignore`, the workflows
    root, and `workflows/starter/` from the `minimal` template — the template
    that pins no model, so the first package an adopter owns runs on whatever
    provider extra they installed.

    **It never writes `.env`.** A generator that emits a credential file is a
    generator whose output someone commits; the caller prints how to make one
    instead. The `.gitignore` names it all the same, so the rule is in place
    before the user creates it by hand.

    `label` is the directory as the *user spelled it*, for the refusals — a
    message about `my_demo/` is one they can act on; a message about
    `/private/var/folders/…/my_demo` is one they have to decode.

    Raises `ScaffoldError` when the target is already an OpenStateGraph
    project, unless `force`. `force`'s only remaining job is that one waiver
    — the directory-is-not-empty case (launch-readiness/32) is a warning
    that always proceeds now, and the shared-workflows-root refusal below has
    never been forceable at all — so `force` no longer touches either of
    them.
    """
    from openstategraph.config_file import (
        CONFIG_FILENAMES,
        gitignore_gaps,
        render_config_file,
        render_gitignore,
    )

    target = Path(directory).expanduser()
    name = label if label is not None else str(directory)

    if not force:
        refusal = _existing_directory_refusal(target, name)
        if refusal is not None:
            raise ScaffoldError(refusal)
    elif target.exists() and not target.is_dir():
        # `--force` is consent to use a directory that has things in it, not
        # consent to delete a file standing where the directory should be.
        raise ScaffoldError(f"{name} exists and is not a directory. Nothing was written.")

    existing_project_warning = _existing_directory_warning(target, name, workflows_dir)

    adopted = review_workflows_root(target / workflows_dir) if adopt else ()
    if not adopt:
        shared = _shared_workflows_root_refusal(target, workflows_dir, name)
        if shared is not None:
            raise ScaffoldError(shared)

    reused_empty = target.is_dir() and not any(target.iterdir())
    target.mkdir(parents=True, exist_ok=True)

    created: list[Path] = []
    config = target / CONFIG_FILENAMES[0]
    if not config.exists():
        from openstategraph.project_identity import ensure_project_identity

        # Minted before the file is written, never after: `render_config_file`
        # needs the value in hand, and this is the one call site where
        # `project_id=None` is the correct argument — a config that does not
        # exist yet cannot have one. kanban-patrol/03.
        #
        # `target / ".openstategraph"`, not `state_dir(target / workflows_dir)`
        # — the latter lives *inside* the workflows root, which two existing
        # tests pin as holding nothing but packages right after `init`
        # (`TestWhatItWrites::test_empty_skips_the_starter`, and the adopt
        # review). The project root's own `.openstategraph/` is a sibling
        # directory, already covered by the existing `**/.openstategraph/`
        # gitignore rule, so nothing else needs to change to keep it ignored.
        identity = ensure_project_identity(project_id=None, state_dir=target / ".openstategraph")
        elected = _elected_model()
        config.write_text(
            render_config_file(
                workflows_dir=workflows_dir,
                default_model=elected,
                project_id=identity.project_id,
            )
        )
        created.append(config)

    gitignore = target / ".gitignore"
    ignore_gaps: tuple[str, ...] = ()
    if not gitignore.exists():
        gitignore.write_text(render_gitignore())
        created.append(gitignore)
    else:
        ignore_gaps = gitignore_gaps(gitignore.read_text(errors="replace"))

    # The brief the wheel carries, put where an agent looks. Never touches a
    # byte outside its markers, so it is safe on a directory that already had
    # an AGENTS.md — which is the common case for the reader this exists for.
    agents_md, agents_md_action = agent_brief.write_into(target)
    if agents_md_action == agent_brief.CREATED:
        created.append(agents_md)

    # OpenStateGraph's own skills, installed project-locally — kanban-patrol/24.
    # Same reasoning as the brief above: a wheel cannot write into a user's
    # repository by itself, so `init` is the door. Unlike `AGENTS.md`, a
    # skill file is not shared with the user's own notes, so a `created`
    # state is the only one that adds to `created` below — `refreshed` means
    # something was already there and this project owns overwriting it.
    from openstategraph.bundled_skills import CREATED as SKILL_CREATED
    from openstategraph.bundled_skills import install_bundled_skills

    skills_installed = install_bundled_skills(target)
    for (skill_root, relative), state in skills_installed.items():
        if state == SKILL_CREATED:
            created.append(target / skill_root / relative)

    # The four files four coding agents read to find this project's MCP
    # server, rendered from one descriptor — osg-agent-experience/25. Same
    # door, same reason as the skills above: a wheel cannot write into a
    # user's repository by itself. An existing file is merged into, never
    # replaced; see `agent_config`.
    from openstategraph.agent_config import AgentFileState, render_all

    agent_files = render_all(target)
    for action in agent_files:
        if action.state is AgentFileState.CREATED:
            created.append(action.path)

    root = target / workflows_dir
    root.mkdir(parents=True, exist_ok=True)

    package: Path | None = None
    # No starter into a root that already holds somebody else's packages. It
    # is a teaching aid for an empty root; in an adopted one it is litter,
    # under a slug (`starter`) the owners may already be using.
    if starter and not adopted:
        package = root / STARTER_SLUG
        if not package.exists():
            new_package(root, STARTER_SLUG, template=templates.DEFAULT_TEMPLATE)
            created.append(package)

    return InitResult(
        directory=target,
        config=config,
        gitignore=gitignore,
        agents_md=agents_md,
        agents_md_action=agents_md_action,
        workflows=root,
        starter=package,
        created=frozenset(created),
        reused_empty=reused_empty,
        existing_project_warning=existing_project_warning,
        gitignore_gaps=ignore_gaps,
        adopted=adopted,
        skills_installed=skills_installed,
        agent_files=agent_files,
    )


def _elected_model() -> str | None:
    """The instance default's model string, for the generated file's comment.

    Best-effort and deliberately so: `init` must work on a machine with no
    provider integration at all — that is one of the states it exists to
    explain — so a catalogue that cannot answer produces a generic example
    rather than a failure.
    """
    try:
        from openstategraph.providers import provider_catalogue

        return provider_catalogue().elected_default().model
    except Exception:  # pragma: no cover - a catalogue that cannot load
        return None


__all__ = [
    "GalleryFootprint",
    "InitResult",
    "NEXT_SENTENCE",
    "RESTART_SENTENCE",
    "ScaffoldError",
    "SLUG_PATTERN",
    "STARTER_SLUG",
    "agent_surface_changed",
    "copy_all_examples",
    "copy_example",
    "gallery_footprint",
    "init_project",
    "new_package",
    "new_team",
    "new_workflow",
    "review_lines",
    "review_workflows_root",
    "starter_document",
    "team_document",
]
