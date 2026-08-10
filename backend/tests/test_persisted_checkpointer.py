"""A paused approval survives a restart — ticket 05, register RC-02/RC-03.

The gap this closes, stated as it was found: `api/main.py` held one
module-level `InMemorySaver` for the whole process, so a `human.approval`
pause died with the process. The dev stack restarts on *every file save*, so
"survives a restart" was not a hosting concern — it was a concern about
saving a file while someone was looking at an approval prompt.

The test that matters is `TestSurvivesARestart`: it starts a run, throws the
entire services object away, builds a NEW one against the same sqlite path,
and resumes the SAME thread. An `InMemorySaver` cannot pass it, which is what
makes it a guard against someone quietly reverting the default.
"""

from __future__ import annotations

import sys
from typing import Any

from openstategraph.api.services import WorkflowServices
from openstategraph.compile.node_runtime import RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.memory import (
    CHECKPOINT_FILE_NAME,
    CHECKPOINT_PATH_ENV,
    STATE_DIR_NAME,
    build_checkpointer,
    checkpoint_path,
    checkpointer_for,
)

from test_human_approval import approval_document


def _fake_model(answer: str = "Draft answer") -> Any:
    """`RespondingModel`, not `GenericFakeChatModel`: these runs go through
    `WorkflowServices.runtime_for`, which binds the memory tools, and
    `create_agent` therefore calls `bind_tools` — which the bare fake refuses.
    """
    from conftest import RespondingModel

    return RespondingModel([], default=answer)


