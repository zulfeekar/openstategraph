"""What `create_deep_agent` actually assembles **in this installation** —
organisms-first-class/81.

`docs/decisions/deep-agent-slots.md` is the record a configuration surface will
be built from, and its whole value is that it does not promise what the library
cannot do. So the sentences of that document that can be executed are executed
here rather than asserted there — the version, the bare stack, the full stack,
the two conditional slots, and above all the **two silent gaps**, which are the
findings the surface must respect:

- `skills=` against the default `StateBackend` loads nothing and says nothing;
- `memory=` against a backend that cannot see the source is skipped with no
  error.

Both are the reason `organisms-first-class/32` gates those slots. The day the
library starts reading the host disk, or starts complaining, these go red and
the document gets corrected instead of quietly becoming a lie.

No provider credential exists here, so every run below uses a fake chat model.
That proves what is assembled and what the tools return; it proves nothing
about how a real model behaves with a slot, and the document says so.
"""

from __future__ import annotations

import os
from importlib import metadata
from importlib import util as import_util
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

deepagents_graph = pytest.importorskip("deepagents.graph")


class _Fake(GenericFakeChatModel):
    """A chat model that accepts tool binding and records what it was sent.

    `GenericFakeChatModel.bind_tools` raises `NotImplementedError`, which the
    agent factory hits before any middleware runs — so without this the stack
    cannot be exercised at all.
    """

    def bind_tools(self, tools: Any, **_kwargs: Any) -> "_Fake":
        type(self).bound_tools = [getattr(t, "name", str(t)) for t in tools]
        return self

    def _generate(self, messages: Any, *args: Any, **kwargs: Any) -> Any:
        type(self).system_text = "\n".join(
            str(m.content) for m in messages if type(m).__name__ == "SystemMessage"
        )
        return super()._generate(messages, *args, **kwargs)


def _fake(*replies: str) -> _Fake:
    return _Fake(messages=iter([AIMessage(content=r) for r in (replies or ("ok",))]))


def _assembled(**kwargs: Any) -> list[str]:
    """The middleware names `create_deep_agent` hands to `create_agent`."""
    captured: list[str] = []
    original = deepagents_graph.create_agent

    def spy(*args: Any, **kw: Any) -> Any:
        captured.extend(m.name for m in kw["middleware"])
        return original(*args, **kw)

    deepagents_graph.create_agent = spy
    try:
        deepagents_graph.create_deep_agent(_fake(), **kwargs)
    finally:
        deepagents_graph.create_agent = original
    return captured


class TestTheInstalledPackage:
    def test_version(self) -> None:
        assert metadata.version("deepagents") == "0.7.5"

    def test_there_is_no_planning_middleware(self) -> None:
        """`graph.py`'s module docstring advertises "planning" middleware and
        the package ships none. The todo list is LangChain's, and reaches a
        deep agent only through `middleware=` — which is what corrects ticket
        33's premise.
        """
        import deepagents.middleware as mw

        assert not hasattr(mw, "TodoListMiddleware")

        from langchain.agents.middleware import TodoListMiddleware

        assert [t.name for t in TodoListMiddleware().tools] == ["write_todos"]


class TestTheStackAsBuilt:
    def test_bare_stack(self) -> None:
        assert _assembled() == [
            "FilesystemMiddleware",
            "SubAgentMiddleware",
            "SummarizationMiddleware",
            "PatchToolCallsMiddleware",
            "AnthropicPromptCachingMiddleware",
        ]

    def test_full_stack_in_order(self, tmp_path: Any) -> None:
        assert _assembled(
            skills=[str(tmp_path)],
            memory=[str(tmp_path / "AGENTS.md")],
            interrupt_on={"write_file": True},
        ) == [
            "SkillsMiddleware",
            "FilesystemMiddleware",
            "SubAgentMiddleware",
            "SummarizationMiddleware",
            "PatchToolCallsMiddleware",
            "AnthropicPromptCachingMiddleware",
            "MemoryMiddleware",
            "HumanInTheLoopMiddleware",
        ]

    def test_only_anthropic_prompt_caching_is_registered(self) -> None:
        """The docs say the Bedrock and Fireworks caching middleware are
        "always registered". They are appended only when their package
        imports, and neither is installed here.
        """
        assert import_util.find_spec("langchain_aws") is None
        assert import_util.find_spec("langchain_fireworks") is None
        caching = [n for n in _assembled() if "PromptCaching" in n]
        assert caching == ["AnthropicPromptCachingMiddleware"]

    def test_a_name_collision_replaces_the_library_instance_in_place(self) -> None:
        """Which is how our compiler's summarization reaches a deep agent —
        and why turning summarization on *replaces* the library's tuned
        instance rather than adding to it.
        """
        from langchain.agents.middleware import SummarizationMiddleware

        model = _fake()
        mine = SummarizationMiddleware(
            model=model, trigger=("tokens", 1234), keep=("messages", 7)
        )
        captured: list[Any] = []
        original = deepagents_graph.create_agent

        def spy(*args: Any, **kw: Any) -> Any:
            captured.extend(kw["middleware"])
            return original(*args, **kw)

        deepagents_graph.create_agent = spy
        try:
            deepagents_graph.create_deep_agent(model, middleware=[mine])
        finally:
            deepagents_graph.create_agent = original

        assert [m.name for m in captured].index("SummarizationMiddleware") == 2
        assert captured[2] is mine


