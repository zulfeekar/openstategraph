"""Where a node's static text comes from, decided once for the whole compiler.

`input.markdown` carries **two** fields describing one piece of text —
`filename`, which the editor writes when a file is picked, and `content`, the
copy it pastes in beside it — and until `launch-readiness/94` the compiler read
only the second. Nothing read `filename` at run time at all, and nothing
compared the two.

The consequence, found by running a shipped package rather than by reading it:
a NL2SQL workflow whose SQL validator loads `skills/lenses/*.md` from disk
while its agent reads the embedded copy, with **seven of twelve files drifted**.
A commit declaring four lenses, two routing rules and the "ask, don't guess"
guidance reached the validator and never reached the model. The traces looked
like an agent ignoring its rules; it had never been shown them.

**The inline copy is not the mistake and is not removed.** A document carrying
its own text is self-contained, and `mcp_server.compile_workflow` is stateless
with no package on disk to read from. The defect was narrower: both fields
were populated and neither was declared authoritative.

## The rule, which is the same rule at every door

| the document says | the run uses | and reports |
| --- | --- | --- |
| inline `instruction` text | that text | `SKILL_FILE_UNUSED`, if a file was also named and readable |
| a `filename` this run can read | **the file** | `SKILL_SOURCE_DRIFTED`, if the stored copy differs |
| a `filename` this run cannot read | the stored copy | `SKILL_FROM_SNAPSHOT` |
| no `filename` at all | the stored copy | nothing — there is one source |

Read that table for the stateless door and every run of it lands on row three.
That is deliberate, and it is why the sentence exists: the rule does not change
with the door, only the answer it reaches does, and a caller who cannot see the
difference cannot know their edit did not apply. Refusing instead would break
that door outright; re-reading in silence would make the document stop being
self-contained without saying so. So: re-read, and say so.

**`filename` addresses the package and nothing above it.** A candidate that
resolves outside the package directory is not read — a document is data from
wherever it came from, and a compiler that opens an arbitrary path named in one
is a compiler that can be pointed anywhere. Costing nothing in portability:
`skills/` travels beside `workflow.json`, so a file reference is exactly as
portable as the package, which is the promise a package already makes.

**`instruction` still wins over the file, deliberately.** The editor's card
lets a developer load a file and then tweak it, and a load that discarded the
tweak would be this same defect pointing the other way. What changes is that
the file it leaves unread is named — a whole lens hiding behind one typed
sentence is the ticket's shape one field over, and a package-local gate in the
wild had already had to grow a check for exactly it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openstategraph.compile.diagnostics import Finding

#: The node types whose text *is* their configuration. `NodeRuntime` registers
#: `_static_text` from this set rather than from its own literals, so the list
#: of types that have a static source and the list this module resolves for
#: cannot drift apart.
STATIC_TEXT_NODE_TYPES: frozenset[str] = frozenset({"input.markdown", "input.skill"})

#: The typed-in fields, in the order they win. Two spellings because both have
#: been authored; `content` last because it is the machine-written copy.
INLINE_FIELDS: tuple[str, ...] = ("instruction", "instructions")

#: The field holding the copy of a picked file.
STORED_FIELD = "content"

#: The field naming where that copy came from.
SOURCE_FIELD = "filename"


@dataclass(frozen=True)
class StaticSource:
    """One node's resolved text, and what resolving it turned up.

    `findings` is carried rather than recorded, so this function stays pure and
    one caller decides where a sentence lands. Each entry is a `Finding` and
    its subjects, ready for `CompileDiagnostics.record`.
    """

    text: str
    findings: tuple[tuple[Finding, tuple[str, ...]], ...] = ()


def _read(package_dir: Any, named: str) -> str | None:
    """The file `named` names inside `package_dir`, or `None`.

    Two candidates and no more: the path as written, and the same name under
    `skills/`. The second exists because the editor's file picker stores a
    basename while the settled home for a skill file is `skills/` — a document
    saying `analyst.md` means the one in this package, and looking only at the
    package root would leave every picked file unresolvable and every run on
    row three of the table above.
    """
    if not named or package_dir is None:
        return None
    root = Path(package_dir).expanduser()
    try:
        root = root.resolve()
    except OSError:
        return None
    for candidate in (root / named, root / "skills" / named):
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        # Inside the package, or not read at all. `Path.is_relative_to` rather
        # than a string prefix: `<root>-backup` starts with `<root>`.
        if not resolved.is_relative_to(root) or not resolved.is_file():
            continue
        try:
            return resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    return None


def resolve_static_source(
    node_id: str, data: dict[str, Any], package_dir: Any = None
) -> StaticSource:
    """The text this node contributes, and every disagreement behind it."""
    inline = ""
    for field in INLINE_FIELDS:
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            inline = value
            break
    stored = data.get(STORED_FIELD)
    stored = stored if isinstance(stored, str) else ""
    named = data.get(SOURCE_FIELD)
    named = named.strip() if isinstance(named, str) else ""

    on_disk = _read(package_dir, named)

    if inline:
        # A named file that this run could not read is not worth a sentence
        # here: the typed text was going to win either way, so nothing about
        # the run would have differed.
        findings = (
            ((Finding.SKILL_FILE_UNUSED, (node_id, named)),) if on_disk is not None else ()
        )
        return StaticSource(inline, findings)

    if on_disk is not None:
        if stored.strip() and stored != on_disk:
            return StaticSource(
                on_disk, ((Finding.SKILL_SOURCE_DRIFTED, (node_id, named)),)
            )
        return StaticSource(on_disk)

    if named:
        return StaticSource(stored, ((Finding.SKILL_FROM_SNAPSHOT, (node_id, named)),))
    return StaticSource(stored)


def resolve_static_sources(
    document: dict[str, Any], package_dir: Any = None
) -> dict[str, StaticSource]:
    """Every static-text node in one document, resolved once at compile time.

    Once, and here, because there are two readers downstream and they run at
    different moments: `_static_text` builds a graph node, while `_wired_skill`
    is consulted inside an agent's closure on every lap. Resolving in the
    closure would re-read the file mid-run — a graph whose prompt changes under
    it — and would report the same disagreement once per lap.
    """
    resolved: dict[str, StaticSource] = {}
    for node in document.get("nodes") or ():
        if str(node.get("type", "")) not in STATIC_TEXT_NODE_TYPES:
            continue
        node_id = str(node.get("id", ""))
        resolved[node_id] = resolve_static_source(
            node_id, node.get("data") or {}, package_dir
        )
    return resolved
