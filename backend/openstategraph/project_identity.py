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

import uuid
from dataclasses import dataclass
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
