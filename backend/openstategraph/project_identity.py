"""`project_id` — the identity every kanban card is permanently attached to.

kanban-patrol/03. A card (`kanban-patrol/19`) keys itself off
`project_id + thread_id`, so `project_id` has to be stable across an ordinary
reopen and legible enough that a stray `kanban.sqlite` can be traced to the
project that wrote it. Neither a bare path (moves, gets remounted in a
container — the exact failure `openstategraph.yaml` itself once required
moving under `backend/` to dodge) nor a bare name (three projects can all be
called "Untitled") is either of those things on its own.

## The story this module exists to close

Clone `openstategraph.yaml` into a second folder to bootstrap a new project
from an old one — a `cp -r`, a git clone, a zip someone emailed — and the
`project_id` line comes along, because it is a plain committed file, same as
copying a repo carries its history. Now two projects share one identity, and
every kanban card from either one lands in the same bucket, silently.

The fix used here is `/etc/machine-id`'s own: a VM cloned from a disk image
does not inherit the image's identity, because a *second*, un-copied marker is
checked on boot. `project_id` (committed, travels with the file) is paired
with a **companion marker** written to the same directory as `.openstategraph/`
at the moment `project_id` is minted — and `.openstategraph/` is already
gitignored (`scaffold.py`'s own `init_project` writes that line), so an
ordinary clone or copy never carries the companion, only the id.

## What each outcome means, so the caller can act on it truthfully

Three states, not a boolean — this project's own idiom throughout
`InitResult` (`agents_md_action`, `existing_project_warning`): "we minted it",
"we found ours", and "we found someone else's" are three different sentences
and the caller has to be able to print the right one.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path

_COMPANION_FILENAME = "project_identity"


class ProjectIdentityState(Enum):
    #: No `project_id` in the config at all. Minted both halves together.
    MINTED = "minted"
    #: `project_id` present, companion present, they agree. The checkout that
    #: minted it, or a later run on the same checkout. Nothing written.
    VERIFIED = "verified"
    #: `project_id` present, companion **absent**. This checkout never minted
    #: it — copied here from a clone, a `cp -r`, a template. Ambiguous by
    #: construction: could be a continuation of that project (keep it) or the
    #: start of a new one that happened to start from a copy (re-mint).
    #: Nothing is written; the caller must ask rather than guess either way.
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class ProjectIdentityResult:
    state: ProjectIdentityState
    project_id: str | None


def ensure_project_identity(
    *, project_id: str | None, state_dir: Path
) -> ProjectIdentityResult:
    """Read-then-decide. Never writes on the `UNVERIFIED` path — see module
    docstring: an ambiguous case is answered by asking, not by this function
    picking for the caller.

    `project_id is None` means the config has no `project_id:` line yet, which
    is the only case this function is allowed to mint into. A present
    `project_id` is never overwritten and never regenerated here, matching
    `InitResult.created`'s own rule of only ever adding, never replacing.
    """
    companion = state_dir / _COMPANION_FILENAME

    if project_id is None:
        minted = str(uuid.uuid4())
        state_dir.mkdir(parents=True, exist_ok=True)
        companion.write_text(minted + "\n")
        return ProjectIdentityResult(ProjectIdentityState.MINTED, minted)

    if companion.is_file() and companion.read_text().strip() == project_id:
        return ProjectIdentityResult(ProjectIdentityState.VERIFIED, project_id)

    return ProjectIdentityResult(ProjectIdentityState.UNVERIFIED, project_id)


class ProjectIdentityError(Exception):
    """A carrier this module will not append to. Named, never guessed at."""


#: The two suffixes where a column-0 key at end of file is a valid document
#: key. A `pyproject.toml`'s `[tool.openstategraph]` table and a `.json`
#: config are both files where appending a YAML line is corruption, not a
#: field — so they are refused by name (kanban-patrol/23).
_APPENDABLE_SUFFIXES = (".yaml", ".yml")

_PROJECT_ID_KEY = re.compile(r"^project_id\s*:", re.MULTILINE)


def adopt_project_id(*, config_path: Path, state_dir: Path) -> ProjectIdentityResult:
    """Give an **existing** config an identity, by appending one line.

    kanban-patrol/23. `ensure_project_identity` mints for a config being
    created; `init_project` is its one call site, and it only ever writes a
    file it is authoring. A project made before this field existed has a real
    `openstategraph.yaml` — comments, an order somebody chose, possibly
    hand-edited — and until this function nothing could add the field to it,
    so the kanban board was permanently unusable there.

    The owner's decision, dated 2026-09-04 in that ticket: **append and
    print**, rather than print-and-refuse. Refusing leaves the board dead
    until a hand edit, and the hand edit is exactly what this writes.

    Why appending is the safe edit and a rewrite is not: a column-0 key at
    the end of the file is a valid top-level mapping key **whatever precedes
    it**, so nothing above is parsed, re-serialised, re-ordered or
    de-commented. A round-trip through a YAML loader would have to rewrite
    the whole document to add one key, and would silently discard every
    comment in a file this code does not own.

    Never touches a file that already carries the key — the same only-add,
    never-replace rule `ensure_project_identity` states — and returns that
    file's own verdict instead, so a caller sees `VERIFIED`/`UNVERIFIED`
    exactly as it would from a read.
    """
    if config_path.suffix.lower() not in _APPENDABLE_SUFFIXES:
        raise ProjectIdentityError(
            f"cannot add project_id to {config_path.name} — only "
            f"{' or '.join(_APPENDABLE_SUFFIXES)} takes an appended key. "
            "Add `project_id: <uuid>` to it by hand."
        )

    text = config_path.read_text()
    existing = _PROJECT_ID_KEY.search(text)
    if existing is not None:
        value = text[existing.end() :].splitlines()[0].strip().strip("\"'")
        return ensure_project_identity(project_id=value or None, state_dir=state_dir)

    minted = ensure_project_identity(project_id=None, state_dir=state_dir)
    # Exactly one newline between the last line somebody wrote and ours,
    # whether or not their file ended with one: a config that already ends in
    # a newline must not grow a blank line every time this runs.
    if text and not text.endswith("\n"):
        text += "\n"
    today = date.today().isoformat()
    text += (
        f"# project_id — added by openstategraph on {today} for the patrol board "
        "(kanban-patrol/03); a copy of this file into another project must not keep it\n"
        f"project_id: {minted.project_id}\n"
    )
    config_path.write_text(text)
    return minted


def project_id_line(project_id: str) -> str:
    """The one sentence every door prints when it adopts, so three doors do
    not spell it three ways."""
    return f"project_id: {project_id}  (minted and written to this project's config — kanban-patrol/23)"


def adopt_for_active_config() -> ProjectIdentityResult | None:
    """The whole move, for the doors that need an identity and find none:
    locate the project's own config, append, and drop the memoised config so
    the very next `active_config()` carries the new field.

    `None` when there is no config file at all — nothing to append to, and
    inventing one is `init`'s job, not a side effect of opening a board.
    Imports are local for the reason `scaffold`'s are: `config_file` is on the
    import path of every run and this module is not.
    """
    from openstategraph.config_file import find_config_file, reset_active_config

    config_path = find_config_file()
    if config_path is None:
        return None
    result = adopt_project_id(
        config_path=config_path, state_dir=config_path.parent / ".openstategraph"
    )
    reset_active_config()
    return result
