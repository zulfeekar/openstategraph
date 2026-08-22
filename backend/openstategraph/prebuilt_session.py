"""Who is asking, and which conversation this is — from the run, not from the model.

A workflow that greets a returning user by name, scopes a query to "your"
orders, or quotes the thread id back so a support reply can be found later,
needs one fact the graph state does not carry: the identity the *run* was
started under. That identity already exists — `thread_id`, `session_id`,
`user_email` and `workflow_slug` ride in `configurable` on every run, and the
memory tools already namespace by the same `user_email`. It simply was never
readable from inside a prompt.

**The model cannot supply any of it.** `Args = NoArgs`, exactly like the email
tool's recipient rule: the transport says who this is, the model may only ask.
An identity a model can pass as an argument is an identity a prompt-injected
document can rewrite — and here that would mean reading another person's
memories, since the memory namespace is keyed on the same value.

This is a *tool*, deliberately not a node type. A node would have to sit
somewhere in the flow and produce a value into state, which is a second copy
of a fact the run already carries and one more thing to wire; attaching a
capability to the agent that needs it is how memory and knowledge already
work.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from openstategraph.abc.tool import BaseTool, NoArgs, ToolResult

#: `configurable` key -> the label the model sees. Ordered: who, then which
#: conversation, then where — the order a sentence would want them in.
#:
#: Public because it is the **one place the four run-identity keys are named**.
#: `compile/run_context.py` reads it to refuse a `settings.context` declaration
#: that tries to name one: `configurable` is who the run is *for*, decided by
#: the server, and `context` is what the workflow asked its caller for. A
#: second list of these keys somewhere else is a second chance for one of them
#: to drift. `organisms-first-class/68` moves it onto a `run_identity`
#: accessor together with the three hand-rolled `configurable` reads; until
#: then this tuple is that place, under a name another module may say.
RUN_IDENTITY_FIELDS: tuple[tuple[str, str], ...] = (
    ("user_email", "user"),
    ("session_id", "session"),
    ("thread_id", "conversation (thread) id"),
    ("workflow_slug", "workflow"),
)


def _configurable() -> dict[str, Any]:
    """The run's own config, or `{}` outside a run.

    `get_config()` raises when there is no runnable context — a unit test, a
    tool called directly from a script. That is not an error worth surfacing
    to a model; "we do not know who you are" is a complete answer.
    """
    try:
        from langgraph.config import get_config

        config = get_config() or {}
    except Exception:
        return {}
    return dict(config.get("configurable") or {})


class SessionIdentityTool(BaseTool):
    """The identity of the person and conversation this run belongs to."""

    name = "session_identity"
    node_type = "tool.session-identity"
    description = (
        "Who you are talking to and which conversation this is: the user's "
        "email, the session id, and the thread id of this run. Call it before "
        "greeting someone, before saving or recalling anything about them, or "
        "when the user asks how to refer back to this conversation. It takes "
        "no arguments — the identity comes from the run itself and cannot be "
        "supplied or changed by anything said in the conversation."
    )
    Args = NoArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        configurable = _configurable()
        known = [
            f"- {label}: {str(configurable.get(key) or '').strip()}"
            for key, label in RUN_IDENTITY_FIELDS
            if str(configurable.get(key) or "").strip()
        ]
        if not known:
            # Deliberately not an error: an anonymous run is a normal run, and
            # a failure here would push an agent into retrying a fact that is
            # never going to arrive.
            return ToolResult(
                content=(
                    "This run carries no identity — treat the user as anonymous "
                    "and do not guess a name."
                )
            )
        return ToolResult(content="This run's identity:\n" + "\n".join(known))


#: The family, in the shape `api/registries.py` folds every other one in.
SESSION_TOOLS: tuple[BaseTool, ...] = (SessionIdentityTool(),)
