"""The two agent tiers this workflow uses.

Both are **siblings**, not a hierarchy. `create_deep_agent` is `create_agent`
plus a fixed middleware slot assembly, so the difference between these two is
*which preset they declare* — a fact, not a modelling preference (ticket 08).

Neither function subclasses anything from LangChain. We call the factories and
hold the compiled result; the library's internals stay the library's.
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from pydantic import BaseModel, Field

from tools.chinook import TOOLS

#: Bound once. Every agent here gets the same read-only Chinook surface.
CHINOOK_TOOLS = [tool.as_langchain_tool() for tool in TOOLS]

SQL_SYSTEM_PROMPT = """\
You answer questions about the Chinook music-store database by querying it.

Always work in this order:
1. `chinook_list_tables` to see what exists.
2. `chinook_get_table_schema` on the tables you need — **read the foreign keys**,
   they tell you how to join.
3. `chinook_execute_sql` with a single SELECT.

Rules:
- One SELECT per call. No writes; the connection is read-only and will refuse them.
- Prefer explicit JOINs over subqueries, and always alias aggregates.
- If a query errors, read the error and fix the SQL rather than guessing again.
- Answer the question first, then state the SQL you settled on. The answer is
  what was asked for; the query is how you got it, and a reader should not have
  to scroll past the working to reach the result.
"""

SYNTHESIS_SYSTEM_PROMPT = """\
You turn query results into a short, direct answer for a human.

- Lead with the answer, not a description of what you did.
- Quote concrete figures from the rows; never invent one.
- Two or three sentences unless the data genuinely needs more.
- If the rows do not answer the question, say so plainly.
"""


class SqlAnswer(BaseModel):
    """Structured result from the SQL tier.

    `response_format` is what makes the agent's output *machine-usable* by the
    next node instead of prose the grader has to parse back out.
    """

    sql: str = Field(description="The final SELECT statement that produced the rows.")
    rows_markdown: str = Field(description="The result rows, as a Markdown table.")
    reasoning: str = Field(default="", description="Why this query answers the question.")


def as_model(model: Any) -> Any:
    """Normalises a model identifier into a chat-model object.

    Needed because the two factories disagree: `create_agent` accepts a string
    like `"ollama:llama3.1:8b"` and resolves it, while `create_deep_agent`
    inspects `model.profile` and raises `AttributeError` on a string. Coercing
    here keeps that asymmetry from leaking into every caller.
    """
    if isinstance(model, str):
        from langchain.chat_models import init_chat_model

        return init_chat_model(model)
    return model


def build_sql_agent(model: Any, middleware: tuple = (), *, structured: bool = False) -> Any:
    """Tier: **LangChain framework** — `create_agent`, a minimal ReAct harness.

    Returns a *compiled graph*, which is why it can be dropped into a
    `StateGraph` as a node. `middleware` is threaded through rather than
    hardcoded: the base owns the capability to compose, never the composition.

    `structured` is **off by default**, which was a correction rather than a
    preference. With `response_format=SqlAnswer`, a model that emits slightly
    malformed JSON makes `create_agent` raise
    `StructuredOutputValidationError` and the whole run dies — observed with a
    real model on the first live query.

    The node does not need the model to restate its work anyway: the SQL is in
    the `chinook_execute_sql` tool call and the rows are in the `ToolMessage` it
    produced. Reading that evidence is both model-agnostic and more trustworthy
    than a paraphrase, since the grader then judges what the database actually
    returned. Set `structured=True` only for a model known to be reliable at it.
    """
    return create_agent(
        model=as_model(model),
        tools=CHINOOK_TOOLS,
        system_prompt=SQL_SYSTEM_PROMPT,
        middleware=middleware,
        name="chinook_sql_agent",
        **({"response_format": SqlAnswer} if structured else {}),
    )


def build_synthesis_agent(model: Any, middleware: tuple = ()) -> Any:
    """Tier: **Deep Agents harness** — `create_deep_agent`.

    Imported lazily so the module stays importable without `deepagents`
    installed, and so the SQL tier does not pay for a harness it does not use.

    It gets **no Chinook tools on purpose.** Its job is to phrase an answer from
    rows the SQL tier already fetched; handing it the database would let it
    re-query and drift from the evidence the grader approved.
    """
    from deepagents import create_deep_agent

    return create_deep_agent(
        model=as_model(model),
        tools=[],
        system_prompt=SYNTHESIS_SYSTEM_PROMPT,
        middleware=middleware,
        name="chinook_synthesiser",
    )


__all__ = [
    "CHINOOK_TOOLS",
    "as_model",
    "SqlAnswer",
    "build_sql_agent",
    "build_synthesis_agent",
]
