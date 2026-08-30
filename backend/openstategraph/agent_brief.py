"""The brief a coding agent reads, and the one command that delivers it.

`install-experience/25`. The wheel already carried the *shape* of a workflow
package — the examples, the templates, an `AGENTS.md` beside each — and none
of the *principles*: `docs/` and `CLAUDE.md` are repository files and a
stranger who ran `pip install openstategraph` never saw them. So an agent
opened on their project could copy a package and could not learn the rules
that decide whether what it wrote is right.

**A wheel cannot close that gap by itself, and must not try.** The format is
defined as an unpack — *"a wheel file may be installed by simply unpacking
into site-packages with the standard 'unzip' tool"*, and *"Wheel does not
contain setup.py or setup.cfg"* (PEP 427, and the binary distribution format
specification it became). There is no install hook by design, because a
distribution that writes into your repository while you install it is the
supply-chain shape. That is a property to keep.

So the delivery is the split every sanctioned mechanism uses: **the
distribution carries the material, and a console script the user runs puts it
where their agent looks.** `openstategraph init` is that script — it already
makes the project, so a second verb would only mean a second thing to know.

## Where it lands, and why there

`AGENTS.md` at the project root: a published, multi-vendor convention whose
whole subject is this problem, and whose resolution rule — an agent reads the
nearest one up the tree — is what makes a project-root file reach an agent
working anywhere inside it. This repository already writes an `AGENTS.md` into
every scaffolded package for the same reason.

**Inside markers, and the markers are the honesty.** Everything between them
is generated and is replaced wholesale on the next `init`; everything outside
is the user's and is never read, moved or rewritten. That is what lets an
upgrade deliver a new brief without a merge, and what lets somebody keep their
own house rules in the same file. The idiom is not invented here — this
repository's own root `AGENTS.md` carries a marked block from a generator it
does not own.

**The bytes written are the bytes that ship.** `agent_brief.md` is copied, not
re-rendered, so there is no second copy to drift and
`tests/test_the_wheel_teaches_what_it_ships.py` can assert the equality
directly. The same test derives the brief's lexicon out of `CLAUDE.md` and
compares it byte for byte, which is the only reason a summary of the rules is
allowed to exist at all.
"""

from __future__ import annotations

from pathlib import Path

#: Package data, beside this module — so a wheel carries it for the same
#: reason it carries `templates/`. Deliberately not named `AGENTS.md`: a file
#: by that name here would become the *nearest* one for anybody working in
#: this directory, and an agent editing the compiler would take the adopter's
#: brief as its instructions.
BRIEF = Path(__file__).resolve().parent / "agent_brief.md"

MARKER_START = "<!-- OPENSTATEGRAPH:START -->"
MARKER_END = "<!-- OPENSTATEGRAPH:END -->"

#: What `write_into` did, as one word each, because `init` has to be able to
#: print a true sentence for all four.
CREATED = "created"
ADDED = "added"
REFRESHED = "refreshed"
CURRENT = "current"


def brief_text() -> str:
    """The shipped brief, verbatim."""
    return BRIEF.read_text(encoding="utf-8")


def _block() -> str:
    return f"{MARKER_START}\n{brief_text().strip()}\n{MARKER_END}\n"


def write_into(directory: Path | str) -> tuple[Path, str]:
    """Put the brief in `<directory>/AGENTS.md`. Returns the path and which
    of the four things happened.

    Never writes a byte outside the markers, and never writes at all when the
    block is already current — so running `init` again is free.
    """
    target = Path(directory) / "AGENTS.md"
    block = _block()

    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(block, encoding="utf-8")
        return target, CREATED

    existing = target.read_text(encoding="utf-8", errors="replace")
    if MARKER_START not in existing or MARKER_END not in existing:
        if existing.endswith("\n\n"):
            separator = ""
        elif existing.endswith("\n"):
            separator = "\n"
        else:
            separator = "\n\n"
        target.write_text(existing + separator + block, encoding="utf-8")
        return target, ADDED

    head, rest = existing.split(MARKER_START, 1)
    _, tail = rest.split(MARKER_END, 1)
    replacement = head + block.rstrip("\n") + tail
    if replacement == existing:
        return target, CURRENT
    target.write_text(replacement, encoding="utf-8")
    return target, REFRESHED


__all__ = [
    "ADDED",
    "BRIEF",
    "CREATED",
    "CURRENT",
    "MARKER_END",
    "MARKER_START",
    "REFRESHED",
    "brief_text",
    "write_into",
]
