"""The tool promised "every workflow" and returned one of six.

`every-workflow-green` 12. `morning-brief` asked the platform what it hosts and
reported *"It is the only workflow installed"*. Six packages were installed;
five were withheld by `visible_to_platform_tools` — two hidden, three
unpublished — and neither the tool's description nor its output gave the model
any reason to doubt the count.

The filter is correct and stays: these tools speak to /chat users. What was
wrong is that the words around it claimed more than the filter delivers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openstategraph.prebuilt_platform import ListWorkflowsTool


def _package(root: Path, slug: str, **envelope: object) -> None:
    package = root / slug
    package.mkdir(parents=True)
    (package / "workflow.json").write_text(
        json.dumps({"name": slug.replace("-", " ").title(), "document": {}, **envelope})
    )


@pytest.fixture
def board(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """One visible package and two withheld — the shape of the real board."""
    root = tmp_path / "workflows"
    root.mkdir()
    _package(root, "chinook-assistant")
    _package(root, "concierge", hidden=True)
    _package(root, "morning-brief", published=False)
    monkeypatch.setattr("openstategraph.prebuilt_platform.workflows_root", lambda: root)
    return root


class TestTheDescriptionMatchesTheFilter:
    def test_it_does_not_promise_every_workflow(self) -> None:
        """"every workflow available on this platform" is what produced the
        inventory claim. The tool cannot see hidden or unpublished packages."""
        assert "every workflow" not in ListWorkflowsTool.description.lower()

    def test_it_says_whose_list_this_is(self) -> None:
        """A reader must be able to tell this is the chat app's list."""
        assert "chat" in ListWorkflowsTool.description.lower()


class TestTheOutput:
    def test_the_result_says_whose_list_it_is(self, board: Path) -> None:
        """Changing only the description was not enough, and the browser said so.

        With the description narrowed, the agent *still* reported "the only
        workflow currently installed on this platform". A model summarises the
        tool's **output**, not the sentence that persuaded it to call — so the
        scope has to travel with the result.
        """
        content = ListWorkflowsTool()._execute(ListWorkflowsTool.Args()).content
        assert "chat app" in content.lower()

    def test_one_visible_package_is_singular(self, board: Path) -> None:
        content = ListWorkflowsTool()._execute(ListWorkflowsTool.Args()).content
        assert "1 workflows" not in content
        assert "1 workflow is available" in content

    def test_withheld_packages_are_not_listed(self, board: Path) -> None:
        content = ListWorkflowsTool()._execute(ListWorkflowsTool.Args()).content
        assert "chinook-assistant" in content
        assert "concierge" not in content
        assert "morning-brief" not in content

    def test_several_visible_packages_stay_plural(
        self, board: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _package(board, "workflow-architect")
        content = ListWorkflowsTool()._execute(ListWorkflowsTool.Args()).content
        assert "2 workflows are available" in content
