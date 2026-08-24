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
    valid = result.error is None
    if valid:
        # `plan.advisories` (launch-readiness/24): a `data` key no field
        # declares, or a node type with no static field schema to check at
        # all. Read straight from the plan rather than scraped out of
        # `ValidateWorkflowTool`'s printed report — that report's "- " lines
        # are read by `cli.cmd_validate` as *problems* with no notion of
        # section, so an advisory can never ride that text. Appended only
        # when the document is otherwise VALID: an invalid document already
        # has its own findings, and a plan that never got past a hard
        # failure has nothing here worth a second compile to find out.
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        inner = document.get("document", document) if isinstance(document, dict) else document
        try:
            findings = findings + WorkflowCompiler().plan(inner).advisories
        except Exception:
            # A plan that fails here despite `ValidateWorkflowTool` succeeding
            # is not this function's failure to report — its own findings
            # already answered VALID, and this is best-effort advice on top.
            pass
    return valid, findings


def mount_targets(document: dict[str, Any]) -> list[tuple[str, str]]:
    """`(node id, slug)` for every mount in this document, in canvas order.

    The slug may be empty — that is a mount nobody chose a package for, which
    is a real state of a canvas mid-edit and a real defect in a saved one. A
    reader that only wants the resolvable ones filters here rather than being
    handed a list that has already forgotten the difference.
    """
    found: list[tuple[str, str]] = []
    nodes = document.get("nodes")
    if not isinstance(nodes, list):
        # Not this function's malformed-document to report — `validate_document`
        # already turns a non-list `nodes` into its own finding. A caller that
        # also asks this function must not crash on the document `valid_document`
        # was built to survive.
        return found
    for node in nodes:
        if not isinstance(node, dict):
            continue
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


#: The refusal `compile/node_runtime.py::_subgraph` raises when a mount closes
#: a cycle, and the sentence `src/core/validation/mountCycleRule.ts` already
#: quotes verbatim so a user meets one sentence rather than three that sound
#: like different problems. The compiler stays the authority; this module and
#: the editor report the same verdict earlier.
def mount_cycle_refusal(slug: str, chain: tuple[str, ...]) -> str:
    """`_subgraph`'s sentence for `slug` closing `chain`, built its way."""
    return (
        f"Workflow {slug!r} mounts itself ({' -> '.join((*chain, slug))}); "
        "a mount cycle can never terminate"
    )


def unresolved_mounts(
    document: dict[str, Any],
    root: Path,
    *,
    slug: str | None = None,
    _ancestry: tuple[str, ...] = (),
    _chain: str = "",
) -> list[str]:
    """Mounts this document cannot reach, named — recursively (ticket 53).

    **Why this is not part of `validate_document`.** That function plans the
    graph *in memory*; a mount is the one thing in a document that points
    outside it, so answering "is it there" needs a workflows root, which a
    document does not carry. `validate` reported VALID for a package mounting
    `no-such-package-anywhere` for exactly that reason — not because the check
    was wrong, but because nothing had ever asked the question.

    Recursive, because the defect is a typo and a typo two packages down
    breaks the run just as completely.

    **A cycle is reported here too, and stops the descent (ticket 27).** The
    walk has always had to close the loop or hang; until this it closed it by
    `continue`, so a package mounting itself validated clean and learned about
    it from `load_workflow` instead. Termination was the guard's argument, and
    silence was never part of it — `_ancestry` gives both: the chain that led
    here, so a repeat can be *named* before the descent stops.

    `slug` is this document's own package name, so a top-level self-mount
    reads `selfmount -> selfmount` rather than starting one level in. Optional,
    because a bare document validated by path has no folder to take it from.

    **Ancestry, not "every slug seen".** A package mounted twice down two
    branches is a diamond, not a cycle, and a run terminates through it
    perfectly well.
    """
    findings: list[str] = []
    if slug and not _ancestry:
        _ancestry = (slug.strip(),)
    for node_id, slug in mount_targets(document):
        if not slug:
            where = f"{_chain} -> {node_id}" if _chain else node_id
            findings.append(
                f'Workflow node "{where}" has no workflow selected, so the step '
                "produces nothing. Pick a package on the node, or delete it."
            )
            continue
        if slug in _ancestry:
            findings.append(mount_cycle_refusal(slug, _ancestry))
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
                _ancestry=(*_ancestry, slug),
                _chain=f"{_chain} -> {slug}" if _chain else slug,
            )
        )
    # One typo is one finding however many nodes repeat it, and the first
    # occurrence keeps its place — a list ordered by canvas is what a reader
    # can walk.
    return list(dict.fromkeys(findings))


