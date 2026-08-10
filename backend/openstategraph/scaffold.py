"""Creating a conforming workflow package — the one copy of the scaffold.

**Tier 2, provisional** (`docs/stability.md`): importable and documented, may
change in a minor release with a changelog note.

This used to live in `scripts/new_workflow.py` and `scripts/new_team.py`, which
worked exactly as long as you had a checkout. `scripts/` is not in the wheel, so
`openstategraph new` could not have called it — and the alternative, a second
copy of the document literal inside the CLI, is precisely the duplicated
*knowledge* CLAUDE.md names as the defect: the two copies would agree on the day
they were written and diverge on the first port rename.

So the scaffold moved **here**, and both entry points are thin:

- `scripts/new_workflow.py` / `scripts/new_team.py` keep their exact
  command lines and now call these functions;
- `openstategraph new <slug> [--team]` calls the same functions.

Neither knows what a starter document looks like. This module does, once.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: A package's directory name is its frozen identity, and it is what scopes
#: tool, function, skill and knowledge discovery. Same rule as `slugify`.
SLUG_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*")

#: Discovered by convention, so a scaffold that omits them is a scaffold whose
#: conventions are invisible until someone reads the docs.
WORKFLOW_DIRECTORIES = ("tools", "functions", "middlewares", "skills", "tests", "data")
TEAM_DIRECTORIES = ("tools", "functions", "middlewares", "tests")


class ScaffoldError(ValueError):
    """A slug that cannot name a package, or a directory already there."""


def _prepare(root: Path | str, slug: str, subdirectories: tuple[str, ...]) -> Path:
    if not SLUG_PATTERN.fullmatch(slug):
        raise ScaffoldError(f"slug {slug!r} must be lowercase letters, digits and hyphens")
    target = Path(root) / slug
    if target.exists():
        raise ScaffoldError(f"{target} already exists")
    target.mkdir(parents=True)
    for name in subdirectories:
        (target / name).mkdir()
    return target


def _envelope(name: str, document: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "name": name,
        # Ticket 04: scaffolded workflows are DRAFTS. Publish via
        # POST /api/workflows/<slug>/publish (or the editor's Workflows panel)
        # to appear on the customer /chat surface.
        "published": False,
        "savedAt": datetime.now(timezone.utc).isoformat(),
        "document": document,
    }


def starter_document(name: str) -> dict[str, Any]:
    """input → agent → output. The smallest document that compiles and runs."""
    return {
        "version": 2,
        "name": name,
        "settings": {},
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 40, "y": 200}},
            {"id": "agent1", "type": "agent.llm", "data": {}, "position": {"x": 380, "y": 180}},
            {
                "id": "out1",
                "type": "output.formatted",
                "data": {},
                "position": {"x": 720, "y": 200},
            },
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "agent1", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "agent1", "portId": "result"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    }


def team_document(name: str, outcome: str) -> dict[str, Any]:
    """The prebuilt minimum-viable Team (ticket 52): supervisor + worker + grader.

    The grader's criteria ARE the team's outcome contract — the first thing a
    developer edits — and the `revise` edge back to the supervisor is what
    makes the loop a loop. A cycle needs a conditional edge to terminate, and
    the grader is it.
    """
    nodes = [
        {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 40, "y": 200}},
        {
            "id": "lead1",
            "type": "orchestrate.supervisor",
            "title": f"{name} Lead",
            "data": {
                "maxSubtasks": 3,
                "instruction": "Split the task into the smallest set of independent subtasks.",
            },
            "position": {"x": 360, "y": 200},
        },
        {
            "id": "member1",
            "type": "orchestrate.worker",
            "title": "Generalist",
            "data": {"default": True},
            "position": {"x": 700, "y": 200},
        },
        {
            "id": "join1",
            "type": "function.format_report",
            "data": {"reportTitle": f"{name} findings"},
            "position": {"x": 1040, "y": 200},
        },
        {
            "id": "grader1",
            "type": "route.grader",
            "data": {"criteria": outcome, "criteriaMode": "extend", "maxAttempts": 2},
            "position": {"x": 1380, "y": 200},
        },
        {"id": "out1", "type": "output.formatted", "data": {}, "position": {"x": 1720, "y": 200}},
    ]

    def edge(source: str, source_port: str, target: str, target_port: str) -> dict[str, Any]:
        return {
            "source": {"nodeId": source, "portId": source_port},
            "target": {"nodeId": target, "portId": target_port},
        }

    edges = [
        edge("in1", "text", "lead1", "instruction"),
        edge("lead1", "workers", "member1", "dispatch"),
        edge("member1", "result", "join1", "candidate"),
        edge("join1", "report", "grader1", "candidate"),
        edge("grader1", "pass", "out1", "result"),
        edge("grader1", "revise", "lead1", "feedback"),
    ]
    return {"version": 2, "name": name, "settings": {}, "nodes": nodes, "edges": edges}


def new_workflow(root: Path | str, slug: str, name: str | None = None) -> Path:
    """Create `<root>/<slug>/` — the contract's files plus the conventions.

    Returns the directory, which is exactly what `load_workflow` takes.
    """
    display = name or slug.replace("-", " ").title()
    target = _prepare(root, slug, WORKFLOW_DIRECTORIES)
    document = starter_document(display)
    (target / "workflow.json").write_text(json.dumps(_envelope(display, document), indent=2) + "\n")
    (target / "AGENTS.md").write_text(
        f"# {display}\n\nAn OpenStateGraph workflow package. `workflow.json` is the source of "
        "truth —\nedit through the editor. `tools/`, `functions/`, `middlewares/` (one slot\n"
        "per file exposing `MIDDLEWARE`), `skills/*.md` (prompt context for every\n"
        "agent here) and `tests/` are discovered by convention.\n"
    )
    return target


def new_team(root: Path | str, slug: str, outcome: str | None = None) -> Path:
    """Create `<root>/<slug>/` as a Team package. Returns the directory."""
    display = slug.replace("-", " ").title()
    contract = outcome or "- The answer must actually complete the task it was given."
    target = _prepare(root, slug, TEAM_DIRECTORIES)
    document = team_document(display, contract)
    (target / "workflow.json").write_text(json.dumps(_envelope(display, document), indent=2) + "\n")
    (target / "AGENTS.md").write_text(
        f"""# {display} (a Team)

An OpenStateGraph **team package** — supervisor + default worker + a grader whose
criteria are the team's outcome contract. Scaffolded by `scripts/new_team.py`.

- **Mount it**: add a **Team** node in any workflow with slug `{slug}`.
- **Outcome**: edit `grader1`'s criteria — that is what "done" means here.
- **Members**: add workers (each a new archetype by title) and bind tools from
  `tools/`; `middlewares/` and `functions/` are discovered by convention.
"""
    )
    return target


__all__ = [
    "ScaffoldError",
    "SLUG_PATTERN",
    "new_team",
    "new_workflow",
    "starter_document",
    "team_document",
]
