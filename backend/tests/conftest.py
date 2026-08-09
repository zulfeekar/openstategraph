"""Shared test doubles.

Lives in `conftest.py` so pytest puts it on the path for every test module
(the suite deliberately has no `__init__.py` — see `pytest.ini`), and so
`RespondingModel` has one owner. It previously had five, in
`test_orchestrator_graph`, `test_intent_routed_workflow`,
`test_intent_routed_demo_file`, `test_chinook_demo_file` and
`test_code_workshop_file`, each carrying a docstring pointing at one of the
others as the original. They had already drifted: two dropped the `calls`
list, one dropped `bind_tools`, and only one still recorded *why* the fake
is predicate-driven. That is the failure mode the rule against duplicated
knowledge names — the `object.__setattr__` workaround below is a real fact
about the library, and five copies is how one of them ends up wrong.
"""

from __future__ import annotations

from typing import Callable

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

#: A predicate over the model's incoming context, and the reply to give.
RouteRule = tuple[Callable[[str], bool], str]


class RespondingModel(GenericFakeChatModel):
    """Answers by matching a **predicate** over the incoming message, not call order.

    A queue-based fake (`iter(["a", "b"])`) would make a test's correctness
    depend on which of two concurrently dispatched tasks happens to call the
    model first — which `Send` does not guarantee. Matching on content
    instead means the answer is deterministic regardless of dispatch order.

    A predicate rather than a substring, because substring containment
    cannot express what these tests actually need to distinguish: "the
    report has only task-1" is a *negative* condition (task-2 absent), and a
    grader's own prompt legitimately echoes the original question into its
    context, so a short worker-routing string is a genuine, unavoidable
    substring of the grader's call too. A predicate says exactly what is
    meant instead of fighting string containment to approximate it.

    `object.__setattr__` is not a style choice: `GenericFakeChatModel` is a
    Pydantic model and ordinary attribute assignment in `__init__` is
    refused.
    """

    rules: list[RouteRule] = []
    default: str = "PASS"
    #: Every context the model was called with, in order — what a test
    #: asserts against when it needs to prove *what the node was told*,
    #: not just what came back.
    calls: list[str] = []

    def __init__(self, rules: list[RouteRule], default: str = "PASS"):
        super().__init__(messages=iter([]))
        object.__setattr__(self, "rules", rules)
        object.__setattr__(self, "default", default)
        object.__setattr__(self, "calls", [])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        content = "\n".join(str(m.content) for m in messages)
        self.calls.append(content)
        answer = self.default
        for predicate, reply in self.rules:
            if predicate(content):
                answer = reply
                break
        return self._reply(answer)

    def _reply(self, text: str):  # noqa: ANN001
        from langchain_core.outputs import ChatGeneration, ChatResult

        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):  # noqa: ANN001
        """`GenericFakeChatModel.bind_tools` raises by default.

        Every caller needs this for the same reason, stated once here rather
        than five times: `create_agent` calls `bind_tools` for any agent
        given tools (the Chinook and workshop documents bind real ones), and
        `create_deep_agent` calls it *even with* `tools=[]`, because it
        always attaches its own filesystem/subagent tools. The fake still
        answers purely from message content; it never looks at what was
        bound.
        """
        return self.bind(tools=tools, tool_choice=tool_choice, **kwargs)
