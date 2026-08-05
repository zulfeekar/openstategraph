"""The Chinook NL-to-SQL workflow, as a `StateGraph`.

A POC that exercises all three LangChain tiers in one graph, which is the point:
the canvas *is* a `StateGraph`, an Agent node *is* a loop, and composition is
subgraphs (CLAUDE.md).

```
START -> orient ----------------------------------- deterministic node (LangGraph)
      -> write_sql --------------------------------- create_agent      (LangChain)
      -> grade ------------------------------------- deterministic node + router
           |-- revise --> write_sql  (cycle)
           |-- exhausted -> synthesise
           '-- pass ------> synthesise ------------- create_deep_agent (Deep Agents)
      -> END
```

Three design rules from CLAUDE.md are visible here, and each would be easy to get
wrong:

**The cycle is gated by a typed feedback path, not by a flag.** `grade` may route
back to `write_sql` only by writing `feedback`, and the cycle contains a
conditional edge — an all-static cycle can never terminate.

**The step budget is not an iteration count.** `recursion_limit` counts
*supersteps*, so the graph carries its own `attempts` counter for the thing a user
actually means by "try again twice", and uses `RemainingSteps` to bail out
gracefully instead of raising `GraphRecursionError`.

**Retry and timeout are graph-assembly parameters.** They are `add_node`
arguments, never declared on a node or agent base. (`set_node_defaults` would
declare them graph-wide in one call, but it does not exist in the installed
langgraph 1.0.3 — the docs describe a later version.)
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Callable, Literal, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.managed.is_last_step import RemainingSteps
from langgraph.types import RetryPolicy

from tools.chinook import ExecuteSqlTool, ListTablesTool

#: What a user means by "try again" — distinct from the superstep budget.
MAX_ATTEMPTS = 3


class Verdict(TypedDict):
    """The grader's structured output. A named shape, not free text."""

    passed: bool
    reason: str


