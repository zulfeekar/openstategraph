"""`GET /api/runs/spend` — what the work cost, over one door.

`stable-beta-public/03`, slice 1 of `docs/plans/token-status-bar/04-slices.md`.
The tracer bullet: the door exists, answers a whole `SpendResponse`, and is
published in `docs/openapi.json`. **It reads no store yet** — every figure is
the zero-or-absent one a fresh install would answer with — so the shape is
settled and pinned before the query that fills it lands (slice 2).

The reason a zero document is worth a test of its own is the one the response
schema is built around: *zero* and *not reported* are two different answers.
`grand_total` is an integer and a store with no runs really has spent nothing;
`cached_total` is `int | None` and a fresh install has not been told anything
about caching, which is `None` rather than `0`. A route that flattened the
second into the first would be inventing a measurement, and every later slice
would inherit it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openstategraph.api.main import create_app  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """A deployment with no run store at all — the fresh-install case."""
    return TestClient(create_app(workflows_root=tmp_path / "workflows"))


class TestTheDoorAnswers:
    def test_a_fresh_install_gets_a_whole_document(self, client: TestClient) -> None:
        response = client.get("/api/runs/spend")

        assert response.status_code == 200
        assert response.json() == {
            "grand_total": 0,
            "cached_total": None,
            "by_model": [],
            "session_by_model": [],
            "session_total": 0,
            "sessions": [],
        }

    def test_a_session_id_is_accepted_and_answers_the_same_shape(
        self, client: TestClient
    ) -> None:
        """The parameter is part of the door from the first slice.

        Nothing is filtered yet — slice 3 fills the session block — but a
        client that sends the id must not get a 422 for it, or the client half
        of this seam cannot be written until the backend half is finished.
        """
        body = client.get("/api/runs/spend", params={"session_id": "s-1"}).json()

        assert body["session_total"] == 0
        assert body["session_by_model"] == []

    def test_zero_is_a_number_and_not_reported_is_null(self, client: TestClient) -> None:
        """The distinction the whole schema exists for, asserted rather than
        implied by the equality above: a reader must be able to tell *this
        deployment spent nothing* from *nobody said*."""
        body = client.get("/api/runs/spend").json()

        assert body["grand_total"] == 0
        assert body["cached_total"] is None


class TestThePublishedContract:
    """`docs/openapi.json` is the generated publication, not a second opinion.

    Regenerated with `scripts/generate_openapi.py`; asserted here so the door
    cannot land without it, which is the drift `contractDrift.test.ts` reads
    on the TypeScript side.
    """

    @pytest.fixture(scope="class")
    def openapi(self) -> dict:
        return json.loads((REPO / "docs/openapi.json").read_text(encoding="utf-8"))

    def test_the_path_is_published(self, openapi: dict) -> None:
        assert "/api/runs/spend" in openapi["paths"]

    def test_the_nullable_figures_are_published_nullable(self, openapi: dict) -> None:
        schemas = openapi["components"]["schemas"]
        spend = schemas["SpendResponse"]["properties"]["cached_total"]
        assert {"type": "null"} in spend["anyOf"]

        model = schemas["ModelSpendResponse"]["properties"]
        for field in ("cached_tokens", "cache_creation_tokens", "reasoning_tokens"):
            assert {"type": "null"} in model[field]["anyOf"], field
