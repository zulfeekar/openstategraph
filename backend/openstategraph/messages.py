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

import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

__all__ = [
    "REASONING_BLOCK_TYPES",
    "TokenUsage",
    "content_text",
    "is_tool_message",
    "is_transcript_record",
    "reasoning_text",
    "usage_of",
]

#: The block types that are a model *thinking*, in every spelling that reaches
#: us.
#:
#: Two, not one, and this is a version fact rather than defensive breadth.
#: langchain-core 1.5.3 publishes `ReasoningContentBlock` as `type:
#: "reasoning"`, and its Anthropic and Google translators map those providers'
#: raw `"thinking"` blocks onto it — but the *raw* blocks are what arrive on
#: `stream_mode="messages"`, because `pregel/_messages.py` keeps direct
#: `graph.stream` callers on the v1 `AIMessageChunk` shape. The library itself
#: treats the pair as one thing where it counts: `messages/utils.py` tests
#: `block.get("type") in {"thinking", "reasoning"}`.
REASONING_BLOCK_TYPES: frozenset[str] = frozenset({"reasoning", "thinking"})


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


def reasoning_text(content: Any) -> str:
    """The model's *deliberation*, which `content_text` deliberately drops.

    The other half of the same piece of knowledge, so it lives beside it: a
    thinking model puts both in one content list, and until now the second
    half was read by nobody. Reasoning effort is already a per-node field, so
    a developer could ask for reasoning and then had no way to see any of it
    (ticket 23).

    **A plain string is never reasoning.** A provider that sends a bare string
    is sending the answer; there is no shape in which deliberation arrives
    unlabelled, and guessing would be the exact failure `content_text`'s
    docstring catalogues five times over.

    The text lives under a key named after the block type — `reasoning` for
    the standard block, `thinking` for the raw provider spelling — so both are
    read rather than one being silently empty. See `REASONING_BLOCK_TYPES`.
    """
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind not in REASONING_BLOCK_TYPES:
            continue
        parts.append(str(block.get("reasoning") or block.get("thinking") or ""))
    return "".join(parts)


class TokenUsage(BaseModel):
    """What one model message cost, as the provider reported it.

    Modelled rather than passed through as a raw dict for the reason
    `openstategraph.progress` is: this is **provider metadata**, so its shape
    is not ours and the seam that publishes it is a contract. LangChain's own
    `UsageMetadata` carries optional per-modality breakdowns beside these
    three; only the three cross the wire, because the breakdown differs by
    provider and a field that is sometimes there is a field a client cannot
    rely on.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def as_frame(self) -> dict[str, int]:
        """The published spelling — camelCase, like every other frame field."""
        return {
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "totalTokens": self.total_tokens,
        }


def usage_of(message: Any) -> TokenUsage | None:
    """This message's token usage, or `None` when it reported none.

    Usage rides the **last** chunk of a streamed message — the docs' own
    `message-finish` — and that chunk's content is empty, which is precisely
    why none of it ever reached a client: the fold gated on `if content:` and
    dropped the one frame carrying the numbers.

    Total by construction: provider metadata is third-party data, and a
    malformed payload must cost its own field rather than the run. `None`
    where the numbers are absent or unreadable, never a zeroed record — "this
    message cost nothing" and "nobody said" are different claims.
    """
    raw = getattr(message, "usage_metadata", None)
    if not isinstance(raw, dict):
        return None
    try:
        counted = TokenUsage(
            input_tokens=int(raw.get("input_tokens") or 0),
            output_tokens=int(raw.get("output_tokens") or 0),
            # Derived when the provider omits it rather than published as 0:
            # a total that contradicts the two numbers beside it is worse than
            # no total, and this is the one field trivially recoverable.
            total_tokens=int(
                raw.get("total_tokens")
                or (int(raw.get("input_tokens") or 0) + int(raw.get("output_tokens") or 0))
            ),
        )
    except (TypeError, ValueError):
        logger.debug("a provider reported usage this version cannot read")
        return None
    if not (counted.input_tokens or counted.output_tokens or counted.total_tokens):
        return None
    return counted


def is_transcript_record(message: Any) -> bool:
    """Whether this is a node **writing the conversation record**, not the model.

    `_input` logs the user's turn and `_output` logs the answer where every path
    converges, which is what gives a thread memory (ticket 73). Both are right
    and stay. But `stream_mode=["updates", "messages", "custom"]` emits every
    message on that channel — written or streamed — and nothing told them apart,
    so the record re-entered the token stream and `AskPanel`, which concatenates
    every token, held the answer twice before the answer block showed it a third
    time (`every-workflow-green` 02).

    **Measured on the wire**, not inferred, by tapping one real run of
    `workflow-2026` in the editor:

        AIMessageChunk  AIMessageChunk  model                     744 chars
        AIMessage       ai              node_output_formatted_1   744 chars
        HumanMessage    human           node_input_text_1          21 chars
        ToolMessage     tool            tools                     478 chars

    744 + 744 + 21 = 1509, against 1466 measured in the DOM. The model's own
    text arrives **only** as chunks; the two settled non-tool messages are
    exactly the two records.

    So: a settled `ai` or `human` message is the record. A **tool** message is
    not — a tool produces its output whole rather than token by token, and the
    developer's per-call result cards are fed from it.

    Duck-typed on `.type` like `is_tool_message`, for the reason recorded
    there: this channel yields chunk classes and settled messages, and one test
    covers the family without importing one of each. Verified against
    langchain-core 1.5.3, where `AIMessageChunk.type` is the class name and
    `AIMessage.type` is `"ai"`.

    **The cost, stated rather than discovered.** A provider that does not stream
    returns its reply as one settled `AIMessage`, which this drops from the
    *live* stream. Nothing is lost — the answer still arrives on the `updates`
    fold and the terminal frame — and a provider that does not stream had no
    live text to offer anyway.
    """
    kind = str(getattr(message, "type", ""))
    return kind in {"ai", "human"}


def is_tool_message(message: Any) -> bool:
    """Whether a streamed message is a tool's *result* rather than model text.

    Duck-typed on LangChain's own `type` discriminator rather than
    `isinstance(message, ToolMessage)`: the `messages` stream yields chunk
    classes (`ToolMessageChunk`) as well as settled messages, and both answer
    `"tool"` here, so one test covers the family without importing it.
    """
    return str(getattr(message, "type", "")) == "tool"
