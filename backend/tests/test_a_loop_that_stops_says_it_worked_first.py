"""A node whose tool loop ended saying nothing reports that, not "produced no output".

`production-ready` 96, and the ticket's own question was *which of two readings
is true*. It was settled by tapping the raw Ollama wire underneath
`ChatOllama`, on a live `chinook-assistant` run against `gpt-oss:120b-cloud`.
The lap that ends an agent's loop arrives like this:

    ChatResponse(done=True, done_reason='stop', eval_count=11,
                 message=Message(role='assistant', content='',
                                 thinking=None, tool_calls=None))

**Nothing is lost in extraction.** `thinking` is `None` on the wire, so the
harmony/reasoning-channel reading is false: `langchain_ollama` does drop
`message.thinking` whenever `reasoning` is unset, but there is no thinking on
this lap to drop. The eleven tokens are the model's scaffolding around an empty
turn. Every lap that *did* produce something carried a `thinking` block of
150–858 characters beside its tool calls; the terminating laps carried nothing
in any channel.

So the model genuinely stopped, and `_final_text` returning `""` is correct.
That leaves the second half of the ticket, which is the whole of this fix: a
node that ran three tools and then went quiet is a different report from a node
that never ran, and both were one sentence.

    Node "agent-sql" produced no output. The run continued with the previous
    answer, so what you are reading came from an earlier step.

That sentence is true of both and actionable for neither. A reader of the first
needs to know the node *worked* — it called tools, it got results back, and the
model then ended its turn without writing an answer, which is a run to retry.
A reader of the second is looking at a node that never got started.

Deliberately **not** fixed here, and both were priced in the ticket:

- Nothing retries the empty lap. Retry is a graph-assembly parameter in this
  project (`CLAUDE.md`, "Retry, timeout and caching"), never a node concern,
  and inventing a node-level retry to paper over a provider's empty turn is the
  symptom fix `production-ready/73` already priced and rejected once.
- Nothing widens extraction. The measurement above says there is nothing there
  to widen towards, and "tolerant in reading" is not licence to invent a
  channel the wire does not carry.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from openstategraph.compile.node_runtime import (
    NodeRuntime,
    RunState,
    chinook_tool_registry,
)
from openstategraph.compile.workflow_compiler import (
    run_health,
    run_health_from_state,
    silent_node_warnings,
    WorkflowCompiler,
)

from conftest import RespondingModel


class TestTheSentenceSeparatesTwoDifferentReports:
    """The reporting layer, asked directly."""

    def test_a_node_that_never_ran_keeps_the_sentence_it_had(self) -> None:
        """The ordinary case, pinned so the widening cannot take it with it."""
        assert silent_node_warnings({"a1": ""}) == [
            'Node "a1" produced no output. The run continued with the previous '
            "answer, so what you are reading came from an earlier step."
        ]

    def test_a_node_with_tools_bound_and_none_used_keeps_it_too(self) -> None:
        """Bound-but-unused is a *capability* report and already has its own
        door (`used_no_tools`). It is not what this ticket measured, and it
        must not start borrowing this sentence."""
        tool_use = {"a1": {"bound": ["chinook_execute_sql"], "ran": []}}
        assert silent_node_warnings({"a1": ""}, tool_use)[0].startswith(
            'Node "a1" produced no output.'
        )

    def test_a_loop_that_ran_tools_and_then_went_quiet_says_so(self) -> None:
        """The defect. The measured shape: tools ran, the loop ended empty."""
        tool_use = {
            "a1": {
                "bound": ["chinook_list_tables", "chinook_get_table_schema"],
                "ran": ["chinook_list_tables", "chinook_get_table_schema"],
            }
        }
        (warning,) = silent_node_warnings({"a1": ""}, tool_use)
        assert "chinook_list_tables" in warning
        assert "chinook_get_table_schema" in warning
        assert "ended its turn without writing an answer" in warning
        # Still says what a reader downstream needs — the half that was
        # already right must not be traded away for the half that was not.
        assert "came from an earlier step" in warning

    def test_a_node_with_no_model_is_untouched(self) -> None:
        """The third sentence in this function, which has nothing to do with
        tools and whose fix is a setting rather than a retry."""
        from openstategraph.compile.workflow_compiler import NO_MODEL_MARKER

        tool_use = {"a1": {"bound": ["t"], "ran": ["t"]}}
        assert "had no model configured" in silent_node_warnings(
            {"a1": NO_MODEL_MARKER}, tool_use
        )[0]

    def test_a_node_that_answered_reports_nothing_however_many_tools_ran(self) -> None:
        tool_use = {"a1": {"bound": ["t"], "ran": ["t"]}}
        assert silent_node_warnings({"a1": "an answer"}, tool_use) == []


class TestBothDoorsReadIt:
    """A sentence only `silent_node_warnings` can produce is a sentence nobody
    reads. `run_health` is where the doors meet, and its parameter names *are*
    the state keys — see `run_health_from_state`."""

    def test_run_health_carries_the_new_report(self) -> None:
        health = run_health(
            {"a1": ""},
            {},
            {},
            {},
            None,
            {"a1": {"bound": ["chinook_list_tables"], "ran": ["chinook_list_tables"]}},
        )
        assert health.failures == []
        assert "ended its turn without writing an answer" in health.silent[0]

    def test_the_library_door_reads_tool_use_off_the_state(self) -> None:
        health = run_health_from_state(
            {
                "outputs": {"a1": ""},
                "tool_use": {
                    "a1": {"bound": ["chinook_list_tables"], "ran": ["chinook_list_tables"]}
                },
            }
        )
        assert "ended its turn without writing an answer" in health.silent[0]

    def test_the_streaming_door_reads_it_too(self) -> None:
        """`/api/runs/stream` calls `run_health` positionally rather than off
        the signature, so it is the one door that can silently fall behind —
        which is exactly how this assembly drifted twice before
        (`every-workflow-green` 14, 16)."""
        import inspect

        from openstategraph.api import streaming

        source = inspect.getsource(streaming)
        call = source.split("health = run_health(")[1].split(")")[0]
        assert "tool_use" in call, (
            "the streaming door does not pass tool_use, so a loop that stopped "
            "reads as a node that never ran on the door both shipped UIs use"
        )


class _StopsAfterOneTool(RespondingModel):
    """The measured provider behaviour, scripted.

    First call: one tool call, no content. Second call: an `AIMessage` with
    `content=''`, no tool calls, nothing in `additional_kwargs` — byte for byte
    the shape the wire carried, minus the token counts nothing reads.
    """

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        content = "\n".join(str(m.content) for m in messages)
        self.calls.append(content)
        already_called = any(getattr(m, "type", None) == "tool" for m in messages)
        if already_called:
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content=""))]
            )
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "chinook_list_tables",
                                "args": {},
                                "id": "call_1",
                            }
                        ],
                    )
                )
            ]
        )


def _document() -> dict[str, Any]:
    """input -> agent (with one tool on its bus) -> output."""
    return {
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            {"id": "a1", "type": "agent.llm", "data": {}},
            {"id": "t1", "type": "tool.chinook-get-all-tables", "data": {}},
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "a1", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "t1", "portId": "tool"},
                "target": {"nodeId": "a1", "portId": "tools"},
            },
            {
                "source": {"nodeId": "a1", "portId": "result"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    }


class TestTheLiveSymptomPinnedWithoutAModel:
    """End to end through a real compiled graph, so a fix wired into the wrong
    function cannot stay green. Nothing here asks `silent_node_warnings`
    anything — it runs the node and reads the report a door would."""

    def _final_state(self) -> dict[str, Any]:
        model = _StopsAfterOneTool([], default="")
        runtime = NodeRuntime(model=model, tools=chinook_tool_registry())
        graph = WorkflowCompiler().build(_document(), RunState, runtime.factory(_document()))
        return graph.invoke(
            {"question": "top artists by revenue", "attempts": 0, "decisions": {}, "outputs": {}},
            {"recursion_limit": 40},
        )

    def test_the_node_is_silent_and_the_tool_really_ran(self) -> None:
        """The premise, measured rather than assumed — if the tool did not run
        the test below would be asserting about the wrong situation."""
        state = self._final_state()
        assert state["outputs"]["a1"] == ""
        assert state["tool_use"]["a1"]["ran"] == ["chinook_list_tables"]

    def test_the_report_names_the_tools_the_loop_got_through(self) -> None:
        health = run_health_from_state(self._final_state())
        (warning,) = [w for w in health.silent if 'Node "a1"' in w]
        assert "chinook_list_tables" in warning
        assert "ended its turn without writing an answer" in warning
