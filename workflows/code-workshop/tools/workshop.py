"""Code Workshop tools — a sandboxed coding loop for the coder workflow (ticket 43).

Safety rails, non-negotiable and enforced *here*, in trusted code, never left
to the model's good behaviour:

- **Every file operation is jailed** to this workflow's own ``scratch/``
  directory. Paths are resolved (symlinks and ``..`` included) and verified to
  stay inside the jail before any read, write or listing; an escape attempt
  comes back as a readable refusal, not an exception and never an actual read.
- **Git state is isolated.** The workspace is a *copy* of the pristine fixture
  under ``data/fixture-repo``, given its own fresh git repository. Every git
  invocation runs with global/system config disabled, so nothing about the
  developer's real identity, hooks or aliases leaks in — and nothing this
  workflow does can touch the enclosing Dyflow repository's git state.
- **No arbitrary shell.** There is no "run command" tool. The only process
  the model can start is a fixed pytest invocation with a fixed argument list;
  the only git commands that exist are the fixed ones written below.
- **PR creation is dry-run by default.** ``workshop_create_pr`` writes a
  ``.patch`` and a PR body into the workflow's ``output/`` directory. Actually
  invoking ``gh pr create`` requires the node's explicit ``useGh`` opt-in
  field — and the workflow graph still routes through ``human.approval``
  before this tool's node can run at all.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from dyflow.abc.tool import BaseTool, NoArgs, ToolResult

#: This workflow's own directory — everything below is anchored to it.
WORKFLOW_DIR = Path(__file__).resolve().parent.parent
#: The pristine project template, checked into the repo. Never edited in place.
FIXTURE_DIR = WORKFLOW_DIR / "data" / "fixture-repo"
#: The jail. Every file tool resolves against this and refuses to leave it.
SCRATCH_DIR = WORKFLOW_DIR / "scratch" / "repo"
#: Where the PR dry-run artifacts (.patch + PR body) land. Gitignored.
OUTPUT_DIR = WORKFLOW_DIR / "output"

#: Ceiling for one file read / one subprocess, so a runaway never eats a run.
MAX_READ_BYTES = 64_000
MAX_REPORT_CHARS = 6_000
SUBPROCESS_TIMEOUT = 120


def _isolated_git_env() -> dict[str, str]:
    """An environment where git sees no user/system config and a fixed identity.

    ``GIT_CONFIG_GLOBAL``/``GIT_CONFIG_SYSTEM`` pointed at the null device is
    git's own documented mechanism for "run with no inherited config" — hooks
    templates, aliases, signing and the developer's identity all stay out.
    """
    env = dict(os.environ)
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_AUTHOR_NAME="Code Workshop",
        GIT_AUTHOR_EMAIL="workshop@dyflow.local",
        GIT_COMMITTER_NAME="Code Workshop",
        GIT_COMMITTER_EMAIL="workshop@dyflow.local",
    )
    return env


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """One fixed git invocation inside the jail. Never shell, never user args."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=_isolated_git_env(),
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT,
    )


def _tail(text: str, limit: int = MAX_REPORT_CHARS) -> str:
    """The end of a long report — where pytest puts the summary — not the start."""
    if len(text) <= limit:
        return text
    return f"[... {len(text) - limit} chars truncated ...]\n{text[-limit:]}"


