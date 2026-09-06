"""The reducers a state key may declare, **by name**.

CLAUDE.md's portability guardrails list four rules that "cost nothing now and
are expensive to retrofit". This is the second of them:

> **Reducers are a named enum**, not arbitrary functions.

It was the one that was broken. `merge_decisions`, `keep_max` and
`keep_latest_nonempty` were plain functions bound straight into
`Annotated[...]`, with no enum, registry or name→function map anywhere on
either side — and `merge_decisions`' own docstring claimed to be "the `merge`
member" of an enum that did not exist (reviews-2026-08-14 ticket 07).

**Why a name rather than a function.** `workflow.json` is the vendor-neutral
layer, and it is the only thing standing between this project and being a
LangGraph front end. A reducer written as a Python function is unserialisable
and unportable in one move: a second runtime cannot read it, and neither can
anything that inspects a stored workflow. A name is data — it round-trips, it
can be validated, and it can be implemented again elsewhere.

Nothing stored references a reducer *yet*, which is exactly why this is cheap
today. Every workflow saved before the enum exists would have to be migrated
after.

Adding a member is a contract change: the name becomes something a stored
document may contain, and a second runtime must implement. That is the point
of the ceiling being small.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable

#: The marker a turn reset carries. A reducer that sees it clears rather than
#: merges, so a new turn does not inherit the last one's decisions.
RESET = "__turn_reset__"


def merge_decisions(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Merge two maps, honouring a turn reset.

    A named merge rather than last-write-wins, because two nodes can decide in
    the same superstep during a fan-out and one silently clobbering the other
    would be invisible.
    """
    if RESET in right:
        return {k: v for k, v in right.items() if k != RESET}
    return {**left, **right}


def merge_rows(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Merge two maps like `merge_decisions`, but a key on both sides gets its
    **row** merged rather than replaced.

    Right for `tool_use` (`production-ready` 106) and wrong for `decisions`:
    a node re-invoked by a grader's revise loop writes a fresh row each lap,
    and `merge_decisions`' `{**left, **right}` drops the whole earlier row —
    the key is the node id, so the newer lap's `{"bound": [...], "ran": []}`
    silently erased the earlier lap's record of a tool that genuinely ran.
    `decisions` wants exactly that overwrite (a node's newest decision is the
    one that counts); this is for state that instead records what happened,
    and what happened does not un-happen.

    A row's list-valued members are unioned in first-seen order. A member
    absent from **both** rows stays absent rather than becoming `[]` — the
    row shape `tool_report` writes leaves `queried` out entirely when nothing
    was ever sent, and a present-but-empty list is a different claim
    ("checked, found nothing"). Since the union of "absent" with "absent" is
    still nothing to add, that absence survives here with no special case.
    """
    if RESET in right:
        return {k: v for k, v in right.items() if k != RESET}
    result: dict[str, Any] = dict(left)
    for key, new_row in right.items():
        old_row = result.get(key)
        if not isinstance(old_row, dict) or not isinstance(new_row, dict):
            result[key] = new_row
            continue
        merged_row = dict(old_row)
        for field, new_value in new_row.items():
            old_value = old_row.get(field)
            if isinstance(old_value, list) and isinstance(new_value, list):
                merged = list(old_value)
                for item in new_value:
                    if item not in merged:
                        merged.append(item)
                merged_row[field] = merged
            else:
                merged_row[field] = new_value
        result[key] = merged_row
    return result


def keep_max(left: int, right: int) -> int:
    """The larger of two counters, with a negative write meaning reset.

    `attempts` has more than one legitimate writer: an agent's revise budget
    and an orchestrator's replan budget can both be live in one graph, and two
    landing in the same superstep is `InvalidUpdateError` for a bare scalar.
    `max` matches the field's meaning — a budget counter only grows, so the
    higher of two concurrent writes is right whichever node produced it.

    **A negative write zeroes it**, which is the numeric spelling of `RESET`:
    this channel stays `int` end to end, because a string marker here broke
    every consumer that casts. Without the reset a thread's second run
    inherits the first run's count and graders burn their budget before ever
    retrying.
    """
    if right < 0:
        return 0
    return max(left, right)


def keep_latest_nonempty(left: str, right: str) -> str:
    """The newer value unless it is empty, and cleared by a turn reset.

    A node that writes `""` on the steps where it has nothing to say must not
    erase what another node said in the same superstep.
    """
    if right == RESET:
        return ""
    return right if right else left


class Reducer(str, Enum):
    """The permitted reducers, as names a document could carry.

    `str`-valued so a member serialises as itself: `Reducer.MERGE` is
    `"merge"` in JSON with no encoder, which is what makes this a *data*
    contract rather than a Python one.
    """

    #: Two maps combined; a turn reset clears rather than merges.
    MERGE = "merge"
    #: Two maps combined like MERGE, but a key present on both sides has its
    #: *row* merged (list-valued members unioned) rather than replaced. For
    #: state that records what happened rather than what was last decided.
    MERGE_ROWS = "merge_rows"
    #: The larger of two numbers.
    MAX = "max"
    #: The newer value unless it is empty; a turn reset clears.
    LATEST_NONEMPTY = "latest_nonempty"
    #: LangGraph's own message accumulator. Named here so the set is complete —
    #: a second runtime has to implement something equivalent, and pretending
    #: this key is not reduced would hide that.
    ADD_MESSAGES = "add_messages"


def reducer_for(name: Reducer) -> Callable[..., Any]:
    """The implementation behind a name.

    The single place a name becomes behaviour, so a stored document never has
    to name a function and nothing downstream has to guess.
    """
    from langgraph.graph.message import add_messages

    implementations: dict[Reducer, Callable[..., Any]] = {
        Reducer.MERGE: merge_decisions,
        Reducer.MERGE_ROWS: merge_rows,
        Reducer.MAX: keep_max,
        Reducer.LATEST_NONEMPTY: keep_latest_nonempty,
        Reducer.ADD_MESSAGES: add_messages,
    }
    return implementations[name]
