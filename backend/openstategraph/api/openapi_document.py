"""The published API contract — generated from the app, committed to git.

Tier 3 (internal), like everything under `openstategraph.api`: this module is
the *generator*, and it is ours to move. The **artifact** it writes,
`docs/openapi.json`, is what a third party reads, alongside `docs/api.md`.

---

## Why commit a document FastAPI already serves

`/openapi.json` is live and always correct, and that is exactly its weakness:
nobody reviews it. Committing the same bytes puts an endpoint's shape into the
pull-request diff, where a response field quietly changing type is visible
next to the code that changed it — and gives anyone a URL-free way to generate
a client (`npx openapi-typescript docs/openapi.json`) without booting us first.

A generated file that nothing checks rots, so two gates guard it: a byte
comparison on every backend test leg (`backend/tests/test_openapi_contract.py`)
and a `generated-openapi` CI job that regenerates and diffs the working tree —
the same belt-and-braces the generated port catalogue already has.

## What the document structurally cannot cover

The three SSE endpoints. OpenAPI 3.1 can say a response is
`text/event-stream`; it has no vocabulary for a *sequence* of frames, for the
union of `event:` names that sequence may contain, or for the guarantee that
exactly one of `done`/`interrupt`/`error` is the last one. A document that
declared a JSON body for them would be worse than silence — it would generate
a client that calls `.json()` on an infinite stream. So they are declared as
streams and the vocabulary lives in prose (`docs/api.md`), which is also what
`SSE_ENDPOINTS` below exists to keep honest.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

#: Where the committed snapshot lives. Repo-relative, and only meaningful in a
#: checkout: an installed wheel has no repository around it and needs none —
#: it serves the same document live at `/openapi.json`. Nothing at runtime
#: reads this path; the generator script and the drift test do.
ARTIFACT_PATH = Path(__file__).resolve().parents[3] / "docs" / "openapi.json"

#: Named in the failure message, because "the artifact is stale" without the
#: command is a comment asking a human to remember.
GENERATE_COMMAND = "python3 scripts/generate_openapi.py"

#: The endpoints whose contract is prose. Listed here so the audit can assert
#: they are declared as streams and point at the guide, rather than trusting
#: that whoever adds the fourth one remembers to.
SSE_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("/api/runs/stream", "post"),
    ("/api/runs/resume", "post"),
    ("/api/events", "get"),
)


def openapi_document() -> dict[str, Any]:
    """The OpenAPI document for a freshly built app.

    Built against a **throwaway workflows root**, deliberately. The schema
    does not depend on which packages exist, but `create_app` resolves a
    checkpointer and a store at startup; pointing that at the developer's real
    tree would mean generating a document could write a sqlite file. A
    generator with side effects is a generator people stop running.
    """
    from openstategraph.api.main import create_app

    with TemporaryDirectory() as scratch:
        return dict(create_app(workflows_root=scratch).openapi())


def serialise(document: dict[str, Any]) -> str:
    """The artifact's exact bytes.

    `sort_keys` and a two-space indent so the file is a readable diff and its
    ordering cannot depend on Python's dict insertion order changing under a
    refactor — a snapshot that reshuffles is a gate that cries wolf.
    """
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def write_snapshot(path: Path | None = None) -> Path:
    """Regenerates the committed snapshot. Returns where it landed."""
    target = path or ARTIFACT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(serialise(openapi_document()), encoding="utf-8")
    return target
