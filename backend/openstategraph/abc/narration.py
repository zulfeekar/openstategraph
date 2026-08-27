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

**Content stays generic on purpose *in this class*.** It has no domain
knowledge — it wraps `before_model`/`after_model` for *any* agent, so it never
has a tool id, a lens name, or a token count to report honestly. CLAUDE.md's
instruction is "free of internals" and "a wall of debug text is a worse answer
than silence" — a generic line is the honest one to author here.

**The sharper line is a contribution into this slot, and it now exists**
(`launch-readiness/112`). `abc/tool_sentences.py` holds a pure
`(name, args) -> sentence` table over this project's own tool surface, and
`build_narration_middleware` injects it as `describe=`. So the class still
knows no tool names — the table is passed in, not imported by the class — and
the keyword phrases below stay exactly what they always were: the floor a tool
nobody has authored a sentence for still gets. Until 2026-08-27 this paragraph
ended "a node type that wants a sharper line contributes its own middleware",
and nobody ever had, which is what the ticket was filed about.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState, ToolCallRequest
from langgraph.runtime import Runtime

from openstategraph.abc.tool_sentences import describe_tool_call
from openstategraph.progress import report_progress
from openstategraph.run_identity import run_identity

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

#: "nothing on record", distinct from a tool that legitimately returned `None`.
_MISS = object()
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
        describe: Callable[[str, dict[str, Any]], str | None] | None = None,
    ) -> None:
        super().__init__()
        self._quiet = quiet
        self._before_text = before_text
        self._after_text = after_text
        # `launch-readiness/112`: what this call *is doing*, when somebody
        # knows. Injected rather than imported here, so this class keeps the
        # property its own header claims — no domain knowledge — and a
        # workflow contributing its own sentences into the `"narration"` slot
        # replaces a table rather than subclassing a middleware. `None` is
        # the keyword floor below and nothing else.
        self._describe = describe
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

    # --- the async twins (`async-first/06`) ---------------------------------
    #
    # Phase D makes `_agent`'s node body `async def`, so the agent it builds is
    # reached through `ainvoke`, and LangChain's guidance for that path is
    # explicit: "custom middleware must use async hooks. Synchronous hooks
    # remain supported with Deep Agents `invoke` and `stream`."
    #
    # The two halves fail differently, and the quiet one is the dangerous one.
    # `awrap_tool_call` has no usable default and raises `NotImplementedError`
    # naming the sync method — loud, and it killed a run. `abefore_model` and
    # `aafter_model` default to **no-ops**, so a narration middleware without
    # them would simply have gone silent on an async agent: a blank panel,
    # nothing in the logs, both suites green — `launch-readiness/110` exactly,
    # which is why they are here and pinned rather than left to the default.
    #
    # What is *not* duplicated is the deciding. Every hook below is the same
    # body as its sync twin with the `await` in it; the cache lookup, the
    # store write and the choice of line live in `_reuse`, `_remember` and
    # `_narrate_after_tool`, so the two paths cannot drift into disagreeing
    # about what this thread already knows.

    async def abefore_model(
        self, state: AgentState[Any], runtime: Runtime[Any]
    ) -> dict[str, Any] | None:
        return self.before_model(state, runtime)

    async def aafter_model(
        self, state: AgentState[Any], runtime: Runtime[Any]
    ) -> dict[str, Any] | None:
        return self.after_model(state, runtime)

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
        cache_key, thread_id, hit = self._reuse(request)
        if hit is not _MISS:
            return hit
        result = handler(request)
        return self._remember(result, cache_key, thread_id)

    async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        """`wrap_tool_call` with the one `await` that path needs.

        The cache is the *same* store, deliberately: a reuse that depended on
        which door the run came through would make `findings_inventory` — which
        a retry's own prompt is built from (`launch-readiness/106`) — an
        accident of transport.
        """
        cache_key, thread_id, hit = self._reuse(request)
        if hit is not _MISS:
            return hit
        result = await handler(request)
        return self._remember(result, cache_key, thread_id)

    def _reuse(self, request: ToolCallRequest) -> tuple[tuple[str, str] | None, str | None, Any]:
        """What this thread already knows about this exact call, if anything.

        Returns the cache key, the thread it belongs to, and either the stored
        result or `_MISS`. Emits the before-line on a miss, which is why this
        is one method rather than a lookup: the line must be out on the wire
        *before* the handler runs, and the two callers must not each remember
        to do that.
        """
        cache_key = self._cache_key(request)
        thread_id = self._thread_id(request) if cache_key is not None else None
        if thread_id is not None:
            bucket = self._findings.get(thread_id)
            if bucket is not None and cache_key in bucket:
                if not self._quiet:
                    report_progress(_REUSE_TEXT)
                return cache_key, thread_id, bucket[cache_key]
        if not self._quiet:
            report_progress(self._before_tool_text(request))
        return cache_key, thread_id, _MISS

    def _remember(
        self, result: Any, cache_key: tuple[str, str] | None, thread_id: str | None
    ) -> Any:
        """Store the result where a later call can find it, and say what came back."""
        if thread_id is not None:
            # `thread_id` is only ever set when `cache_key` is not `None` —
            # this assert is for mypy's narrowing, not a new runtime
            # possibility.
            assert cache_key is not None
            self._findings.setdefault(thread_id, {})[cache_key] = result
        if not self._quiet:
            text = self._after_tool_text(result)
            if text is not None:
                report_progress(text)
        return result

    def findings_inventory(self, thread_id: str) -> list[str]:
        """`launch-readiness/106`: what this thread already knows, named —
        never re-derived, and never re-classified.

        One line per finding on record, `tool(args)` — the call that was
        made, never the result it returned. That silence is the point: a
        result can be a schema (safe to trust again) or a row count (stale
        the instant a new attempt asks), and this store was never asked to
        tell those apart on the way *out* — `_cache_key` already told them
        apart on the way *in*. Only an allowlisted, STRUCTURE-returning tool
        is ever written to `self._findings` (`launch-readiness/105`'s
        allowlist, reused rather than re-derived); a measurement is never
        cached at all, so there is nothing measurement-shaped in here to
        exclude. Reusing that allowlist is the whole answer to "how are
        measurements excluded" — there is no second gate.

        `[]` when the thread has nothing on record (a first attempt, or an
        empty store) — the caller's cue to add no inventory at all.
        """
        bucket = self._findings.get(thread_id)
        if not bucket:
            return []
        return [
            f"{name}({args_key})" if args_key not in ("{}", "") else name
            for name, args_key in sorted(bucket)
        ]

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
        """The per-thread scope, read through the one accessor
        (`openstategraph.run_identity.run_identity`) rather than hand-rolled
        here — a second `configurable.get("thread_id")` is exactly the drift
        `run_identity` exists to make impossible. `None` (never cached)
        outside a run or when no thread id was set, rather than guessing a
        shared bucket across unrelated callers."""
        try:
            config = request.runtime.config or {}
        except Exception:  # noqa: BLE001 — a cache lookup must never fail a run
            return None
        thread_id = run_identity(config).get("thread_id", "")
        return thread_id or None

    def _before_tool_text(self, request: ToolCallRequest) -> str:
        """The sharpest honest line available for this call.

        Three tiers, narrowest first (`launch-readiness/112`): a sentence
        authored for *this* tool, then the keyword phrase derived from its
        name, then the generic line. The floor never went away — it is what a
        tool nobody has authored a sentence for still says — and no tier ever
        names the tool.
        """
        raw_name = request.tool_call.get("name") or ""
        if self._describe is not None:
            try:
                sentence = self._describe(raw_name, request.tool_call.get("args") or {})
            except Exception:  # noqa: BLE001 — narration must never fail a run
                sentence = None
            if sentence:
                return sentence
        name = raw_name.lower()
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

    This is also the one place `launch-readiness/112`'s sentence table is
    wired in, and there is exactly one of these functions, so every agent gets
    the sharper line without any node type opting in. The table is a
    *contribution into the slot* rather than a change to the middleware: the
    class above still knows no tool names, and passing `describe=` something
    else is how a workflow overrides it.
    """
    return NarrationMiddleware(quiet=quiet, describe=describe_tool_call)
