"""Two Output nodes finished, and one answer was thrown away — `launch-readiness/174`.

`matchMode: "all"` is the platform's own parallel-router feature, and the
field's own hint invites the drawing: *"Run every match… they run in
parallel"*. Draw it the obvious way — a desk on each branch, an Output on each
desk — and both desks run, both Outputs finish, and `answer` is
`Annotated[str, LATEST_NONEMPTY]`, so one of the two answers is kept and
nothing anywhere says the other existed. Nine live runs across two documents,
2026-08-29; reproduced twice more here on `ollama:gpt-oss:120b-cloud` before a
line of this file was written.

**The reducer is not the defect and cannot be.** A reducer is handed one update
at a time, and LangGraph applies two updates landing in one superstep exactly
as it applies two landing in successive supersteps: `f(f(current, u1), u2)`.
So `LATEST_NONEMPTY` cannot tell a *supersession* — a mount writes `answer`,
then the Output downstream writes it again — from a *race*, and any reducer put
in its place would be wrong about one of the two. The question "how many exits
finished this run" is only answerable when the run is over, which is where this
fix lives.

**The join is the one `every-workflow-green` 27 already chose**, moved to the
last node instead of a node the author has to remember to draw. That ticket met
this loss one node upstream and answered it by *gathering* the branches into
`function.format_report` — not by refusing the drawing. `_upstream_text` joins
several producers into one node with `"\\n"`, so that is the join used here,
byte for byte: the shape the editor forbids (two producers into one Output, on
a `maxConnections: 1` port) and the shape the editor draws (an Output per desk)
now produce the *same string*, which is asserted below rather than described.
That equality is the whole answer to the inversion the ticket found — the
platform's working answer used to be unreachable through its own UI, and the
reachable one lost half the work.

Disclosure rides on the developer channel and not the customer one, and the
reason is that nothing is being withheld any more: `published_rejected` is on
both audiences because a customer who was handed a rejected answer has a fact
they cannot otherwise learn. A customer handed both halves has lost nothing;
*which nodes* produced them is a fact about the drawing, which is what
`warnings` is for.

Every assertion below drives a real compiled graph over a real document
through a real door, because that is where this defect lives: the reducer,
`_output` and every single-writer test in this suite are all green on the
broken behaviour, which is how it survived to beta.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from conftest import RespondingModel
from openstategraph.loader import load_workflow

COST = "COST: about two weeks of an engineer's time."
RISK = "RISK: an hour of downtime for the billing cutover."


class _TwoDesks(RespondingModel):
    """A classifier that names both branches, and a desk per system prompt."""

    def __init__(self) -> None:
        super().__init__(
            rules=[
                (lambda c: "only the cost side" in c, COST),
                (lambda c: "only the risk side" in c, RISK),
            ],
            default="cost and risk",
        )


def _node(node_id: str, node_type: str, **data: Any) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "title": node_id,
        "data": dict(data),
        "position": {"x": 0, "y": 0},
    }


def _edge(src: str, src_port: str, dst: str, dst_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": src_port},
        "target": {"nodeId": dst, "portId": dst_port},
    }


_DESKS = [
    _node("in1", "input.text"),
    _node(
        "router",
        "route.classifier",
        matchMode="all",
        fallback="cost",
        branches=[{"id": "b1", "name": "cost"}, {"id": "b2", "name": "risk"}],
        rules="Money goes to 'cost'. Danger goes to 'risk'. Both goes to both.",
        rulesMode="extend",
    ),
    _node("costdesk", "agent.llm", systemPrompt="Answer only the cost side."),
    _node("riskdesk", "agent.llm", systemPrompt="Answer only the risk side."),
]

_TO_DESKS = [
    _edge("in1", "text", "router", "question"),
    _edge("router", "branch:b1", "costdesk", "prompt"),
    _edge("router", "branch:b2", "riskdesk", "prompt"),
]


def _package(tmp_path: Path, name: str, nodes: list, edges: list) -> Path:
    directory = tmp_path / name
    directory.mkdir(parents=True)
    (directory / "workflow.json").write_text(
        json.dumps(
            {
                "version": 1,
                "name": name,
                "document": {"version": 3, "name": name, "nodes": nodes, "edges": edges},
            }
        )
    )
    return directory


def _two_exits(tmp_path: Path) -> Path:
    """The drawing the editor permits, and the one that lost an answer."""
    return _package(
        tmp_path,
        "two-exits",
        [*_DESKS, _node("out1", "output.formatted"), _node("out2", "output.formatted")],
        [
            *_TO_DESKS,
            _edge("costdesk", "result", "out1", "result"),
            _edge("riskdesk", "result", "out2", "result"),
        ],
    )


def _one_exit(tmp_path: Path) -> Path:
    """The drawing the editor forbids — two producers on a `maxConnections: 1`
    port — which the backend has always compiled, and which has always been
    right."""
    return _package(
        tmp_path,
        "one-exit",
        [*_DESKS, _node("out1", "output.formatted")],
        [
            *_TO_DESKS,
            _edge("costdesk", "result", "out1", "result"),
            _edge("riskdesk", "result", "out1", "result"),
        ],
    )


def _request() -> dict[str, Any]:
    """The two-exit document, posted the way the editor posts one."""
    return {
        "workflow": {
            "version": 3,
            "name": "two-exits",
            "nodes": [
                *_DESKS,
                _node("out1", "output.formatted"),
                _node("out2", "output.formatted"),
            ],
            "edges": [
                *_TO_DESKS,
                _edge("costdesk", "result", "out1", "result"),
                _edge("riskdesk", "result", "out2", "result"),
            ],
        },
        "workflow_slug": "two-exits",
        "question": "What will it cost and what could go wrong?",
    }


def _ask(package: Path) -> Any:
    workflow = load_workflow(package, model=_TwoDesks())
    return workflow.ask("What will it cost and what could go wrong?")


class TestBothDesksReachTheCaller:
    def test_the_library_door_publishes_both_answers(self, tmp_path: Path) -> None:
        answer = _ask(_two_exits(tmp_path))
        assert COST in str(answer)
        assert RISK in str(answer)

    def test_the_forbidden_fan_in_and_the_drawable_shape_say_the_same_thing(
        self, tmp_path: Path
    ) -> None:
        """The inversion, pinned. If these ever disagree again, one of the two
        drawings is losing work."""
        assert str(_ask(_two_exits(tmp_path))) == str(_ask(_one_exit(tmp_path)))

    def test_a_warning_names_the_exits_that_both_finished(self, tmp_path: Path) -> None:
        result = _ask(_two_exits(tmp_path))
        said = " ".join(result.warnings)
        assert "out1" in said and "out2" in said

    def test_the_second_answer_is_not_a_failure(self, tmp_path: Path) -> None:
        """A run with two exits is a report about how the answer was reached,
        never a claim the run broke — `cli.run_exit_code` reads `failures`."""
        assert _ask(_two_exits(tmp_path)).failures == []


class TestOneExitIsUntouched:
    def test_a_single_exit_answers_exactly_as_before(self, tmp_path: Path) -> None:
        result = _ask(_one_exit(tmp_path))
        assert result.warnings == []
        assert COST in str(result) and RISK in str(result)


class TestTheHttpDoors:
    @pytest.fixture()
    def client(self, tmp_path: Path) -> Any:
        from fastapi.testclient import TestClient

        from openstategraph import chat_model as chat_model_module
        from openstategraph.api.main import create_app

        _two_exits(tmp_path)
        original = chat_model_module.build_chat_model
        chat_model_module.build_chat_model = lambda _name: _TwoDesks()
        yield TestClient(create_app(workflows_root=tmp_path))
        chat_model_module.build_chat_model = original


    def test_the_blocking_door_publishes_both(self, client: Any) -> None:
        body = client.post(
            "/api/runs",
            json=_request(),
        ).json()
        assert COST in body["answer"] and RISK in body["answer"]

    def test_the_streaming_door_publishes_both(self, client: Any) -> None:
        with client.stream(
            "POST",
            "/api/runs/stream",
            json=_request(),
        ) as response:
            body = "".join(response.iter_text())
        done = [
            json.loads(frame.split("data: ", 1)[1])
            for frame in body.split("\n\n")
            if frame.startswith("event: done\n")
        ]
        assert done, body[-400:]
        answer = str(done[-1].get("answer") or "")
        assert COST in answer and RISK in answer


class TestNoSixthDoorWritesItsOwn:
    """The seam, guarded the way `api/diagram.py` and `run_doors.py` are.

    Five doors each wrote `str(final.get("answer") or "")`, and that is not a
    style complaint: measured above, the streaming door published the cost desk
    and the blocking door the risk desk **for the same run**, because the fold
    and the reducer race independently. Four call sites that must each remember
    the same call is a defect with a fifth instance waiting, so the *absence* of
    the wrong call is the test.

    Parsed rather than grepped, because the modules' own prose quotes the wrong
    call while explaining why it is wrong — this file's header included.

    `final` and `values` are the names a **finished** state carries in this
    package; a node body's `state` is mid-run and reading `answer` off it is
    ordinary and correct (`_output`'s own fallback does it), so it is not
    flagged.
    """

    FINISHED_STATE = ("final", "values")

    #: The one module holding a `final` that is not a compiled workflow's.
    #: `api/routes/demo.py` is the hand-built Chinook loop that predates the
    #: canvas, registered only when `create_app` is handed a `graph_factory`,
    #: which nothing in this package ever does. Its state has no `published`
    #: channel because it has no Output node — it has neither the defect nor
    #: anywhere to put the fix. Named here for the reason
    #: `test_a_fan_out_answers_the_blocking_door.py` names it: passed over
    #: silently is how an exemption becomes a hole.
    NOT_A_RUN = {"api/routes/demo.py"}

    def test_no_module_reads_a_finished_states_answer_directly(self) -> None:
        import ast
        from pathlib import Path

        import openstategraph

        root = Path(openstategraph.__file__).parent
        offenders: list[str] = []
        for module in sorted(root.rglob("*.py")):
            if module.relative_to(root).as_posix() in self.NOT_A_RUN:
                continue
            tree = ast.parse(module.read_text())
            for node in ast.walk(tree):
                receiver = key = None
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                ):
                    receiver, key = node.func.value, node.args[0].value
                elif isinstance(node, ast.Subscript) and isinstance(
                    node.slice, ast.Constant
                ):
                    receiver, key = node.value, node.slice.value
                if key != "answer" or not isinstance(receiver, ast.Name):
                    continue
                if receiver.id in self.FINISHED_STATE:
                    offenders.append(
                        f"{module.relative_to(root).as_posix()}:{node.lineno}"
                    )

        assert offenders == [], (
            "a finished run's answer is assembled by "
            "`openstategraph.compile.state.published_answer` — a door that reads "
            "`answer` itself publishes one exit of a run that may have finished "
            "at several: " + ", ".join(offenders)
        )

    def test_every_door_that_publishes_an_answer_uses_the_seam(self) -> None:
        from pathlib import Path

        import openstategraph

        root = Path(openstategraph.__file__).parent
        for door in (
            "loader.py",
            "api/routes/runs.py",
            "api/streaming.py",
            "api/threads.py",
            "mcp_server.py",
        ):
            assert "published_answer(" in (root / door).read_text(), door
