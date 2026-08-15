"""A run request may name a workflow. It may not name a file.

Install-experience ticket 06, and the second half of the class `7754d13`
closed on `credentials` ("a run request could tell the server where to send
its own key"). `RunRequest.workflow_slug` arrives in the request **body**,
carried no pattern, and reached
`state_dir(root) / f"checkpoints-{slug}.sqlite"` — so the caller chose where
this process created a sqlite file. Auth is opt-in, so on the default posture
nothing stood in front of it.

Two failures, one missing validation, and the second one is the one that
actually worked end to end. Measured on 2026-08-15 against
`POST /api/runs` with `settings.checkpointer: "sqlite"`:

    '../../../../../../tmp/pwned' -> 500 Internal Server Error
    'no-such-workflow'            -> 200, state dir now holds
                                     checkpoints-no-such-workflow.sqlite

The traversal was stopped by luck rather than by a rule: `runtime_for` runs
before `checkpointer_for` and asks the store for the package directory, so
`InvalidSlugError` escaped as an unhandled 500 with a stack trace. The
*well-formed unknown* slug sailed through — one new sqlite file, one open
descriptor and one permanent entry in `WorkflowServices._workflow_checkpointers`
(whose only eviction is `close()`) per distinct string, against a soft
`RLIMIT_NOFILE` of 256 on macOS.

So the rule has two halves, and both are about the same question — *can the
store name this?*

* **Grammar**, at the Pydantic field, so every transport that validates a
  `RunRequest` inherits it and the answer is a 422 rather than a stack trace.
* **Existence**, at the run endpoints, so a slug the store cannot address is
  a 404 *before* any filesystem path is built — which is also what makes the
  per-workflow saver cache bounded: an entry can only exist for a package
  that exists on disk.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app
from openstategraph.api.services import WorkflowServices
from openstategraph.api.workflow_store import SLUG_PATTERN, InvalidSlugError, is_slug

REPO = Path(__file__).resolve().parents[2]

#: A document that runs with no model and asks for its own sqlite file — the
#: `settings` half is what reaches `checkpointer_for`, and is the whole point.
SQLITE_DOCUMENT: dict[str, Any] = {
    "version": 1,
    "settings": {"checkpointer": "sqlite"},
    "nodes": [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        {"id": "out1", "type": "output.formatted", "position": {"x": 200, "y": 0}, "data": {}},
    ],
    "edges": [
        {
            "source": {"nodeId": "in1", "portId": "text"},
            "target": {"nodeId": "out1", "portId": "result"},
        }
    ],
}

#: The two spellings the audit executed, plus the ones a slug grammar exists
#: to refuse. Every one of them can name a path component.
NOT_SLUGS = [
    "../../../../../../tmp/pwned",
    "../escape",
    "..",
    "/etc/passwd",
    "with/slash",
    "with\\backslash",
    "UPPER Case",
    "trailing-",
    "",
]


@pytest.fixture
def workflows_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated workflows root, with the state directory inside it."""
    root = tmp_path / "workflows"
    root.mkdir()
    monkeypatch.setenv("OPENSTATEGRAPH_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("OPENSTATEGRAPH_CHECKPOINT_PATH", raising=False)
    return root


@pytest.fixture
def client(workflows_root: Path) -> TestClient:
    return TestClient(create_app(workflows_root=workflows_root), raise_server_exceptions=False)


def _install(root: Path, slug: str) -> None:
    """A real package on disk — the only thing a run may name."""
    directory = root / slug
    directory.mkdir(parents=True)
    (directory / "workflow.json").write_text(
        json.dumps(
            {
                "version": 1,
                "name": slug,
                "savedAt": "2026-08-15T00:00:00Z",
                "document": SQLITE_DOCUMENT,
            }
        )
    )


def _per_workflow_files(tmp_path: Path) -> list[str]:
    """Only the per-workflow savers. `checkpoints.sqlite` is the process-wide
    one, opened at startup by every deployment and nobody's slug."""
    state = tmp_path / "state"
    return sorted(p.name for p in state.glob("checkpoints-*.sqlite")) if state.exists() else []


def _run(client: TestClient, slug: Any, endpoint: str = "/api/runs") -> Any:
    body: dict[str, Any] = {"workflow": SQLITE_DOCUMENT, "question": "hi"}
    if slug is not None:
        body["workflow_slug"] = slug
    return client.post(endpoint, json=body)


class TestASlugIsRefusedAtValidation:
    """The grammar, at the field — so it is the same answer on every transport."""

    @pytest.mark.parametrize("slug", NOT_SLUGS)
    def test_a_slug_that_could_name_a_path_is_a_422(self, client: TestClient, slug: str) -> None:
        assert _run(client, slug).status_code == 422

    @pytest.mark.parametrize("slug", NOT_SLUGS)
    def test_the_stream_endpoint_refuses_it_too(self, client: TestClient, slug: str) -> None:
        assert _run(client, slug, "/api/runs/stream").status_code == 422

    @pytest.mark.parametrize("slug", NOT_SLUGS)
    def test_a_resume_refuses_it_too(self, client: TestClient, slug: str) -> None:
        response = client.post(
            "/api/runs/resume",
            json={
                "thread_id": "t-1",
                "workflow": SQLITE_DOCUMENT,
                "decision": "approve",
                "workflow_slug": slug,
            },
        )
        assert response.status_code == 422

    def test_the_traversal_writes_nothing(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        """The audit's own repro, end to end. Refused, and nothing on disk."""
        _run(client, "../../../../../../tmp/pwned")

        assert not (tmp_path / "tmp").exists()
        assert _per_workflow_files(tmp_path) == []

    def test_the_message_names_the_field_and_the_rule(self, client: TestClient) -> None:
        detail = _run(client, "Not A Slug").json()["detail"]

        assert any("workflow_slug" in str(item.get("loc", "")) for item in detail), detail
        assert any("slug" in str(item.get("msg", "")).lower() for item in detail), detail


class TestASlugTheStoreDoesNotKnow:
    """Existence, at the endpoint — before a path is built, not after."""

    def test_an_unknown_slug_is_a_404(self, client: TestClient) -> None:
        response = _run(client, "no-such-workflow")

        assert response.status_code == 404
        assert "no-such-workflow" in response.json()["detail"]

    def test_it_opens_no_file(self, client: TestClient, tmp_path: Path) -> None:
        """The half that actually worked before this change."""
        _run(client, "no-such-workflow")

        assert "checkpoints-no-such-workflow.sqlite" not in _per_workflow_files(tmp_path)

    def test_n_unknown_slugs_add_no_cache_entries(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        """The descriptor-exhaustion half: 50 requests, 50 distinct slugs.

        Before, each one minted a permanent `_workflow_checkpointers` entry
        holding an open sqlite connection, and the only eviction was
        `close()` — i.e. process shutdown.
        """
        for index in range(50):
            _run(client, f"mint-me-{index}")

        services: WorkflowServices = client.app.state.services  # type: ignore[attr-defined]
        assert services._workflow_checkpointers == {}
        assert _per_workflow_files(tmp_path) == []

    def test_a_stream_refuses_it_too(self, client: TestClient) -> None:
        assert _run(client, "no-such-workflow", "/api/runs/stream").status_code == 404


class TestWhatStillWorks:
    """The field is still optional, still additive, and still binds a package."""

    def test_no_slug_still_runs(self, client: TestClient) -> None:
        assert _run(client, None).status_code == 200

    def test_a_slug_naming_a_real_package_still_runs(
        self, client: TestClient, workflows_root: Path, tmp_path: Path
    ) -> None:
        _install(workflows_root, "billing")

        assert _run(client, "billing").status_code == 200
        assert "checkpoints-billing.sqlite" in _per_workflow_files(tmp_path)


class TestThePublishedGrammarMatchesTheEnforcedOne:
    """`SLUG_PATTERN` is a hand-mirror of `is_slug`, and this is its pin.

    The rule is enforced by `is_slug`, which is derived from `slugify` and
    cannot be serialised into a JSON Schema. A client reading
    `docs/openapi.json` needs the rule anyway, so the pattern is published —
    and published-and-unpinned is precisely the shape this repository forbids
    (`RuntimeClient.ts`, and the DRY rule in CLAUDE.md).
    """

    CORPUS = [
        *NOT_SLUGS,
        "billing",
        "chinook-assistant",
        "a",
        "9",
        "a1-b2-c3",
        "double--hyphen",
        "-leading",
        "with_underscore",
        "café",
        "with space",
        "MiXeD",
        "trailing-hyphen-",
        ".hidden",
        "a.b",
    ]

    @pytest.mark.parametrize("value", CORPUS)
    def test_they_agree(self, value: str) -> None:
        assert bool(re.match(SLUG_PATTERN, value)) is is_slug(value), value

    def test_the_contract_publishes_it(self) -> None:
        """A 422 a client cannot explain from the published document is a 422
        it will keep provoking."""
        published = json.loads((REPO / "docs" / "openapi.json").read_text())
        field = published["components"]["schemas"]["RunRequest"]["properties"]["workflow_slug"]

        assert any(option.get("pattern") == SLUG_PATTERN for option in field["anyOf"]), field


class TestTheSecondDoor:
    """MCP reaches the same cache, and had the same gap.

    `run(slug=...)` alone has always gone through the store and refused an
    unknown name. `run(document=..., slug=...)` did not — and the slug still
    bound tools, the memory namespace and the per-workflow saver.
    """

    def test_a_document_plus_an_unknown_slug_is_refused(self, workflows_root: Path) -> None:
        from openstategraph.mcp_server import WorkflowRuns

        services = WorkflowServices(workflows_root=workflows_root)

        result = WorkflowRuns(services).run(
            question="hi", document=SQLITE_DOCUMENT, slug="no-such-workflow"
        )

        assert "no-such-workflow" in result["error"]
        assert services._workflow_checkpointers == {}
        services.close()

    def test_a_document_plus_a_traversal_slug_is_refused(self, workflows_root: Path) -> None:
        from openstategraph.mcp_server import WorkflowRuns

        services = WorkflowServices(workflows_root=workflows_root)

        result = WorkflowRuns(services).run(
            question="hi", document=SQLITE_DOCUMENT, slug="../../../tmp/pwned"
        )

        assert "error" in result
        assert services._workflow_checkpointers == {}
        services.close()


class TestTheCacheKeyDomain:
    """What `_workflow_checkpointers` may be keyed by, stated where it is keyed.

    The endpoints answer *existence*; this answers *grammar*, at the one
    method that turns a slug into a filename — so a transport added later
    cannot re-open the hole by forgetting the boundary check.
    """

    def test_a_non_slug_never_becomes_a_filename(
        self, workflows_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services = WorkflowServices(workflows_root)

        with pytest.raises(InvalidSlugError):
            services.checkpointer_for({"checkpointer": "sqlite"}, "../../../tmp/pwned")

        assert services._workflow_checkpointers == {}
        services.close()

    def test_a_valid_slug_is_untouched(self, workflows_root: Path) -> None:
        """`TestAPerWorkflowSaverIsOpenedOnceNotPerRequest`'s contract, restated
        here so the guard above cannot quietly grow into an existence check the
        services object has no business making."""
        services = WorkflowServices(workflows_root)

        first = services.checkpointer_for({"checkpointer": "sqlite"}, "billing")

        assert first is services.checkpointer_for({"checkpointer": "sqlite"}, "billing")
        assert first is not services.checkpointer
        services.close()