class QueryState(TypedDict):
    """Shared state.

    Raw data only — no formatted prompts. Nodes format on demand, so a prompt
    change never becomes a state-schema change.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    question: str
    schema_hint: str
    sql: str
    rows: str
    verdict: Verdict | None
    feedback: str
    attempts: int
    answer: str
    #: Managed channel. Lets a node see how close the run is to the budget.
    remaining_steps: RemainingSteps


# --------------------------------------------------------------------------- #
# Deterministic nodes — the LangGraph tier
# --------------------------------------------------------------------------- #


def orient(state: QueryState) -> dict[str, Any]:
    """Puts the table list in state before any model runs.

    Deliberately not an LLM call. "What tables exist" is a fact, and paying a
    model to discover it every run is slower, costlier and less reliable than
    reading it. This is the mixed deterministic/agentic shape LangGraph exists
    for.
    """
    listing = ListTablesTool().run()
    return {"schema_hint": listing.content if listing.ok else ""}


_SELECT = re.compile(r"\b(select|with)\b.*", re.IGNORECASE | re.DOTALL)


def grade(state: QueryState) -> dict[str, Any]:
    """Checks the SQL tier's answer before it reaches synthesis.

    Deterministic on purpose. These are the failure modes that actually occur —
    no rows, an error, no SQL at all — and each is cheaper and more reliable to
    detect with a check than with a second model call. An LLM grader belongs here
    only for judgements a rule cannot express.
    """
    rows = state.get("rows", "") or ""
    sql = state.get("sql", "") or ""

    if not sql.strip():
        verdict = Verdict(passed=False, reason="No SQL was produced.")
    elif "error" in rows.lower():
        verdict = Verdict(passed=False, reason=f"The query failed: {rows[:200]}")
    elif "no rows" in rows.lower() or rows.strip() == "":
        verdict = Verdict(
            passed=False,
            reason="The query returned no rows — the filters or joins are probably wrong.",
        )
    else:
        verdict = Verdict(passed=True, reason="Rows returned.")

    return {
        "verdict": verdict,
        # The typed feedback path. Writing this is what makes the loop legal.
        "feedback": "" if verdict["passed"] else verdict["reason"],
    }


def route_after_grade(state: QueryState) -> Literal["revise", "synthesise"]:
    """The conditional edge. Every cycle must contain one.

    Three exits, and the middle one is the one people forget: run out of budget
    and **still produce an answer**, rather than raising `GraphRecursionError` and
    handing the user nothing.
    """
    verdict = state.get("verdict")
    if verdict is not None and verdict["passed"]:
        return "synthesise"

    if state.get("attempts", 0) >= MAX_ATTEMPTS:
        return "synthesise"

    # `remaining_steps` is a managed channel, absent outside a run.
    remaining = state.get("remaining_steps")
    if isinstance(remaining, int) and remaining <= 3:
        return "synthesise"

    return "revise"


# --------------------------------------------------------------------------- #
# Agent nodes — injected, so the graph's topology is testable without a model
# --------------------------------------------------------------------------- #

AgentNode = Callable[[QueryState], dict[str, Any]]


def make_sql_node(agent: Any) -> AgentNode:
    """Wraps the `create_agent` loop as a graph node.

    Invoked from inside a node rather than added as a bare subgraph so the
    structured `SqlAnswer` can be unpacked into our own channels. Both are
    supported; this one keeps state explicit and the node independently testable.
    """

    def write_sql(state: QueryState) -> dict[str, Any]:
        prompt = _sql_prompt(state)
        result = agent.invoke({"messages": [HumanMessage(content=prompt)]})

        messages = result.get("messages") or []

        # Preferred: read what actually happened. The SQL is in the
        # `chinook_execute_sql` tool call and the rows are in the ToolMessage it
        # returned, so the grader judges the database's real output rather than
        # the model's paraphrase of it. Works with any model, and needs no
        # structured-output support.
        sql, rows = _from_tool_calls(messages)

        if not sql:
            structured = result.get("structured_response")
            if structured is not None:
                sql = getattr(structured, "sql", "") or ""
                rows = getattr(structured, "rows_markdown", "") or ""

        if not sql:
            # Last resort: the model described the query without calling the
            # tool. Run it ourselves so the grader has rows to judge.
            match = _SELECT.search(_last_text(result))
            sql = match.group(0).strip() if match else ""
            rows = ExecuteSqlTool().run(query=sql).content if sql else ""

        return {
            "sql": sql,
            "rows": rows,
            "attempts": state.get("attempts", 0) + 1,
            "messages": result.get("messages", [])[-1:],
        }

    return write_sql


def make_synthesis_node(agent: Any) -> AgentNode:
    """Wraps the `create_deep_agent` harness as a graph node."""

    def synthesise(state: QueryState) -> dict[str, Any]:
        verdict = state.get("verdict") or Verdict(passed=True, reason="")
        caveat = (
            ""
            if verdict["passed"]
            else f"\n\nNote: the query was not satisfactory ({verdict['reason']}). "
            "Say what could not be determined rather than inventing a figure."
        )
        prompt = (
            f"Question: {state['question']}\n\n"
            f"SQL used:\n```sql\n{state.get('sql', '')}\n```\n\n"
            f"Rows:\n{state.get('rows', '')}{caveat}"
        )
        result = agent.invoke({"messages": [HumanMessage(content=prompt)]})
        return {"answer": _last_text(result), "messages": result.get("messages", [])[-1:]}

    return synthesise


def _from_tool_calls(messages: list[Any]) -> tuple[str, str]:
    """Recovers the last executed query and its rows from the message history.

    Returns the *last* successful execution, because a ReAct loop routinely runs
    a query, sees an error, and fixes it — the earlier attempts are not the
    answer.
    """
    sql_by_call_id: dict[str, str] = {}
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            if call.get("name") == "chinook_execute_sql":
                sql_by_call_id[call.get("id", "")] = (call.get("args") or {}).get("query", "")

    for message in reversed(messages):
        if getattr(message, "type", "") != "tool":
            continue
        call_id = getattr(message, "tool_call_id", "")
        if call_id not in sql_by_call_id:
            continue
        content = message.content
        return sql_by_call_id[call_id], content if isinstance(content, str) else str(content)

    return "", ""


def _sql_prompt(state: QueryState) -> str:
    feedback = state.get("feedback", "")
    parts = [f"Question: {state['question']}"]
    if state.get("schema_hint"):
        parts.append(f"\nTables available:\n{state['schema_hint']}")
    if feedback:
        # The retry carries *why* it is retrying. Without this the agent repeats
        # the same query and the loop is pure cost.
        parts.append(
            f"\nYour previous attempt was rejected: {feedback}\n"
            f"Previous SQL:\n{state.get('sql', '')}\n"
            "Fix it — inspect the schema again if the joins are the problem."
        )
    return "\n".join(parts)


def _last_text(result: dict[str, Any]) -> str:
    messages = result.get("messages") or []
    if not messages:
        return ""
    content = messages[-1].content
    if isinstance(content, str):
        return content
    # Content blocks: keep the text ones.
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def build_graph(sql_node: AgentNode, synthesis_node: AgentNode, *, compile_graph: bool = True):
    """Assembles the workflow.

    Agent nodes are injected rather than constructed here, which is what lets the
    topology — the cycle, the router, the budget guard — be tested without a model
    or an API key.
    """
    builder = StateGraph(QueryState)

    # Retry belongs to **graph assembly**, not to any node or agent base — it is
    # an `add_node` parameter available to every family.
    #
    # Applied per node because `StateGraph.set_node_defaults(...)`, which declares
    # it graph-wide once, does not exist in the installed langgraph (1.0.3); the
    # docs describe a later version. Checked against the installed package rather
    # than trusted from the documentation. Collapse this into one call when the
    # dependency moves to >= 1.2.
    retry = RetryPolicy(max_attempts=2)
    builder.add_node("orient", orient, retry_policy=retry)
    builder.add_node("write_sql", sql_node, retry_policy=retry)
    builder.add_node("grade", grade, retry_policy=retry)
    builder.add_node("synthesise", synthesis_node, retry_policy=retry)

    builder.add_edge(START, "orient")
    builder.add_edge("orient", "write_sql")
    builder.add_edge("write_sql", "grade")

    # The router's complete declared destination set, named explicitly — a
    # renderer that has to infer it draws the router as connected to everything.
    builder.add_conditional_edges(
        "grade",
        route_after_grade,
        {"revise": "write_sql", "synthesise": "synthesise"},
    )
    builder.add_edge("synthesise", END)

    return builder.compile() if compile_graph else builder


def build_live_graph(model: Any, deep_model: Any | None = None):
    """The real thing: both agent tiers wired to a model."""
    from agents import build_sql_agent, build_synthesis_agent

    return build_graph(
        make_sql_node(build_sql_agent(model)),
        make_synthesis_node(build_synthesis_agent(deep_model or model)),
    )


def mermaid(graph: Any) -> str:
    """Mermaid **text** for the editor to render.

    Never `draw_mermaid_png()`, which posts the graph to the Mermaid.Ink API.
    `xray=True` expands the agent subgraphs, so a preview shows what the compiler
    actually produced rather than a hand-drawn approximation that can drift.
    """
    return graph.get_graph(xray=True).draw_mermaid()


__all__ = [
    "MAX_ATTEMPTS",
    "QueryState",
    "Verdict",
    "build_graph",
    "build_live_graph",
    "grade",
    "make_sql_node",
    "make_synthesis_node",
    "mermaid",
    "orient",
    "route_after_grade",
]
