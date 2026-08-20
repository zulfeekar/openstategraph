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

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openstategraph import templates

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


def copy_example(root: Path | str, slug: str) -> tuple[Path, ...]:
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
    exists — checked for the *whole* set before the first byte is written, so a
    refusal never leaves half a dependency chain behind.
    """
    from openstategraph import examples

    needed = examples.get(slug).requires()
    root = Path(root)
    targets = [(name, root / name) for name in needed]

    clashes = [str(path) for _, path in targets if path.exists()]
    if clashes:
        raise ScaffoldError(
            f"{', '.join(clashes)} already exists — "
            f"copying {slug} would overwrite it, so nothing was written"
        )

    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    try:
        for name, path in targets:
            shutil.copytree(
                examples.get(name).directory,
                path,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            written.append(path)
    except Exception:
        for path in written:
            shutil.rmtree(path, ignore_errors=True)
        raise
    return tuple(written)


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


def _existing_directory_refusal(target: Path, label: str) -> str | None:
    """The four cases of install-experience design §2.3, or `None` to proceed.

    Two refusals, and they must never collapse into one sentence: an existing
    OpenStateGraph project sends the reader to `serve`, while somebody else's
    directory sends them to a different name. A single "directory exists"
    message would answer neither.

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

    entries = list(target.iterdir())
    if entries:
        count = len(entries)
        noun = "file" if count == 1 else "files"
        return (
            f"{label}/ already exists and has {count} {noun} in it. Nothing was written.\n"
            f"  pick another name:  openstategraph init {label}_2\n"
            f"  use it anyway:      openstategraph init {label} --force\n"
            f"--force adds openstategraph.yaml, .gitignore and workflows/ to {label}/ and\n"
            f"overwrites nothing that is already there."
        )
    return None

def _looks_like_our_project(target: Path) -> bool:
    """Whether `target` carries an OpenStateGraph config file.

    The same marker `_existing_directory_refusal` uses for case two, reused
    here for a different question: whose `workflows/` is that? A directory
    with our config file is ours and so is its workflows root, which is what
    keeps `init x --force` idempotent on a project we made.
    """
    from openstategraph.config_file import CONFIG_FILENAMES

    return any((target / name).is_file() for name in CONFIG_FILENAMES)


def _shared_workflows_root_refusal(
    target: Path, workflows_dir: str, label: str
) -> str | None:
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
        return (
            f"{label}/{workflows_dir} exists and is not a directory. Nothing was written."
        )
    # Never suggest the name that just collided — a suggestion that repeats
    # the failing input is a loop rather than an exit. Ordinals, the same
    # spelling case four uses for the project directory.
    ordinal = 2
    while (target / f"{workflows_dir}_{ordinal}").exists():
        ordinal += 1
    return (
        f"{label}/{workflows_dir}/ already exists and is not ours. Nothing was written.\n"
        f"  pick another root:  openstategraph init {label} --force"
        f" --workflows-dir {workflows_dir}_{ordinal}\n"
        f"  or move theirs:     mv {label}/{workflows_dir} {label}/{workflows_dir}_old\n"
        f"--force is consent to use a directory with things in it, not consent to share\n"
        f"the workflows root: OpenStateGraph scans {workflows_dir}/ for packages, so from\n"
        f"then on it would be reading directories it did not write."
    )


def init_project(
    directory: Path | str,
    *,
    label: str | None = None,
    workflows_dir: str = "workflows",
    force: bool = False,
    starter: bool = True,
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

    Raises `ScaffoldError` for the two existing-directory refusals unless
    `force`, which waives only the "not empty" precondition — never the
    standing refusal to overwrite a file it did not write.
    """
    from openstategraph.config_file import CONFIG_FILENAMES, render_config_file, render_gitignore

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

    shared = _shared_workflows_root_refusal(target, workflows_dir, name)
    if shared is not None:
        raise ScaffoldError(shared)

    reused_empty = target.is_dir() and not any(target.iterdir())
    target.mkdir(parents=True, exist_ok=True)

    created: list[Path] = []
    config = target / CONFIG_FILENAMES[0]
    if not config.exists():
        elected = _elected_model()
        config.write_text(render_config_file(workflows_dir=workflows_dir, default_model=elected))
        created.append(config)

    gitignore = target / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(render_gitignore())
        created.append(gitignore)

    root = target / workflows_dir
    root.mkdir(parents=True, exist_ok=True)

    package: Path | None = None
    if starter:
        package = root / STARTER_SLUG
        if not package.exists():
            new_package(root, STARTER_SLUG, template=templates.DEFAULT_TEMPLATE)
            created.append(package)

    return InitResult(
        directory=target,
        config=config,
        gitignore=gitignore,
        workflows=root,
        starter=package,
        created=frozenset(created),
        reused_empty=reused_empty,
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
    "ScaffoldError",
    "SLUG_PATTERN",
    "STARTER_SLUG",
    "copy_all_examples",
    "copy_example",
    "gallery_footprint",
    "init_project",
    "new_package",
    "new_team",
    "new_workflow",
    "starter_document",
    "team_document",
]
