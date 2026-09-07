#!/usr/bin/env python3
"""Scaffolds a new Team workflow package — ticket 56.

    python3 scripts/new_team.py sourcing-team "Deliver a sourced summary"

Creates `workflows/<slug>/` with the prebuilt minimum-viable Team (ticket 52's
design): supervisor + one default worker + a grader closing the revise loop.
The grader's criteria ARE the team's outcome contract — edit them first. Mount
the team in any workflow with a **Team** node pointing at this slug.

**The scaffold itself lives in `openstategraph.scaffold`** (ticket 08), so this
command line and `openstategraph new --team` produce the identical package from
one definition rather than two copies that agree only on the day they are written.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from openstategraph.scaffold import ScaffoldError, new_team  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / "workflows"


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: new_team.py <slug> [expected outcome sentence]")
    try:
        target = new_team(ROOT, sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    except ScaffoldError as exc:
        sys.exit(str(exc))
    print(f"team package created: {target}")


if __name__ == "__main__":
    main()
