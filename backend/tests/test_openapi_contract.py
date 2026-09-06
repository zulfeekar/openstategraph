"""The published API contract, and the gate that keeps it from rotting.

Scale-and-adopt ticket 05. "Build your own UI" is true — both surfaces go
through the same public HTTP endpoints — but a promise a stranger cannot
machine-read is a slogan. `docs/openapi.json` is that machine-readable form,
generated from the app and **committed**, so it is reviewable in a pull
request and diffable when an endpoint changes shape.

Committing a generated artifact only works if something fails when it drifts.
That is this module (the byte comparison, on every backend leg) and the
`generated-openapi` CI job (regenerate, then `git diff`) — the same
belt-and-braces the generated port catalogue already has.

The audits below are the other half: an OpenAPI document that says
`"responses": {"200": {"schema": {}}}` is technically a document and
practically a shrug.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from openstategraph.api.openapi_document import (
    ARTIFACT_PATH,
    GENERATE_COMMAND,
    SSE_ENDPOINTS,
    openapi_document,
)

#: Where the prose lives for everything OpenAPI structurally cannot express.
PROSE = "docs/api.md"


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    return openapi_document()


def operations(document: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (path, method, operation)
        for path, methods in document["paths"].items()
        for method, operation in methods.items()
    ]


class TestTheCommittedSnapshot:
    def test_it_exists(self) -> None:
        assert ARTIFACT_PATH.is_file(), (
            f"The published API contract is missing at {ARTIFACT_PATH}. "
            f"Run `{GENERATE_COMMAND}`."
        )

    def test_it_matches_the_app(self, document: dict[str, Any]) -> None:
        # Bytes, not parsed equality: the file is reviewed as a diff, so the
        # formatting is part of the artifact and a generator that writes it
        # differently is drift too.
        committed = ARTIFACT_PATH.read_text(encoding="utf-8")
        assert committed == json.dumps(document, indent=2, sort_keys=True) + "\n", (
            f"{ARTIFACT_PATH} no longer matches the app. Run `{GENERATE_COMMAND}`."
        )

    def test_it_is_generated_deterministically(self) -> None:
        # A snapshot that differs run to run cannot be a gate — it would fail
        # CI on an unrelated pull request and train everyone to regenerate
        # without reading the diff.
        assert openapi_document() == openapi_document()


class TestEveryOperationIsDocumented:
    def test_each_one_has_a_summary(self, document: dict[str, Any]) -> None:
        missing = [
            f"{method.upper()} {path}"
            for path, method, operation in operations(document)
            if not (operation.get("summary") or "").strip()
        ]
        assert not missing, f"No summary: {missing}"

    def test_each_one_has_a_description(self, document: dict[str, Any]) -> None:
        # FastAPI takes the description from the handler's docstring, so this
        # fails for an endpoint added without one — which is the point.
        missing = [
            f"{method.upper()} {path}"
            for path, method, operation in operations(document)
            if len((operation.get("description") or "").strip()) < 40
        ]
        assert not missing, f"No usable description: {missing}"


class TestEveryResponseIsNamed:
    def test_no_json_response_is_an_anonymous_shape(
        self, document: dict[str, Any]
    ) -> None:
        """A `dict[str, Any]` return type produces `{}` — an empty promise.

        Every JSON-returning operation must reach a named component schema,
        directly or through an array/map of one, so a generated client has a
        type to bind and a reviewer has a name to search for.
        """
        anonymous = []
        for path, method, operation in operations(document):
            for status, response in (operation.get("responses") or {}).items():
                schema = (
                    (response.get("content") or {})
                    .get("application/json", {})
                    .get("schema")
                )
                if schema is None:
                    continue  # 204, or a non-JSON media type — checked elsewhere.
                if "$ref" not in json.dumps(schema):
                    anonymous.append(f"{method.upper()} {path} -> {status}")
        assert not anonymous, f"Anonymous response shapes: {anonymous}"


class TestTheStreamsAreFlaggedNotFaked:
    """OpenAPI cannot express an SSE event vocabulary — so it must not pretend.

    There is no place in OpenAPI 3.1 to say "this response is an unbounded
    sequence of frames, each tagged with one of six event names, and exactly
    one of three of them is last". Declaring a JSON body for these endpoints
    would generate a client that calls `.json()` on an infinite stream. So the
    document says `text/event-stream` and hands the reader to the prose.
    """

    def test_each_stream_declares_the_event_stream_media_type(
        self, document: dict[str, Any]
    ) -> None:
        for path, method in SSE_ENDPOINTS:
            content = document["paths"][path][method]["responses"]["200"]["content"]
            assert "text/event-stream" in content, path
            assert "application/json" not in content, (
                f"{path} advertises a JSON body it never returns."
            )

    def test_each_stream_points_at_the_prose(self, document: dict[str, Any]) -> None:
        for path, method in SSE_ENDPOINTS:
            operation = document["paths"][path][method]
            assert PROSE in operation["description"], (
                f"{path} does not tell a client where the event vocabulary is."
            )
