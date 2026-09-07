"""Which files a read-only tool may see, and how to walk to them without
descending into what it may not.

Two families of tools jail themselves to a directory and enumerate what is
inside: the platform tools (`prebuilt_platform`, jailed to the repo root)
and the codebase-knowledge tools (`knowledge_explorer`, jailed to a
package's code roots). Both had their own copy of the same traversal, and
both had the same defect in it — `rglob("*")` descends into `node_modules`,
`.git` and `.venv` and only *then* filters them out, so the walk was
proportional to what must never be read rather than to what may be. On this
repo that measured 48,555 paths enumerated to admit 549.

What is shared here is the **traversal**, not the **policy**. The two
callers deliberately keep their own exclusion sets, because they answer
different questions: the platform jail also hides build output and caches
(`dist`, `coverage`, `graphify-out`) that are noise to a concierge reading
the repo, while the codebase jail is pointed at a handful of package
directories where those names mean nothing. Merging the sets would silently
change what each tool can read, which is a security-relevant decision and
not a refactor. So the set is a parameter, and only the walking is owned
here.

The one rule both share and neither may drop: a name beginning with `.` is
never admitted. `.env` holds credentials and `.git` holds history; a
read-only jail that reads secrets is not one.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path


def admitted_files(root: Path, excluded: Iterable[str]) -> list[Path]:
    """Every admissible file under ``root``, sorted by path.

    Directories in ``excluded``, and anything whose name starts with a dot,
    are pruned *before* the walk descends into them.

    Sorted on the way out because callers cap their results (grep stops at
    a match limit), which makes visit order load-bearing: `os.walk` yields a
    directory's files before its subdirectories, which is not the order
    sorting whole paths gives. Sorting the admitted set keeps output
    identical to the `sorted(rglob(...))` this replaced.
    """
    blocked = set(excluded)
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # In place, as `os.walk` requires — a rebound name is ignored and
        # the prune silently does nothing.
        dirnames[:] = [d for d in dirnames if d not in blocked and not d.startswith(".")]
        base = Path(dirpath)
        for name in filenames:
            if name.startswith("."):
                continue
            found.append(base / name)
    return sorted(found)
