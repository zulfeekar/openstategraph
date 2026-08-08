#!/usr/bin/env python3
"""Scaffolds a conforming workflow package — ticket 49.

    python3 scripts/new_workflow.py my-flow "My Flow"

Creates the contract's required files plus the conventional directories, all
discovered automatically: tools/ functions/ middlewares/ skills/ tests/ data/.
For a prebuilt supervisor+worker+grader loop, use scripts/new_team.py instead.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "workflows"


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: new_workflow.py <slug> [display name]")
    slug = sys.argv[1]
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        sys.exit(f"slug {slug!r} must be lowercase letters, digits and hyphens")
    name = sys.argv[2] if len(sys.argv) > 2 else slug.replace("-", " ").title()
    target = ROOT / slug
    if target.exists():
        sys.exit(f"{target} already exists")

    target.mkdir(parents=True)
    for sub in ("tools", "functions", "middlewares", "skills", "tests", "data"):
        (target / sub).mkdir()

    document = {
        "version": 2, "name": name, "settings": {},
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 40, "y": 200}},
            {"id": "agent1", "type": "agent.llm", "data": {}, "position": {"x": 380, "y": 180}},
            {"id": "out1", "type": "output.formatted", "data": {}, "position": {"x": 720, "y": 200}},
        ],
        "edges": [
            {"source": {"nodeId": "in1", "portId": "text"}, "target": {"nodeId": "agent1", "portId": "prompt"}},
            {"source": {"nodeId": "agent1", "portId": "result"}, "target": {"nodeId": "out1", "portId": "result"}},
        ],
    }
    (target / "workflow.json").write_text(json.dumps({
        "version": 1, "name": name,
        "savedAt": datetime.now(timezone.utc).isoformat(), "document": document,
    }, indent=2) + "\n")
    (target / "AGENTS.md").write_text(
        f"# {name}\n\nA OpenStateGraph workflow package. `workflow.json` is the source of truth —\n"
        "edit through the editor. `tools/`, `functions/`, `middlewares/` (one slot\n"
        "per file exposing `MIDDLEWARE`), `skills/*.md` (prompt context for every\n"
        "agent here) and `tests/` are discovered by convention.\n"
    )
    print(f"workflow package created: {target}")


if __name__ == "__main__":
    main()
