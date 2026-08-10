"""Where this process **writes**, as opposed to where it reads.

**Tier 2, provisional.** One module, one question, and it exists because the
two questions had been answered by one function. `workflows_root()` says where
the *content* is — a directory the user chose and, since the wheel shipped,
usually a directory we do not own. State was then put inside it:
`<workflows root>/.openstategraph/checkpoints.sqlite`.

In this checkout that is correct and stays correct. Pointed at somebody else's
folder it is three defects at once — we litter a tree we were only asked to
read, we may be writing inside their version control, and on a read-only mount
we cannot write at all, which turned "run this workflow" into a warning about
lost durability for no reason the user could act on.

So: **READ location and WRITE location are separate questions**, and this is
the single place the write one is answered. The discriminator is the one this
codebase already trusts and already tests, `checkout_root()`:

1. **`OPENSTATEGRAPH_STATE_DIR`** — the deployment's own answer, absolute, and
   it wins. A container mounting a writable volume names it here.
2. **Inside a checkout** — `<workflows root>/.openstategraph`, exactly as
   before. A developer expects state beside the content it is state about, it
   is already gitignored, and keeping it byte-identical is what makes this
   change reviewable rather than a migration.
3. **Installed** — the platform's per-user state directory, keyed per project.

Ticket 03 (scale-and-adopt).

**The platform conventions, cited rather than invented:**

- **Linux/BSD** — the XDG Base Directory Specification: state that should
  persist between restarts but is not portable or user-data goes in
  `$XDG_STATE_HOME`, defaulting to `~/.local/state`. Thread checkpoints are
  precisely the spec's own example class (logs, history, current state).
- **macOS** — Apple's *File System Programming Guide*: application support
  files go in `~/Library/Application Support/<app>`. macOS has no separate
  state directory, and `~/.local/state` is not a location a Mac user would
  ever look in.
- **Windows** — the Known Folders API's `FOLDERID_LocalAppData`, i.e.
  `%LOCALAPPDATA%`. Local rather than Roaming: a sqlite file must not be
  synchronised between machines behind our back.

No `platformdirs` dependency. The lean core is four packages
(`docs/decisions/framework-packaging.md` §3.1), and this is fifteen lines that
change roughly never.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

#: The deployment's explicit answer for where *everything* this process writes
#: goes. Absolute, and it outranks both branches below.
STATE_DIR_ENV = "OPENSTATEGRAPH_STATE_DIR"

#: The dotted directory used inside a checkout. Dotted so `WorkflowStore.list`
#: (which requires a `workflow.json`) and every `ls` read it as plumbing.
STATE_DIR_NAME = ".openstategraph"

#: The per-user directory's own name, under whichever platform root applies.
APP_DIR_NAME = "openstategraph"

_LABEL = re.compile(r"[^a-z0-9]+")


def user_state_home() -> Path:
    """This application's per-user state directory, per platform convention.

    See the module docstring for the three specifications this implements.
    Read from the environment on every call rather than frozen at import,
    because a test — and a container's entrypoint — legitimately move `HOME`.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", "").strip()
        root = Path(base) if base else Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_STATE_HOME", "").strip()
        root = Path(base) if base else Path.home() / ".local" / "state"
    return root / APP_DIR_NAME


def project_key(workflows_root_dir: Path) -> str:
    """A per-project directory name: readable label, then a digest.

    Both halves earn their place. The **digest** is the correctness half —
    two projects on one machine must never share a thread namespace, and the
    old default got that right only by accident, because the root itself was
    the location. The **label** is the human half: a state tree full of
    eight-hex-digit directories is a tree nobody can ever clean up.

    The label prefers the *parent* when the root is literally called
    `workflows`, since that is the convention and every project's root would
    otherwise be labelled the same word.
    """
    resolved = Path(workflows_root_dir).expanduser().resolve()
    named = resolved.parent if resolved.name == "workflows" else resolved
    label = _LABEL.sub("-", named.name.lower()).strip("-") or "project"
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:8]
    return f"{label}-{digest}"


def state_dir(workflows_root_dir: Path | str | None = None) -> Path:
    """The directory this process may write to. Never guaranteed to exist yet.

    Creating it is the caller's job, at the moment it actually writes, so that
    merely *asking* where state would go never has a side effect — which is
    what lets `openstategraph` be pointed at a read-only mount and still list,
    compile and run.
    """
    configured = os.environ.get(STATE_DIR_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    from openstategraph.workflows_root import checkout_root, workflows_root

    root = Path(workflows_root_dir) if workflows_root_dir else workflows_root()
    if checkout_root() is not None:
        return root / STATE_DIR_NAME
    return user_state_home() / project_key(root)


__all__ = ["APP_DIR_NAME", "STATE_DIR_ENV", "STATE_DIR_NAME", "project_key", "state_dir",
           "user_state_home"]