def unresolved_tool_bindings(document: dict[str, Any], package_dir: Path) -> list[str]:
    """Tools this document binds that nothing here implements (ticket 79).

    **Why this is not part of `validate_document`.** Same reason as
    `unresolved_mounts` above: that function plans the graph *in memory*, and
    whether a tool type has an implementation is a question about this
    installation — built-in tools, installed plugins, and the package's own
    `tools/` directory. A document does not carry the answer, so nothing had
    ever asked. `validate` therefore answered VALID for a document copied
    without its package's `tools/`, and printed `Tool bindings: {...}` under
    it, which reads as confirmation the bindings are real. The run was the
    only honest surface — three `No implementation for tool` warnings and an
    agent that correctly refused to invent an answer.

    **The registry is the runtime's own.** `build_tool_registry` is what
    `NodeRuntime.services.tools` is built from, and the lookup here is
    `_bound_tool`'s lookup — the same dict, keyed by the same node type. A
    check that resolved by a different rule would be a second validator, which
    is the thing `cmd_validate` exists to avoid. It costs an import of the
    package's `tools/*.py` and no model call: binding is a registry lookup.

    **Only *bound* tool nodes**, again mirroring the runtime: `_bound_tool` is
    reached for a tool wired to an agent. A tool card parked on the canvas
    gives nothing a capability, so its absence costs nothing.

    A package-scoped discovered type (`<slug>/tools.QueryTool`) is resolved by
    exactly this registry too, so it is clean when its package is present and
    named when it is not — reported, never refused. CLAUDE.md states that cost
    openly; this is where a person finds out about it before a run.
    """
    from openstategraph.api.registries import build_tool_registry
    from openstategraph.api.workflow_store import WorkflowStore
    from openstategraph.compile.workflow_compiler import WorkflowCompiler

    types = {
        str(node.get("id") or ""): str(node.get("type") or "")
        for node in document.get("nodes") or []
    }
    try:
        plan = WorkflowCompiler().plan(document)
    except Exception:
        # A document that will not plan has a louder problem, already reported
        # by the verdict this list is folded into.
        return []
    bound = [node_id for ids in plan.tool_bindings.values() for node_id in ids]
    if not bound:
        return []

    slug = package_dir.name
    registry = build_tool_registry(WorkflowStore(root=package_dir.parent), slug)

    findings: list[str] = []
    seen: set[str] = set()
    for node_id in bound:
        tool_type = types.get(node_id, "")
        if tool_type in registry or tool_type in seen:
            continue
        seen.add(tool_type)
        findings.append(
            f'Tool "{node_id}" has type "{tool_type}", which nothing in this '
            "installation implements — the agent it is wired to will run without it, "
            "so its answer will not be grounded in that data source. Copy the "
            "package's tools/ folder next to workflow.json, or install the plugin "
            "that provides it."
        )
    # One absent implementation is one thing to fix however many cards name it.
    return list(dict.fromkeys(findings))


__all__ = [
    "MOUNT_NODE_TYPES",
    "mount_targets",
    "unresolved_mounts",
    "unresolved_tool_bindings",
    "validate_document",
]
