"""Who is asking, and which conversation this is — from the run, not from the model.

A workflow that greets a returning user by name, scopes a query to "your"
orders, or quotes the thread id back so a support reply can be found later,
needs one fact the graph state does not carry: the identity the *run* was
started under. That identity already exists — `thread_id`, `session_id`,
`user_email` and `workflow_slug` ride in `configurable` on every run, and the
memory tools already namespace by the same `user_email` — and since
`organisms-first-class/68` every one of those readings goes through
`openstategraph.run_identity`. It simply was never readable from inside a
prompt.

**The model cannot supply any of it.** `Args = NoArgs`, exactly like the email
tool's recipient rule: the transport says who this is, the model may only ask.
An identity a model can pass as an argument is an identity a prompt-injected
document can rewrite — and here that would mean reading another person's
memories, since the memory namespace is keyed on the same value.

This is a *tool a developer wires by hand*, not a node that produces a value
into state. A node would have to sit somewhere in the flow and write a second
copy of a fact the run already carries; attaching a capability to the agent
that needs it, the way memory and knowledge already work, is enough — the
agent calls it, reads the answer, and nothing new enters state. It still has
a real editor card (`tool.session-identity` in `PlatformToolsNode.ts`), so a
developer can see it in the palette and attach it deliberately, the same as
any other bindable tool; `production-ready/61` found this file once claiming
the tool could not be placed on a canvas at all, which was never true — only
"produces no state" was ever the intent.
"""

from __future__ import annotations

from pydantic import BaseModel

from openstategraph.abc.tool import BaseTool, NoArgs, ToolResult
from openstategraph.run_identity import RUN_IDENTITY_FIELDS, run_identity

#: Re-exported, not redefined: `run_identity` owns the four keys and their
#: labels, and this module renders them. `organisms-first-class/68`.
__all__ = ["RUN_IDENTITY_FIELDS", "SESSION_TOOLS", "SessionIdentityTool"]


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
        identity = run_identity()
        known = [
            f"- {label}: {identity.get(key, '').strip()}"
            for key, label in RUN_IDENTITY_FIELDS
            if identity.get(key, "").strip()
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
