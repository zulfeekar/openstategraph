"""Reading a model message, whichever shape the provider sent it in.

**One function, because this has now been the same bug five times.**
LangChain documents `content` as "loosely-typed, supporting strings and lists
of untyped objects", and an Anthropic `AIMessage` in particular "can either be
a single string or a list of content blocks". Which one arrives is not the
caller's choice: adding `"messages"` to `stream_mode` — which both shipped UIs
do — is enough to turn

    content="PASS"

into

    content=[{"type": "text", "text": "PASS", "index": 0}]

Every call site that met that with `isinstance(content, str)` had a wrong
answer waiting in it, and each one failed differently and quietly:

- the **agent** returned the user's own question as the answer, because the
  walk-back skipped a full message and kept going onto the `HumanMessage`;
- the **grader** stringified the block list, so `"PASS"` became
  `"[{'type': 'text', 'text': 'PASS'…}]"` — which starts with neither `pass`
  nor `fail`, so it fell through to *"Verdict unclear; passing by default"*
  and stopped grading. A `FAIL` verdict fared worse: the repr *contains*
  "fail", so it rejected the answer and handed the raw Python repr to the
  customer as the reason;
- the **router** and the **orchestrator** the same way — an unparseable label
  falls back to a default branch or a default worker, inside an
  `except Exception`, so the degradation is invisible;
- the **token stream** dropped block chunks entirely, so a run produced no
  live text and the flow diagram never lit up.

None of it raised. That is why it lives here now: the knowledge is "how to
read a message", it is one piece of knowledge, and it was duplicated into five
`isinstance` checks that each got it wrong in their own way.
"""

from __future__ import annotations

from typing import Any

__all__ = ["content_text"]


def content_text(content: Any) -> str:
    """The human-readable text of a message's content.

    Only `text` blocks are joined. A thinking model puts its reasoning in the
    same list, and concatenating blindly would hand a customer the model's
    private deliberation as if it were the answer.

    Deliberately not `message.text`: that accessor is a property on current
    message classes and a deprecated *method* on others, so reading it
    generically means guessing which — and the hand-rolled stand-ins this
    codebase also passes around have neither.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""