class _WorkshopTool(BaseTool):
    """Shared jail plumbing for every workshop tool.

    Directories are constructor parameters (defaulting to the module's real
    locations) so tests can point a tool at a temp directory without touching
    the shipped fixture. ``_resolve`` is the single place a model-supplied
    path becomes a filesystem path — every subclass goes through it.
    """

    def __init__(
        self,
        *,
        scratch_dir: Path = SCRATCH_DIR,
        fixture_dir: Path = FIXTURE_DIR,
        output_dir: Path = OUTPUT_DIR,
    ) -> None:
        self.scratch_dir = scratch_dir
        self.fixture_dir = fixture_dir
        self.output_dir = output_dir

    def _resolve(self, relative: str) -> tuple[Path | None, str | None]:
        """Resolve a model-supplied path inside the jail, or say why not.

        ``resolve()`` collapses ``..`` and follows symlinks *before* the
        containment check, so neither trick can step outside. ``.git`` is
        additionally off-limits by name: the model edits the project, never
        the repository's own machinery.
        """
        raw = (relative or "").strip()
        if not raw or Path(raw).is_absolute():
            return None, f"Path must be relative to the workspace root, got: {raw!r}"
        jail = self.scratch_dir.resolve()
        candidate = (jail / raw).resolve()
        if candidate != jail and jail not in candidate.parents:
            return None, f"Refused: {raw!r} escapes the workspace jail"
        inside = candidate.relative_to(jail)
        if ".git" in inside.parts:
            return None, "Refused: the workspace's .git directory is off-limits"
        return candidate, None

    def _require_workspace(self) -> str | None:
        if not (self.scratch_dir / ".git").is_dir():
            return (
                "No workspace yet. Call workshop_reset_workspace first — it "
                "creates the sandboxed copy of the project."
            )
        return None


class ResetWorkspaceTool(_WorkshopTool):
    """Create (or recreate) the sandboxed workspace from the pristine fixture."""

    name = "workshop_reset_workspace"
    node_type = "tool.workshop-reset"
    description = (
        "Create a fresh, sandboxed copy of the project to work on, with its own "
        "isolated git repository and a committed baseline. Call this first. "
        "Calling it again discards every change and starts over."
    )
    Args = NoArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        if not self.fixture_dir.is_dir():
            return ToolResult.failure(f"Fixture project not found: {self.fixture_dir}")

        if self.scratch_dir.exists():
            shutil.rmtree(self.scratch_dir)
        shutil.copytree(
            self.fixture_dir, self.scratch_dir, ignore=shutil.ignore_patterns(".git")
        )

        for step in (["init", "-b", "main"], ["add", "-A"], ["commit", "-m", "baseline"]):
            proc = _git(step, self.scratch_dir)
            if proc.returncode != 0:
                return ToolResult.failure(
                    f"git {' '.join(step)} failed: {proc.stderr.strip() or proc.stdout.strip()}"
                )

        files = sorted(
            str(p.relative_to(self.scratch_dir))
            for p in self.scratch_dir.rglob("*")
            if p.is_file() and ".git" not in p.parts
        )
        listing = "\n".join(f"- {f}" for f in files)
        return ToolResult(
            content=f"Workspace ready with a committed baseline. Files:\n{listing}"
        )


class ListFilesArgs(BaseModel):
    model_config = {"extra": "forbid"}
    directory: str = Field(
        default=".",
        description="Directory to list, relative to the workspace root (default: root).",
    )


class ListFilesTool(_WorkshopTool):
    """List files inside the workspace jail."""

    name = "workshop_list_files"
    node_type = "tool.workshop-list-files"
    description = "List the files in the sandboxed workspace (optionally one subdirectory)."
    Args = ListFilesArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, ListFilesArgs)
        if (missing := self._require_workspace()) is not None:
            return ToolResult.failure(missing)
        target, err = self._resolve(args.directory)
        if err is not None:
            return ToolResult.failure(err)
        assert target is not None
        if not target.is_dir():
            return ToolResult.failure(f"Not a directory in the workspace: {args.directory!r}")

        files = sorted(
            str(p.relative_to(self.scratch_dir))
            for p in target.rglob("*")
            if p.is_file() and ".git" not in p.parts
        )
        if not files:
            return ToolResult(content="(no files)")
        return ToolResult(content="\n".join(files))


class ReadFileArgs(BaseModel):
    model_config = {"extra": "forbid"}
    path: str = Field(description="File to read, relative to the workspace root.")


