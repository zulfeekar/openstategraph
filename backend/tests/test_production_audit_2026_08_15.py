"""Production audit 2026-08-15 — pins for what the sweep *proved true*.

Sibling of `test_architecture_audit_2026_08.py`, which pins the gaps the
2026-08-09 audit **closed**. This file pins the two things the 2026-08-15
sweep **measured and found sound**, because both are the kind of property
that decays silently:

1. **Compiling a package repeatedly leaks nothing.** Measured over 100
   `load_workflow()` cycles: zero file-descriptor growth, zero net object
   growth, flat heap — and identically so whether or not the caller closes
   the handle, because the `SqliteSaver` connection is released on collection.
   That result is only true while nothing hangs process-lifetime state off the
   compile path; the first module-level cache keyed by slug would break it, and
   nothing else would say so.

2. **An unregistered node family is reported, not swallowed.** The editor's
   half of "extend by registering" holds (walked in
   `src/core/extendability.test.ts`). The compiler's half **now does too**:
   ticket 08 made contributed families an entry-point group and left the
   built-in table un-shadowable, and `tests/test_node_families.py` is that
   seam's own pin.

   What stays here is the case that has no owner — a node type *nothing*
   implements, registered or built-in. The ticket asked the honest question
   (should it still be a silent `_passthrough`?) and answered no twice over:
   `validate_document` names the type, and the step itself says it produced
   nothing rather than forwarding the question and looking like it worked.
   Both are pinned below, because "reported" is exactly the property that
   decays to "silent" without anyone noticing.
"""

from __future__ import annotations

import gc
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "workflows" / "workflow-architect"


class _FakeModel:
    """A chat model that is never called — compilation must not need one."""

    def bind_tools(self, *_args: Any, **_kwargs: Any) -> "_FakeModel":
        return self

    def with_structured_output(self, *_args: Any, **_kwargs: Any) -> "_FakeModel":
        return self

    def invoke(self, *_args: Any, **_kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("compilation must not invoke the model")


def _open_fds() -> int:
    """How many descriptors this process holds, via the platform's own view."""
    return len(os.listdir("/dev/fd"))


class TestRepeatedCompilationReleasesEverythingItOpened:
    """The reproduction, frozen. Reading the code cannot establish this."""

    @pytest.mark.parametrize("close_the_handle", [True, False], ids=["closed", "dropped"])
    def test_no_descriptor_or_object_growth_over_many_cycles(
        self, tmp_path: Path, close_the_handle: bool
    ) -> None:
        from openstategraph.loader import load_workflow

        if not PACKAGE.exists():  # pragma: no cover - source checkout only
            pytest.skip("workflow package not present in this distribution")
        shutil.copytree(PACKAGE, tmp_path / PACKAGE.name)
        package_dir = tmp_path / PACKAGE.name

        # Warm up, so every lazy import and module-level cache is already paid
        # for. Without this the first cycle's import cost reads as a leak.
        for _ in range(3):
            load_workflow(package_dir, model=_FakeModel()).close()
        gc.collect()
        gc.collect()

        baseline_fds = _open_fds()
        baseline_objects = len(gc.get_objects())

        for _ in range(25):
            compiled = load_workflow(package_dir, model=_FakeModel())
            if close_the_handle:
                compiled.close()
            del compiled

        gc.collect()
        gc.collect()

        assert _open_fds() == baseline_fds, (
            "compiling the same package 25 times leaked file descriptors: "
            f"{baseline_fds} -> {_open_fds()}. Each compile opens a SqliteSaver; "
            "something is now holding one past collection."
        )
        # A small allowance: the interpreter's own bookkeeping moves by a few
        # objects between collections. A leak shows up as hundreds per cycle.
        drift = len(gc.get_objects()) - baseline_objects
        assert drift < 100, (
            f"25 compile cycles left {drift} objects behind — the compile seam "
            "is meant to be one-directional and to own nothing process-wide."
        )


def _unregistered_family_document() -> dict[str, Any]:
    """in -> a node type nothing implements -> out.

    `analyse.sentiment` is the audit's own example and is deliberately not
    registered anywhere: `tests/test_node_families.py` fakes a distribution
    that contributes it, and this file is about the case where nobody does.
    """
    return {
        "version": 1,
        "name": "audit",
        "settings": {},
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 0, "y": 0}},
            {"id": "s1", "type": "analyse.sentiment", "data": {}, "position": {"x": 200, "y": 0}},
            {"id": "o1", "type": "output.formatted", "data": {}, "position": {"x": 400, "y": 0}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "s1", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "s1", "portId": "result"},
                "target": {"nodeId": "o1", "portId": "text"},
            },
        ],
    }


class TestAnUnregisteredNodeFamilyIsNamedRatherThanSwallowed:
    """The compiler's builder table is not a registry — so say so, loudly."""

    def test_builder_lookup_is_total_and_falls_through_to_passthrough(self) -> None:
        from openstategraph.compile.node_runtime import NodeRuntime

        runtime = NodeRuntime(model=None)

        # Conventions that DO extend without an engine edit.
        assert runtime.builder_for("function.anything").__name__ == "_discovered_function"
        assert runtime.builder_for("workflow.subgraph").__name__ == "_subgraph"

        # A node type nothing implements — no built-in, no registered family.
        # Still total, still the passthrough, and the passthrough is the loud
        # one: see `test_the_skipped_step_says_so` below.
        assert runtime.builder_for("analyse.sentiment").__name__ == "_passthrough"

    def test_the_skipped_step_says_so_instead_of_forwarding_the_question(self) -> None:
        """Asked "what is 2+2?", a document with one unrecognised node used to
        answer "what is 2+2?" — which is what made the gap invisible."""
        from openstategraph.compile.diagnostics import Finding
        from openstategraph.compile.node_runtime import NodeRuntime
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        document = _unregistered_family_document()
        runtime = NodeRuntime(model=None)
        plan = WorkflowCompiler().plan(document)

        step = runtime.factory(document)("s1", document["nodes"][1], plan)
        update = step({"question": "what is 2+2?", "outputs": {"in1": "what is 2+2?"}})

        assert ("analyse.sentiment", "s1") in runtime.diagnostics.subjects(
            Finding.UNKNOWN_NODE_TYPE
        )
        assert "produced nothing" in update["outputs"]["s1"]

    def test_validate_document_names_the_unregistered_type(self) -> None:
        from openstategraph.validation import validate_document

        document = _unregistered_family_document()

        valid, findings = validate_document(document)

        assert valid is False
        assert any("analyse.sentiment" in finding and "s1" in finding for finding in findings), (
            "an unregistered node family compiles to a no-op passthrough; the only "
            f"thing that reports it is this finding, and it is missing: {findings}"
        )
        # Round-trips as JSON, because every transport renders these lines.
        json.dumps(findings)
