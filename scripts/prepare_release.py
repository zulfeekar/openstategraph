#!/usr/bin/env python3
"""Turn the working tree into a release candidate commit. Two edits, no more.

    scripts/prepare_release.py 0.3.0

    1. `backend/pyproject.toml`  version = "0.3.0"
    2. `CHANGELOG.md`            `## 0.3.0 — unreleased` -> `## 0.3.0 — <today>`

That diff *is* the release proposal: a maintainer reviewing the "chore: release
v0.3.0" pull request is reviewing the version bump and the release notes
together, which is the only moment where reading them side by side is cheap.

`backend/pyproject.toml` is the single source of the released version.
`package.json` is deliberately NOT touched — the editor is `"private": true`
and is not published to any registry, so its version number describes nothing a
user can install. See `docs/releasing.md`.

Run by `.github/workflows/release-pr.yml`; runnable by hand for the recovery
paths in `docs/releasing.md`. Refuses rather than guesses: a malformed version,
a section that is already dated, or an empty section all exit non-zero.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "backend" / "pyproject.toml"

# Deliberately narrower than PEP 440: the release train only knows how to route
# `X.Y.Z` (PyPI) and `X.Y.ZrcN`/`aN`/`bN` (TestPyPI only). Anything else — an
# epoch, a local version, a `.post` — would be published under rules nobody has
# written down, so it is refused here rather than discovered at upload.
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?$")


def bump_pyproject(version: str) -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    # Anchored to the first `version = "…"` at column 0, which is the
    # `[project]` table's. `tool.ruff`'s key is `target-version`, and every
    # dependency pin lives inside a list, so neither can match.
    match = re.search(r'^version = "(?P<old>[^"]+)"$', text, re.MULTILINE)
    if match is None:
        raise SystemExit(f"no `version = \"…\"` line found in {PYPROJECT}")
    old = match.group("old")
    if old == version:
        print(f"    backend/pyproject.toml already says {version}")
        return old
    PYPROJECT.write_text(
        text[: match.start()] + f'version = "{version}"' + text[match.end() :],
        encoding="utf-8",
    )
    print(f"    backend/pyproject.toml {old} -> {version}")
    return old


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="the version to release, e.g. 0.3.0")
    parser.add_argument("--date", default=_dt.date.today().isoformat())
    args = parser.parse_args(argv)

    if not VERSION_RE.match(args.version):
        raise SystemExit(
            f"{args.version!r} is not a version this train can ship.\n"
            "Use X.Y.Z, or X.Y.ZrcN / aN / bN for a pre-release."
        )

    existing = subprocess.run(
        ["git", "tag", "--list", f"v{args.version}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if existing:
        raise SystemExit(
            f"tag {existing} already exists — that version has been through the\n"
            "train. Pick the next one, or see the 'a tag pushed by mistake'\n"
            "section of docs/releasing.md."
        )

    # `flush` so this line cannot appear *after* a child process's refusal —
    # the parent writes to a buffered stdout, the child to an unbuffered stderr.
    print(f"==> preparing v{args.version}", flush=True)
    changelog = [sys.executable, str(ROOT / "scripts" / "changelog_section.py")]
    # Check the changelog BEFORE editing pyproject.toml. Half a release
    # preparation left in the working tree is a worse state to explain than a
    # clean refusal, and the changelog is the edit most likely to be refused.
    # No `check=True`: the child already printed a sentence explaining itself,
    # and a Python traceback on top of it would bury the one line that matters.
    checked = subprocess.run(
        [*changelog, args.version, "--require-unreleased"],
        stdout=subprocess.DEVNULL,
    )
    if checked.returncode:
        return checked.returncode
    bump_pyproject(args.version)
    dated = subprocess.run([*changelog, args.version, "--set-date", args.date])
    if dated.returncode:
        return dated.returncode
    print(
        "\nReview the diff, then commit it as:\n"
        f"    chore: release v{args.version}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
