"""`launch-readiness/122`: the gate is above the send, in both copies.

`121` built the detectors and deliberately left the drawing alone. Both fired
on `workflows/support-triage`, and both were right:

- `REPEATED_SIDE_EFFECT` on `a-account` — three `tool.email-send` nodes bound
  to an agent that sits inside `router1 -> a-account -> grader1 -> router1`,
  with `RetryPolicy(max_attempts=3)` on top of the loop.
- `APPROVAL_COMES_TOO_LATE` on `gate1` — a `human.approval` reading *"This
  reply goes to a customer under your name. Approve to send it"*, **below** the
  only send capability in the document.

**Which copy was intended, and the evidence for it.** The packaged example has
never had the three nodes; the dev workspace copy arrived with them in
`ad52781` ("Six packages that existed only on this disk"). `workflow-gallery`
78 looked at the difference, declined to sync it either way, and said so. This
is that deferred question, answered — the three nodes are an **authoring
accident on the workspace copy**, and six facts say so:

1. Three copies of one capability, none of them configured (`"to": ""`).
2. On `a-account` only. If sending were the design, `a-billing` and
   `a-technical` would send too; they answer the same kind of ticket.
3. Ids `node:tool.email-send-1/2/3` — what the editor mints when a card is
   dragged onto the canvas — where every other node in the document carries an
   authored name (`a-account`, `gate1`, `out-sent`).
4. Above the gate, in a document whose whole promise is that nothing reaches a
   customer without it. The gate's own message says "Approve to send it".
5. Inside the revision cycle, so a `revise` lap sends again.
6. `gate1.approved` goes to `out-sent`, an `output.formatted`. Nothing on the
   approved path sends anything, so the capability was never reachable as a
   send in the first place.

So the drawing is corrected rather than re-designed: the three nodes and their
edges are gone, and the two copies now agree on the node set as well as on the
relay edge `78` synced.

**What this file pins is the invariant, not the deletion.** Asserting "there
are no `tool.email-send` nodes" would go green against a document that
reintroduced the hazard with a different capability. The rule
`docs-langchain` states — *"place side effects after `interrupt` calls"* — is
about the shape, so that is what is asserted: in either copy, no node upstream
of an approval gate holds a capability that acts outside the run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from openstategraph.compile.diagnostics import Finding
from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.api.services import WorkflowServices

ROOT = Path(__file__).resolve().parents[2]

COPIES = {
    "workspace": ROOT / "workflows" / "support-triage" / "workflow.json",
    "packaged": ROOT / "backend" / "openstategraph" / "examples" / "support-triage" / "workflow.json",
}


def _document(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    return payload.get("document", payload)


def _diagnostics(tmp_path: Path, document: dict[str, Any]) -> Any:
    """Every node's step built through the real runtime, so a finding recorded
    by a factory nobody calls cannot pass for one that fires."""
    runtime = WorkflowServices(tmp_path).runtime_for(None, document, None, warnings=[])
    plan = WorkflowCompiler().plan(document)
    factory = runtime.factory(document)
    for node in document["nodes"]:
        factory(node["id"], node, plan)
    return runtime.diagnostics


@pytest.mark.parametrize("copy", sorted(COPIES))
class TestNeitherCopyDrawsASendAboveItsGate:
    def test_the_send_cannot_repeat_because_there_is_none_to_repeat(
        self, copy: str, tmp_path: Path
    ) -> None:
        diagnostics = _diagnostics(tmp_path, _document(COPIES[copy]))
        assert not diagnostics.any(Finding.REPEATED_SIDE_EFFECT), diagnostics.warnings()

    def test_the_approval_is_not_below_the_action(
        self, copy: str, tmp_path: Path
    ) -> None:
        diagnostics = _diagnostics(tmp_path, _document(COPIES[copy]))
        assert not diagnostics.any(Finding.APPROVAL_COMES_TOO_LATE), diagnostics.warnings()

    def test_no_acting_capability_sits_above_an_approval(
        self, copy: str, tmp_path: Path
    ) -> None:
        """The invariant itself, read off the plan rather than off a type name,
        so a different acting capability drawn into the same place fails here
        too."""
        from openstategraph.compile.node_runtime import NodeRuntime, RuntimeServices
        from openstategraph.compile.side_effects import upstream_of

        document = _document(COPIES[copy])
        plan = WorkflowCompiler().plan(document)
        runtime = NodeRuntime(services=RuntimeServices(model=None))  # type: ignore[arg-type]
        runtime._types = {n["id"]: n["type"] for n in document["nodes"]}
        runtime._nodes = {n["id"]: n for n in document["nodes"]}
        gates = [n["id"] for n in document["nodes"] if n["type"] == "human.approval"]
        assert gates, "this example exists to draw an approval gate"
        for gate in gates:
            for source in upstream_of(gate, plan):
                assert runtime._acting_capabilities(source, plan) == [], (copy, gate, source)


class TestTheTwoCopiesNoLongerDisagreeAboutTheirNodes:
    """`78` recorded the node-set difference as deliberate-and-unsynced and
    deferred the question. It is answered, so the record must not go on saying
    a difference exists that does not."""

    def test_the_same_node_ids(self) -> None:
        ids = {
            name: sorted(n["id"] for n in _document(path)["nodes"])
            for name, path in COPIES.items()
        }
        assert ids["workspace"] == ids["packaged"]

    def test_the_packaged_agents_md_no_longer_claims_a_difference(self) -> None:
        text = (COPIES["packaged"].parent / "AGENTS.md").read_text()
        assert "thirteen" not in text
        assert "deliberately absent" not in text
