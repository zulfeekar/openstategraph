"""The compiled diagram, rewritten for the person who did not compile it.

`draw_mermaid()` renders LangGraph's own view: `__start__`, `__end__`,
`__default_error_handler__`, and each node under `safe_name(node_id)`. That is
exactly right for a developer — it is the name the compiler used, and the name
a mount bug will be reported under. It is wrong for a customer, who was shown

    __start__   __default_error_handler__   in1   router1   agent_general

on `/chat` with edge labels `b-general` and `b-build`
(reviews-2026-08-14 ticket 04).

**This is a rendering choice per audience, not a change to the frames.** The
audience boundary already decides what a customer may read in an error and in
a run's outputs; the picture is the same question. Nothing here alters what
the compiler produced — the developer surface keeps every id.

Two rules:

- **Machinery is hidden.** `__*` nodes are not steps in anybody's workflow,
  and an edge into one is an arrow into nothing once it is gone, so those go
  too.
- **A node reads as the name its author gave it.** Only the *label* is
  rewritten; the mermaid identifier is untouched, because every edge line
  references it and the frontend's highlight matches on `safe_name` as well.

Where a node has no title, its label is left alone. Inventing a friendly name
for something the author never named would be a different kind of lie.
"""

from __future__ import annotations

import re
from typing import Any

#: A node declaration: `\tagent_sql(agent_sql)` or `\t__start__(<p>__start__</p>)`.
_DECLARATION = re.compile(r"^(\s*)([A-Za-z0-9_]+)\((.*)\)\s*$")

#: Anything the compiler named for itself rather than for a reader.
_INTERNAL = "__"


def _safe_name(node_id: str) -> str:
    """`WorkflowCompiler.safe_name`, which mermaid identifiers already use."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", node_id)


def _labels(document: Any) -> dict[str, str]:
    """safe_name → the title its author gave it, where there is one."""
    nodes = (document or {}).get("nodes") or []
    titles: dict[str, str] = {}
    for node in nodes:
        node_id = str(node.get("id") or "")
        title = str(node.get("title") or "").strip()
        if node_id and title:
            titles[_safe_name(node_id)] = title
    return titles


def _branch_names(document: Any) -> dict[str, str]:
    """Branch id → branch name, for the labels a router puts on its edges.

    `b-data` is an id this product minted; `data_query` is what the developer
    called the branch and what the router is actually deciding between.
    """
    names: dict[str, str] = {}
    for node in (document or {}).get("nodes") or []:
        for branch in (node.get("data") or {}).get("branches") or []:
            branch_id = str(branch.get("id") or "")
            name = str(branch.get("name") or "").strip()
            if branch_id and name:
                names[branch_id] = name
    return names


def customer_mermaid(text: str, document: Any) -> str:
    """The same diagram with the compiler's vocabulary removed."""
    if not text:
        return text

    titles = _labels(document)
    branches = _branch_names(document)

    kept: list[str] = []
    for line in text.splitlines():
        # An edge touching hidden machinery goes with it, rather than pointing
        # at a node that is no longer drawn.
        if _INTERNAL in line and ("-->" in line or ".->" in line):
            continue

        declaration = _DECLARATION.match(line)
        if declaration:
            indent, identifier, label = declaration.groups()
            if _INTERNAL in identifier:
                continue
            kept.append(f"{indent}{identifier}({titles.get(identifier, label)})")
            continue

        for branch_id, name in branches.items():
            # Bounded by the non-breaking spaces mermaid pads edge labels with,
            # so a branch id can never match a fragment of a node name.
            line = line.replace(f"&nbsp;{branch_id}&nbsp;", f"&nbsp;{name}&nbsp;")
        kept.append(line)

    return "\n".join(kept) + ("\n" if text.endswith("\n") else "")
