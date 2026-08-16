"""Is this document one we can compile? One answer, every transport.

`ValidateWorkflowTool` is the seam that actually knows: it plans the graph in
memory, throws it away, and reports unknown node types, compiler warnings and
missing entry/exit points. This module is only the adapter that turns its
human-readable report into a verdict and a list of lines.

**Why it lives here and not in `mcp_server`.** It began there, under a comment
reading "No second validator lives here" — a rule about one transport that
became a rule about two the moment the editor needed the same check. MCP
validated before every run while the HTTP API could not validate at all, and
that asymmetry is what let a document containing an unregistered node type
reach a run and answer with the user's own question. A hand-written HTTP copy
would have been the same defect the provider catalogue was built to end.

Deliberately not a *gate*. Callers decide what a finding means: MCP refuses to
run an invalid document, because an LLM client can act on the findings and a
run that cannot produce a meaningful answer wastes a model call. The HTTP run
path does not refuse, because a canvas mid-edit is invalid most of the time and
`errors.py`'s "degrade loud, never silent" rule says an unknown node type is
reported rather than raised.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: The node types that mount another workflow as a child. One tuple, because
#: "which nodes hold a cross-package reference" is a single fact that three
#: readers need — this module, `knowledge_builders.mounted_slugs`, and
#: `schema`'s v2→v3 migration, which is what produced the name.
MOUNT_NODE_TYPES = ("workflow.subgraph",)


def validate_document(document: dict[str, Any]) -> tuple[bool, list[str]]:
    """`(valid, findings)` for one workflow document.

    `findings` is a list of single lines, never one blob: every caller renders
    them — the editor as a list, MCP as a reply — and a caller that has to
    split a string is a caller that will split it differently.
    """
    from openstategraph.prebuilt_architect import ValidateWorkflowTool

    result = ValidateWorkflowTool().run(document=json.dumps(document))
    report = result.error if result.error is not None else result.content
    findings = [line[2:].strip() for line in report.splitlines() if line.startswith("- ")]
    if result.error is not None and not findings:
        # A hard failure (unparseable, no nodes) has no bulleted list; the
        # message itself is the single finding.
        findings = [report.strip()]
    return result.error is None, findings


def mount_targets(document: dict[str, Any]) -> list[tuple[str, str]]:
    """`(node id, slug)` for every mount in this document, in canvas order.

    The slug may be empty — that is a mount nobody chose a package for, which
    is a real state of a canvas mid-edit and a real defect in a saved one. A
    reader that only wants the resolvable ones filters here rather than being
    handed a list that has already forgotten the difference.
    """
    found: list[tuple[str, str]] = []
    for node in document.get("nodes") or []:
        if str(node.get("type") or "") not in MOUNT_NODE_TYPES:
            continue
        data = node.get("data")
        slug = str((data or {}).get("workflow") or "").strip() if isinstance(data, dict) else ""
        found.append((str(node.get("id") or ""), slug))
    return found


def _read_package(root: Path, slug: str) -> dict[str, Any] | None:
    """One package's document, migrated, or `None` if there is no package."""
    manifest = root / slug / "workflow.json"
    if not manifest.is_file():
        return None
    try:
        from openstategraph.schema import normalize_document

        return normalize_document(json.loads(manifest.read_text()))
    except Exception:
        # Unreadable is not *absent*, and this function answers only the
        # second question. A malformed child is the child's own validation
        # failure, reported when somebody validates the child.
        return {}


def unresolved_mounts(
    document: dict[str, Any], root: Path, *, _seen: frozenset[str] = frozenset(), _chain: str = ""
) -> list[str]:
    """Mounts this document cannot reach, named — recursively (ticket 53).

    **Why this is not part of `validate_document`.** That function plans the
    graph *in memory*; a mount is the one thing in a document that points
    outside it, so answering "is it there" needs a workflows root, which a
    document does not carry. `validate` reported VALID for a package mounting
    `no-such-package-anywhere` for exactly that reason — not because the check
    was wrong, but because nothing had ever asked the question.

    Recursive, because the defect is a typo and a typo two packages down
    breaks the run just as completely. `_seen` closes the cycle: a
    self-including mount is refused at compile time with its own error, and
    this runs first, so it must terminate rather than let the better message
    never arrive.
    """
    findings: list[str] = []
    for node_id, slug in mount_targets(document):
        if not slug:
            where = f"{_chain} -> {node_id}" if _chain else node_id
            findings.append(
                f'Workflow node "{where}" has no workflow selected, so the step '
                "produces nothing. Pick a package on the node, or delete it."
            )
            continue
        if slug in _seen:
            continue
        child = _read_package(root, slug)
        if child is None:
            where = f"{_chain} -> {slug}" if _chain else slug
            findings.append(
                f'Mount "{where}" names a package that is not in {root} — check the '
                "slug, or copy the package into this workflows root."
            )
            continue
        findings.extend(
            unresolved_mounts(
                child,
                root,
                _seen=_seen | {slug},
                _chain=f"{_chain} -> {slug}" if _chain else slug,
            )
        )
    # One typo is one finding however many nodes repeat it, and the first
    # occurrence keeps its place — a list ordered by canvas is what a reader
    # can walk.
    return list(dict.fromkeys(findings))


__all__ = ["MOUNT_NODE_TYPES", "mount_targets", "unresolved_mounts", "validate_document"]
