"""The packaged copy of an example must not lose a feedback relay the dev
workspace copy has — `workflow-gallery` ticket 78.

`workflow-gallery` 48 wired `grader1.revise -> router1.feedback` into
`workflows/support-triage`, the live editor workspace. `1f63aff` had already
shipped a *packaged* copy at `backend/openstategraph/examples/support-triage`
— the one `pip install` actually ships — and 48 never touched it. The two
copies drifted silently across at least three commits: the packaged copy kept
compiling, kept passing its own tests, and kept firing `Finding.UNWIRED_REVISE`
exactly as designed, so nothing failed. The worked example that exists to
prove the router-relay feature stopped demonstrating it to anyone who installs
the product, and nothing said so.

This is the gate that would have caught it. `workflows/` is the live,
autosave-rewritten editor workspace — nothing here reads it to decide what
ships, only to check that what ships did not silently lose a capability the
dev copy has. The check is narrow on purpose: it compares only edges that
touch a `feedback` port or originate from a `revise` port (the router-relay
shape from `docs/decisions/router-feedback-input.md`), never full node or
edge sets. A packaged copy is allowed to omit nodes the dev copy carries —
`support-triage`'s three `tool.email-send` nodes are deliberately absent,
because a fresh install has no credentials for them (this ticket's own scope
decision) — so a full-graph comparison would be the wrong gate and would
falsely fail on that difference. It is walked across every package present
under both `workflows/` and the packaged examples directory, not just
`support-triage`, per the ticket's own "twenty other packages are in the same
wheel" note.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openstategraph import examples

REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_WORKFLOWS = REPO_ROOT / "workflows"


def _document(path: Path) -> dict:
    raw = json.loads(path.read_text())
    return raw.get("document", raw)


def _relay_edges(document: dict) -> set[tuple[str, str, str, str]]:
    """Edges that are part of the router-relay/feedback shape: anything
    landing on a `feedback` port, or leaving a `revise` port."""
    edges = set()
    for edge in document.get("edges", []):
        source, target = edge["source"], edge["target"]
        if target["portId"] == "feedback" or source["portId"] == "revise":
            edges.add((source["nodeId"], source["portId"], target["nodeId"], target["portId"]))
    return edges


def _slugs_present_in_both() -> list[str]:
    packaged = {p.parent.name for p in examples.DATA.glob("*/workflow.json")}
    dev = {p.parent.name for p in DEV_WORKFLOWS.glob("*/workflow.json")}
    return sorted(packaged & dev)


@pytest.mark.parametrize("slug", _slugs_present_in_both())
def test_packaged_copy_keeps_the_dev_copys_relay_edges(slug: str) -> None:
    dev_doc = _document(DEV_WORKFLOWS / slug / "workflow.json")
    packaged_doc = _document(examples.DATA / slug / "workflow.json")

    dev_relay = _relay_edges(dev_doc)
    packaged_relay = _relay_edges(packaged_doc)

    missing = dev_relay - packaged_relay
    assert missing == set(), (
        f"{slug}: the packaged copy is missing feedback/revise edge(s) the dev "
        f"workspace copy has: {sorted(missing)}. The dev workspace "
        "(workflows/) is the one under active development; if this edge is "
        "genuinely new capability, sync it into the packaged copy that ships "
        "in the wheel. Node-set differences (e.g. credentialed tool nodes "
        "deliberately absent from the packaged copy) are not flagged by this "
        "check — only relay wiring is."
    )
