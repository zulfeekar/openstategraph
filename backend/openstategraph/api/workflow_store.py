"""File-backed workflow persistence — tickets 10/14/16, resolved.

**Files own the definition.** This is the settled split from ticket 10: a
`workflow.json` under `workflows/<slug>/` is the source of truth, diffable and
git-reviewable, the same as `functions/`/`tools/` already are for the seeded
Chinook workflow. Postgres (or any runtime store) would own *execution* state
(threads, checkpoints) — out of scope here, and nothing here assumes it exists.

**The browser cannot write to disk** (ticket 16's hard constraint — the File
System Access API is Chromium-only and permission-gated, not a production
answer), so every write goes through this module, called only from the
backend. The editor posts a document; this is where it actually becomes bytes
on disk.

**Slug is frozen identity; name is not** (ticket 14's own recommendation,
argued out rather than assumed): renaming a workflow must not move its
directory, or every reference to it — and its git history — breaks. The slug
is derived once, from the name, at creation, and never changes; the display
name inside `workflow.json` can change freely.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: `workflows/<slug>/` sits at the repo root, the same as the seeded
#: `chinook-nl-to-sql` workflow — not inside the `backend/` package (ticket 12:
#: Python-package code and authored-workflow content are different things
#: with different owners and different lifecycles).
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKFLOWS_ROOT = _REPO_ROOT / "workflows"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """A stable, filesystem- and URL-safe identity, derived once from a name.

    Never recomputed from a later rename — see the module's own docstring on
    why the slug is frozen. Falls back to a generic name rather than an empty
    string, since an empty slug would either collide with every other empty
    name or, worse, resolve to the workflows root itself.
    """
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return slug or "workflow"


class WorkflowNotFoundError(Exception):
    pass


class InvalidSlugError(Exception):
    """Raised for a slug that cannot be a directory name under the workflows
    root — most importantly, one attempting to escape it (`..`, an absolute
    path, a path separator). Never trust a slug read from a request without
    this check; it is the one thing standing between "delete a workflow" and
    "delete an arbitrary directory this process can reach."
    """


@dataclass(frozen=True)
class WorkflowSummary:
    slug: str
    name: str
    saved_at: str
    node_count: int
    edge_count: int


class WorkflowStore:
    """CRUD over `workflows/<slug>/workflow.json`.

    The root is injectable — never a module-level constant baked into the
    methods — so a test operates on a throwaway directory rather than this
    developer's real `workflows/` tree, the same reasoning `NodeRuntime`'s
    injectable tool registry and `WorkflowCompiler`'s injectable port resolver
    already follow.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or DEFAULT_WORKFLOWS_ROOT

    def directory_for(self, slug: str) -> Path:
        """The validated, resolved directory a slug maps to.

        Public — capability discovery (ticket 18) needs the directory to scan
        `tools/`/`functions/` under, and reaching for a `_`-prefixed method
        from outside the class would be the wrong kind of coupling for a
        genuinely reusable operation.
        """
        if not slug or slug != slugify(slug) or "/" in slug or "\\" in slug:
            raise InvalidSlugError(f"{slug!r} is not a valid workflow slug")
        candidate = (self.root / slug).resolve()
        if candidate.parent != self.root.resolve():
            raise InvalidSlugError(f"{slug!r} escapes the workflows root")
        return candidate

    def list(self) -> list[WorkflowSummary]:
        if not self.root.exists():
            return []
        summaries: list[WorkflowSummary] = []
        for entry in sorted(self.root.iterdir()):
            path = entry / "workflow.json"
            if not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                # One unreadable workflow must not blank the whole list —
                # the same reasoning `workflowStore.ts`'s `listWorkflows`
                # already applies on the frontend's own (soon to be former)
                # localStorage store.
                continue
            document = payload.get("document", payload)
            # A hidden workflow (the concierge gateway, ticket 67) is loadable
            # by slug but never advertised — the list is the customer surface.
            if payload.get("hidden") is True:
                continue
            summaries.append(
                WorkflowSummary(
                    slug=entry.name,
                    name=str(payload.get("name") or document.get("name") or entry.name),
                    saved_at=str(payload.get("savedAt") or ""),
                    node_count=len(document.get("nodes") or []),
                    edge_count=len(document.get("edges") or []),
                )
            )
        return sorted(summaries, key=lambda s: s.saved_at, reverse=True)

    def load(self, slug: str) -> dict[str, Any]:
        path = self.directory_for(slug) / "workflow.json"
        if not path.is_file():
            raise WorkflowNotFoundError(slug)
        payload = json.loads(path.read_text())
        # Documents saved before the envelope existed (or a hand-authored
        # workflow.json with no envelope at all) are the document itself.
        return payload.get("document", payload)

    def save(self, slug: str, *, name: str, document: dict[str, Any], saved_at: str) -> None:
        directory = self.directory_for(slug)
        is_new = not directory.exists()
        directory.mkdir(parents=True, exist_ok=True)

        payload = {"version": 1, "name": name, "savedAt": saved_at, "document": document}
        # Two-space indent, trailing newline, sorted-by-the-serializer-not-here
        # keys: `workflow.json`'s own determinism is ticket 19's job upstream
        # of this — this just needs to not *add* nondeterminism on top of a
        # document that already sorts its own nodes/edges.
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        (directory / "workflow.json").write_text(text)

        if is_new:
            # Cheapest thing that makes the directory legible to a coding
            # agent, per ticket 14's own recommendation — deliberately not
            # `graph.py`: an empty or stub entry point invites exactly the
            # "assumed load-bearing, found nothing" trap the ticket warns
            # against. Generation is a separate, explicit export step
            # (ticket 15), not something a save silently produces.
            (directory / "AGENTS.md").write_text(_agents_md(name, slug))

    def delete(self, slug: str) -> None:
        directory = self.directory_for(slug)
        if not directory.exists():
            raise WorkflowNotFoundError(slug)
        shutil.rmtree(directory)


