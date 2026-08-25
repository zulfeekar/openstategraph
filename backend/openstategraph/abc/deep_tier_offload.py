"""Progressive skill loading and tool-result offload — the deep-tier seam.

`launch-readiness/101` and `102` share one seam: `AbstractAgentNode.SLOT_ORDER`
already names `"skills"` and `"filesystem"` and nothing fills either. Both
built here as plain functions/middleware that a compiler contributes into
`resolve_middleware()`'s slot table — never a new base member, never a new
node type. `docs/decisions/nl2sql-lens-layer.md` records why `create_deep_agent`'s
own `skills=` kwarg is not the seam (it wants `StateBackend` + `invoke(files=)`,
which nothing provisions for a compiled node).

Both middlewares are built on `deepagents.backends.FilesystemBackend` in its
default `virtual_mode=True`, which is the jail: path traversal (`..`, `~`)
and root escapes are rejected, and every operation returns a result object
with `.error` set rather than raising — confirmed by reading
`FilesystemBackend._resolve_path` and its callers (`write_file`, `read_file`,
`edit_file`, `grep`, `glob`) in the installed `deepagents==0.7.5`. This module
does not reimplement that guarantee; it only relies on it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence

from deepagents.backends import FilesystemBackend
from deepagents.middleware.skills import SkillsMiddleware
from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage

#: Default: a tool result whose text exceeds this many characters is a
#: candidate for offload. Below it, inlining is cheaper than a file written
#: and read back (`launch-readiness/102`, "Watch for").
DEFAULT_OFFLOAD_THRESHOLD_CHARS = 4000


def build_skills_middleware(
    *, root_dir: str | Path, sources: Sequence[str | tuple[str, str]]
) -> SkillsMiddleware:
    """Fills the `"skills"` slot: name + description now, body on demand.

    `SkillsMiddleware` accepts any `BackendProtocol`, not only `StateBackend`
    — `FilesystemBackend` reads skill files straight off disk, so no caller
    has to provision `invoke(files={...})`. The library's own system prompt
    fragment lists each skill's name and description; the body is read later
    by the agent's own `read_file` tool, on the path shown in that list.
    """
    return SkillsMiddleware(
        backend=FilesystemBackend(root_dir=root_dir, virtual_mode=True),
        sources=list(sources),
    )


class OffloadMiddleware(AgentMiddleware):
    """Fills the `"filesystem"` slot: large tool results go to disk, not the transcript.

    Prefix-filtered, never blanket (`launch-readiness/102`): only tool calls
    whose name starts with one of `tool_name_prefixes` are even considered,
    and only a result whose text exceeds `threshold_chars` is written out —
    a short result stays inline, because a store of one-line files makes
    `grep` useless. A written result is replaced with a pointer naming the
    path and instructing the agent to use `grep`/`read_file` on the backend,
    so retrieval is a real capability and not a promise the model must recall
    unprompted.
    """

    def __init__(
        self,
        *,
        backend: FilesystemBackend,
        tool_name_prefixes: Sequence[str] = (),
        threshold_chars: int = DEFAULT_OFFLOAD_THRESHOLD_CHARS,
        path_for: Callable[[ToolCallRequest], str] | None = None,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._prefixes = tuple(tool_name_prefixes)
        self._threshold = threshold_chars
        self._path_for = path_for or _default_path_for

    def _eligible(self, tool_name: str) -> bool:
        if not self._prefixes:
            return False
        return any(tool_name.startswith(p) for p in self._prefixes)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        result = handler(request)
        if not isinstance(result, ToolMessage):
            return result
        tool_name = request.tool_call.get("name", "")
        if not self._eligible(tool_name):
            return result
        text = result.text if hasattr(result, "text") else str(result.content)
        if len(text) <= self._threshold:
            return result
        path = self._path_for(request)
        try:
            write_result = self._backend.write(path, text)
        except (ValueError, OSError, RuntimeError):
            # `FilesystemBackend.write` (deepagents==0.7.5) only catches
            # `(OSError, RuntimeError)` around path resolution — a
            # traversal path (`..`) makes `_resolve_path` raise
            # `ValueError`, uncaught, straight out of `write`. That
            # contradicts "refuse via a result, not a raise": recorded as
            # a finding in `launch-readiness/102`, not re-implemented
            # here. This `except` is *this middleware's* seam keeping its
            # own promise regardless — a bad path is a recoverable,
            # un-offloaded message, never a dead run.
            return result
        if write_result.error:
            # An ordinary write failure the backend *did* catch and
            # report as a result.
            return result
        pointer = (
            f"[offloaded: {len(text)} chars written to path={path!r}. "
            f"Use grep(path={path!r}, ...) or read_file({path!r}) to inspect it.]"
        )
        return result.model_copy(update={"content": pointer})


def _default_path_for(request: ToolCallRequest) -> str:
    name = request.tool_call.get("name", "tool")
    call_id = request.tool_call.get("id", "0")
    return f"/offload/{name}/{call_id}.txt"


__all__ = [
    "DEFAULT_OFFLOAD_THRESHOLD_CHARS",
    "OffloadMiddleware",
    "build_skills_middleware",
]
