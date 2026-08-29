"""Which streamed text is machinery, and how machinery is kept off the stream.

Carved out of `compile/node_runtime.py` (`docs-and-gaps/03`), unchanged. One
sentence, and both halves of it are the same fact seen twice — which is why
they are one module rather than two:

- `MACHINERY_NODE_TYPES` records *which* nodes produce text nobody asked to
  read, and `api/audience.AnswerChannel` empties their frames on the way out.
  That is the fold.
- `silence_tokens` stops those tokens being generated onto the stream at all,
  through LangGraph's own `TAG_NOSTREAM`. That is the door.

`silence_tokens`' own docstring is an account of why the door does not replace
the fold, and it names the constant above it in the first paragraph. Splitting
them would put that argument in one file and its subject in another.

Who is *entitled* to see machinery remains `api/audience`'s question and stays
there: the compiler knows a node's type, so the compiler answers this one.
Two layers, one fact each.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.constants import TAG_NOSTREAM

logger = logging.getLogger(__name__)


#: Node types whose streamed text is machinery, not the reply.
#:
#: The compiler is what knows a node's type, so it is what answers this; who
#: is entitled to *see* machinery is `api/audience.AnswerChannel`'s question
#: and stays there. Two layers, one fact each — the same split
#: `developer_channel` already makes for the suggestion fence.
#:
#: Each entry earns its place from a frame QA read on screen (ticket 25):
#:
#: - `route.classifier` streams the branch NAME it chose — `music_store`,
#:   `data_query`, `general`, arriving glued to the sentence beside it.
#: - `route.grader` streams its verdict and rubric complaint — `FAIL Include
#:   the SQL SELECT statement...` on the end of a finished answer.
#: - `input.text` writes the turn's `HumanMessage` (see `_input`), so the
#:   question rides this stream and reads as the beginning of the reply.
#: - `input.markdown` / `input.skill` are static text sources: an instruction
#:   file or a skill, addressed to a model and to nobody else.
#:
#: `agent.llm`, `orchestrate.*` and `output.formatted` are deliberately
#: absent. Their prose IS the reply being written, and watching it appear is
#: the only thing that makes a 70-second run bearable.
MACHINERY_NODE_TYPES: frozenset[str] = frozenset(
    {
        "input.text",
        "input.markdown",
        "input.skill",
        "route.classifier",
        "route.grader",
    }
)

#: LangGraph's own tag for "run this model, but keep its tokens off the
#: `messages` stream". Read from the library rather than retyped, because a
#: misspelling here is silent — the invocation simply keeps streaming.
NOSTREAM_TAG: str = TAG_NOSTREAM


def silence_tokens(model: Any) -> Any:
    """The same model, with its tokens omitted from `stream_mode="messages"`.

    `MACHINERY_NODE_TYPES` above records *which* nodes produce text nobody
    asked to read; `api/audience.AnswerChannel` then empties their frames on
    the way out. That works, and its tests are untouched — but it is a curtain
    in front of a door. The bytes are still generated, streamed across the
    subgraph boundary and folded before anything blanks them, and a developer
    audience receives every one of them.

    LangGraph publishes the door. `pregel/_messages.py` gates the whole
    forward on `TAG_NOSTREAM not in tags`, so an invocation carrying the tag
    never reaches the stream at all.

    **This does not replace the fold**, and nothing here removes it. The fold
    guards three things the tag cannot: a mounted child's nodes (whose models
    this compiler never resolved), a tool's raw payload (a `ToolMessage`, not
    a model invocation), and the hand-rolled stand-ins this codebase passes
    around, which have no `with_config` at all. Those degrade to exactly
    today's behaviour, which is why the fallback below returns the model
    untouched rather than raising.

    Tags are **merged here, by hand, because the library replaces them.**
    Measured on the installed langchain-core 1.5.3 rather than assumed:

        r.with_config(tags=["mine"]).with_config(tags=["nostream"])
        # RunnableBinding config -> {'tags': ['nostream']}

    — `mine` is gone. Reasoning effort already binds these models
    (`_apply_effort`), so the naive spelling would silently drop a caller's
    tags on exactly the nodes this touches. Existing tags are read from both
    spellings for the same reason: a `BaseChatModel` carries them on `.tags`,
    a `RunnableBinding` in `.config["tags"]`, and both shapes reach here.

    **Every probe below is inside the `try`, and that is load-bearing rather
    than defensive habit.** `chat_model.UnconfiguredProvider` stands in for a
    model this machine has no credential for, and its rule is stated as *"a
    provider is required at the moment a model is used, not at the moment one
    is built"* — which it enforces by raising from `__getattr__`. So a bare
    `getattr(model, "with_config", None)` does not return `None` there, it
    raises `MissingProviderKey` **at compile time**, turning a workflow whose
    router never runs into one that cannot be built. Caught live by
    `test_behind_the_scenes.py`, not reasoned about here first.

    Any failure therefore leaves the model exactly as it was: a model that
    cannot be tagged still streams, which is today's behaviour, and the
    sentinel goes on raising at the moment it is genuinely used, with its own
    message rather than one from here.
    """
    if model is None:
        return None
    try:
        with_config = getattr(model, "with_config", None)
        if not callable(with_config):
            return model
        bound = getattr(model, "config", None)
        existing = tuple(
            getattr(model, "tags", None)
            or (bound.get("tags") if isinstance(bound, dict) else None)
            or ()
        )
        if NOSTREAM_TAG in existing:
            return model
        return with_config(tags=[*existing, NOSTREAM_TAG])
    except Exception:  # noqa: BLE001 — a model that cannot be tagged is not an error
        logger.debug("could not tag a model %s; its tokens still stream", NOSTREAM_TAG)
        return model


__all__ = ["MACHINERY_NODE_TYPES", "NOSTREAM_TAG", "silence_tokens"]
