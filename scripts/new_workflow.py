#!/usr/bin/env python3
"""Scaffolds a conforming workflow package — ticket 49.

    python3 scripts/new_workflow.py my-flow "My Flow"

Creates the contract's required files plus the conventional directories, all
discovered automatically: tools/ functions/ middlewares/ skills/ tests/ data/.
For a prebuilt supervisor+worker+grader loop, use scripts/new_team.py instead.

**The scaffold itself lives in `openstategraph.scaffold`** (ticket 08), because
`scripts/` is not in the wheel and `openstategraph new` needs the same one.
This file is the checkout's command line over it — same arguments, same output.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from openstategraph.scaffold import ScaffoldError, new_workflow  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / "workflows"


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: new_workflow.py <slug> [display name]")
    try:
        target = new_workflow(ROOT, sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    except ScaffoldError as exc:
        sys.exit(str(exc))
    print(f"workflow package created: {target}")


if __name__ == "__main__":
    main()
