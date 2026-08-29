"""When a model ends its turn without writing, ask it once for the answer.

`launch-readiness/185`. One function, and the whole of it fits the sentence
above — a node reads its loop's messages through here instead of through
`_final_text` alone, and gets back either what the model said or what it says
when asked a second time.

**Why it is not in `reporting.py`.** `_final_text` lives there and stays there:
that module reads a record and never spends anything, and a model call inside
it would make every caller's cost depend on what a message happened to contain.
This is the opposite kind of thing — a deliberate, bounded second call on a
path that has already produced nothing — so it is its own module, named for
the situation rather than for the mechanism.

**Why a second ask is the right shape, and not a widened parser.** The turn
that goes silent was measured twice, once by `production-ready/96` off the raw
Ollama wire and once by `185` off a live reproduction of the owner's own
question:

    content="", tool_calls=[], done_reason="stop", eval_count=92

Ninety-two tokens generated and none of them published. There is no channel to
widen towards and nothing was lost in extraction — the model genuinely stopped.
What is available is the conversation it stopped in the middle of, tool results
and all, and asking it to write the answer down from that recovered four of
five silent turns on the reproduction.

**Once, and narrowly.** The nudge is a single call, only when the loop actually
got somewhere, with no tools bound so it cannot restart the loop it is ending.
A nudge that also says nothing returns `""` exactly as before, and a nudge that
raises returns `""` rather than turning a recoverable silence into a dead run —
`Grader.normalise`'s rule, and the more so because the provider observed going
silent under this load is the same one observed answering 500 under it.
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.reporting import _final_text
from openstategraph.messages import content_text

#: What the model is asked, on a turn it ended without writing.
#:
#: Two clauses, both load-bearing. *From what you already have* points it at
#: the tool results in its own context rather than at its memory — every
#: grounded node in the catalogue forbids the second, and a nudge that invited
#: it would be the platform doing the thing its own graders exist to catch.
#: *Do not call any more tools* ends the loop rather than restarting it: this
#: call is made with no tools bound, so a request for one could only fail.
NUDGE = (
    "Write your final answer now, from what you already have. "
    "Do not call any more tools."
)


def _the_loop_got_somewhere(messages: list[Any]) -> bool:
    """Did anything happen after the question, that an answer could come from?

    The floor is `_final_text`'s own: a conversation still on its human turn
    has produced no evidence, so the only thing a second ask could draw on is
    the model's own memory. That is not a recovery, it is an invitation to
    invent, and it is not worth a model call to get.
    """
    for message in reversed(messages):
        kind = getattr(message, "type", None)
        if kind in ("human", "system"):
            return False
        if kind in ("ai", "tool"):
            return True
    return False


async def text_or_ask_again(messages: list[Any], model: Any) -> str:
    """What the model said this turn — or, if it said nothing, what it says now.

    Returns `""` when there is nothing and the second ask did not change that,
    which is the same answer this call site gave before and still means the
    same thing: `silent_node_warnings` has the sentence for it.
    """
    text = _final_text(messages or [])
    if text.strip():
        return text
    if model is None or not _the_loop_got_somewhere(messages or []):
        return ""

    from langchain_core.messages import HumanMessage

    try:
        reply = await model.ainvoke(list(messages) + [HumanMessage(content=NUDGE)])
    except Exception:  # noqa: BLE001 - a failed recovery is still a silence
        return ""
    # `content_text`, never `str(content)`: a provider answering in blocks is
    # the shape that once made this codebase publish the user's own question
    # back as the answer.
    recovered = content_text(getattr(reply, "content", ""))
    return recovered if recovered.strip() else ""
