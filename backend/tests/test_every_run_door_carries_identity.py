"""Every door that starts a run carries the same identity — ship-it/54.

Ticket 47 taught `ask()` who is asking. Two of the three doors learned it; the
MCP door kept building `{"thread_id": ...}` alone, so a run started by a model
lost the one key that scopes a workflow's durable memory — its slug.

The tests below come in two shapes on purpose.

**Behaviour**, because a dict with four keys in it is not a reproduction. A
`memory.segment` node is the deterministic half of memory and reaches no model
at all, so a run through the MCP door can be *driven* and its ledger read: the
entry either lands under the workflow's own slug or it lands in the shared
`"unsaved"` bucket with every other workflow that ever ran over this transport.

**A census**, because tonight's recurring defect is not "this door is wrong",
it is "the fix reached some doors and not others". `TestNoFifthDoorCanForget`
walks the package for `configurable` dict literals and fails on one it has not
been told about — so a fifth door is a red test rather than a ticket filed in
three months by somebody reading a table.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any

import pytest

from openstategraph.api.services import WorkflowServices
from openstategraph.mcp_server import WorkflowLibrary, WorkflowRuns
from openstategraph.memory_segment import SEGMENT_ROOT


def _n(i: str, t: str, **d: Any) -> dict[str, Any]:
    return {"id": i, "type": t, "data": d, "position": {"x": 0, "y": 0}}


def _ledger_document() -> dict[str, Any]:
    """Input → tollbooth → output. Deterministic, model-free, and it writes."""
    return {
        "version": 2,
        "name": "Ledger",
        "nodes": [
            _n("in1", "input.text"),
            _n("seg1", "memory.segment", segment="crossings"),
            _n("out1", "output.formatted"),
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "seg1", "portId": "crossing"},
            },
            {
                "source": {"nodeId": "seg1", "portId": "onward"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    }


@pytest.fixture()
def services(tmp_path: Path) -> WorkflowServices:
    root = tmp_path / "workflows"
    root.mkdir()
    return WorkflowServices(workflows_root=root)


def _segment_namespaces(services: WorkflowServices) -> set[tuple[str, ...]]:
    return {
        tuple(ns)
        for ns in services.memory_store.list_namespaces()
        if tuple(ns)[:1] == (SEGMENT_ROOT,)
    }


class TestARunStartedOverMCPKnowsWhichWorkflowItIs:
    """The reproduction, and it is a durable write in the wrong place."""

    def test_a_crossing_is_stamped_with_the_workflows_own_slug(
        self, services: WorkflowServices
    ) -> None:
        WorkflowLibrary(services).save_draft("ledger-demo", "Ledger", _ledger_document())

        result = WorkflowRuns(services).run(slug="ledger-demo", question="the crossing")

        assert result["error"] is None
        assert _segment_namespaces(services) == {
            (SEGMENT_ROOT, "ledger-demo", "crossings")
        }, (
            "the MCP door dropped `workflow_slug`, so this workflow's ledger "
            "merged into the bucket every other MCP run shares"
        )

    def test_two_workflows_do_not_share_one_ledger(
        self, services: WorkflowServices
    ) -> None:
        """The consequence spelled out: without the slug these are one namespace."""
        library, runs = WorkflowLibrary(services), WorkflowRuns(services)
        library.save_draft("alpha", "Alpha", _ledger_document())
        library.save_draft("beta", "Beta", _ledger_document())

        runs.run(slug="alpha", question="from alpha")
        runs.run(slug="beta", question="from beta")

        assert _segment_namespaces(services) == {
            (SEGMENT_ROOT, "alpha", "crossings"),
            (SEGMENT_ROOT, "beta", "crossings"),
        }

    def test_an_inline_document_gains_no_identity_it_does_not_have(
        self, services: WorkflowServices
    ) -> None:
        """The inverse, and it is the honest half.

        A client that posts a document has no package and therefore no slug.
        The fallback stays the shared, visible `"unsaved"` label — inventing
        one here would be a fabricated identity, which is the failure mode the
        fix must not introduce while removing the other one.
        """
        result = WorkflowRuns(services).run(document=_ledger_document(), question="hi")

        assert result["error"] is None
        assert _segment_namespaces(services) == {(SEGMENT_ROOT, "unsaved", "crossings")}

    def test_the_door_does_not_fabricate_a_person(
        self, services: WorkflowServices
    ) -> None:
        """`user_email` has no honest source at this door and must stay empty.

        An MCP client is a model, not a person, and the HTTP door refuses a
        client-supplied `user_email` outright because the *server* determines
        it. So user-scoped memory stays unbound here — loudly, which is what
        `_user_namespace` already does with an empty value — rather than
        bound to a name nobody authenticated.
        """
        seen: dict[str, Any] = {}
        WorkflowLibrary(services).save_draft("ledger-demo", "Ledger", _ledger_document())
        runs = WorkflowRuns(services)

        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        original = WorkflowCompiler.build

        def spy(self: Any, *args: Any, **kwargs: Any) -> Any:
            graph = original(self, *args, **kwargs)
            inner = graph.ainvoke

            async def ainvoke(state: Any, config: Any = None, **kw: Any) -> Any:
                seen["configurable"] = dict((config or {}).get("configurable") or {})
                return await inner(state, config, **kw)

            graph.ainvoke = ainvoke  # type: ignore[method-assign]
            return graph

        WorkflowCompiler.build = spy  # type: ignore[method-assign]
        try:
            runs.run(slug="ledger-demo", question="hi")
        finally:
            WorkflowCompiler.build = original  # type: ignore[method-assign]

        assert seen["configurable"]["user_email"] == ""
        assert seen["configurable"]["session_id"] == ""
        assert seen["configurable"]["workflow_slug"] == "ledger-demo"
        assert seen["configurable"]["thread_id"].startswith("mcp-")


# ----------------------------------------------------- the census


def _package_root() -> Path:
    import openstategraph

    return Path(openstategraph.__file__).parent


def _ask_configurable_keys() -> set[str]:
    from openstategraph.loader import CompiledWorkflow

    source = inspect.getsource(CompiledWorkflow.ask)
    for node in ast.walk(ast.parse(source.strip())):
        if isinstance(node, ast.Dict) and any(
            isinstance(k, ast.Constant) and k.value == "thread_id" for k in node.keys
        ):
            return {k.value for k in node.keys if isinstance(k, ast.Constant)}
    raise AssertionError("`ask()` no longer builds a `configurable` dict literal")


#: Every module holding a `configurable` dict literal, and what it is.
#:
#: `run` — a door that starts a run, and therefore must build exactly the key
#: set `ask()` builds. `read` — code that *reads* `configurable` back, or
#: addresses a checkpoint thread, which is not an identity claim. `mount` — the
#: one deliberate partial: a child inherits the parent's identity and overrides
#: `workflow_slug` alone (`CLAUDE.md`, "State flows down"). `inherit` — passes
#: the identity it was handed through unchanged, claiming nothing and
#: overriding nothing, which is the only shape weaker than `mount`.
CLASSIFIED: dict[str, str] = {
    "loader.py": "run",
    "mcp_server.py": "run",
    "api/routes/runs.py": "run",
    # The mount family moved out of `node_runtime.py` (`docs-and-gaps/03`).
    # Both halves of this file's interest in it moved too: the classification
    # here, and the literal read by name in
    # `test_a_mount_overrides_only_the_workflow_slug` below.
    "compile/nodes/mount.py": "mount",
    "api/threads.py": "read",
    "generated_module_contract.py": "read",
    # The one accessor every other reader now goes through
    # (`organisms-first-class` 68). `memory.py`, `api/streaming.py` and
    # `prebuilt_session.py` left this table when they stopped spelling
    # `configurable` themselves; `tests/test_one_accessor_reads_run_identity.py`
    # is the census that keeps them from spelling it again.
    "run_identity.py": "read",
    # Addresses one stored thread to ask *where* its pause is waiting, and
    # starts nothing: a `thread_id` handed to `checkpointer.list` is a lookup
    # key, not a claim about who is running (`organisms-first-class` 64).
    "compile/paused_mount.py": "read",
    # An async subagent's `ainvoke`, in the agent family since
    # `docs-and-gaps/03`. It forwards the identity the middleware
    # was handed, unchanged and only when there is one — the child needs
    # `workflow_slug` and `thread_id` or a memory-scoped tool inside it
    # resolves both to nothing, and `memory.workflow_scope_slug` says a
    # nameless run *shares* a key. Not a door: it starts no run of ours and
    # decides no key.
    "compile/nodes/agent.py": "inherit",
}


def _modules_with_configurable() -> set[str]:
    root = _package_root()
    found = set()
    for path in root.rglob("*.py"):
        if '"configurable"' in path.read_text(encoding="utf-8"):
            found.add(path.relative_to(root).as_posix())
    return found


class TestNoFifthDoorCanForget:
    """The rule this ticket is really about: one seam, plus a test that fails
    when a new door forgets it. Three doors carried four keys; the fourth
    carried one for as long as nobody read them side by side."""

    def test_every_configurable_site_is_classified(self) -> None:
        unknown = _modules_with_configurable() - set(CLASSIFIED)
        assert not unknown, (
            "a new `configurable` site appeared and nothing says what it is. If "
            "it starts a run it must carry every key `ask()` carries; if it "
            "reads config back, classify it as `read` here with a reason: "
            f"{sorted(unknown)}"
        )

    def test_no_classified_module_has_vanished(self) -> None:
        """The census is only a census while its entries exist."""
        gone = set(CLASSIFIED) - _modules_with_configurable()
        assert not gone, f"classified but no longer present: {sorted(gone)}"

    @pytest.mark.parametrize(
        "module", sorted(m for m, kind in CLASSIFIED.items() if kind == "run")
    )
    def test_every_run_door_builds_the_keys_ask_builds(self, module: str) -> None:
        expected = _ask_configurable_keys()
        tree = ast.parse((_package_root() / module).read_text(encoding="utf-8"))

        literals = [
            {k.value for k in value.keys if isinstance(k, ast.Constant)}
            for node in ast.walk(tree)
            if isinstance(node, ast.Dict)
            for key, value in zip(node.keys, node.values)
            if isinstance(key, ast.Constant)
            and key.value == "configurable"
            and isinstance(value, ast.Dict)
        ]

        assert literals, f"{module} is classified as a run door and builds no config"
        for keys in literals:
            assert keys == expected, (
                f"{module} starts a run with {sorted(keys)} while `ask()` carries "
                f"{sorted(expected)} — ship-it/54's defect, at a new door"
            )

    def test_a_mount_overrides_only_the_workflow_slug(self) -> None:
        """The deliberate partial, pinned so it stays deliberate.

        A mounted child inherits the parent's `thread_id`, `user_email` and
        `session_id` untouched and re-binds its own workflow. A future edit
        that "completes" this dict to four keys would sever the child from the
        person the run is for.
        """
        module = _package_root() / "compile/nodes/mount.py"
        tree = ast.parse(module.read_text(encoding="utf-8"))
        literals = [
            {k.value for k in value.keys if isinstance(k, ast.Constant)}
            for node in ast.walk(tree)
            if isinstance(node, ast.Dict)
            for key, value in zip(node.keys, node.values)
            if isinstance(key, ast.Constant)
            and key.value == "configurable"
            and isinstance(value, ast.Dict)
        ]

        assert literals == [{"workflow_slug"}]
