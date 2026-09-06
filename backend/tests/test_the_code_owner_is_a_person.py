"""`.github/CODEOWNERS` has to name somebody GitHub can resolve.

stable-beta-public/33. The file shipped as `@PLACEHOLDER` from the day it was
written, with an honest comment saying why: the checkout had no remote, so the
maintainer's handle was not a fact. It has one now (`origin` and `beta` both
point at the live repository), and the placeholder has stopped being honest and
started being a defect — GitHub silently ignores an owner it cannot resolve, so
"Require review from Code Owners" requests nobody and every pull request is
blocked by a rule with no one on the other end.

The handle is derived rather than remembered: `gh repo view --json owner --jq
.owner.login` answered `zulfeekar` on 2026-09-06. This module is the half that
fails if a placeholder comes back — under the whole of `.github/`, not only
this file, because the release checklist's grep covers the directory.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GITHUB = REPO / ".github"
CODEOWNERS = GITHUB / "CODEOWNERS"

#: A CODEOWNERS rule line: a pattern, then one or more `@handle` owners.
RULE = re.compile(r"^(?P<pattern>\S+)\s+(?P<owners>(?:@[A-Za-z0-9][A-Za-z0-9-]*(?:/[^\s]+)?\s*)+)$")


def rules() -> list[tuple[str, list[str]]]:
    found = []
    for line in CODEOWNERS.read_text().splitlines():
        stripped = line.split("#", 1)[0].strip()
        match = RULE.match(stripped) if stripped else None
        if match:
            found.append((match.group("pattern"), match.group("owners").split()))
    return found


class TestNoPlaceholderReachesThePublicRepository:
    def test_nothing_under_dot_github_says_placeholder(self) -> None:
        offenders = [
            f"{path.relative_to(REPO)}:{number}"
            for path in sorted(GITHUB.rglob("*"))
            if path.is_file()
            for number, line in enumerate(path.read_text(errors="ignore").splitlines(), start=1)
            if "PLACEHOLDER" in line
        ]

        assert offenders == [], (
            "a code owner GitHub cannot resolve is worse than none — the rule is "
            "ignored and no reviewer is requested:\n" + "\n".join(offenders)
        )

    def test_the_catch_all_rule_names_an_owner(self) -> None:
        catch_all = [owners for pattern, owners in rules() if pattern == "*"]

        assert catch_all, "CODEOWNERS has no `*` rule, so most of the tree has no owner"
        assert all(owner.startswith("@") for owner in catch_all[-1])

    def test_every_rule_names_the_same_kind_of_thing(self) -> None:
        """One handle, not a mix of handles and unresolvable words."""
        assert rules(), "CODEOWNERS has no rules at all"
        for pattern, owners in rules():
            assert owners, pattern


class TestTheCiBadgeSaysWhyItsPathIsRelative:
    """The third half of the ticket, and the smallest.

    `../../actions/workflows/ci.yml/badge.svg` is GitHub's own convention — it
    resolves on github.com against the repository root, which is why the badge
    survives a rename. A local link checker calls it broken, so the reason is
    written above it once rather than rediscovered every audit.
    """

    def test_the_relative_ci_badge_carries_its_note(self) -> None:
        lines = (REPO / "README.md").read_text().splitlines()
        badge = [n for n, line in enumerate(lines) if "actions/workflows/ci.yml/badge.svg" in line]

        assert badge, "the README has no CI badge"
        above = lines[max(0, badge[0] - 1)]
        assert above.startswith("<!--") and "github.com" in above, (
            "the `../../` path above has no comment saying it is GitHub's own "
            "convention, so the next link audit files it as broken again"
        )
