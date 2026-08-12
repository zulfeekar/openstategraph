#!/usr/bin/env python3
"""Re-derive an eval dataset's committed expectations by running the gold SQL.

    python3 scripts/refresh_eval_expectations.py workflows/chinook-assistant/evals/chinook.eval.json

Expected rows are never hand-written: they are what the gold query returns
against the committed database, so a change to either shows up as changed rows
in a pull request rather than as a score that quietly moved. Run this after
editing a gold query or the database, and **read the diff** — a refresh that
changes rows you did not expect to change is the regression, not the fix.

The logic lives in `openstategraph.evaluation.dataset.refresh_expectations`,
not here; this file is the checkout's command line over it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from openstategraph.evaluation import refresh_expectations  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    dataset, changed = refresh_expectations(argv[0])
    print(f"{dataset.name}: {len(dataset.cases)} cases, {len(dataset.answerable())} answerable")
    print(f"changed: {', '.join(changed) if changed else 'nothing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
