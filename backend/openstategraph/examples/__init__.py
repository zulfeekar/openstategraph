"""The shipped gallery — the worked examples, and the middle of a chain.

**Tier 2, provisional** (`docs/stability.md`): importable and documented, may
change in a minor release with a changelog note. The *command line* over it —
`openstategraph examples list` / `openstategraph examples copy <slug>` —
follows the Tier 1 policy.

**What an example is, and how it differs from a template.** A template is a
*scaffold input*: three substitution tokens, a starter document, an AGENTS.md,
and a set of empty directories waiting for the developer's code. An example is
a **finished package** — its document, its tests, its knowledge store, its
eval fixture and, for `sql-qa`, its database — the whole of what the gallery
built and smoke-ran. Nothing is substituted into it, because there is nothing
in it that is a placeholder.

They share one property, and it is the important one: **you get it by copying,
and the copy is severed.** `docs/on-the-canvas.md`'s table is the rule —

    Mount a package        by reference    change the original, every instance changes
    Start from a template  by copy         nothing changes; the link was severed

— and an example is on the *copy* side of it, deliberately:

- These files live inside `site-packages`. A mount is by reference, so a
  workflow mounting one would silently change on the user's next
  `pip install -U`, and the reference would point at a directory they cannot
  edit (and, on a read-only install, cannot write at all). That is not "read
  only", it is "someone else's package pretending to be yours".
- The mount seam resolves a slug through `WorkflowStore(root=workflows_root())`
  — one root. Teaching it a second search path would create two directories
  that can disagree about what `chained-summarizer` means, which is the class
  of ambiguity `workflows_root` exists to remove.

So: **copy-on-use, and never mountable in place.** `scaffold.copy_example` is
the one writer, and it copies transitively — three examples mount others, and
a copy of `nested-mounts` whose `nested-mounts-mid` was left behind is a broken
package delivered by the command whose job is to deliver a working one.

**Where they are, and what that decides.** `openstategraph/examples/`, package
data beside `openstategraph/templates/`, for the same reason: a wheel carries
its own directory and nothing has to remember to include it. The consequence
is a *visibility* rule that needs no flag (gallery ticket 33): the gallery is
not under `workflows_root()`, so `platform_list_workflows`, the generated
project-knowledge doc and the `/chat` picker cannot see it however its envelope
is spelled. The examples keep `published: false` — and once copied, that flag
finally *means* something: the user's package is a draft they publish when they
choose, exactly as anything `openstategraph new` writes.

**This module reads; it never writes.** Same split as `templates`: the
catalogue is data, and `openstategraph.scaffold` is the single place a package
appears on disk.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from openstategraph.validation import MOUNT_NODE_TYPES

#: The package-data directory: this module's own, so it travels with the wheel.
#: `__file__` is the right answer here for exactly the reason it is the wrong
#: one in `workflows_root` — these files really are inside `site-packages`.
DATA = Path(__file__).resolve().parent

#: The node types that mount another package by slug — the same set the
#: editor's drill-in and the compiler's mount resolution use.
#: Derived, not restated (ticket 08) — and this copy is the evidence for that
#: rule: it still carried `team.workflow` months after schema v3 collapsed it,
#: because nothing made the two facts one.
MOUNT_TYPES = MOUNT_NODE_TYPES


class UnknownExampleError(ValueError):
    """A slug that is not in the gallery. The message lists what is."""


@lru_cache(maxsize=None)
def _envelope(slug: str) -> dict[str, Any]:
    """The stored envelope — `{version, name, published, savedAt, document}`.

    Cached because the catalogue reads every one of them to answer a listing,
    and these files are immutable package data: nothing in a running process
    can change them.
    """
    loaded = json.loads((DATA / slug / "workflow.json").read_text())
    assert isinstance(loaded, dict)
    return loaded


def document_shape(document: Any) -> str:
    """What a document actually contains, counted by node family.

    The honest half of `every-workflow-green` 03. `settings.purpose` is prose a
    person wrote once, and nothing reads it back against the graph — so
    `workflow-2026` advertised "classify the ticket … grade the reply … let a
    person decide" on a document with no classifier, no grader and no gate. The
    owner's decision was to **show the shape beside the claim** rather than
    police the sentence or generate it away: a reader sees both and judges, and
    nobody's words are rewritten.

    Counted from each type's **family segment** — the part before the first dot
    in `route.grader`. That is deliberate rather than lazy: the family is
    already carried in the type id, so this duplicates no vocabulary table and
    cannot drift from the editor's own census, which documents the identical
    fallback ("1 agent · 1 route · 3 tool") for a type it has no word for.

    Empty for a document with no readable nodes. A shape nobody can compute is
    left unsaid rather than printed as "0 nodes", which would read as a broken
    package rather than an unreadable one.
    """
    nodes = document.get("nodes") if isinstance(document, dict) else None
    if not isinstance(nodes, list):
        return ""
    counts: dict[str, int] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = node.get("type")
        if not isinstance(node_type, str) or not node_type:
            continue
        family = node_type.split(".", 1)[0]
        counts[family] = counts.get(family, 0) + 1
    # Document order, not alphabetical: the reader is scanning for what is
    # *missing* against a sentence, and the graph's own order is the one they
    # can follow.
    return " · ".join(f"{count} {family}" for family, count in counts.items())


@dataclass(frozen=True)
class Example:
    """One shipped example. `pattern` is the only thing `index.json` adds."""

    slug: str
    #: The catalogue's own label — "revision loop", "orchestrator-worker".
    #: Not derivable from the document, which is why it is declared.
    pattern: str
    #: Findings this example ships **on purpose**, as `(kind, subjects)`.
    #:
    #: Declared, not derived, for the same reason `pattern` is: it is the
    #: author's intent, and the whole question is whether the warning the
    #: compiler produced is the one somebody meant. `support-triage` is the
    #: shipped case — three desk agents behind a classifier and a grader used
    #: as a recorder, so its `revise` port is wired to nothing deliberately
    #: (`workflow-gallery` 31, and its `AGENTS.md` says so in prose).
    #:
    #: By kind and subject rather than by pasted prose, so rewording a
    #: sentence in `diagnostics._SENTENCES` cannot turn a correct declaration
    #: into drift. See `warning_drift`.
    expected_findings: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def directory(self) -> Path:
        return DATA / self.slug

    @property
    def name(self) -> str:
        """The display name, from the package's own envelope."""
        name = _envelope(self.slug)["name"]
        assert isinstance(name, str)
        return name

    @property
    def summary(self) -> str:
        """One line, from `settings.purpose` — the field the card already
        shows on the canvas. Never a second sentence written in `index.json`."""
        purpose = self.document().get("settings", {}).get("purpose", "")
        assert isinstance(purpose, str)
        return purpose

    @property
    def shape(self) -> str:
        """The census of this example's own document — see `document_shape`.

        Printed beside `summary` by `openstategraph examples list`, so the
        claim and the contents are read together.
        """
        return document_shape(self.document())

    def document(self) -> dict[str, Any]:
        """The workflow document, exactly as it ships. No substitution: an
        example has no placeholders."""
        document = _envelope(self.slug)["document"]
        assert isinstance(document, dict)
        return document

    @property
    def mounts(self) -> tuple[str, ...]:
        """The packages this one mounts, read from its own nodes.

        Derived rather than declared: the slugs are already in the document,
        and a second list in `index.json` would be right on the day it was
        written and wrong after the first rewire.
        """
        seen: list[str] = []
        for node in self.document()["nodes"]:
            if node["type"] in MOUNT_TYPES:
                slug = node.get("data", {}).get("workflow")
                if slug and slug not in seen:
                    seen.append(slug)
        return tuple(seen)

    def requires(self) -> tuple[str, ...]:
        """This example first, then every package it mounts, transitively.

        The order a copy is written in, and the answer to "what does taking
        this one actually cost me". Cycle-safe by construction — a self-mount
        is refused at compile time, but a catalogue read must not hang on one.
        """
        order: list[str] = []

        def walk(slug: str) -> None:
            if slug in order:
                return
            order.append(slug)
            for mounted in get(slug).mounts:
                walk(mounted)

        walk(self.slug)
        return tuple(order)



