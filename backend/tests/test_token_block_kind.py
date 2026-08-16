"""A reasoning model's thinking and its answer were the same frame (23).

`langgraph/event-streaming.mdx` models model output as `message-start`,
`content-block-start`, `content-block-delta`, `content-block-finish`,
`message-finish`, with **`text-delta` distinct from `reasoning-delta`**, and
token usage carried on `message-finish`. Our `token` frame was a flat string,
so:

- a reasoning model's private deliberation and its answer arrived as the same
  kind of frame and no client could tell them apart — while **reasoning effort
  is already a per-node field**, i.e. a developer could ask for reasoning and
  then never see it;
- **token usage never reached a client at all**, which is why
  `multi-agent/index.mdx`'s call/token comparisons are something we cannot
  help a developer reason about: it scores patterns in calls and tokens and we
  published neither.

**Where the facts come from, at this version.** `graph.stream(stream_mode=
"messages")` does *not* deliver the content-block protocol — `pregel/
_messages.py` states that direct callers "keep the v1 AIMessageChunk shape",
and the v2 messages handler is behind an internal config key. So the block
kind has to be read off the chunk's own content, which is what
`openstategraph.messages` already exists to do. And it must accept **two**
spellings: langchain-core 1.5.3 normalises Anthropic's and Google's raw
`"thinking"` blocks to `"reasoning"` in its translators, but treats them as
one thing where it matters (`messages/utils.py:1938` tests `block.get("type")
in {"thinking", "reasoning"}`), and raw provider blocks reach this stream.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openstategraph.api.audience import Audience  # noqa: E402
from openstategraph.api.streaming import _stream_run  # noqa: E402
from openstategraph.compile.diagnostics import CompileDiagnostics  # noqa: E402
from openstategraph.messages import content_text, reasoning_text  # noqa: E402

KNOWN = {"agent_llm_1": "node:agent.llm-1"}


def _frames(chunks: list[Any], audience: Audience = Audience.DEVELOPER) -> list[tuple[str, Any]]:
    class _Graph:
        def stream(self, *_args: Any, **_kwargs: Any) -> Any:
            return iter(chunks)

        def get_state(self, _config: Any) -> Any:
            return SimpleNamespace(next=(), tasks=())

        def get_graph(self, **_kwargs: Any) -> Any:
            return SimpleNamespace(draw_mermaid=lambda: "graph TD;")

    runtime = SimpleNamespace(diagnostics=CompileDiagnostics())
    out: list[tuple[str, Any]] = []
    for frame in _stream_run(
        _Graph(), {}, {}, SimpleNamespace(warnings=[]), KNOWN, runtime, "t1", audience
    ):
        name = frame.split("\n")[0][len("event: ") :]
        out.append((name, json.loads(frame.split("\n")[1][len("data: ") :])))
    return out


def _chunk(content: Any, **extra: Any) -> Any:
    message = SimpleNamespace(type="AIMessageChunk", content=content, **extra)
    return ((), "messages", (message, {"langgraph_node": "agent_llm_1"}))


def _tokens(events: list[tuple[str, Any]]) -> list[Any]:
    return [data for name, data in events if name == "token"]


class TestReadingBlocksOffAMessage:
    """`reasoning_text` is `content_text`'s sibling, in the same module.

    The knowledge is "how to read a message", it is one piece of knowledge,
    and `messages.py` exists precisely because it was once duplicated into
    five `isinstance` checks that each got it wrong in their own way.
    """

    def test_reasoning_blocks_are_read(self) -> None:
        assert reasoning_text([{"type": "reasoning", "reasoning": "Let me think"}]) == "Let me think"

    def test_anthropics_and_googles_spelling_is_read_too(self) -> None:
        # Both providers emit raw `thinking` blocks; langchain-core's own
        # translators map them to `reasoning`, and its `utils.py` treats the
        # two as one. Raw blocks reach this stream, so both must work.
        assert reasoning_text([{"type": "thinking", "thinking": "Hmm"}]) == "Hmm"

    def test_the_two_readers_do_not_take_each_others_blocks(self) -> None:
        mixed = [
            {"type": "reasoning", "reasoning": "privately"},
            {"type": "text", "text": "publicly"},
        ]

        assert content_text(mixed) == "publicly"
        assert reasoning_text(mixed) == "privately"

    def test_a_plain_string_has_no_reasoning(self) -> None:
        # A string is the answer, never deliberation — the invariant
        # `content_text` already relies on.
        assert reasoning_text("just an answer") == ""
        assert reasoning_text(None) == ""


class TestTheBlockKindIsOnTheFrame:
    def test_ordinary_text_is_a_text_block(self) -> None:
        token = _tokens(_frames([_chunk("Rock")]))[0]

        assert token["block"] == "text"
        # Additive only: everything an older client reads is untouched.
        assert token["content"] == "Rock"
        assert token["kind"] == "ai"

    def test_thinking_arrives_as_its_own_frame(self) -> None:
        tokens = _tokens(
            _frames([_chunk([{"type": "reasoning", "reasoning": "Weigh the options"}])])
        )

        assert [t["block"] for t in tokens] == ["reasoning"]
        assert tokens[0]["content"] == "Weigh the options"

    def test_thinking_and_answer_in_one_chunk_are_two_frames(self) -> None:
        """The defect, stated exactly.

        A provider may put both in one chunk. Concatenated they are one blob
        and a client renders a model's private deliberation as its reply;
        split, a reasoning UI is possible for the first time — and **the
        reasoning comes first**, which is the order it was produced in.
        """
        tokens = _tokens(
            _frames(
                [
                    _chunk(
                        [
                            {"type": "reasoning", "reasoning": "Rock outsells Latin"},
                            {"type": "text", "text": "Rock earns the most."},
                        ]
                    )
                ]
            )
        )

        assert [(t["block"], t["content"]) for t in tokens] == [
            ("reasoning", "Rock outsells Latin"),
            ("text", "Rock earns the most."),
        ]

    def test_a_tool_result_is_still_text(self) -> None:
        # A tool has no deliberation; `kind` and `block` answer different
        # questions and must not collapse into one another.
        message = SimpleNamespace(
            type="tool", content="| Album | 347 |", name="list_tables", tool_call_id="c1"
        )
        token = _tokens(_frames([((), "messages", (message, {"langgraph_node": "tools"}))]))[0]

        assert (token["kind"], token["block"]) == ("tool", "text")


class TestThinkingIsNotAddressedToACustomer:
    """The audience boundary, applied to a kind of text that never had one.

    `content_text`'s own docstring already states the rule this enforces:
    only `text` blocks are joined, because "a thinking model puts its
    reasoning in the same list, and concatenating blindly would hand a
    customer the model's private deliberation as if it were the answer".
    Making reasoning visible must not make it visible to *everyone*.

    Dropped rather than emptied, unlike a withheld tool frame. An emptied
    frame is kept because it is the only carrier of `activeNode` mid-node —
    but a reasoning frame is always accompanied by the text frames of the same
    node, which carry it already. So a customer's stream is byte-for-byte what
    it was before this ticket.
    """

    def test_a_customer_gets_no_reasoning_frame_at_all(self) -> None:
        tokens = _tokens(
            _frames(
                [_chunk([{"type": "reasoning", "reasoning": "secret"}])],
                Audience.CUSTOMER,
            )
        )

        assert tokens == []

    def test_the_answer_beside_it_still_reaches_them(self) -> None:
        tokens = _tokens(
            _frames(
                [
                    _chunk(
                        [
                            {"type": "reasoning", "reasoning": "secret"},
                            {"type": "text", "text": "Rock."},
                        ]
                    )
                ],
                Audience.CUSTOMER,
            )
        )

        assert [(t["block"], t["content"]) for t in tokens] == [("text", "Rock.")]


class TestUsageRidesTheSettledMessage:
    def test_a_chunk_that_carries_usage_publishes_it(self) -> None:
        token = _tokens(
            _frames(
                [
                    _chunk(
                        "done",
                        usage_metadata={
                            "input_tokens": 350,
                            "output_tokens": 240,
                            "total_tokens": 590,
                        },
                    )
                ]
            )
        )[0]

        assert token["usage"] == {"inputTokens": 350, "outputTokens": 240, "totalTokens": 590}

    def test_every_other_frame_says_it_has_none(self) -> None:
        # Present and null rather than absent, so a client reads one field
        # unconditionally — and so "usage present" is the signal that this
        # frame settled a message, which is what `message-finish` means.
        assert _tokens(_frames([_chunk("Rock")]))[0]["usage"] is None

    def test_the_final_empty_chunk_is_no_longer_thrown_away(self) -> None:
        """Why usage never reached a client, precisely.

        A provider's usage arrives on the LAST chunk of a message, and that
        chunk's content is empty. The fold gated on `if content:`, so the one
        frame carrying the numbers was the one frame dropped.
        """
        tokens = _tokens(
            _frames([_chunk("", usage_metadata={"input_tokens": 1, "output_tokens": 2})])
        )

        assert len(tokens) == 1
        assert tokens[0]["content"] == ""
        assert tokens[0]["usage"] == {"inputTokens": 1, "outputTokens": 2, "totalTokens": 3}

    def test_an_empty_chunk_with_no_usage_is_still_dropped(self) -> None:
        # The old rule survives where it was right: an empty token frame that
        # carries nothing at all says "the model produced nothing just then",
        # which is a lie.
        assert _tokens(_frames([_chunk("")])) == []

    def test_a_customer_is_not_told_what_a_turn_cost(self) -> None:
        # Token counts are cost, which is developer material — the same rule
        # that blanks a tool's name on this frame.
        tokens = _tokens(
            _frames(
                [_chunk("Rock.", usage_metadata={"input_tokens": 9, "output_tokens": 1})],
                Audience.CUSTOMER,
            )
        )

        assert tokens[0]["usage"] is None

    def test_a_malformed_usage_payload_costs_nothing(self) -> None:
        # Provider metadata, so it is not ours to trust.
        token = _tokens(_frames([_chunk("Rock", usage_metadata="lots")]))[0]

        assert token["usage"] is None
