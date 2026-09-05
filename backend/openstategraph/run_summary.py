"""What this run actually did, in the four numbers a judge needs.

`osg-agent-experience/50`. Two judges stand between a model's prose and a
reader — `route.grader` and `guard.check` — and both of them were handed the
**text** and nothing else. On 2026-09-05 a lens ran three T-SQL statements,
every one answered *Login timeout expired*, and the grader passed the
paragraph explaining that it could not connect. It was a correct paragraph.
It was not a graded answer, and nothing said so.

**This module invents no state.** `tool_use` is already the run's own record,
already merged by a named reducer (`Reducer.MERGE_ROWS`), already written
through the single seam every tool-binding factory shares
(`compile/reporting.tool_report`). A second key carrying the same knowledge is
the duplication `CLAUDE.md` forbids by name. What was missing from the record
was two integers and the last thing a tool said; what was missing from the
judges was a reader for them.

So: a `RunSummary` is a **derived view**, built where it is needed and held
nowhere. That is also why the guard's function receives one rather than raw
state — `fn(text) -> str` is a narrow, serialisable seam on purpose, and a
package function with access to whole graph state would be a second place for
control flow to hide. Six fields, all of them facts about tool calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RunSummary:
    """The tools this run reached, and what came back.

    Frozen because it is a reading of the record, not a place to write one: a
    package function that could mutate it would be writing into a judgement
    the platform is about to make.
    """

    #: Every tool the run's nodes actually reached, in first-seen order.
    tools: tuple[str, ...] = ()
    #: How many calls reached a tool at all. A refused name and a delegation
    #: that reached nobody are not calls and are not counted.
    calls: int = 0
    #: How many of those came back with something.
    succeeded: int = 0
    #: How many came back with nothing — our own `Error: …`, or a body that
    #: raised.
    failed: int = 0
    #: The last failure's own words, bounded by `TOOL_ERROR_RECORD_CAP` where
    #: it was recorded. Empty when nothing failed.
    last_error: str = ""
    #: Which tool said it. Empty when nothing failed.
    last_error_tool: str = ""

    @property
    def every_call_failed(self) -> bool:
        """At least one call was made and not one of them returned anything.

        The conjunction is the safety. A run that called nothing is a writer
        agent doing exactly what it was drawn to do, and must never be
        accused — the same distinction `used_no_tools` draws, one field along.
        """
        return self.calls > 0 and self.succeeded == 0


def _rows(tool_use: Any, nodes: Any = ()) -> list[dict[str, Any]]:
    """The rows to read, narrowed to `nodes` when any of them are present.

    Same shape as `unbound_capability_claim`'s: named nodes if the caller knew
    which ones it meant, every row otherwise. A grader knows its own upstream;
    a guard's candidate is whatever reached it, so it reads the run.
    """
    table = tool_use if isinstance(tool_use, dict) else {}
    named = [str(n) for n in (nodes or []) if str(n) in table]
    chosen = named or list(table)
    return [table[key] for key in chosen if isinstance(table.get(key), dict)]


def summarise_run(tool_use: Any, nodes: Any = ()) -> RunSummary:
    """Add the run's rows up.

    Tolerant in reading: a row written by an older checkpoint carries none of
    these fields, and reads as a run that made no calls rather than as an
    error. Strict in trusting: nothing is inferred from `ran` alone, because
    `ran` is a set of names and says nothing about how a call went.
    """
    tools: list[str] = []
    calls = failed = 0
    last_error = last_error_tool = ""
    for row in _rows(tool_use, nodes):
        for name in row.get("ran") or []:
            if str(name) not in tools:
                tools.append(str(name))
        calls += int(row.get("calls") or 0)
        failed += int(row.get("failed") or 0)
        if row.get("last_error"):
            last_error = str(row["last_error"])
            last_error_tool = str(row.get("last_error_tool") or "")
    return RunSummary(
        tools=tuple(tools),
        calls=calls,
        succeeded=max(calls - failed, 0),
        failed=failed,
        last_error=last_error,
        last_error_tool=last_error_tool,
    )


def every_tool_call_failed(tool_use: Any, nodes: Any = ()) -> str | None:
    """"Nothing this answer could rest on ever arrived" — or None.

    A deterministic fact, read off the run's own record with no model call and
    no string matching against *"I could not connect"*: nothing upstream is
    asked to self-report a failure it has every incentive to describe
    gracefully. The sixth such fact on this project and the same argument as
    the first five.

    **It does not touch the refusal clause, and the distinction is the whole
    of it.** `BaseGrader.PROMPT` says an honest decline is a PASS, and that
    clause was added on evidence — a grader rejected a correct refusal and the
    retries destroyed the only good answer in the run. It still holds *when
    the workflow is whole*. This is the fact that says it was not: a timeout
    is not a missing capability, and the next lap may well reach the
    warehouse. That is why this returns a `revise` reason rather than forcing
    a pass the way `unbound_capability_claim` does, where retrying genuinely
    cannot help.

    Two conjuncts, and the narrowness is the safety:

    1. **The considered nodes made calls and not one returned anything.** A
       node that called nothing is never accused.
    2. **No node anywhere in the run had a call come back.** Same shape as
       `unrun_query_claim`'s "any query anywhere clears the run": a document
       whose other agent did the reading is not a run without evidence.
    """
    whole = summarise_run(tool_use)
    if whole.succeeded:
        return None
    summary = summarise_run(tool_use, nodes)
    if not summary.every_call_failed:
        return None
    tool = summary.last_error_tool or (summary.tools[0] if summary.tools else "a tool")
    made = f"{summary.calls} tool {'call' if summary.calls == 1 else 'calls'}"
    return (
        f"This run made {made} and every one of them failed. The last was "
        f'"{tool}": {summary.last_error or "no message"}. Nothing here rests '
        "on a result, because no result arrived — say so, and say which tool "
        "and what it reported."
    )


def evidence_for_grader(summary: RunSummary) -> str:
    """The evidence block a judgement is shown, or "" when there is none.

    **Silent when nothing failed**, which is this repository's default and not
    an economy: a grader shown *"3 calls, 3 succeeded"* on every ordinary run
    is being invited to reason about a fact that changes nothing, and the
    prompt every existing grader composes would change for no reader.

    It rides in the generated **Context** layer, before the candidate and
    never inside it, so what the workflow publishes is untouched.
    """
    if not summary.failed:
        return ""
    ran = ", ".join(summary.tools) or "no tool"
    line = (
        f"This run's own record of its tool calls: {summary.calls} made, "
        f"{summary.succeeded} returned a result, {summary.failed} failed "
        f"({ran})."
    )
    if summary.last_error:
        line += (
            f' The last failure was "{summary.last_error_tool}", which '
            f"reported: {summary.last_error}"
        )
    return line + (
        " This is the run's record, not the candidate's account of itself; "
        "judge the candidate against it."
    )


__all__ = [
    "RunSummary",
    "evidence_for_grader",
    "every_tool_call_failed",
    "summarise_run",
]
