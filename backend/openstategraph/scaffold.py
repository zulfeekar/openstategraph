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


__all__ = [
    "ScaffoldError",
    "SLUG_PATTERN",
    "copy_example",
    "new_package",
    "new_team",
    "new_workflow",
    "starter_document",
    "team_document",
]
