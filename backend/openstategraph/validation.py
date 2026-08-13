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
from typing import Any


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


__all__ = ["validate_document"]