class ReadFileTool(_WorkshopTool):
    """Read one file inside the workspace jail."""

    name = "workshop_read_file"
    node_type = "tool.workshop-read-file"
    description = "Read a file from the sandboxed workspace."
    Args = ReadFileArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, ReadFileArgs)
        if (missing := self._require_workspace()) is not None:
            return ToolResult.failure(missing)
        target, err = self._resolve(args.path)
        if err is not None:
            return ToolResult.failure(err)
        assert target is not None
        if not target.is_file():
            return ToolResult.failure(f"No such file in the workspace: {args.path!r}")
        data = target.read_bytes()
        if len(data) > MAX_READ_BYTES:
            return ToolResult.failure(
                f"File too large to read ({len(data)} bytes; cap {MAX_READ_BYTES})"
            )
        try:
            return ToolResult(content=data.decode("utf-8"))
        except UnicodeDecodeError:
            return ToolResult.failure(f"Not a UTF-8 text file: {args.path!r}")


class WriteFileArgs(BaseModel):
    model_config = {"extra": "forbid"}
    path: str = Field(description="File to write, relative to the workspace root.")
    content: str = Field(description="The complete new contents of the file.")


class WriteFileTool(_WorkshopTool):
    """Write one file inside the workspace jail."""

    name = "workshop_write_file"
    node_type = "tool.workshop-write-file"
    description = (
        "Write (create or fully replace) a file in the sandboxed workspace. "
        "Always write the complete file contents."
    )
    Args = WriteFileArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, WriteFileArgs)
        if (missing := self._require_workspace()) is not None:
            return ToolResult.failure(missing)
        target, err = self._resolve(args.path)
        if err is not None:
            return ToolResult.failure(err)
        assert target is not None
        if target.is_dir():
            return ToolResult.failure(f"{args.path!r} is a directory, not a file")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(args.content, encoding="utf-8")
        return ToolResult(content=f"Wrote {len(args.content)} chars to {args.path}")


class RunTestsTool(_WorkshopTool):
    """The fixed pytest runner — the only process the model can start.

    A *failing* test run is a successful tool call: the report is the data
    the coder needs. Only "could not run at all" is a failure.
    """

    name = "workshop_run_tests"
    node_type = "tool.workshop-run-tests"
    description = (
        "Run the workspace's test suite with pytest and return the report. "
        "The command is fixed; there is no way to run anything else."
    )
    Args = NoArgs

    def __init__(self, *, timeout_seconds: int = SUBPROCESS_TIMEOUT, **kwargs) -> None:
        super().__init__(**kwargs)
        self.timeout_seconds = timeout_seconds

    def configure(self, data):
        configured = data.get("timeoutSeconds")
        if isinstance(configured, (int, float)) and configured > 0:
            return type(self)(
                timeout_seconds=int(configured),
                scratch_dir=self.scratch_dir,
                fixture_dir=self.fixture_dir,
                output_dir=self.output_dir,
            )
        return self

    def _execute(self, args: BaseModel) -> ToolResult:
        if (missing := self._require_workspace()) is not None:
            return ToolResult.failure(missing)
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--color=no", "-p", "no:cacheprovider"],
                cwd=self.scratch_dir,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ToolResult.failure(f"pytest timed out after {self.timeout_seconds}s")
        report = _tail((proc.stdout + "\n" + proc.stderr).strip())
        verdict = "ALL TESTS PASSED" if proc.returncode == 0 else "TESTS FAILED"
        return ToolResult(content=f"{verdict} (exit code {proc.returncode})\n\n{report}")


class DiffTool(_WorkshopTool):
    """The workspace's full diff against the committed baseline."""

    name = "workshop_diff"
    node_type = "tool.workshop-diff"
    description = (
        "Show the unified diff of every change made in the workspace since the "
        "baseline commit, including new files."
    )
    Args = NoArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        if (missing := self._require_workspace()) is not None:
            return ToolResult.failure(missing)
        # Stage everything first so new files appear in the diff too.
        staged = _git(["add", "-A"], self.scratch_dir)
        if staged.returncode != 0:
            return ToolResult.failure(f"git add failed: {staged.stderr.strip()}")
        proc = _git(["diff", "--cached", "HEAD"], self.scratch_dir)
        if proc.returncode != 0:
            return ToolResult.failure(f"git diff failed: {proc.stderr.strip()}")
        diff = proc.stdout.strip()
        return ToolResult(content=diff or "_No changes since the baseline._")


