"""The Chinook demo endpoint is not part of the published contract.

Production-ready ticket 54. `POST /api/workflows/chinook-assistant/ask` was the
**first path** in `docs/openapi.json` — the generated, committed publication of
the API — and it answered `500 Internal Server Error` on every install, with
`ModuleNotFoundError: No module named 'graph'` in the log. The module it wanted
is `workflows/chinook-assistant/graph.py`, importable only from inside that
directory of this checkout; no wheel has ever carried it, and the graph it
builds needs a Chinook sqlite file that no wheel carries either.

A published route that cannot succeed anywhere is worse than an absent one: it
is the first thing a stranger reading the contract meets, and what it teaches
them is that the contract is not checked.

So the route is **withdrawn from the default assembly** and kept as what it
always really was — a fixture the tests that cover it inject. `create_app()`
registers it only when a `graph_factory` is handed in, which is the same
condition under which it can work.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEMO_PATH = "/api/workflows/chinook-assistant/ask"


def _paths(app: object) -> set[str]:
    """What this app *publishes* — the same view `docs/openapi.json` is
    generated from, rather than `app.routes`, which is the assembly."""
    return set(app.openapi()["paths"])  # type: ignore[attr-defined]


class TestTheDemoRouteIsNotMountedByDefault:
    def test_a_default_app_does_not_carry_it(self, tmp_path: Path) -> None:
        from openstategraph.api.main import create_app

        app = create_app(workflows_root=tmp_path)

        assert DEMO_PATH not in _paths(app)

    def test_asking_for_it_is_a_404_rather_than_a_500(self, tmp_path: Path) -> None:
        """The distinction the ticket turns on: "this server does not offer
        that" is an answer; a stack trace naming somebody's checkout is not."""
        from fastapi.testclient import TestClient

        from openstategraph.api.main import create_app

        client = TestClient(create_app(workflows_root=tmp_path))
        response = client.post(DEMO_PATH, json={"question": "hi"})

        assert response.status_code == 404

    def test_injecting_a_graph_still_mounts_it(self, tmp_path: Path) -> None:
        """Withdrawn from the published contract, not deleted: the demo still
        runs wherever its graph exists, which is the condition it needed all
        along."""
        from openstategraph.api.main import create_app

        app = create_app(graph_factory=lambda _model: object(), workflows_root=tmp_path)

        assert DEMO_PATH in _paths(app)

    def test_nothing_imports_a_top_level_graph_module(self) -> None:
        """The `_default_factory` that produced the `ModuleNotFoundError`.

        A bare `from graph import …` resolves against whatever happens to be on
        `sys.path`, so on the one machine where it worked it worked by cwd.

        Read as a syntax tree rather than as text, so that the sentence in
        `create_app`'s docstring explaining why the import is gone does not
        itself trip the assertion.
        """
        import ast

        source = (ROOT / "backend" / "openstategraph" / "api" / "main.py").read_text()
        imported = {
            node.module
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ImportFrom)
        }

        assert "openstategraph.api.editor_assets" in imported  # the control
        assert "graph" not in imported


class TestTheCommittedContractSaysSo:
    def test_the_snapshot_no_longer_publishes_it(self) -> None:
        document = json.loads((ROOT / "docs" / "openapi.json").read_text())

        assert DEMO_PATH not in document["paths"]

    def test_the_snapshot_still_publishes_the_general_seam(self) -> None:
        """The control. A snapshot that lost every path would pass the
        assertion above and mean nothing."""
        document = json.loads((ROOT / "docs" / "openapi.json").read_text())

        assert "/api/runs/stream" in document["paths"]

    def test_the_api_page_does_not_send_a_reader_to_it(self) -> None:
        assert "chinook-assistant/ask" not in (ROOT / "docs" / "api.md").read_text()


class TestAFreshInstallAsksForNothingItDoesNotHave:
    """`/chat` with nothing published (workflow-gallery 43's residue).

    Source assertions, for the reason `test_chat_picker_disambiguates.py`
    records: `chat.html` is a dependency-free page with no JS test harness in
    this repository, and the alternative to pinning it here is pinning it
    nowhere.
    """

    @staticmethod
    def _render_flow() -> str:
        from openstategraph.api.chat_page import chat_page_html

        body = chat_page_html().split("async function renderFlow(")[1]
        return body.split("\nfunction ")[0].split("\nasync function ")[0]

    def test_the_extractor_found_the_function(self) -> None:
        """The control every pin in this repository carries: a rename that
        emptied the extractor would make the two assertions below vacuous."""
        assert "/graph?audience=customer" in self._render_flow()

    def test_an_empty_slug_never_reaches_the_wire(self) -> None:
        body = self._render_flow()
        guard, _, request = body.partition("await fetch(")

        assert "if (!slug)" in guard

    def test_no_status_code_is_shown_to_a_customer(self) -> None:
        assert "resp.status" not in self._render_flow()


@pytest.mark.parametrize("surface", ["editor", "chat"])
def test_the_demo_slug_is_not_special_cased_anywhere_else(surface: str) -> None:
    """The route is gone; the *package* is an ordinary one and stays so."""
    from openstategraph.api.routes import workflows as workflow_routes

    assert "chinook" not in Path(workflow_routes.__file__).read_text()
