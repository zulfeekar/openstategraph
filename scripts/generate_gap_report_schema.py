#!/usr/bin/env python3
"""Publish the gap report's JSON Schema to `docs/gap-report.schema.json`.

    python3 scripts/generate_gap_report_schema.py --write
    python3 scripts/generate_gap_report_schema.py --check

Same shape and same reason as `generate_openapi.py`: Pydantic is the source of
truth for the wire and the committed document is its **generated** publication,
so the one thing this file must not do is hold a second description of the
model. It holds none — `gap_report.gap_report_schema()` is the one
implementation, and `--check` compares against exactly what `--write` would
write (`team-board-and-gap-reports/07`).

`--check` is the drift gate's command line; the same comparison is asserted in
`backend/tests/test_a_gap_report_carries_the_allowlist_and_nothing_else.py`, so
a stale schema is a red test and not only a red pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from openstategraph.gap_report import (  # noqa: E402
    GAP_REPORT_SCHEMA_PATH,
    gap_report_schema,
)


def rendered() -> str:
    return json.dumps(gap_report_schema(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the committed schema is not what the model produces; write nothing",
    )
    parser.add_argument(
        "--write", action="store_true", help="write the schema (the default)"
    )
    arguments = parser.parse_args(argv)

    wanted = rendered()
    if arguments.check:
        found = (
            GAP_REPORT_SCHEMA_PATH.read_text(encoding="utf-8")
            if GAP_REPORT_SCHEMA_PATH.exists()
            else ""
        )
        if found == wanted:
            print(f"{GAP_REPORT_SCHEMA_PATH} is current")
            return 0
        print(
            f"{GAP_REPORT_SCHEMA_PATH} is stale — run "
            "`python3 scripts/generate_gap_report_schema.py --write`",
            file=sys.stderr,
        )
        return 1

    GAP_REPORT_SCHEMA_PATH.write_text(wanted, encoding="utf-8")
    print(f"wrote {GAP_REPORT_SCHEMA_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