class TestTheDefaultLocation:
    """Nothing configured must still mean durable — `openstategraph serve` for
    a stranger cannot silently lose an approval."""

    def test_the_default_is_a_sqlite_file_under_the_workflows_root(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        assert checkpoint_path(tmp_path) == tmp_path / STATE_DIR_NAME / CHECKPOINT_FILE_NAME

    def test_the_state_dir_is_hidden_from_the_workflow_listing(
        self, tmp_path, monkeypatch
    ) -> None:
        """The state dir lives *inside* the workflows root, so it must not
        read as a workflow. It holds no `workflow.json`, which is the store's
        own filter — pinned here because moving the file is otherwise a
        one-line change that adds a phantom workflow to every listing."""
        from openstategraph.api.workflow_store import WorkflowStore

        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        build_checkpointer(tmp_path)
        assert (tmp_path / STATE_DIR_NAME / CHECKPOINT_FILE_NAME).exists()
        assert WorkflowStore(root=tmp_path).list() == []

    def test_an_explicit_path_wins(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv(CHECKPOINT_PATH_ENV, str(tmp_path / "elsewhere" / "cp.sqlite"))
        assert checkpoint_path(tmp_path) == tmp_path / "elsewhere" / "cp.sqlite"

    def test_memory_is_the_documented_opt_out(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv(CHECKPOINT_PATH_ENV, "memory")
        assert checkpoint_path(tmp_path) is None
        assert type(build_checkpointer(tmp_path)).__name__ == "InMemorySaver"


class TestItSaysWhichOneItGot:
    """One log line at startup, either way. A limitation a user discovers by
    losing work is not a stated limitation."""

    def test_persistence_is_announced_with_the_path(self, tmp_path, monkeypatch, caplog) -> None:
        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        with caplog.at_level("INFO", logger="openstategraph.memory"):
            build_checkpointer(tmp_path)
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "approvals persist at" in message
        assert STATE_DIR_NAME in message

    def test_the_in_memory_opt_out_is_announced_as_a_loss(
        self, tmp_path, monkeypatch, caplog
    ) -> None:
        monkeypatch.setenv(CHECKPOINT_PATH_ENV, "memory")
        with caplog.at_level("WARNING", logger="openstategraph.memory"):
            build_checkpointer(tmp_path)
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "approvals are in-memory and will NOT survive a restart" in message

    def test_a_missing_sqlite_package_degrades_loudly_and_names_the_extra(
        self, tmp_path, monkeypatch, caplog
    ) -> None:
        """The default is sqlite, so the `[sqlite]` extra moved onto the
        `[server]` extra — but a hand-rolled install can still lack it, and
        that must never be silent (ticket 04's rule, applied to the default)."""
        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        monkeypatch.setitem(sys.modules, "langgraph.checkpoint.sqlite", None)
        with caplog.at_level("WARNING", logger="openstategraph.memory"):
            saver = build_checkpointer(tmp_path)
        message = " ".join(r.getMessage() for r in caplog.records)
        assert type(saver).__name__ == "InMemorySaver"
        assert "pip install 'openstategraph[sqlite]'" in message
        assert "approvals are in-memory and will NOT survive a restart" in message


class TestOneSeam:
    """`WorkflowServices` is the assembly point; there is no second wiring."""

    def test_services_hold_the_checkpointer_and_default_it_from_their_root(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        services = WorkflowServices(tmp_path)
        assert type(services.checkpointer).__name__ == "SqliteSaver"
        assert (tmp_path / STATE_DIR_NAME / CHECKPOINT_FILE_NAME).exists()

    def test_an_injected_checkpointer_wins_and_nothing_is_opened(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        sentinel = object()
        services = WorkflowServices(tmp_path, checkpointer=sentinel)
        assert services.checkpointer is sentinel
        assert not (tmp_path / STATE_DIR_NAME).exists()

    def test_the_api_module_holds_no_process_wide_saver_any_more(self) -> None:
        """The guard against reverting. A module-level saver is exactly the
        object that cannot be swapped, cannot be scoped to a test, and dies
        with the process."""
        from openstategraph.api import main

        assert not hasattr(main, "_HUMAN_IN_THE_LOOP_CHECKPOINTER")

    def test_the_app_resolves_its_checkpointer_at_startup(self, tmp_path, monkeypatch) -> None:
        """Wiring proof at the HTTP seam: `create_app` reaches the services'
        checkpointer, and resolves it at startup rather than on the first
        approval — so the log line is emitted before anyone can lose work."""
        from openstategraph.api.main import create_app

        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        app = create_app(workflows_root=tmp_path)
        assert type(app.state.services.checkpointer).__name__ == "SqliteSaver"
        assert (tmp_path / STATE_DIR_NAME / CHECKPOINT_FILE_NAME).exists()

    def test_a_document_asking_for_sqlite_still_overrides_the_default(
        self, tmp_path, monkeypatch
    ) -> None:
        """`settings.checkpointer: "sqlite"` predates this ticket and keeps
        its own per-workflow file — the default is the *fallback*, not a
        replacement for the document's own say."""
        monkeypatch.chdir(tmp_path)
        services = WorkflowServices(tmp_path, checkpointer=object())
        saver = checkpointer_for({"checkpointer": "sqlite"}, "my-flow", services.checkpointer)
        assert type(saver).__name__ == "SqliteSaver"
        assert (tmp_path / ".dev" / "checkpoints-my-flow.sqlite").exists()


class TestLoadWorkflowStillOwnsItsOwn:
    def test_an_explicit_checkpointer_beats_the_default(self, tmp_path, monkeypatch) -> None:
        """`load_workflow(checkpointer=...)` is the consumer owning durability
        themselves; the new default must never quietly outrank it."""
        import json

        from openstategraph import load_workflow

        monkeypatch.delenv(CHECKPOINT_PATH_ENV, raising=False)
        package = tmp_path / "root" / "tiny-flow"
        package.mkdir(parents=True)
        (package / "workflow.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "name": "tiny",
                    "nodes": [
                        {
                            "id": "node:input.text-1",
                            "type": "input.text",
                            "data": {},
                            "position": {"x": 0, "y": 0},
                        },
                        {
                            "id": "node:output.formatted-1",
                            "type": "output.formatted",
                            "data": {},
                            "position": {"x": 0, "y": 0},
                        },
                    ],
                    "edges": [
                        {
                            "source": {"nodeId": "node:input.text-1", "portId": "text"},
                            "target": {"nodeId": "node:output.formatted-1", "portId": "result"},
                        }
                    ],
                }
            )
        )
        from langgraph.checkpoint.memory import InMemorySaver

        mine = InMemorySaver()
        compiled = load_workflow(package, model=_fake_model("x"), checkpointer=mine)
        assert compiled.graph.checkpointer is mine
        # Nothing was opened on disk, because nothing needed to be.
        assert not (tmp_path / "root" / STATE_DIR_NAME).exists()


class TestSurvivesARestart:
    """The test that matters. Tear the whole services object down; build a new
    one against the same path; resume the same thread."""

    def _paused_graph(self, services: WorkflowServices, document: dict[str, Any]) -> Any:
        runtime = services.runtime_for(None, document, _fake_model("Draft answer"))
        return WorkflowCompiler().build(
            document,
            RunState,
            runtime.factory(document),
            checkpointer=services.checkpointer,
        )

    def test_an_approval_paused_before_a_restart_resumes_after_it(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setenv(CHECKPOINT_PATH_ENV, str(tmp_path / "checkpoints.sqlite"))
        document = approval_document()
        config = {"configurable": {"thread_id": "approval-across-restart"}}

        before = WorkflowServices(tmp_path)
        paused = self._paused_graph(before, document).invoke(
            {"question": "draft something", "attempts": 0, "decisions": {}, "outputs": {}},
            config,
        )
        assert "__interrupt__" in paused

        # The restart. Everything the first process held is unreachable now —
        # the services, the runtime, the compiled graph and the saver's
        # connection. Only the file on disk crosses.
        del paused
        before.checkpointer.conn.close()
        del before

        after = WorkflowServices(tmp_path)
        from langgraph.types import Command

        final = self._paused_graph(after, document).invoke(
            Command(resume={"decision": "approve"}), config
        )

        assert "__interrupt__" not in final
        assert final["decisions"]["node:human.approval-1"] == "approved"
        assert final["answer"] == "Draft answer"

    def test_the_same_run_is_lost_when_the_saver_is_in_memory(
        self, tmp_path, monkeypatch
    ) -> None:
        """The negative control. With the opt-out — which is exactly what the
        old module-level `InMemorySaver` gave everyone — the second process
        has never heard of the thread: the resume value is discarded and the
        approval is simply not there. If this ever starts recording an
        approval, the test above has stopped proving anything."""
        monkeypatch.setenv(CHECKPOINT_PATH_ENV, "memory")
        document = approval_document()
        config = {"configurable": {"thread_id": "approval-across-restart"}}

        before = WorkflowServices(tmp_path)
        self._paused_graph(before, document).invoke(
            {"question": "draft something", "attempts": 0, "decisions": {}, "outputs": {}},
            config,
        )
        del before

        after = WorkflowServices(tmp_path)
        from langgraph.types import Command

        final = self._paused_graph(after, document).invoke(
            Command(resume={"decision": "approve"}), config
        )
        # The exact shape of the loss, worth pinning rather than paraphrasing:
        # the answer the human gave is discarded, the graph runs from the top,
        # and they are asked to approve the same thing a second time.
        assert final.get("decisions", {}).get("node:human.approval-1") is None
        assert "__interrupt__" in final
