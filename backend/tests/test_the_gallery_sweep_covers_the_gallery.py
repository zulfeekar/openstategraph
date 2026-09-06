"""Every package the gallery ships has a question waiting for it.

`launch-readiness/188`. The sweep itself cannot run in CI — it calls a model —
but the thing that rots about it can be checked for nothing: a package added to
`examples/` without an entry in `scripts/gallery_questions.json` is simply not
swept, and the sweep reports a clean run over a gallery it did not fully cover.

That is the same defect shape the sweep was built to find, one layer up: a
surface reporting health about something it never looked at.

So this file asserts the *coverage*, never the answers. No model, no network,
no spend — it reads two directory listings and one JSON file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
QUESTIONS = REPO / "scripts" / "gallery_questions.json"
EXAMPLES = REPO / "backend" / "openstategraph" / "examples"
WORKFLOWS = REPO / "workflows"

SPEC = json.loads(QUESTIONS.read_text(encoding="utf-8"))["packages"]


def packages(root: Path) -> set[str]:
    return {p.name for p in root.iterdir() if (p / "workflow.json").is_file()}


#: The slug each entry actually drives. Most entries are named for their
#: package; `chinook-assistant-simple` is the exception and says so with
#: `package`, because `185` needs one package asked two different questions.
DRIVEN = {entry.get("package", name) for name, entry in SPEC.items()}


class TestNoPackageIsMissedByTheSweep:
    def test_every_example_has_a_question(self) -> None:
        missing = sorted(packages(EXAMPLES) - DRIVEN)
        assert not missing, (
            f"{missing} ship a workflow.json and no question, so the sweep "
            "reports on a gallery it did not fully cover. Add an entry to "
            "scripts/gallery_questions.json — the smallest question that "
            "forces this package's own mechanism to run."
        )

    def test_every_workflow_in_the_repo_root_has_one_too(self) -> None:
        missing = sorted(packages(WORKFLOWS) - DRIVEN)
        assert not missing, f"{missing} are in workflows/ and are never asked anything."

    def test_no_question_names_a_package_that_is_gone(self) -> None:
        known = packages(EXAMPLES) | packages(WORKFLOWS)
        assert not sorted(DRIVEN - known)


class TestAnEntrySaysEnoughToBeReviewed:
    @pytest.mark.parametrize("name", sorted(SPEC))
    def test_it_carries_a_question_an_expectation_and_the_reason(
        self, name: str
    ) -> None:
        entry = SPEC[name]
        assert entry.get("question", "").strip()
        # The expectation is what keeps a package that is *supposed* to refuse
        # or pause out of the defect column — `budget-exhaustion` and the two
        # human-approval packages are all correct behaviour and all not
        # `answered`.
        assert entry.get("expect") in {"answered", "refused", "paused", "empty"}
        # And the reason, because a question with no argument behind it is the
        # thing the next person deletes or replaces without knowing what it
        # was holding.
        assert len(entry.get("why", "")) > 40
