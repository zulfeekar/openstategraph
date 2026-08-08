"""Prebuilt platform-introspection tools — read-only, for the concierge.

The gateway's spec (ticket 67, user): the top workflow should be able to
*explore* the platform — list what exists, describe what a workflow does —
without any ability to write. These are that, as tools rather than raw
`ls`/`grep`: the jail is structural (they can only read what the
WorkflowStore exposes plus each package's own AGENTS.md), so there is no
path argument to escape with and nothing to sandbox.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from dyflow.abc.tool import BaseTool, NoArgs, ToolResult

WORKFLOWS_ROOT = Path(__file__).resolve().parent.parent.parent / "workflows"


def _packages() -> list[Path]:
    if not WORKFLOWS_ROOT.is_dir():
        return []
    return sorted(
        entry for entry in WORKFLOWS_ROOT.iterdir() if (entry / "workflow.json").is_file()
    )


def _envelope(package: Path) -> dict[str, Any]:
    try:
        return json.loads((package / "workflow.json").read_text())
    except (json.JSONDecodeError, OSError):
        return {}


class ListWorkflowsTool(BaseTool):
    """What exists — the same list the workflow picker shows (hidden ones stay hidden)."""

    name = "platform_list_workflows"
    node_type = "tool.platform-list-workflows"
    description = (
        "List every workflow available on this platform, with its name and "
        "what it is for. Call this when the user asks what this system can do "
        "or which workflows exist."
    )
    Args = NoArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        rows = []
        for package in _packages():
            payload = _envelope(package)
            if payload.get("hidden") is True:
                continue
            document = payload.get("document", payload)
            name = str(payload.get("name") or document.get("name") or package.name)
            rows.append(
                f"- **{package.name}** — {name} "
                f"({len(document.get('nodes') or [])} nodes)"
            )
        if not rows:
            return ToolResult(content="No workflows exist yet.")
        return ToolResult(
            content=f"{len(rows)} workflows are available:\n" + "\n".join(rows)
        )


class DescribeWorkflowArgs(BaseModel):
    model_config = {"extra": "forbid"}
    slug: str = Field(description="The workflow's slug, e.g. 'tabular-analytics'.")


class DescribeWorkflowTool(BaseTool):
    """One workflow's own story: its AGENTS.md plus a structural summary."""

    name = "platform_describe_workflow"
    node_type = "tool.platform-describe-workflow"
    description = (
        "Describe one workflow: what it is for (its own documentation) and "
        "its structure. Use after platform_list_workflows when the user asks "
        "about a specific capability."
    )
    Args = DescribeWorkflowArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, DescribeWorkflowArgs)
        slug = args.slug.strip().strip("/")
        package = WORKFLOWS_ROOT / slug
        # Resolve + containment check: the slug is model-supplied input.
        if (
            not package.resolve().is_relative_to(WORKFLOWS_ROOT)
            or not (package / "workflow.json").is_file()
        ):
            known = ", ".join(p.name for p in _packages())
            return ToolResult.failure(f"No workflow '{slug}'. Available: {known}")
        payload = _envelope(package)
        if payload.get("hidden") is True:
            return ToolResult.failure(f"No workflow '{slug}'.")
        document = payload.get("document", payload)
        node_types = sorted({str(n.get("type", "")) for n in document.get("nodes") or []})
        parts = [
            f"### {payload.get('name') or slug}",
            f"Nodes: {len(document.get('nodes') or [])} · "
            f"Edges: {len(document.get('edges') or [])} · "
            f"Node types: {', '.join(node_types)}",
        ]
        agents_md = package / "AGENTS.md"
        if agents_md.is_file():
            try:
                parts.append(agents_md.read_text()[:2000])
            except OSError:
                pass
        return ToolResult(content="\n\n".join(parts))


PLATFORM_TOOLS = [ListWorkflowsTool(), DescribeWorkflowTool()]


# --- read-only filesystem tools: everything readable, nothing writable ---- #

REPO_ROOT = WORKFLOWS_ROOT.parent
#: Never descended into: bulk, caches, VCS internals — noise, not knowledge.
EXCLUDED_DIRS = {".git", "node_modules", ".venv", "venv", ".dev", "__pycache__",
                 "dist", "coverage", ".pytest_cache", "graphify-out"}
MAX_READ_BYTES = 40_000
MAX_MATCHES = 60


