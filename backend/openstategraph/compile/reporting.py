"""What a node writes down about what it did — the run's own record.

Carved out of `compile/node_runtime.py` (`docs-and-gaps/03`, step 3 of the
recommended order), unchanged. Its one reason to change is **the shape of the
record a step leaves behind**, which is a different reason from "what the step
does", and the two had been sharing a module only because the families that
build the steps are the callers.

Three things and the caps that bound them:

- `tool_report` — the `tool_use` row, which is what every grounding gate
  afterwards reads instead of re-reading the transcript.
- `_final_text` — the last thing a model actually said, read through
  `messages.content_text` and never by stringifying a block list. That is why
  `test_message_content_is_read_the_same_way.py` names this module: the census
  moved with the code, rather than going on naming the file the code left.
  (Its scan reads prose too, and caught the first draft of this very
  paragraph quoting the bug by name — which is the census being
  non-vacuous rather than a reason to weaken it.)
- `_values_never_sent` — which substituted value a step never put on the wire.

The caps are here rather than beside the gates that consume them because it is
this module that decides how much of an answer the record keeps, and a cap
declared away from the write it bounds is a cap nobody sees when they widen the
write.
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.state import RunState
from openstategraph.messages import content_text
from openstategraph.table_coverage import declarations_in_result
from openstategraph.compile.workflow_compiler import values_no_statement_carried


#: How much of a query's answer the run's record keeps (`launch-readiness` 165).
#:
#: State is checkpointed, so an uncapped copy of every result row would grow
#: the run's own record without bound for the sake of a gate that needs a
#: number. A scalar aggregate — the shape this exists for — is a few dozen
#: characters, so the cap is never reached by the case it was written for.
#:
#: Stated so nobody rediscovers it as a bug: a gate reading this sees the
#: **head** of a large result. That is a real hole for a check that must see
#: every row, and none for one about a `COUNT(*)`, whose whole answer is one
#: cell.
QUERY_RESULT_RECORD_CAP = 2000

#: How many table declarations one node's row may carry. A lens's bulk schema
#: dump is a handful of tables; past this a payload is not declaring, it is
#: enumerating, and the state key is not the place for it.
DECLARATION_RECORD_CAP = 32


def _final_text(messages: list[Any]) -> str:
    """What the model said this turn — or "", never something else.

    An agent loop can legitimately end on a message with empty content — a
    dangling tool call the loop cut off, or a provider blip mid-stream — and
    `out[-1].content` then records "" as the worker's entire answer (observed
    live under concurrent fan-out, ticket 61). Walking back keeps whatever the
    agent actually said.

    **Two rules, and the walk-back is only the first.** The second exists
    because the first, alone, produced the worst bug this project has had
    (the-editor-makes-a-real-package ticket 03): `POST /api/runs` answered
    `49` while `POST /api/runs/stream` answered *the question*, on the same
    workflow, seconds apart — and both shipped UIs use the streaming endpoint,
    so every run a person could see was wrong while every run a test made was
    right.

    1. **Read the text, whatever shape it arrives in.** LangChain's `content`
       is documented as "loosely-typed, supporting strings and lists of
       untyped objects", and an Anthropic `AIMessage` in particular "can
       either be a single string or a list of content blocks". Adding
       `"messages"` to `stream_mode` is enough to switch a settled message
       from `"30"` to `[{"text": "30", "type": "text", "index": 0}]`. The old
       `isinstance(content, str)` test read that as *no text at all*, so the
       guard meant to skip empty messages skipped a full one.
       `openstategraph.messages.content_text` reads both shapes and joins
       only the `text` blocks — so a thinking model's private reasoning,
       which rides in the same list, stays out of the answer. It is the one
       reader in this codebase, and its module docstring is the account of
       why: until docs-and-gaps 14 this module carried a byte-identical
       private copy of it.

    2. **Never walk past the last human turn.** This is the floor, and it is
       about what a failure is *allowed to look like*. With rule 1 broken the
       walk continued past the AI message and returned the `HumanMessage` —
       the user's own question, handed back as the answer. That is the one
       wrong answer nothing downstream can catch: a grader reads it as a
       reply, a customer reads it as a reply, and the run reports success. An
       empty answer is visibly a failure; an echo is a lie. Rule 1 is fixed,
       and rule 2 means the next thing that breaks upstream degrades loudly
       instead.
    """
    for message in reversed(messages):
        # The floor. Anything at or before the current turn's question belongs
        # to the *conversation*, not to this turn's answer.
        if getattr(message, "type", None) in ("human", "system"):
            return ""
        # A message that *requests* tool calls is never the final answer —
        # its content is preamble or echoed arguments. Observed live: a
        # degraded loop ended on a dangling call and the "answer" rendered
        # as {"path": ...} in the customer chat.
        if getattr(message, "tool_calls", None):
            continue
        # And a message that *carries a tool's result* is never the answer
        # either — the third member of the same family, and the one that got
        # through (`every-workflow-green` 32). A loop ending on a tool result
        # published it verbatim: "Error: web_fetch is not a valid tool, try one
        # of [...]" was shown to the user as the answer to their question.
        #
        # A tool result is **evidence for the model, not prose for a person**,
        # and that holds whether it succeeded or failed: a page of search hits
        # is no more an answer than an error is.
        #
        # When nothing the model said remains, "" is correct. That is a silent
        # node and `silent_node_warnings` has a sentence for it (ticket 01).
        # Publishing the nearest string instead is how a completely broken run
        # looked completely healthy — no node failed, the output was non-empty,
        # and every health channel on this map saw nothing wrong.
        if getattr(message, "type", None) == "tool":
            continue
        text = content_text(getattr(message, "content", ""))
        if text.strip():
            return text
    return ""


def _values_never_sent(state: RunState, notes: Any) -> frozenset[str]:
    """The canonical values in `notes` that no statement of this run carried.

    `launch-readiness/155`, and it is one line in two places on purpose: the
    grader is told what the reader will be handed (`154`), so the two must
    reach the same measurement or the judge is shown a paragraph nobody gets.
    """
    from openstategraph.abc.tool_notes import Substitution

    return values_no_statement_carried(
        state, [n.canonical_value for n in notes if isinstance(n, Substitution)]
    )


def tool_report(
    node_id: str,
    messages: list[Any],
    bound: list[str],
    unbound: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """What this node was given, what it used, and what it was refused.

    The seam every tool-binding factory shares. Ticket 33 built the
    deterministic route — read the name out of **our own** refusal, look it up,
    offer the tool — and wired it into `_agent` by hand. `_worker` binds tools
    the same way and got nothing, so `morning-brief` asked for `web_fetch`, was
    refused by name, and no card appeared for a tool we ship
    (`every-workflow-green` 36). The worker's own docstring already records
    this failure once, about `advisor_context`: composed into one factory and
    not the other.

    Read from the **messages**, never from the answer: the refusal is a
    `ToolMessage` in the middle and the answer that follows it usually says
    nothing about it, which is exactly what proved unreliable in 33.

    **`ran` names the tools this node's loop actually reached — a real tool
    that was invoked and returned, whether it answered or errored — and never a
    name the runtime refused because no such tool exists.** Both halves are
    load-bearing and both have been wrong once. An error is data and the tool
    is wired (`the-agent-asks-for-what-it-cannot-get` 01), so it counts; an
    invented `execute_sql?` reached nothing at all, so it does not
    (`production-ready` 98). The filter is the refusal, never membership of
    `bound` — `bound` is *canvas-wired only*, so filtering by it would drop a
    memory or knowledge tool the agent genuinely used, and a deep agent's
    preset tools with it.

    **A delegation is recorded as the worker, not as the harness's tool**
    (`launch-readiness` 178, `openstategraph/delegations.py`). Every deep-agent
    delegation returns under `deepagents`' single `task` tool, so `ran` carried
    that one entry however many workers ran and whichever ones they were: a run
    that used both declared workers and a run that used the anonymous built-in
    left the identical record. It reads `delegate:data-classifier` now, which is
    our own vocabulary (guardrail 4) and matters beyond tidiness, because
    `silent_node_warnings` prints `ran` back to a reader verbatim. A delegation
    the harness refused — an undeclared worker's name, answered with a sentence
    and no run — records nothing at all, exactly as an invented tool name does.

    Returns no `unmet_tools` key rather than an empty map when nothing was
    refused, so a clean run writes nothing there — a node that reports `[]` and
    a node that reports nothing must not look the same to the reducer.

    **`tool_use` is written on every run, including the empty one**, and that
    asymmetry is the point (`every-workflow-green` 35). The verdict this feeds
    has to tell a workflow whose agent had tools and used none from a workflow
    that has no tools at all — the first is offered a door and the second must
    never be, or the card appears on every turn of a writer workflow and
    becomes something people learn to skip. Absent and empty therefore mean
    different things here and both have to be sayable.

    One function rather than two calls per site, because the cost of two is on
    the record: `advisor_context` was composed into `_agent` and not `_worker`,
    so a worker refused a tool we ship and no card appeared (36). A factory
    that binds tools now says all three things or none.
    """
    from openstategraph.compile.workflow_compiler import (
        arguments_were_rejected,
        looks_like_sql_query,
        rejected_tool_names,
    )
    from openstategraph.delegations import DELEGATION_TOOL, delegations_by_call

    #: `tool_call_id -> our own name for the worker that answered`
    #: (`launch-readiness/178`). A deep agent's delegations all come back
    #: under `deepagents`' one tool name, so without this the record says
    #: `task` once however many workers ran and whichever they were — and a
    #: vendor's spelling reaches `ran`, which `silent_node_warnings` prints
    #: to a reader. Resolved from the delegating call's own arguments, paired
    #: to the answer by id, and only for the calls an answer bears out.
    delegations = delegations_by_call(messages or [])

    #: Calls whose **arguments** a real tool refused, by `tool_call_id`
    #: (`production-ready` 100). Gathered in a pass of its own because the
    #: answer arrives *after* the call that has to be judged by it, and
    #: keyed by id rather than by tool name because the rejection is per
    #: call: the model's next lap usually fixes the argument name, and that
    #: query really was sent.
    unaccepted: set[str] = set()
    for message in messages or []:
        if getattr(message, "type", None) != "tool":
            continue
        if getattr(message, "status", None) != "error":
            continue
        if not arguments_were_rejected(
            getattr(message, "content", None), getattr(message, "name", None)
        ):
            continue
        call_id = str(getattr(message, "tool_call_id", "") or "")
        if call_id:
            unaccepted.add(call_id)

    refused: list[str] = []
    ran: list[str] = []
    #: Tools a **query** was actually handed to, read off the call arguments
    #: rather than the tool's name (`production-ready` 95). A name pattern —
    #: `execute_sql`, `query`, `run_*` — is a guess about how somebody spelled
    #: their tool; the argument is the query itself, so this says what happened
    #: for a tool called `warehouse` exactly as well as for `chinook_execute_sql`.
    #:
    #: **`queried` names the tools a query was actually handed to *and whose
    #: body ran with it*.** Both halves are load-bearing. The call arguments
    #: alone are only a claim that a query was written, and two shapes have
    #: already made that claim falsely: a name the runtime refused because no
    #: such tool exists (`production-ready` 98, filtered by `ran` below), and a
    #: real bound tool whose **arguments** failed their schema, so Pydantic
    #: rejected the call before the body opened anything (`production-ready`
    #: 100, filtered by `unaccepted` above). Any `queried` anywhere clears 95's
    #: check for the **whole run**, so either one is a silent miss.
    #:
    #: A tool that ran a query and *then* errored still counts — "errored" and
    #: "never executed" are different things, and that query did leave the
    #: building.
    queried: list[str] = []
    #: `call id -> the query text`, so the answer can be attached to the
    #: question when it arrives (`launch-readiness` 165). This scan already
    #: had the query in its hand and threw it away, which is why every gate
    #: downstream of an agent was blind: `_agent` returns `outputs`, `answer`
    #: and this row, and **no messages at all**, so a `guard.check` reading
    #: `state["messages"]` sees nothing an agent retrieved.
    asked: dict[str, str] = {}
    queries: list[dict[str, str]] = []
    #: Table declarations this node's loop was shown (`launch-readiness/166`).
    declares: list[dict[str, Any]] = []
    for message in messages or []:
        for call in getattr(message, "tool_calls", None) or []:
            args = call.get("args") if isinstance(call, dict) else None
            if not isinstance(args, dict):
                continue
            sql = next((str(v) for v in args.values() if looks_like_sql_query(v)), "")
            if not sql:
                continue
            if str(call.get("id") or "") in unaccepted:
                continue
            call_id = str(call.get("id") or "")
            if call_id:
                asked[call_id] = sql
            name = str((call.get("name") if isinstance(call, dict) else "") or "")
            if name and name not in queried:
                queried.append(name)
        if getattr(message, "type", None) == "tool" and getattr(message, "status", None) != "error":
            sql = asked.get(str(getattr(message, "tool_call_id", "") or ""), "")
            if sql:
                answer = str(getattr(message, "content", ""))
                exchange: dict[str, Any] = {
                    "sql": sql,
                    # Which tool answered. A gate asks "was this statement
                    # answered"; a person asks "what did this tool actually
                    # do" (`one-chinook-honest/30`), and an exchange with no
                    # tool on it cannot answer the second.
                    "tool": str(getattr(message, "name", "") or ""),
                    "result": answer[:QUERY_RESULT_RECORD_CAP],
                }
                # A result that ended and a result the cap took render
                # identically otherwise — this map's own failure shape, one
                # field along. Only the **answer** is capped: the statement is
                # the evidence and is never cut.
                if len(answer) > QUERY_RESULT_RECORD_CAP:
                    exchange["truncated"] = True
                if exchange not in queries:
                    queries.append(exchange)
            # And the other thing a tool answer can carry that outlives it: a
            # table's own declaration of what one of its rows is and which
            # period it holds (`launch-readiness/166`). Same argument as
            # `queries` one line up — an agent's loop is where this arrives and
            # `_agent` returns no messages, so a gate downstream of it would
            # never see the declaration that makes it able to say anything.
            #
            # **Only a recognised declaration is kept**, never the result it
            # rode in on: `declarations_in_result` prefilters on two marker
            # words and returns nothing for every other answer there is, so a
            # run whose tools declare nothing pays a substring scan and this
            # key stays absent — which is what `queried` and `queries` already
            # mean by absent rather than empty.
            for declaration in declarations_in_result(getattr(message, "content", "")):
                entry: dict[str, Any] = {
                    "table": declaration.table,
                    "row_key": list(declaration.row_key),
                    "coverage": {
                        "column": declaration.coverage_column,
                        "min": str(declaration.coverage_min or ""),
                        "max": str(declaration.coverage_max or ""),
                    },
                }
                if entry not in declares and len(declares) < DECLARATION_RECORD_CAP:
                    declares.append(entry)
        names = rejected_tool_names(getattr(message, "content", None))
        for name in names:
            if name not in refused:
                refused.append(name)
        if getattr(message, "type", None) != "tool" or names:
            # A refusal arrives as a `ToolMessage` too, and counting it as a
            # use would shut the door on precisely the run that needs it. A
            # tool that ran and returned an *error* is a use, though: errors
            # are data, and the tool is wired
            # (`the-agent-asks-for-what-it-cannot-get` 01).
            continue
        used = str(getattr(message, "name", "") or "")
        if used == DELEGATION_TOOL:
            # A delegation is recorded as the **worker**, never as the
            # harness's tool: which worker got the work is the one thing
            # `compile/subagents.py` is strict about before the run, and was
            # the one thing the run did not say. An unresolved id here is a
            # delegation that reached nobody — an undeclared worker's name,
            # which `deepagents` answers with a sentence and no run — so it
            # drops out of `ran` exactly as an invented tool name does
            # (`production-ready` 98).
            used = delegations.get(str(getattr(message, "tool_call_id", "") or ""), "")
        if used and used not in ran:
            ran.append(used)
    # A tool the runtime refused never ran, so it never sent anything either.
    queried = [name for name in queried if name in ran]
    row: dict[str, Any] = {"bound": list(bound), "ran": ran}
    # What the canvas drew and the compile could not produce
    # (`launch-readiness` 103). Absent when nothing failed, for the same reason
    # `queried` is: only presence is a claim, and `bound: []` on its own has
    # meant both "no tools by design" and "every tool here is missing".
    if unbound:
        row["unbound"] = list(unbound)
    # Absent rather than empty, for the reason the docstring gives about
    # `unmet_tools`: a node that sent no query and a node with no query to send
    # must not look the same, and only presence is a claim.
    if queried:
        row["queried"] = queried
    # Absent rather than empty, for the same reason `queried` is.
    if queries:
        row["queries"] = queries
    # Same again: a node shown no declaration and a node whose tools declare
    # nothing must not look the same to a gate. `table_coverage` reads absence
    # as *undeclared* and says so to the reader, which is the whole of 166.
    if declares:
        row["declares"] = declares
    update: dict[str, Any] = {"tool_use": {node_id: row}}
    if refused:
        update["unmet_tools"] = {node_id: refused}
    return update


__all__ = [
    "DECLARATION_RECORD_CAP",
    "QUERY_RESULT_RECORD_CAP",
    "tool_report",
]
