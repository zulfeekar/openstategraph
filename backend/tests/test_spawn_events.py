"""The `spawn` SSE event: seeing the moment a run creates a child.

Synthetic update payloads only — no model, no live stream. What is pinned
here is the *detection*, which is the part a live run cannot be relied on to
exercise reproducibly (a deep agent may or may not choose to spawn).
"""

from __future__ import annotations

from types import SimpleNamespace

from openstategraph.api.streaming import SPAWN_SNIPPET_CHARS, SpawnWatcher, _snippet


def test_fanout_plan_spawns_one_event_per_subtask() -> None:
    watcher = SpawnWatcher()
    update = {
        "subtasks": {
            "node:orch": [
                {"id": "t1", "instruction": "Traffic sources", "archetype": "researcher"},
                {"id": "t2", "instruction": "Conversion funnel", "archetype": "analyst"},
            ]
        }
    }
    spawns = watcher.inspect("node:orch", (), update, internal=False)

    assert [s["kind"] for s in spawns] == ["fanout", "fanout"]
    assert [s["label"] for s in spawns] == ["researcher", "analyst"]
    assert [s["taskId"] for s in spawns] == ["t1", "t2"]
    assert spawns[0]["parent"] == "node:orch"
    assert spawns[0]["instruction"] == "Traffic sources"


def test_a_subtask_is_announced_once_even_if_the_plan_is_re_emitted() -> None:
    """A revise lap re-writes `subtasks`; the same child must not spawn twice."""
    watcher = SpawnWatcher()
    update = {"subtasks": {"node:orch": [{"id": "t1", "instruction": "x", "archetype": "w"}]}}

    assert len(watcher.inspect("node:orch", (), update, internal=False)) == 1
    assert watcher.inspect("node:orch", (), update, internal=False) == []


def test_an_unlabelled_subtask_falls_back_to_its_id_for_a_label() -> None:
    watcher = SpawnWatcher()
    spawns = watcher.inspect(
        "node:orch",
        (),
        {"subtasks": {"node:orch": [{"id": "t9", "instruction": "y", "archetype": ""}]}},
        internal=False,
    )
    assert spawns[0]["label"] == "t9"


def test_deep_agent_task_tool_call_spawns_a_subagent_event() -> None:
    message = SimpleNamespace(
        tool_calls=[
            {
                "name": "task",
                "id": "call_1",
                "args": {"subagent_type": "research-agent", "description": "Summarise Q3"},
            },
            {"name": "read_file", "id": "call_2", "args": {"path": "a.md"}},
        ]
    )
    watcher = SpawnWatcher()
    spawns = watcher.inspect("model", (), {"messages": [message]}, internal=True)

    assert len(spawns) == 1
    assert spawns[0]["kind"] == "subagent"
    assert spawns[0]["label"] == "research-agent"
    assert spawns[0]["instruction"] == "Summarise Q3"
    assert spawns[0]["taskId"] == "call_1"


def test_a_task_call_arriving_as_a_plain_dict_is_detected_too() -> None:
    watcher = SpawnWatcher()
    update = {
        "messages": [
            {"tool_calls": [{"name": "task", "id": "c1", "args": {"description": "Dig"}}]}
        ]
    }
    spawns = watcher.inspect("model", (), update, internal=True)
    assert spawns[0]["label"] == "subagent"
    assert spawns[0]["instruction"] == "Dig"


def test_the_same_tool_call_is_not_announced_twice() -> None:
    watcher = SpawnWatcher()
    update = {"messages": [{"tool_calls": [{"name": "task", "id": "c1", "args": {}}]}]}
    assert len(watcher.inspect("model", (), update, internal=True)) == 1
    assert watcher.inspect("model", (), update, internal=True) == []


def test_a_new_namespace_head_spawns_once_and_names_its_parent() -> None:
    watcher = SpawnWatcher()
    watcher.inspect("node:in1", (), {}, internal=False)

    first = watcher.inspect("node:x", ("wf_music:abc123",), {}, internal=False)
    again = watcher.inspect("node:y", ("wf_music:abc123",), {}, internal=False)

    assert len(first) == 1
    assert first[0]["kind"] == "subgraph"
    assert first[0]["label"] == "wf_music"
    assert first[0]["parent"] == "node:in1"
    assert first[0]["namespace"] == ["wf_music:abc123"]
    assert again == []


def test_one_mounted_node_is_announced_once_however_many_checkpoints_it_gets() -> None:
    """A dispatched worker gets a fresh checkpoint id per instance (live finding)."""
    watcher = SpawnWatcher()
    first = watcher.inspect("node:agent", ("w_traffic:aaa",), {}, internal=False)
    second = watcher.inspect("node:agent", ("w_traffic:bbb",), {}, internal=False)

    assert len(first) == 1
    assert second == []


def test_a_namespace_belonging_to_a_nodes_own_loop_is_not_a_spawn() -> None:
    """`node_agent_llm_1` is an agent's compiled loop, not a new actor."""
    watcher = SpawnWatcher({"w_traffic": "node:w_traffic"})

    assert watcher.inspect("model", ("node_agent_llm_1:aaa",), {}, internal=True) == []
    announced = watcher.inspect("node:a", ("w_traffic:bbb",), {}, internal=False)
    assert [s["label"] for s in announced] == ["node:w_traffic"]


def test_a_frame_with_nothing_to_report_spawns_nothing() -> None:
    watcher = SpawnWatcher()
    assert watcher.inspect("node:a", (), {}, internal=False) == []
    assert watcher.inspect("node:a", (), {"answer": "hi"}, internal=False) == []


def test_the_instruction_snippet_is_flattened_and_truncated() -> None:
    long = "word " * 200
    snippet = _snippet(long)
    assert len(snippet) <= SPAWN_SNIPPET_CHARS
    assert snippet.endswith("…")
    assert _snippet("a\n  b") == "a b"
    assert _snippet(None) == ""
