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
class Retrieved:
    """One statement this run sent, and what came back from it.

    `osg-agent-experience/86`. The **same five fields** the run record
    publishes, read by the same function
    (`executed_statements.statements_executed`) — so how a query exchange is
    read off `tool_use`, and what a credential looks like, each keep the one
    owner they already had. A second reader of `tool_use[node]["queries"]`
    would be the duplication this module's own docstring refuses one paragraph
    up.
    """

    #: The graph node whose loop made the call. A mounted child's node arrives
    #: here as `<mount>/<child node>`, which is how the record spells it.
    node: str = ""
    #: The tool that answered.
    tool: str = ""
    #: The statement, credentials scrubbed. Never truncated — it is the
    #: evidence.
    statement: str = ""
    #: What came back, capped where it was recorded
    #: (`reporting.QUERY_RESULT_RECORD_CAP`) and credentials scrubbed.
    result: str = ""
    #: Whether that cap took anything. Present on every row, never only on the
    #: cut ones: a result that ended and a result the cap took read the same
    #: otherwise, and a check that compares against a head it believes is whole
    #: is worse than no check.
    truncated: bool = False


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
    #: Every statement this run sent and what came back, in record order
    #: (`osg-agent-experience/86`). The four counters above answer *did any
    #: evidence arrive*; this answers *is this figure a figure the run
    #: retrieved*, which is the one class of defect a machine can settle with
    #: no model and no cost — a misspelt category and a zero from a window the
    #: warehouse holds rows for are both string containment against these, and
    #: neither is answerable against the candidate's prose.
    #:
    #: Empty for a node that called a tool which sends no statements: only a
    #: recognised query exchange is recorded, which is `queries`' own rule.
    retrieved: tuple[Retrieved, ...] = ()

    @property
    def every_call_failed(self) -> bool:
        """At least one call was made and not one of them returned anything.

        The conjunction is the safety. A run that called nothing is a writer
        agent doing exactly what it was drawn to do, and must never be
        accused — the same distinction `used_no_tools` draws, one field along.
        """
        return self.calls > 0 and self.succeeded == 0

    @property
    def any_truncated(self) -> bool:
        """Whether the record cap took any part of any result.

        A check reading `retrieved` is reading a **head** when this is true,
        so absence of a value proves nothing about the row it was cut from.
        Stated as a field rather than left to be rediscovered as a bug, the
        way `QUERY_RESULT_RECORD_CAP` states it where the cut is made.
        """
        return any(row.truncated for row in self.retrieved)

    def contains(self, value: str) -> bool:
        """Whether any result this run retrieved carries `value`.

        Containment, not equality, because a result is a table and a value is
        one cell of it. Two normalisations and no more, each because a model
        writing prose from rows applies exactly it:

        - **case**, so `NAPHTHA` in a heading matches `Naphtha` in a cell;
        - **thousands separators**, so `1,454,449` matches `1454449` — the
          separator is the model's own, added on the way into a sentence.

        Whitespace is left alone: collapsing it would let a needle match
        across two cells, and a check that reports a value as retrieved when
        it never was is worse than one that reports nothing.

        An empty or blank `value` is False rather than True. Containment of
        nothing is trivially satisfiable, and a check that silently passes
        every candidate is the failure mode this module exists to end.
        """
        needle = _comparable(value)
        if not needle:
            return False
        return any(needle in _comparable(row.result) for row in self.retrieved)


def _comparable(text: str) -> str:
    """`text` as `RunSummary.contains` compares it — casefolded, unseparated.

    One function so the needle and the haystack are normalised identically.
    Two normalisations exactly, argued at the method that calls it.
    """
    return str(text or "").replace(",", "").strip().casefold()


def _named_rows(tool_use: Any, nodes: Any = ()) -> dict[str, dict[str, Any]]:
    """The rows to read, narrowed to `nodes` when any of them are present.

    Same shape as `unbound_capability_claim`'s: named nodes if the caller knew
    which ones it meant, every row otherwise. A grader knows its own upstream;
    a guard's candidate is whatever reached it, so it reads the run.

    Keyed rather than listed (`osg-agent-experience/86`): a retrieved row names
    the node that fetched it, and `statements_executed` reads a table.
    """
    table = tool_use if isinstance(tool_use, dict) else {}
    named = [str(n) for n in (nodes or []) if str(n) in table]
    chosen = named or list(table)
    return {key: table[key] for key in chosen if isinstance(table.get(key), dict)}


def summarise_run(tool_use: Any, nodes: Any = ()) -> RunSummary:
    """Add the run's rows up.

    Tolerant in reading: a row written by an older checkpoint carries none of
    these fields, and reads as a run that made no calls rather than as an
    error. Strict in trusting: nothing is inferred from `ran` alone, because
    `ran` is a set of names and says nothing about how a call went.
    """
    from openstategraph.executed_statements import statements_executed

    rows = _named_rows(tool_use, nodes)
    tools: list[str] = []
    calls = failed = 0
    last_error = last_error_tool = ""
    for row in rows.values():
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
        retrieved=tuple(
            Retrieved(
                node=str(entry.get("node") or ""),
                tool=str(entry.get("tool") or ""),
                statement=str(entry.get("statement") or ""),
                result=str(entry.get("result") or ""),
                truncated=bool(entry.get("truncated")),
            )
            for entry in statements_executed(rows)
        ),
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
    "Retrieved",
    "RunSummary",
    "evidence_for_grader",
    "every_tool_call_failed",
    "summarise_run",
]
