"""`GET /api/workflows/{slug}` → edit → `PUT` back, with no reshaping.

workflow-gallery ticket 42. The two envelopes were disjoint in **both**
directions: `GET` returned `{slug, document}`, `PUT` accepted
`{name, document}` with `extra="forbid"`, so the obvious scripted edit —
fetch, change a field, put it back — answered 422 twice over, once for the
`name` the read shape never carried and once for the `slug` it did.

**The test is the round trip, not a field census.** A test asserting that
both models mention `name` would stay green against a `PUT` that still
refused the body, which is the failure a reader actually hits; so this
drives the real endpoints and puts back *exactly* what it was handed.

The narrowness is the other half. `extra="forbid"` is what makes a typo in
a client's payload an error rather than a silent no-op, and it is not
relaxed: `slug` is admitted **only** when it agrees with the path, and
`POST /api/workflows` — where a client-minted slug is ticket 20's data
loss — still refuses it outright.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app


@pytest.fixture()
def client(tmp_path) -> TestClient:  # noqa: ANN001
    root = tmp_path / "workflows"
    (root / "sql-qa").mkdir(parents=True)
    (root / "sql-qa" / "workflow.json").write_text(
        json.dumps(
            {
                "name": "SQL QA",
                "saved_at": "2026-08-21T00:00:00+00:00",
                "document": {"name": "SQL QA", "nodes": [], "edges": []},
            }
        )
    )
    return TestClient(create_app(workflows_root=root), raise_server_exceptions=False)


def test_what_get_hands_you_is_what_put_takes_back(client: TestClient) -> None:
    """The ticket's own sentence: fetch a workflow, change a field, put it back."""
    fetched = client.get("/api/workflows/sql-qa")
    assert fetched.status_code == 200
    body = fetched.json()

    body["document"]["nodes"] = [{"id": "n1", "type": "agent"}]

    saved = client.put("/api/workflows/sql-qa", json=body)
    assert saved.status_code == 200, saved.text

    again = client.get("/api/workflows/sql-qa").json()
    assert again["document"]["nodes"] == [{"id": "n1", "type": "agent"}]
    # And the display name survived a round trip that never named it
    # separately — the field the caller used to have to lift out of the
    # document by hand.
    assert again["name"] == "SQL QA"


def test_a_slug_that_disagrees_with_the_path_is_refused(client: TestClient) -> None:
    """Admitting `slug` is not the same as ignoring it.

    A body carrying somebody *else's* slug is a client that has confused two
    workflows; writing it to the path's package would be the silent
    cross-write ticket 20 removed by a different door.
    """
    refused = client.put(
        "/api/workflows/sql-qa",
        json={"slug": "some-other-workflow", "name": "SQL QA", "document": {}},
    )
    assert refused.status_code == 422
    assert "some-other-workflow" in refused.text


def test_a_typo_is_still_an_error_and_not_a_silent_no_op(client: TestClient) -> None:
    """`extra="forbid"` survives — only `slug` was admitted, not everything."""
    refused = client.put(
        "/api/workflows/sql-qa",
        json={"name": "SQL QA", "documnet": {}, "document": {}},
    )
    assert refused.status_code == 422
    assert "documnet" in refused.text


def test_creation_still_refuses_a_client_minted_slug(client: TestClient) -> None:
    """`POST /api/workflows` mints the identity; a body naming one is ticket 20."""
    refused = client.post(
        "/api/workflows",
        json={"slug": "i-picked-this", "name": "New", "document": {}},
    )
    assert refused.status_code == 422
    assert "slug" in refused.text
