"""The `"narration"` slot: one line before a model call, one line after.

`launch-readiness/104`. The evidence: a real trace of "which lenses are
available?" took 50.2s; inside it, a tool call answered in 66ms and one
`model` call took 40,522ms producing nothing visible. The answer was correct.
The user saw a glowing border for most of a minute with no way to tell
working from stuck. Docs confirmed the fix is possible: `before_model` /
`after_model` are ordinary middleware hooks (`docs-langchain`, "Custom
middleware" / "Node-style hooks"), and a hook can reach a **streaming**
consumer mid-run with `get_stream_writer()` plus `stream_mode="custom"`
(`docs-langchain`, "Custom updates") — the crux the assignment named: if a
hook could not emit mid-run, this whole approach would fail, and it does not.

**This rides the seam `openstategraph.progress` already built, not a second
one.** That module exists for exactly this gap ("a step saying something about
itself mid-execution") and `api/streaming.py` already turns its envelope into
a `progress` SSE frame with the node resolved. A parallel `custom`-channel
vocabulary here would be the DRY violation CLAUDE.md warns about — the same
knowledge (how to reach a live consumer mid-run) declared twice for two
reasons to change. `report_progress()` is also already the swallow-on-failure,
no-op-outside-a-run seam (`RuntimeError` from `get_stream_writer()` outside a
graph), so this module does not re-implement that guard either.

**The middleware narrates, not the model.** A model asked to narrate can
decline — this codebase has already shown what an unenforced instruction is
worth (CLAUDE.md, "Read tolerantly, trust strictly"; `BaseAgentNode.PROMPT`'s
`output_contract` explicitly tells agents *not* to narrate their tool loop,
because a narrating model previously leaked its scratchpad into the
customer-facing answer). A middleware describing the call it is wrapping is
cheaper and cannot lie about whether it ran.

**Content stays generic on purpose.** This class has no domain knowledge — it
wraps `before_model`/`after_model` for *any* agent, so it never has a tool id,
a lens name, or a token count to report honestly. CLAUDE.md's instruction is
"free of internals" and "a wall of debug text is a worse answer than
silence" — a generic line is the honest one here. A node type that wants a
sharper line contributes its own middleware into the same `"narration"` slot;
this default is the floor every agent gets, not a ceiling.
"""

from __future__ import annotations

import json
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState, ToolCallRequest
from langgraph.runtime import Runtime

from openstategraph.progress import report_progress

# `launch-readiness/105`: a read-through cache for tool calls that return
# STRUCTURE — a lens list, a table schema, a canonical spelling — never a
# MEASUREMENT (row counts, volumes, prices, anything a date window touches).
# A stored measurement served again is a stale number wearing a fresh
# timestamp, which is this project's worst failure class (CLAUDE.md).
#
# Explicit allowlist, never a denylist: a denylist defaults every new tool to
# "safe to cache", and the next tool added is then wrong by default. Sourced
# from the 13 tools `~/osg-cpl-mcp`'s server actually advertises
# (`docs/decisions/an-agent-that-reaches-cpl-through-mcp.md`):
#
#   mcp_list_lenses, mcp_resolve_lens, mcp_describe_lens_tables,
#   mcp_describe_table, mcp_search_tables, mcp_lookup_canonical_value,
#   mcp_skill_list, mcp_skill_read, mcp_skill_grep, mcp_lookup_few_shot
#       — each returns a fixed shape (a list of lenses, a schema, a
#         canonical spelling, a skill's text, a documentation match): the
#         same call answers the same way regardless of when it is asked.
#
#   mcp_execute_sql, mcp_fetch_result_page
#       — excluded. These return rows: a measurement, never structure.
#
#   mcp_prepare
#       — excluded, and not because it is measured: its own name and the
#         13-tool list give no way to tell whether it is idempotent or
#         mutates something (warms a cache, provisions a session, etc).
#         "If you cannot tell, do not cache it."
_CACHEABLE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "mcp_list_lenses",
        "mcp_resolve_lens",
        "mcp_describe_lens_tables",
        "mcp_describe_table",
        "mcp_search_tables",
        "mcp_lookup_canonical_value",
        "mcp_skill_list",
        "mcp_skill_read",
        "mcp_skill_grep",
        "mcp_lookup_few_shot",
    }
)
_REUSE_TEXT = "Reusing what I already looked up."

# `launch-readiness/105`: category phrases keyed by a keyword found in the
# tool's *name*, never the raw name or its id. This is deliberately name-based
# only — no argument value is ever interpolated. An argument can be a lens id
# or similarly internal value a user has never met, and there is no generic,
# domain-free way to tell that apart from a value the user actually typed
# (CLAUDE.md, "Never truncate a value into something misleading" / "a port
# name the user typed is fine; a lens id they have never met is not"). Rather
# than guess per-tool which argument is safe, the before-line ships without
# one — the half that works, per the ticket's own honesty clause.
_TOOL_NAME_PHRASES: tuple[tuple[str, str], ...] = (
    ("lookup", "Checking a value against the data."),
    ("canonical", "Checking a value against the data."),
    ("search", "Searching the data."),
    ("list", "Looking up what is available."),
    ("query", "Running a query."),
    ("sql", "Running a query."),
    ("count", "Counting records."),
    ("describe", "Checking the data's structure."),
    ("schema", "Checking the data's structure."),
    ("get", "Retrieving information."),
    ("fetch", "Retrieving information."),
    ("retrieve", "Retrieving information."),
)
_UNKNOWN_TOOL_TEXT = "Calling a tool."
_MAX_NARRATION_LEN = 80


