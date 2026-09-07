#!/usr/bin/env python3
"""Read and date one release section of CHANGELOG.md.

`CHANGELOG.md` here is a hand-written document, not a generated one (the
reasoning is in `docs/releasing.md`). This script is the only thing that
touches it mechanically, and it does exactly three jobs:

    changelog_section.py 0.3.0                    print the section body
    changelog_section.py 0.3.0 --require-unreleased
                                                  exit 1 unless the heading
                                                  still says "unreleased"
    changelog_section.py 0.3.0 --set-date 2026-08-10
                                                  rewrite the heading in place

Headings look like `## 0.3.0 — unreleased` or `## 0.2.0 — 2026-08-09`; the
separator is an em dash, which is why this is Python and not `awk`.

Exit codes: 0 fine, 1 the section is missing or in the wrong state, 2 usage.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from pathlib import Path

DEFAULT_CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
UNRELEASED = "unreleased"


def _heading_re(version: str) -> re.Pattern[str]:
    # The em dash is the committed separator; a hyphen is accepted on read so a
    # contributor's editor cannot silently make the section unfindable.
    return re.compile(
        rf"^##\s+{re.escape(version)}\s+[—-]\s+(?P<when>.+?)\s*$",
        re.MULTILINE,
    )


def _find(text: str, version: str) -> tuple[re.Match[str], str]:
    match = _heading_re(version).search(text)
    if match is None:
        raise SystemExit(
            f"CHANGELOG.md has no `## {version} — …` section.\n"
            "Add one before releasing — the release notes are written by a\n"
            "human here, not generated from commit subjects."
        )
    rest = text[match.end() :]
    nxt = re.search(r"^## ", rest, re.MULTILINE)
    body = rest[: nxt.start()] if nxt else rest
    return match, body.strip("\n")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--changelog", type=Path, default=DEFAULT_CHANGELOG)
    parser.add_argument(
        "--date-only",
        action="store_true",
        help="print the heading's date, or the literal 'unreleased'",
    )
    parser.add_argument(
        "--require-unreleased",
        action="store_true",
        help="fail unless the section is still marked unreleased",
    )
    parser.add_argument(
        "--set-date",
        metavar="YYYY-MM-DD",
        help="rewrite the heading date in place (implies --require-unreleased)",
    )
    args = parser.parse_args(argv)

    text = args.changelog.read_text(encoding="utf-8")
    match, body = _find(text, args.version)
    when = match.group("when").strip()

    if args.date_only:
        print(when)
        return 0

    if args.require_unreleased or args.set_date:
        if when.lower() != UNRELEASED:
            raise SystemExit(
                f"`## {args.version} — {when}` is already dated.\n"
                "Releasing it again would republish a version that shipped.\n"
                "Start a new `## X.Y.Z — unreleased` section instead."
            )

    if args.set_date:
        try:
            _dt.date.fromisoformat(args.set_date)
        except ValueError:
            raise SystemExit(f"--set-date must be YYYY-MM-DD, got {args.set_date!r}")
        if not body:
            raise SystemExit(
                f"`## {args.version} — unreleased` has no entries.\n"
                "A release with an empty changelog section is a release nobody\n"
                "can read. Write the notes first."
            )
        heading = f"## {args.version} — {args.set_date}"
        args.changelog.write_text(
            text[: match.start()] + heading + text[match.end() :],
            encoding="utf-8",
        )
        print(heading)
        return 0

    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
