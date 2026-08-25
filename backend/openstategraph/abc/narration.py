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

from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState, ToolCallRequest
from langgraph.runtime import Runtime

from openstategraph.progress import report_progress

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
        `"narration"` vocabulary, not two."""
        if not self._quiet:
            report_progress(self._before_tool_text(request))
        result = handler(request)
        if not self._quiet:
            text = self._after_tool_text(result)
            if text is not None:
                report_progress(text)
        return result

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
