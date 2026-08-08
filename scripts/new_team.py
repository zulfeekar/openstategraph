#!/usr/bin/env python3
"""Scaffolds a new Team workflow package — ticket 56.

    python3 scripts/new_team.py research-team "Deliver a sourced summary"

Creates `workflows/<slug>/` with the prebuilt minimum-viable Team (ticket 52's
design): supervisor + one default worker + a grader closing the revise loop.
The grader's criteria ARE the team's outcome contract — edit them first. Mount
the team in any workflow with a **Team** node pointing at this slug.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "workflows"


def document(name: str, outcome: str) -> dict:
    nodes = [
        {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 40, "y": 200}},
        {
            "id": "lead1",
            "type": "orchestrate.supervisor",
            "title": f"{name} Lead",
            "data": {"maxSubtasks": 3, "instruction": "Split the task into the smallest set of independent subtasks."},
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
    edge = lambda s, sp, t, tp: {"source": {"nodeId": s, "portId": sp}, "target": {"nodeId": t, "portId": tp}}
    edges = [
        edge("in1", "text", "lead1", "instruction"),
        edge("lead1", "workers", "member1", "dispatch"),
        edge("member1", "result", "join1", "candidate"),
        edge("join1", "report", "grader1", "candidate"),
        edge("grader1", "pass", "out1", "result"),
        edge("grader1", "revise", "lead1", "feedback"),
    ]
    return {"version": 2, "name": name, "settings": {}, "nodes": nodes, "edges": edges}


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: new_team.py <slug> [expected outcome sentence]")
    slug = sys.argv[1]
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        sys.exit(f"slug {slug!r} must be lowercase letters, digits and hyphens")
    outcome = sys.argv[2] if len(sys.argv) > 2 else "- The answer must actually complete the task it was given."
    name = slug.replace("-", " ").title()
    target = ROOT / slug
    if target.exists():
        sys.exit(f"{target} already exists")

    target.mkdir(parents=True)
    for sub in ("tools", "functions", "middlewares", "tests"):
        (target / sub).mkdir()

    envelope = {
        "version": 1,
        "name": name,
        "savedAt": datetime.now(timezone.utc).isoformat(),
        "document": document(name, outcome),
    }
    (target / "workflow.json").write_text(json.dumps(envelope, indent=2) + "\n")
    (target / "AGENTS.md").write_text(
        f"""# {name} (a Team)

A OpenStateGraph **team package** — supervisor + default worker + a grader whose
criteria are the team's outcome contract. Scaffolded by `scripts/new_team.py`.

- **Mount it**: add a **Team** node in any workflow with slug `{slug}`.
- **Outcome**: edit `grader1`'s criteria — that is what "done" means here.
- **Members**: add workers (each a new archetype by title) and bind tools from
  `tools/`; `middlewares/` and `functions/` are discovered by convention.
"""
    )
    print(f"team package created: {target}")


if __name__ == "__main__":
    main()
