"""The `spawn` SSE event: seeing the moment a run creates a child.

Synthetic update payloads only — no model, no live stream. What is pinned
here is the *detection*, which is the part a live run cannot be relied on to
exercise reproducibly (a deep agent may or may not choose to spawn).
"""

from __future__ import annotations

from types import SimpleNamespace

from openstategraph.api.streaming import (
    SPAWN_SNIPPET_CHARS,
    SpawnWatcher,
    _mount_ids,
    _snippet,
)


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


def test_an_agents_own_loop_is_not_announced_as_a_mounted_workflow() -> None:
    """`memory-and-replay/65` — the namespace head *is* a canvas node here.

    Captured off `POST /api/runs/stream` for the shipped `chinook-assistant`,
    a package with no `workflow.subgraph` node anywhere in it:

        node: model  internal: true
        namespace: ["agent_sql:b665d42a-cebf-07b1-2122-81a3b3f59e1e"]
        activeNode: agent-sql

    `create_agent` returns a compiled LangGraph, so an agent's ReAct loop gets
    its own checkpoint namespace named after the canvas node that owns it. The
    older guard only excluded a head that names *no* canvas node
    (`node_agent_llm_1`), so this one passed it, was announced `kind:
    "subgraph"`, and the editor's run surface reported the agent as **a mounted
    workflow** — with the mount's whole explanation and payload caption under
    it, in a run containing no mount.

    The compiler already knows the answer: `mount_slugs` is keyed by mount
    canvas node id, and for this package it is empty.
    """
    watcher = SpawnWatcher({"agent_sql": "agent-sql"}, mount_ids=set())
    watcher.inspect("in1", (), {}, internal=False)

    assert watcher.inspect("model", ("agent_sql:b665d42a",), {}, internal=True) == []


def test_a_mount_the_compiler_named_is_still_announced() -> None:
    watcher = SpawnWatcher({"wf_music": "wf-music"}, mount_ids={"wf-music"})

    announced = watcher.inspect("in1", ("wf_music:abc123",), {}, internal=False)

    assert [spawn["kind"] for spawn in announced] == ["subgraph"]
    assert announced[0]["label"] == "wf-music"


def test_no_compiler_answer_leaves_the_older_reading_in_place() -> None:
    """`None` is *the compiler did not say*, and is not `no mounts`.

    A scripted stub and a caller driving the fold by hand declare no runtime
    names. Suppressing on their behalf would silence a real mount on the
    evidence of a map nobody filled in — the accusation-without-evidence shape
    `serverReadiness` already refuses on the other side of the wire.
    """
    watcher = SpawnWatcher({"wf_music": "wf-music"})

    assert len(watcher.inspect("in1", ("wf_music:abc123",), {}, internal=False)) == 1


def test_the_compilers_answer_reaches_the_watcher() -> None:
    """A capability nothing uses is this repository's named recurring defect.

    So the seam is a function rather than three lines inside a fold: the two
    places a `SpawnWatcher` is built both call it, and it can be asked what it
    answers for each of the three shapes a runtime arrives in.
    """
    mounting = SimpleNamespace(
        names=SimpleNamespace(mount_slugs={"wf-music": "chinook-assistant"})
    )
    assert _mount_ids(mounting) == {"wf-music"}

    # A nested mount is keyed by its whole path; a namespace head only ever
    # names the outermost segment, which is the one a head can match.
    nested = SimpleNamespace(
        names=SimpleNamespace(
            mount_slugs={"mount-mid": "nested-mounts-mid", "mount-mid/mount-inner": "chained"}
        )
    )
    assert _mount_ids(nested) == {"mount-mid"}

    # The compiler saying "this document mounts nothing" — an answer, and the
    # one that fixes `chinook-assistant`.
    assert _mount_ids(SimpleNamespace(names=SimpleNamespace(mount_slugs={}))) == set()

    # Nobody said. Not the same claim, and it must not read as one.
    assert _mount_ids(SimpleNamespace()) is None
    assert _mount_ids(SimpleNamespace(names=None)) is None
