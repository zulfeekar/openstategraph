"""Two doors told two different stories about the same mounted run.

`every-workflow-green` 16. Ran `delegate-by-mount` — a router in front of two
mounted packages — with the identical payload on each door:

    /api/runs/stream   nested outputs: ['mount-sql/in1', 'mount-sql/answer1',
                                        'mount-sql/out1']
    /api/runs          nested: null

The streaming door **reconstructs** the child's per-node outputs from the frame
stream, keying each by its mount path. The blocking door reads the finished
state, and `_subgraph` returned only the child's answer — so nothing inside a
mount existed there to report on.

The consequence is not cosmetic. `silent_node_warnings` and
`node_failure_warnings` are called on the nested map by `streaming.py` and on
nothing by `runs.py`, so a node that went silent or failed **inside** a mount
was reported when you streamed the run and not when you POSTed it — and
`/api/runs` is the door an adopter embeds.

The mount now records what it already had in hand. This does not breach
subagent isolation, which is a rule about what the child *receives*:
`_subgraph`'s own docstring states it as "receives a task and reports a
result", and what the parent writes down about that is the parent's business.
"""

from __future__ import annotations

from openstategraph.compile.node_runtime import nested_record


class TestTheChildsOutputsAreRecordedUnderTheMount:
    def test_each_key_is_prefixed_with_the_mount_node(self) -> None:
        """The same prefix `streaming.py` mints, or the doors disagree anew."""
        record = nested_record("mount-sql", {"in1": "q", "answer1": "59", "out1": "59"})
        assert set(record) == {"mount-sql/in1", "mount-sql/answer1", "mount-sql/out1"}

    def test_the_values_are_carried_through(self) -> None:
        assert nested_record("m", {"a1": "text"})["m/a1"] == "text"

    def test_an_empty_child_records_nothing(self) -> None:
        assert nested_record("m", {}) == {}
        assert nested_record("m", None) == {}

    def test_a_silent_child_node_is_kept_not_dropped(self) -> None:
        """The empty string is the whole point — `silent_node_warnings` reads
        it. Dropping falsy values would delete the defect being reported."""
        assert nested_record("m", {"draft1": ""}) == {"m/draft1": ""}

    def test_a_non_mapping_is_refused_quietly(self) -> None:
        assert nested_record("m", "not a map") == {}

    def test_two_mounts_do_not_collide(self) -> None:
        merged = {**nested_record("m1", {"a": "1"}), **nested_record("m2", {"a": "2"})}
        assert merged == {"m1/a": "1", "m2/a": "2"}


class TestTheWarningsCanSeeIt:
    def test_a_silent_node_inside_a_mount_is_reportable(self) -> None:
        from openstategraph.compile.workflow_compiler import silent_node_warnings

        record = nested_record("mount-sql", {"answer1": ""})
        warnings = silent_node_warnings(record)
        assert warnings
        assert "mount-sql/answer1" in warnings[0]


class TestAMountedGraderThatGaveUp:
    """Found while verifying this ticket, in a live run.

    The streaming door reported *Grader "mount-web/grader1" ran out of attempts
    and published an answer it had rejected*, and the blocking door reported
    nothing — because `forced` was discarded at the mount boundary exactly as
    `outputs` was. One key was fixed and its twin was not, which is the same
    two-doors-two-truths defect one field along.
    """

    def test_a_child_force_pass_is_prefixed_like_its_outputs(self) -> None:
        record = nested_record("mount-web", {"grader1": "not sourced"})
        assert record == {"mount-web/grader1": "not sourced"}

    def test_it_reads_as_a_warning_naming_the_mount(self) -> None:
        from openstategraph.compile.workflow_compiler import forced_pass_warnings

        warnings = forced_pass_warnings(nested_record("mount-web", {"grader1": "too thin"}))
        assert warnings
        assert "mount-web/grader1" in warnings[0]
        assert "too thin" in warnings[0]

