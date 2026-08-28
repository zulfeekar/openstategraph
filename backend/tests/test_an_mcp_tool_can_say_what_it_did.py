"""`launch-readiness/157` — an MCP tool can say what it did, on both rails.

`record_notes` is called from `BaseTool.run`, and `prebuilt_mcp._wrap_async_tool`
re-wraps every remote tool as a plain `StructuredTool`. So until this file,
**no `tool.mcp` tool in any package could carry a `Correction` or a
`Substitution`** — which is why `117`, `127` and `139` were all stalled against
the one tool family that matters most here.

The fix is *not* "make it a `BaseTool`". `777e829` made MCP calls async-first
over a pooled session on a private daemon loop (1.21 s → 0.54 s), and
`async-first/11` established that the awaitable half never passes through
`_execute` at all — it reaches the agent as `StructuredTool(func, coroutine)`
already awaiting `run_on_mcp_loop_async`. So the question this file answers is
**how a tool that is legitimately not a `BaseTool` reaches the same recording
seam**, and the answer is that the seam moves to where the result is: the
wrapper reads the notes off the result envelope, records them on the run and
appends the model's half to the content, exactly as `BaseTool.run` does.

Where the notes come from is the other half. An MCP server is a stranger's, so
nothing here may infer a substitution from a payload shape — that would put one
package's vocabulary in `core/`. A server **declares** them, in its own result
envelope, under `notes`, and every candidate is validated against the
`ToolNote` union before it is believed. Tolerant in reading, strict in
trusting: an ordinary result carrying a column called `notes` is left alone,
which is the half that regresses and so is the half asserted hardest below.

Driven through a real compiled graph, not the wrapper alone. `async-first/16`
is the standing reason: five tools were reached in tests as
`tool.func(runtime=…)` and 5,783 green tests sat on a feature that crashed the
moment a model called it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from openstategraph import load_workflow
from openstategraph import prebuilt_mcp
from openstategraph.abc.tool_notes import take_notes

THREAD = "157-thread"
ANSWER = "Twelve vessels loaded there."

#: A substitution the *server* declares, in its own envelope. Nothing here
#: infers one from a payload shape.
DECLARED = {
    "kind": "substitution",
    "user_term": "Mongstad",
    "axis": "load_port",
    "canonical_value": "Mongstad [NO]",
    "how_matched": "declared_synonym",
}


class FakeRemoteTool:
    """What `load_mcp_tools` hands back: a coroutine, and no `func`."""

    def __init__(self, payload: Any, artifact: Any = None) -> None:
        self.name = "resolve_place"
        self.description = "Resolve a place name against this data."
        self.args_schema = {"type": "object", "properties": {"place": {"type": "string"}}}
        self.func = None
        self.response_format = "content_and_artifact"
        self.metadata: dict[str, Any] = {}
        self._payload = payload
        self._artifact = artifact

    async def coroutine(self, **kwargs: Any) -> tuple[Any, Any]:
        return (self._payload, self._artifact)


def discovery(tool: FakeRemoteTool):
    async def _discover(definition, headers, *, timeout):  # noqa: ANN001, ANN202
        return [tool]

    return _discover


class SilentModel(GenericFakeChatModel):
    """Calls the tool once, then answers without mentioning anything it read.

    Deliberately silent: `127`'s whole argument is that a model told about a
    substitution discloses it *most* of the time, and most of the time is the
    defect. `calls` keeps every message list the provider was handed, which is
    where the model rail is asserted.
    """

    calls: list[list[Any]] = []
    i: int = 0

    def __init__(self) -> None:
        super().__init__(messages=iter([]))
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "i", 0)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN202
        self.calls.append(list(messages))
        object.__setattr__(self, "i", self.i + 1)
        already = any(m.__class__.__name__ == "ToolMessage" for m in messages)
        if already:
            message = AIMessage(content=ANSWER)
        else:
            message = AIMessage(
                content="",
                tool_calls=[
                    {"name": "resolve_place", "args": {"place": "Mongstad"}, "id": "call-1"}
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):  # noqa: ANN001, ANN202
        return self.bind(tools=tools, tool_choice=tool_choice, **kwargs)

    def tool_messages(self) -> str:
        return "\n".join(
            str(m.content)
            for call in self.calls
            for m in call
            if m.__class__.__name__ == "ToolMessage"
        )


DOCUMENT: dict[str, Any] = {
    "version": 1,
    "name": "mcp notes",
    "nodes": [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        {
            "id": "agent1",
            "type": "agent.llm",
            "position": {"x": 200, "y": 0},
            "data": {"role": "Analyst", "systemPrompt": "Answer the question."},
        },
        {
            "id": "mcp1",
            "type": "tool.mcp",
            "position": {"x": 200, "y": 200},
            "data": {"servers": [{"id": "r0", "url": "http://127.0.0.1:9/mcp/"}]},
        },
        {"id": "out1", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
    ],
    "edges": [
        {
            "source": {"nodeId": "in1", "portId": "text"},
            "target": {"nodeId": "agent1", "portId": "prompt"},
        },
        {
            "source": {"nodeId": "mcp1", "portId": "tool"},
            "target": {"nodeId": "agent1", "portId": "tools"},
        },
        {
            "source": {"nodeId": "agent1", "portId": "result"},
            "target": {"nodeId": "out1", "portId": "result"},
        },
    ],
}


def _package(tmp_path: Path) -> Path:
    directory = tmp_path / "mcp-notes"
    directory.mkdir(parents=True)
    (directory / "workflow.json").write_text(
        json.dumps(
            {
                "version": 1,
                "name": "mcp notes",
                "savedAt": "2026-08-28T00:00:00Z",
                "document": DOCUMENT,
                "published": True,
            }
        )
    )
    return directory


def _run(tmp_path: Path, payload: Any, artifact: Any = None) -> tuple[str, SilentModel]:
    model = SilentModel()
    compiled = load_workflow(_package(tmp_path), model=model)
    result = compiled.graph.invoke(
        {"messages": [], "question": "How many vessels loaded at Mongstad?"},
        config={"configurable": {"thread_id": THREAD}},
    )
    return str(result.get("answer") or ""), model


@pytest.fixture(autouse=True)
def _a_clean_bucket(monkeypatch: pytest.MonkeyPatch):
    take_notes(THREAD)
    yield
    take_notes(THREAD)


@pytest.fixture
def remote(monkeypatch: pytest.MonkeyPatch):
    def _install(payload: Any, artifact: Any = None) -> None:
        monkeypatch.setattr(
            prebuilt_mcp, "_discover_tools", discovery(FakeRemoteTool(payload, artifact))
        )

    return _install


class TestTheReaderRail:
    def test_a_substitution_an_mcp_tool_declared_reaches_the_answer(
        self, tmp_path: Path, remote
    ) -> None:
        """`127`, for the tool family it could never fire on."""
        remote(json.dumps({"ok": True, "value": "Mongstad [NO]", "notes": [DECLARED]}))

        answer, model = _run(tmp_path, None)

        assert ANSWER in answer
        assert "Mongstad [NO]" in answer
        assert "Mongstad" in answer
        # The model never said it. The run did.
        assert "Mongstad [NO]" not in ANSWER

    def test_it_travels_in_the_structured_content_too(self, tmp_path: Path, remote) -> None:
        """An MCP result carries `structuredContent` beside its text, and the
        adapters hand it over as the artifact. A server that declares its notes
        there is declaring them in the same place."""
        remote("resolved", {"structured_content": {"ok": True, "notes": [DECLARED]}})

        answer, _ = _run(tmp_path, None)

        assert "Mongstad [NO]" in answer


class TestTheModelRail:
    def test_a_correction_an_mcp_tool_declared_reaches_the_model(
        self, tmp_path: Path, remote
    ) -> None:
        """`117`: a corrective rides on the result, in the same message."""
        remote(
            json.dumps(
                {
                    "ok": True,
                    "value": "Mongstad [NO]",
                    "notes": [{"kind": "next_step", "text": "Filter on load_port, not load_date."}],
                }
            )
        )

        _, model = _run(tmp_path, None)

        assert "Next step: Filter on load_port, not load_date." in model.tool_messages()

    def test_the_result_itself_is_still_delivered_whole(self, tmp_path: Path, remote) -> None:
        remote(json.dumps({"ok": True, "value": "Mongstad [NO]", "notes": [DECLARED]}))

        _, model = _run(tmp_path, None)

        assert '"Mongstad [NO]"' in model.tool_messages()
        assert "Substituted:" in model.tool_messages()


class TestSilenceIsStillTheDefault:
    def test_a_tool_that_declares_nothing_changes_nothing(self, tmp_path: Path, remote) -> None:
        remote(json.dumps({"ok": True, "row_count": 12}))

        answer, model = _run(tmp_path, None)

        assert answer == ANSWER
        assert "Substituted" not in model.tool_messages()
        assert "Next step" not in model.tool_messages()

    def test_free_prose_is_not_read_for_notes(self, tmp_path: Path, remote) -> None:
        remote("Mongstad is a port in Norway. notes: none.")

        answer, _ = _run(tmp_path, None)

        assert answer == ANSWER


class TestStrictInTrusting:
    def test_a_data_column_called_notes_is_not_a_note(self, tmp_path: Path, remote) -> None:
        """The widening test CLAUDE.md asks for. This product prints JSON as
        prose constantly; a `notes` column in a result set is ordinary data."""
        remote(
            json.dumps(
                {
                    "ok": True,
                    "rows": [{"port": "Mongstad [NO]", "notes": "cleared 2026-05-01"}],
                    "notes": "no remarks",
                }
            )
        )

        answer, model = _run(tmp_path, None)

        assert answer == ANSWER
        assert "Substituted" not in model.tool_messages()

    def test_an_unknown_kind_is_dropped_and_the_rest_survive(
        self, tmp_path: Path, remote
    ) -> None:
        remote(
            json.dumps(
                {
                    "ok": True,
                    "notes": [{"kind": "invented", "text": "trust me"}, DECLARED],
                }
            )
        )

        answer, _ = _run(tmp_path, None)

        assert "Mongstad [NO]" in answer
        assert "trust me" not in answer

    def test_a_substitution_missing_how_matched_is_refused(
        self, tmp_path: Path, remote
    ) -> None:
        """`how_matched` has no default on purpose: a substitution that cannot
        say how it knew is exactly the record `127` must be unable to make. A
        stranger's server may not supply one by omission."""
        incomplete = {k: v for k, v in DECLARED.items() if k != "how_matched"}
        remote(json.dumps({"ok": True, "notes": [incomplete]}))

        answer, _ = _run(tmp_path, None)

        assert answer == ANSWER


class TestTheAwaitablePathIsUnchanged:
    def test_both_entry_points_record(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`async-first/11`'s constraint. The sync shim and the coroutine are
        two doors onto one pooled session, and a rail on only one of them
        disappears under an async agent."""
        import asyncio

        from openstategraph.abc import tool_notes

        monkeypatch.setattr(tool_notes, "_current_thread", lambda: THREAD)
        wrapped = prebuilt_mcp._wrap_async_tool(
            FakeRemoteTool(json.dumps({"ok": True, "notes": [DECLARED]})), "a-server"
        )
        assert wrapped.func is not None
        assert wrapped.coroutine is not None

        take_notes(THREAD)
        wrapped.func(place="Mongstad")
        assert take_notes(THREAD), "the sync door recorded nothing"

        asyncio.run(wrapped.coroutine(place="Mongstad"))
        assert take_notes(THREAD), "the awaitable door recorded nothing"