class NarrationMiddleware(AgentMiddleware):
    """Fills the `"narration"` slot: a before/after line around every model call.

    Default **on** for every agent — the owner's scope decision was that a
    silent model-driving step is a defect regardless of node type, not a
    per-workflow opt-in. Silence is still possible and still declared: pass
    `quiet=True` (or contribute `None`/omit the slot on a node whose
    `narrate=False`) rather than deleting the middleware, so "nothing here
    narrates" stays a decision on record instead of code someone removed.
    """

    def __init__(
        self,
        *,
        quiet: bool = False,
        before_text: str = "Thinking about the next step.",
        after_text: str = "Finished thinking.",
    ) -> None:
        super().__init__()
        self._quiet = quiet
        self._before_text = before_text
        self._after_text = after_text
        # Per-thread only (`launch-readiness/105`): the durable cross-session
        # store is `launch-readiness/99` and is deliberately unbuilt. Keyed
        # `thread_id -> {(tool_name, exact_args_json): result}` — never by
        # question text, so two different questions that happen to share
        # words never collide (CLAUDE.md's own example: a port and a window
        # in common is not the same question).
        self._findings: dict[str, dict[tuple[str, str], Any]] = {}

    def before_model(self, state: AgentState[Any], runtime: Runtime[Any]) -> dict[str, Any] | None:
        if not self._quiet:
            report_progress(self._before_text)
        return None

    def after_model(self, state: AgentState[Any], runtime: Runtime[Any]) -> dict[str, Any] | None:
        if not self._quiet:
            report_progress(self._after_text)
        return None

    def wrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        """The `launch-readiness/105` half: a before-line derived from the
        call itself (emitted *before* `handler` runs, so it lands while the
        tool is still in flight, not once it is already done), and an
        after-line derived from the result's shape. Both go through the same
        `report_progress()` seam as `before_model`/`after_model` — one
        `"narration"` vocabulary, not two.

        Also the `launch-readiness/105` read-through cache: an allowlisted
        tool called twice in the same thread with the exact same arguments
        returns the stored result without invoking the tool again, and says
        so — a reuse the user cannot see is a reuse they cannot distrust.
        """
        cache_key = self._cache_key(request)
        thread_id = self._thread_id(request) if cache_key is not None else None
        if thread_id is not None:
            bucket = self._findings.get(thread_id)
            if bucket is not None and cache_key in bucket:
                if not self._quiet:
                    report_progress(_REUSE_TEXT)
                return bucket[cache_key]

        if not self._quiet:
            report_progress(self._before_tool_text(request))
        result = handler(request)
        if thread_id is not None:
            self._findings.setdefault(thread_id, {})[cache_key] = result
        if not self._quiet:
            text = self._after_tool_text(result)
            if text is not None:
                report_progress(text)
        return result

    @staticmethod
    def _cache_key(request: ToolCallRequest) -> tuple[str, str] | None:
        """`None` for anything not on the allowlist or whose arguments this
        cannot serialise exactly — never a fuzzy fallback key."""
        name = request.tool_call.get("name") or ""
        if name not in _CACHEABLE_TOOL_NAMES:
            return None
        args = request.tool_call.get("args") or {}
        try:
            args_key = json.dumps(args, sort_keys=True, default=str)
        except TypeError:
            return None
        return (name, args_key)

    @staticmethod
    def _thread_id(request: ToolCallRequest) -> str | None:
        """The per-thread scope, read from the same `config.configurable`
        LangGraph already threads through every run. `None` (never cached)
        outside a run or when no thread id was set, rather than guessing a
        shared bucket across unrelated callers."""
        try:
            config = request.runtime.config or {}
            thread_id = (config.get("configurable") or {}).get("thread_id")
        except Exception:  # noqa: BLE001 — a cache lookup must never fail a run
            return None
        return str(thread_id) if thread_id else None

    @staticmethod
    def _before_tool_text(request: ToolCallRequest) -> str:
        name = (request.tool_call.get("name") or "").lower()
        for keyword, phrase in _TOOL_NAME_PHRASES:
            if keyword in name:
                return phrase
        return _UNKNOWN_TOOL_TEXT

    @staticmethod
    def _after_tool_text(result: Any) -> str | None:
        """Derived from the result's *shape* only — never a model call, and
        never a guess. A shape this cannot honestly describe is omitted
        rather than mis-described (the ticket's own honesty clause)."""
        content = getattr(result, "content", None)
        if isinstance(content, list):
            n = len(content)
            if n == 0:
                return "No rows."
            return f"{n} result{'' if n == 1 else 's'}."
        if isinstance(content, str):
            if not content.strip():
                return "No rows."
            return None
        return None


def build_narration_middleware(*, quiet: bool = False) -> NarrationMiddleware:
    """The base's default filler for the `"narration"` slot.

    A plain function rather than a bare class reference, so `AbstractAgentNode`
    contributes the *capability* to compose (call this, or contribute
    something else under the same name) and never a hardcoded instance —
    "inherit the capability, not the composition."
    """
    return NarrationMiddleware(quiet=quiet)
