"""A compiled deep agent, presented as the chat model a ladder expects.

Carved out of `compile/node_runtime.py` (`docs-and-gaps/03`), unchanged. Its
own docstring already said where it belongs and why, in `CLAUDE.md`'s words:
`BaseGrader` and `Router` are deliberately model-agnostic, so the adaptation
lives at the compiler/runtime boundary rather than teaching a ladder about a
concrete agent construction — *a collaborator, not a shared ancestor*.

It is used by exactly two families, `route.grader` and `route.classifier`,
which is the definition of a cross-family concern in this project's rules and
therefore the reason it is a module of its own rather than a member of either
family's. A third ladder growing a deep tier imports it; it does not inherit
one.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from openstategraph.compile.reporting import _final_text


class _DeepAgentAsChatModel:
    """Makes a compiled deep agent look like the chat model `BaseGrader.grade()`
    expects — a bare `.invoke(messages) -> object with .content`.

    `BaseGrader` (`openstategraph/abc/grader.py`) is deliberately model-agnostic: it
    knows nothing about `create_deep_agent`, tiers, or LangChain harness
    tiers, and should not have to. So the adaptation lives here, at the
    compiler/runtime boundary, rather than teaching the grader ladder about a
    concrete agent construction — the same boundary rule CLAUDE.md states for
    cross-family concerns (a collaborator, not a shared ancestor).

    Built fresh **per grading call**, not once at compile time, because the
    system prompt — `messages[0]` — varies with the question being judged
    (`BaseGrader.resolve_system_prompt` appends it as context). Mirrors the
    worker's own fix for the identical shape of problem: `create_agent`'s
    `system_prompt=` construction parameter is the proven-working way to
    deliver a directive prompt, not a hand-assembled message list.
    """

    def __init__(self, model: Any, name: str, tags: tuple[str, ...] = ()) -> None:
        self._model = model
        self._name = name
        #: Applied to the *invocation*, never bound onto the model — see
        #: `invoke`. Empty by default; the machinery nodes pass `nostream`.
        self._tags = tuple(tags)

    def invoke(self, messages: list[Any]) -> Any:
        from openstategraph._extras import require_extra

        create_deep_agent = require_extra(
            "deepagents", "deep", "the deep-agent grader"
        ).create_deep_agent

        system_prompt = messages[0].content if messages else ""
        candidate_message = messages[-1]
        agent = create_deep_agent(
            # Deliberately the model as resolved, with nothing bound onto it.
            # `create_deep_agent` does not accept a `RunnableBinding` here: a
            # non-`BaseChatModel` is treated as a model *identifier*, and the
            # failure is `AttributeError: 'RespondingModel' object has no
            # attribute 'count'` from deep inside the string handling — a
            # sentence that names neither this call nor the binding that
            # caused it. So a tag that must reach this tier travels on the
            # invocation below instead, where LangChain propagates it down to
            # the child LLM run, which is the run `nostream` is read from.
            model=self._model,
            tools=[],
            system_prompt=system_prompt,
            name=self._name,
        )
        result = agent.invoke(
            {"messages": [candidate_message]}, config={"tags": list(self._tags)}
        )
        out = result.get("messages") or []
        text = _final_text(out)
        return SimpleNamespace(content=text if isinstance(text, str) else str(text))

__all__ = ["_DeepAgentAsChatModel"]
