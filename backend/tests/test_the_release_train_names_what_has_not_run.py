"""Pins ship-it/46: the release train's status page must stay checkable.

`docs/releasing.md` ends with a "What has run, and what still has not" section.
That section is the only place this repository says which halves of the release
machinery have been *observed* working — and a status written in prose has no
way to fail, which is exactly how it drifted: it counted four `pages.yml`
failures when there were six, and it did not mention `Release PR` at all,
although `Release PR` has run twice and failed twice at the same step.

So the checkable half is pinned here rather than restated in prose:

* every workflow this repository ships is *named* on that page, so a new one
  cannot be silently unaccounted for;
* if the train still opens its release pull request through
  `peter-evans/create-pull-request`, the page must carry the repository setting
  that action needs — a workflow-level `pull-requests: write` does **not**
  satisfy it, which is why both runs failed with a permission error while the
  workflow's own permissions block was already correct;
* the retracted "it has never run" phrasing does not come back.

Run counts are deliberately NOT asserted: they change every push, and a test
that has to be edited on every push is a test people delete.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
RELEASING = REPO_ROOT / "docs" / "releasing.md"

#: The repository-level setting `peter-evans/create-pull-request` needs.
#: Settings -> Actions -> General -> Workflow permissions. No `permissions:`
#: block in a workflow can grant it.
ACTIONS_MAY_OPEN_PRS = "Allow GitHub Actions to create and approve pull requests"

#: Retracted by this page's own dated correction. Case-sensitive substrings.
RETRACTED = (
    "the train has never run",
    "nothing above had ever executed, and still has not",
)


def _releasing_text() -> str:
    return RELEASING.read_text(encoding="utf-8")


def _workflow_names() -> dict[str, str]:
    """`{filename: the workflow's `name:`}` for every shipped workflow."""
    names = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        match = re.search(r'^name:\s*(.+?)\s*$', path.read_text(encoding="utf-8"), re.M)
        assert match, f"{path.name} declares no top-level `name:`"
        names[path.name] = match.group(1).strip('"\'')
    return names


def test_there_are_workflows_to_account_for() -> None:
    # A sentinel: an empty glob would make every assertion below vacuous.
    assert len(_workflow_names()) >= 5


def test_every_workflow_is_named_on_the_releasing_page() -> None:
    text = _releasing_text()
    missing = {
        filename: name
        for filename, name in _workflow_names().items()
        if filename not in text and name not in text
    }
    assert not missing, (
        "docs/releasing.md accounts for the release machinery, and these "
        f"workflows appear on it under neither their filename nor their name: {missing}. "
        "Add them to the 'What has run, and what still has not' section."
    )


def test_the_release_pr_permission_blocker_is_documented() -> None:
    users = [
        path.name
        for path in sorted(WORKFLOWS.glob("*.yml"))
        if "peter-evans/create-pull-request" in path.read_text(encoding="utf-8")
    ]
    if not users:
        return  # the action is gone; so is the blocker
    assert ACTIONS_MAY_OPEN_PRS in _releasing_text(), (
        f"{users} open a pull request from a workflow, which needs the "
        f"repository setting {ACTIONS_MAY_OPEN_PRS!r} — a workflow-level "
        "`pull-requests: write` is not enough, and both Release PR runs failed "
        "on exactly that. docs/releasing.md must say so."
    )


def test_the_page_does_not_claim_the_train_never_ran() -> None:
    text = _releasing_text()
    hits = [claim for claim in RETRACTED if claim in text]
    assert not hits, f"docs/releasing.md carries retracted claims: {hits}"
