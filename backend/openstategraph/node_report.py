"""The node vocabulary, rendered for a terminal.

`osg-agent-experience/33`. `get_node_vocabulary` answers *what can be composed*
over MCP; until this module there was no way to ask the same question from the
command line, and the sheet had to send an agent to read the installed
`compile/port_specs.json` — a generated seven-key document — with its own eyes.
An agent that did not read it invented a `systemPrompt` on a classifier, a dict
where a string goes, and `mssql` in a SQLite path (`osg-agent-experience/32`).

**This module renders; it does not read.** The payload it formats is exactly
`NodeVocabulary.describe()`, which is itself assembled from the generated
catalogue. A second reader of `port_specs.json` here would be a second place a
node type added in the editor has to reach, which is the drift the generated
catalogue exists to end — so the vocabulary arrives as an argument and nothing
in this file opens a file.

Not part of the public API — Tier 3, see ``docs/stability.md``. The *command*
`openstategraph nodes` is the contract; these function names are not.
"""

from __future__ import annotations

import difflib
import textwrap
from collections.abc import Mapping, Sequence
from typing import Any

#: A `max_connections` of `null` is a bus — an agent's `tools` port, a
#: classifier's `skill` port. Printing an empty cell there is the one reading a
#: composing client must not make: "unlimited" and "unknown" lead to opposite
#: documents. `CLAUDE.md` forbids `Infinity` in the serialisable field for the
#: same reason it has to be spelled out here.
UNLIMITED = "unlimited"


def _one_line(text: str) -> str:
    return " ".join(text.split())


def node_list_lines(vocabulary: Mapping[str, Any]) -> list[str]:
    """Every type id, its label, and the sentence the editor's palette shows.

    One physical line per type on purpose: this is a list an agent greps and a
    developer eyeballs, and a wrapped description turns `grep route` into half
    an answer.
    """
    lines = []
    for node in vocabulary["node_types"]:
        label = node.get("label") or "(no label)"
        description = _one_line(node.get("description") or "")
        # `ljust` plus an explicit space, never `:<28` alone: two real type ids
        # (`tool.platform-describe-workflow`) are longer than the column, and a
        # padded-to-nothing row prints `…workflowsList workflows` — one token,
        # which is a row `grep`, a reader and this module's own list test all
        # read as a different type id.
        row = f"{node['type'].ljust(27)} {label}"
        if description:
            row = f"{row} — {description}"
        lines.append(row)
    lines.append("")
    lines.append("openstategraph nodes <type> prints one type's fields and ports.")
    return lines


def _field_lines(node: Mapping[str, Any]) -> list[str]:
    lines = ["fields:"]
    if not node.get("fields"):
        lines.append("  (none — this type takes no config)")
        return lines
    for field in node["fields"]:
        row = f"  {field['key']:<20}{field['kind']}"
        if field.get("required"):
            row = f"{row}  (required)"
        lines.append(row)
        options = field.get("options") or ()
        if options:
            lines.append(
                f"{'':<22}one of: " + ", ".join(str(option["value"]) for option in options)
            )
        hint = _one_line(field.get("hint") or "")
        if hint:
            # Wrapped, because these are the editor's own hints and several run
            # past 300 characters — a terminal's own wrap loses the indent that
            # says the sentence belongs to the field above it.
            lines.extend(
                textwrap.wrap(hint, width=88, initial_indent=" " * 22, subsequent_indent=" " * 22)
            )
    return lines


def _port_lines(node: Mapping[str, Any]) -> list[str]:
    lines = ["ports:"]
    for port in node.get("ports") or ():
        cap = UNLIMITED if port.get("max_connections") is None else str(port["max_connections"])
        row = f"  {port['id']:<20}{port['direction']:<4}{port['type']:<10}max {cap}"
        if port.get("required"):
            row = f"{row}  (required)"
        lines.append(row)
    for group in node.get("generated_ports") or ():
        # Named rather than omitted: a classifier declares no out-port at all
        # until its branches exist, and a reader shown only the three static
        # in-ports concludes the node has no way out — which is how the `32`
        # document came to run fifteen edges from a `result` port the type
        # never had.
        lines.append(
            f"  {group['prefix'] + '<name>':<20}{group['direction']:<4}{group['type']:<10}"
            f"max {UNLIMITED}  (one per branch you configure)"
        )
    if len(lines) == 1:
        lines.append("  (none — this type is never scheduled)")
    return lines


def node_detail_lines(vocabulary: Mapping[str, Any], node_type: str) -> list[str] | None:
    """One type in full, or `None` when the vocabulary does not know it."""
    node = next((item for item in vocabulary["node_types"] if item["type"] == node_type), None)
    if node is None:
        return None

    lines = [f"{node['type']} — {node.get('label') or '(no label)'}"]
    description = _one_line(node.get("description") or "")
    if description:
        lines.append(description)
    if not node.get("executes", True):
        lines.append("(a note on the canvas; the compiler never schedules it)")
    lines.append("")
    lines.extend(_field_lines(node))
    lines.append("")
    lines.extend(_port_lines(node))

    contract = node.get("prompt_contract")
    if contract:
        # The locked halves, said once. A client that restates the preamble or
        # the output contract in its own rules is writing text the runtime
        # already prepends and the contract already overrides.
        lines.append("")
        lines.append("prompt: " + _one_line(contract["editable"]))
    return lines


def nearest_types(node_type: str, known: Sequence[str]) -> list[str]:
    """The near misses for an id nothing resolves.

    A typo is the common case (`route.classifer`), so a plain "unknown type"
    costs a round trip to a list the reader has to read whole. Falls back to
    the prefix family — `route.` — when nothing is close enough, because a
    reader who invented `route.dispatch` needs the four real routers, not the
    empty set difflib gives them.
    """
    close = difflib.get_close_matches(node_type, list(known), n=3, cutoff=0.6)
    if close:
        return close
    prefix = node_type.split(".", 1)[0] + "."
    return sorted(name for name in known if name.startswith(prefix))[:5]