def warning_drift(example: Example, actual: Sequence[str]) -> tuple[list[str], list[str]]:
    """Compare what an example compiled with against what it declared.

    Returns `(undeclared, absent)` — warnings this example produced and never
    declared, and declarations that produced nothing. Both are drift, and both
    matter: the first is a defect nobody has looked at, the second is an
    expectation that has stopped gating anything.

    "No warnings at all" was the old rule, and it was defensible only while
    every warning meant something was wrong. `Finding.UNWIRED_REVISE` exists to
    say a graph is legal and less capable than it looks, so the rule that
    replaces it is *fail on any warning the package has not declared*
    (`workflow-gallery` 55).
    """
    from openstategraph.compile.diagnostics import CompileDiagnostics, Finding

    declared = [
        CompileDiagnostics.sentence_for(Finding(kind)).format(*subjects)
        for kind, subjects in example.expected_findings
    ]
    undeclared = [warning for warning in actual if warning not in declared]
    absent = [sentence for sentence in declared if sentence not in actual]
    return undeclared, absent

@lru_cache(maxsize=1)
def catalogue() -> tuple[Example, ...]:
    """Every example, in the order they should be read: simplest first."""
    index = json.loads((DATA / "index.json").read_text())
    return tuple(
        Example(
            slug=entry["slug"],
            pattern=entry["pattern"],
            expected_findings=tuple(
                (finding["finding"], tuple(finding.get("subjects", ())))
                for finding in entry.get("expectedFindings", ())
            ),
        )
        for entry in index["examples"]
    )


def slugs() -> tuple[str, ...]:
    """The valid `examples copy` arguments, in catalogue order."""
    return tuple(example.slug for example in catalogue())


def get(slug: str) -> Example:
    for example in catalogue():
        if example.slug == slug:
            return example
    raise UnknownExampleError(f"unknown example {slug!r} — choose from {', '.join(slugs())}")


__all__ = [
    "DATA",
    "MOUNT_TYPES",
    "Example",
    "UnknownExampleError",
    "catalogue",
    "get",
    "slugs",
]