def _agents_md(name: str, slug: str) -> str:
    return (
        f"# {name}\n\n"
        f"A OpenStateGraph workflow. `workflow.json` in this directory is the "
        "source of truth for its nodes and edges — edit it through the "
        "editor, not by hand, unless you know the canonical serialization "
        "rules (ticket 19: sorted nodes, content-addressed edges, no "
        "written edge ids).\n\n"
        f"- **Run it**: `POST /api/runs` or `/api/runs/stream` with this "
        f"directory's `workflow.json` as the `workflow` field, or open "
        f"`{slug}` in the editor and use Chat.\n"
        "- **Tools / functions** this workflow's nodes can bind to live in "
        "`tools/` and `functions/` alongside this file, once added.\n"
        "- **Tests** for any hand-written tool/function code belong in "
        "`tests/`.\n"
    )


__all__ = [
    "DEFAULT_WORKFLOWS_ROOT",
    "InvalidSlugError",
    "WorkflowNotFoundError",
    "WorkflowStore",
    "WorkflowSummary",
    "slugify",
]


def validate_package(workflow_dir: Path) -> list[str]:
    """Findings for one workflow package against the contract (ticket 49).

    The contract: `workflow.json` (envelope) required; `AGENTS.md` expected;
    `tools/ functions/ middlewares/ skills/ tests/ data/` optional and
    discovered by convention. Findings are strings a human acts on —
    "error: ..." blocks running, "warning: ..." is advice. Never raises:
    a broken package must be reportable, not un-listable.
    """
    findings: list[str] = []
    manifest = workflow_dir / "workflow.json"
    if not manifest.is_file():
        return [f"error: no workflow.json in {workflow_dir.name}/"]
    try:
        payload = json.loads(manifest.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return [f"error: workflow.json unreadable ({exc})"]
    document = payload.get("document", payload)
    if not isinstance(document.get("nodes"), list):
        findings.append("error: document has no nodes list")
    if not (workflow_dir / "AGENTS.md").is_file():
        findings.append("warning: no AGENTS.md — collaborators (and agents) have no orientation")
    if (workflow_dir / "tools").is_dir() and not (workflow_dir / "tests").is_dir():
        findings.append("warning: tools/ without tests/ — hand-written code with no guard")
    return findings
