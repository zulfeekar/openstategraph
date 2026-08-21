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
from dataclasses import dataclass, field
from typing import Any, Mapping

#: A node declaration: `\tagent_sql(agent_sql)`, `\t__start__(<p>__start__</p>)`,
#: or — inside an opened mount — `\tmount_mid\3ain1(in1)`. `\3a` is how
#: `draw_mermaid` escapes the `:` that `Graph.extend` puts between a mount's
#: name and the child node it prefixes. The escape is the reason this pattern
#: used to match only top-level declarations, and therefore the reason a
#: customer saw the compiler's own ids for every node below the first level
#: (`workflow-gallery` 56).
_DECLARATION = re.compile(r"^(\s*)((?:[A-Za-z0-9_]|\\3a)+)\((.*)\)\s*$")

#: `\tsubgraph mount_inner` — one opened mount. Mermaid nests these, and the
#: name is only the mount's own, so the *stack* of them is what says which
#: document the declarations below it belong to.
_SUBGRAPH = re.compile(r"^(\s*)subgraph\s+([A-Za-z0-9_]+)\s*$")
_END = re.compile(r"^\s*end\s*$")

#: How `draw_mermaid` spells the `:` in a prefixed id.
_ESCAPED_COLON = "\\3a"


@dataclass(frozen=True)
class MountedDocument:
    """One mount, as the *labeller* needs it: the child's own document.

    Recursive by construction, mirroring `compile.composition.MountedGraph`
    — same keys (the graph node name of the mount), the child's document
    instead of the child's compiled graph. The compiler knows which package
    each mount runs; only the package's document knows what its author called
    the nodes inside it, and that is the piece this carries.
    """

    document: Any
    mounts: Mapping[str, "MountedDocument"] = field(default_factory=dict)

#: Anything the compiler named for itself rather than for a reader.
_INTERNAL = "__"


def _safe_name(node_id: str) -> str:
    """`WorkflowCompiler.safe_name`, which mermaid identifiers already use."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", node_id)


def _labels(
    document: Any,
    mounts: Mapping[str, MountedDocument] | None = None,
    prefix: str = "",
) -> dict[str, str]:
    """Path → the title its author gave it, where there is one.

    The path is the mermaid identifier with `\3a` read back as `:`, so a node
    three levels down is `mount_mid:mount_inner:summarise1`. Scoped by path
    and not by bare id on purpose: `in1` exists in all three of
    `nested-mounts`' documents and each author titled it for their own
    workflow. A flat map would answer the parent's word for every one of them.
    """
    nodes = (document or {}).get("nodes") or []
    titles: dict[str, str] = {}
    for node in nodes:
        node_id = str(node.get("id") or "")
        title = str(node.get("title") or "").strip()
        if node_id and title:
            titles[f"{prefix}{_safe_name(node_id)}"] = title
    for name, mounted in (mounts or {}).items():
        titles.update(
            _labels(mounted.document, mounted.mounts, f"{prefix}{name}:")
        )
    return titles


def _branch_names(
    document: Any, mounts: Mapping[str, MountedDocument] | None = None
) -> dict[str, str]:
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
    for mounted in (mounts or {}).values():
        # Flat, unlike the titles: a branch id is what the *edge label* says,
        # and an edge label carries no prefix to scope it by. Ids are minted
        # per document, so a collision is possible in principle; first writer
        # wins, which is the rule `GraphNames.absorb` already settled on.
        for branch_id, name in _branch_names(mounted.document, mounted.mounts).items():
            names.setdefault(branch_id, name)
    return names


def customer_mermaid(
    text: str,
    document: Any,
    mounts: Mapping[str, MountedDocument] | None = None,
) -> str:
    """The same diagram with the compiler's vocabulary removed, to any depth.

    `mounts` is what makes the second half of that sentence true. Without it
    an opened composition kept `mount_mid\3ain1(in1)` for every node below the
    top, because a child's ids are not in the parent's document — the obstacle
    `workflow-gallery` 56 was filed to decide. The decision: **load the child
    documents and relabel properly.** A customer sees the whole composition,
    each node under the name its own author gave it, each opened mount under
    the title the *parent's* author gave the mount.

    Rejected: generic labels for a child's nodes (a picture of a workflow with
    invented names is a different lie from the one this function removes), and
    keeping the customer view flat while the developer view opens (the two
    audiences would then disagree about the shape of the workflow, not just
    about its words).
    """
    if not text:
        return text

    titles = _labels(document, mounts)
    branches = _branch_names(document, mounts)

    kept: list[str] = []
    path: list[str] = []
    for line in text.splitlines():
        # An edge touching hidden machinery goes with it, rather than pointing
        # at a node that is no longer drawn.
        if _INTERNAL in line and ("-->" in line or ".->" in line):
            continue

        block = _SUBGRAPH.match(line)
        if block:
            indent, name = block.groups()
            path.append(name)
            title = titles.get(":".join(path))
            # `subgraph id[title]` keeps the identifier — nothing references a
            # block, but a stable id keeps this a relabelling rather than a
            # rewrite. Quoted because a title may hold the brackets mermaid
            # reads as syntax.
            kept.append(f"{indent}subgraph {name}" + (f'["{_quote(title)}"]' if title else ""))
            continue
        if _END.match(line) and path:
            path.pop()
            kept.append(line)
            continue

        declaration = _DECLARATION.match(line)
        if declaration:
            indent, identifier, label = declaration.groups()
            if _INTERNAL in identifier:
                continue
            key = identifier.replace(_ESCAPED_COLON, ":")
            kept.append(f"{indent}{identifier}({titles.get(key, label)})")
            continue

        for branch_id, name in branches.items():
            # Bounded by the non-breaking spaces mermaid pads edge labels with,
            # so a branch id can never match a fragment of a node name.
            line = line.replace(f"&nbsp;{branch_id}&nbsp;", f"&nbsp;{name}&nbsp;")
        kept.append(line)

    return "\n".join(kept) + ("\n" if text.endswith("\n") else "")


def _quote(title: str) -> str:
    """A block title, safe inside the `["..."]` mermaid reads it from."""
    return title.replace('"', "&quot;")