def _inside_repo(path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(REPO_ROOT)
    except OSError:
        return False


def _excluded(path: Path) -> bool:
    # Hidden files and directories are out too — `.env` holds credentials,
    # `.git` holds history; a read-only jail that reads secrets isn't one
    # (found in self-review after shipping).
    return any(part in EXCLUDED_DIRS or part.startswith(".") for part in path.parts)


class LsArgs(BaseModel):
    model_config = {"extra": "forbid"}
    path: str = Field(default=".", description="Directory relative to the repository root.")


class PlatformLsTool(BaseTool):
    """`ls`, jailed to the repository, read-only by construction."""

    name = "platform_ls"
    node_type = "tool.platform-ls"
    description = (
        "List a directory inside this platform's repository (read-only). "
        "Start at '.' to see the layout; 'workflows/<slug>' shows a package."
    )
    Args = LsArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, LsArgs)
        target = (REPO_ROOT / args.path.strip().lstrip("/")).resolve()
        if not _inside_repo(target) or _excluded(target.relative_to(REPO_ROOT)):
            return ToolResult.failure(f"'{args.path}' is outside the readable area.")
        if not target.is_dir():
            return ToolResult.failure(f"'{args.path}' is not a directory.")
        rows = []
        for entry in sorted(target.iterdir()):
            if entry.name.startswith(".") or entry.name in EXCLUDED_DIRS:
                continue
            rows.append(f"{entry.name}/" if entry.is_dir() else entry.name)
        return ToolResult(content="\n".join(rows) or "(empty)")


class ReadArgs(BaseModel):
    model_config = {"extra": "forbid"}
    path: str = Field(description="File path relative to the repository root.")


class PlatformReadTool(BaseTool):
    """`cat`, jailed and size-capped. There is no write counterpart on purpose."""

    name = "platform_read_file"
    node_type = "tool.platform-read-file"
    description = (
        "Read one text file inside this platform's repository (read-only, "
        "truncated at 40kB). Use for AGENTS.md, workflow.json, tool source."
    )
    Args = ReadArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, ReadArgs)
        target = (REPO_ROOT / args.path.strip().lstrip("/")).resolve()
        if not _inside_repo(target) or _excluded(target.relative_to(REPO_ROOT)):
            return ToolResult.failure(f"'{args.path}' is outside the readable area.")
        if not target.is_file():
            return ToolResult.failure(f"'{args.path}' is not a file.")
        try:
            data = target.read_bytes()[:MAX_READ_BYTES]
            text = data.decode("utf-8", errors="replace")
        except OSError as exc:
            return ToolResult.failure(f"Could not read '{args.path}': {exc}")
        suffix = "\n\n_(truncated at 40kB)_" if target.stat().st_size > MAX_READ_BYTES else ""
        return ToolResult(content=text + suffix)


class GrepArgs(BaseModel):
    model_config = {"extra": "forbid"}
    pattern: str = Field(description="Case-insensitive substring to search for.")
    path: str = Field(default=".", description="Directory to search, relative to the repo root.")


class PlatformGrepTool(BaseTool):
    """`grep -ri`, jailed, match-capped — exploration, not exfiltration."""

    name = "platform_grep"
    node_type = "tool.platform-grep"
    description = (
        "Search text files inside this platform's repository for a "
        "case-insensitive substring (read-only, first 60 matches). Use to "
        "find where something is defined or mentioned."
    )
    Args = GrepArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, GrepArgs)
        root = (REPO_ROOT / args.path.strip().lstrip("/")).resolve()
        if not _inside_repo(root) or _excluded(root.relative_to(REPO_ROOT)):
            return ToolResult.failure(f"'{args.path}' is outside the readable area.")
        needle = args.pattern.strip().lower()
        if not needle:
            return ToolResult.failure("Give a non-empty pattern.")
        matches: list[str] = []
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(REPO_ROOT)
            if not path.is_file() or _excluded(rel) or path.stat().st_size > 400_000:
                continue
            if path.suffix in {".sqlite", ".png", ".pdf", ".ico", ".lock"}:
                continue
            try:
                for i, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                    if needle in line.lower():
                        matches.append(f"{rel}:{i}: {line.strip()[:140]}")
                        if len(matches) >= MAX_MATCHES:
                            return ToolResult(content="\n".join(matches) + "\n\n_(capped at 60 matches)_")
            except OSError:
                continue
        return ToolResult(content="\n".join(matches) or f"No matches for '{args.pattern}'.")


PLATFORM_TOOLS = [
    ListWorkflowsTool(),
    DescribeWorkflowTool(),
    PlatformLsTool(),
    PlatformReadTool(),
    PlatformGrepTool(),
]