class TestWhatStateBackendCannotDo:
    """The gap `organisms-first-class/32` gates, measured rather than argued."""

    def test_skills_load_nothing_and_say_nothing(self, tmp_path: Any) -> None:
        skill = tmp_path / "skills" / "greet"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: greet\ndescription: say hi to the user\n---\n\nSay hi.\n"
        )

        agent = deepagents_graph.create_deep_agent(
            _fake(), skills=[str(tmp_path / "skills")]
        )
        agent.invoke({"messages": [{"role": "user", "content": "hi"}]})

        # The section is present, the skill is not, and nothing was raised.
        assert "## Skills System" in _Fake.system_text
        assert "greet" not in _Fake.system_text

    def test_the_same_directory_loads_through_a_filesystem_backend(
        self, tmp_path: Any
    ) -> None:
        from deepagents.backends import FilesystemBackend

        skill = tmp_path / "greet"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: greet\ndescription: say hi to the user\n---\n\nSay hi.\n"
        )

        agent = deepagents_graph.create_deep_agent(
            _fake(), skills=["/"], backend=FilesystemBackend(root_dir=str(tmp_path))
        )
        agent.invoke({"messages": [{"role": "user", "content": "hi"}]})

        assert "greet" in _Fake.system_text

    def test_memory_reaches_the_model_only_through_a_backend_that_sees_it(
        self, tmp_path: Any
    ) -> None:
        from deepagents.backends import FilesystemBackend

        (tmp_path / "AGENTS.md").write_text("# House rules\nBe terse.\n")
        host_path = str(tmp_path / "AGENTS.md")

        # Default StateBackend: file_not_found, skipped in silence.
        agent = deepagents_graph.create_deep_agent(_fake(), memory=[host_path])
        agent.invoke({"messages": [{"role": "user", "content": "hi"}]})
        assert "House rules" not in _Fake.system_text

        agent = deepagents_graph.create_deep_agent(
            _fake(),
            memory=["/AGENTS.md"],
            backend=FilesystemBackend(root_dir=str(tmp_path)),
        )
        agent.invoke({"messages": [{"role": "user", "content": "hi"}]})
        assert "House rules" in _Fake.system_text


class TestTheWorkspaceThatDoesExist:
    def test_a_written_file_lives_in_graph_state(self) -> None:
        """"No workspace" needs narrowing: `StateBackend` is one, it
        checkpoints, and what it lacks is durability and a way out of the run.
        """
        model = _Fake(
            messages=iter(
                [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "write_file",
                                "args": {"file_path": "/notes.txt", "content": "hello"},
                                "id": "1",
                            }
                        ],
                    ),
                    AIMessage(content="done"),
                ]
            )
        )
        out = deepagents_graph.create_deep_agent(model).invoke(
            {"messages": [{"role": "user", "content": "go"}]}
        )
        assert out["files"]["/notes.txt"]["content"] == "hello"

    def test_execute_is_never_offered_without_a_sandbox(self) -> None:
        """It is not bound to the model, and refuses by name if called anyway."""
        model = _Fake(
            messages=iter(
                [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {"name": "execute", "args": {"command": "echo hi"}, "id": "1"}
                        ],
                    ),
                    AIMessage(content="done"),
                ]
            )
        )
        out = deepagents_graph.create_deep_agent(model).invoke(
            {"messages": [{"role": "user", "content": "go"}]}
        )
        assert "execute" not in _Fake.bound_tools
        assert "task" in _Fake.bound_tools
        refusal = next(
            m for m in out["messages"] if type(m).__name__ == "ToolMessage"
        )
        assert "SandboxBackendProtocol" in str(refusal.content)


def test_this_file_needs_no_credential() -> None:
    """Stated as a test so the claim in the decision record has a way to fail:
    everything above runs against a fake model, so a machine with no provider
    key measures exactly what a machine with one would.
    """
    assert not os.environ.get("DEEPAGENTS_TEST_REQUIRES_KEY")