class CreatePrArgs(BaseModel):
    model_config = {"extra": "forbid"}
    title: str = Field(description="Pull request title, one line.")
    body: str = Field(
        description="Pull request body in Markdown: what changed, why, and how it was tested."
    )


class CreatePrTool(_WorkshopTool):
    """Emit the change as a patch + PR body. Dry-run by default.

    The dry-run artifacts (``output/change.patch`` and ``output/PR.md``) are
    always written. Actually invoking ``gh pr create`` happens only when the
    bound node's ``useGh`` field is explicitly true — and the graph puts a
    ``human.approval`` gate upstream of this node besides.
    """

    name = "workshop_create_pr"
    node_type = "tool.workshop-create-pr"
    description = (
        "Package the workspace's changes as a pull request: writes a .patch file "
        "and a PR body to the workflow's output directory. By default this is a "
        "dry run; pushing a real PR via gh requires the node's explicit opt-in."
    )
    Args = CreatePrArgs

    def __init__(self, *, use_gh: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.use_gh = use_gh

    def configure(self, data):
        if data.get("useGh") is True:
            return type(self)(
                use_gh=True,
                scratch_dir=self.scratch_dir,
                fixture_dir=self.fixture_dir,
                output_dir=self.output_dir,
            )
        return self

    def _run_gh(self, title: str, body: str) -> subprocess.CompletedProcess[str]:
        """Isolated so a test can prove it is never reached by default."""
        return subprocess.run(
            ["gh", "pr", "create", "--title", title, "--body", body],
            cwd=self.scratch_dir,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, CreatePrArgs)
        if (missing := self._require_workspace()) is not None:
            return ToolResult.failure(missing)

        staged = _git(["add", "-A"], self.scratch_dir)
        if staged.returncode != 0:
            return ToolResult.failure(f"git add failed: {staged.stderr.strip()}")
        proc = _git(["diff", "--cached", "HEAD"], self.scratch_dir)
        if proc.returncode != 0:
            return ToolResult.failure(f"git diff failed: {proc.stderr.strip()}")
        diff = proc.stdout
        if not diff.strip():
            return ToolResult.failure("Nothing to submit: the workspace has no changes")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        patch_path = self.output_dir / "change.patch"
        body_path = self.output_dir / "PR.md"
        patch_path.write_text(diff, encoding="utf-8")
        body_path.write_text(f"# {args.title.strip()}\n\n{args.body.strip()}\n", encoding="utf-8")

        written = f"Wrote {patch_path.name} and {body_path.name} to {self.output_dir}"
        if not self.use_gh:
            return ToolResult(content=f"DRY RUN — no PR was opened. {written}")

        gh = self._run_gh(args.title.strip(), args.body.strip())
        if gh.returncode != 0:
            return ToolResult.failure(
                f"gh pr create failed: {gh.stderr.strip() or gh.stdout.strip()}. "
                f"The dry-run artifacts were still written ({written})."
            )
        return ToolResult(content=f"PR opened via gh: {gh.stdout.strip()}. {written}")


#: The workflow's tool catalogue.
TOOLS = [
    ResetWorkspaceTool(),
    ListFilesTool(),
    ReadFileTool(),
    WriteFileTool(),
    RunTestsTool(),
    DiffTool(),
    CreatePrTool(),
]

__all__ = [
    "TOOLS",
    "ResetWorkspaceTool",
    "ListFilesTool",
    "ReadFileTool",
    "WriteFileTool",
    "RunTestsTool",
    "DiffTool",
    "CreatePrTool",
    "WORKFLOW_DIR",
    "FIXTURE_DIR",
    "SCRATCH_DIR",
    "OUTPUT_DIR",
]
