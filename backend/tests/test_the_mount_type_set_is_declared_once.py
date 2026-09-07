"""One declaration of "which node types mount a child" — ticket 08.

The claim this project rests on is that a new capability is a **registration**,
not an engine edit, and it is true nearly everywhere: node types, port types,
executors, providers, connection rules, validation rules, canvas features, card
bodies and knowledge builders are all registries. The mount type set was the
exception — the same tuple hand-kept in four places.

The failure mode is not a crash. A contributor adding a third organism edits
the two obvious sites, and their mount silently fails to resolve in knowledge
building and in the architect's own view of the platform: the two nobody thinks
to check. Ship-it 03 fixed exactly this shape for workflow-scoped node
families, and the count in *its* ticket was wrong too — the missing site was the
consequential one.

**The evidence that the copies do drift is in the repository.**
`examples/__init__.py` still read `("workflow.subgraph", "team.workflow")`
months after schema v3 collapsed `team.workflow` out of existence
(production-ready 16). Nothing was broken by it, and nothing would have caught
it either.

So this walks the source rather than trusting a list: a literal mount type id
outside the module that declares it is a fifth copy waiting to happen.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from openstategraph.validation import MOUNT_NODE_TYPES

PACKAGE = Path(__file__).resolve().parents[1] / "openstategraph"

#: Where the fact is allowed to be written down.
DECLARATION = PACKAGE / "validation.py"

#: Files that may name the id for a reason other than membership.
#:
#: `schema.py` performs the v2 → v3 migration, so it must name the type it
#: migrates *to* — a migration that imported the current set would rewrite
#: itself the next time the set changed, which is the one thing a migration
#: must never do. Example packages are documents, not code: their `workflow.json`
#: and the tests that read them assert the type of a node they contain.
ALLOWED = ("schema.py",)


def sources() -> list[Path]:
    return [
        path
        for path in PACKAGE.rglob("*.py")
        if path != DECLARATION
        and path.name not in ALLOWED
        and "examples" not in path.parts  # documents and their own tests
        and "__pycache__" not in path.parts
    ]


def code_lines(path: Path) -> list[tuple[int, str]]:
    """Lines that are code, not prose.

    A docstring or comment naming `workflow.subgraph` is the module explaining
    itself — the same register split the lexicon guard makes, and for the same
    reason: this rule is about a *value the program branches on*, not about
    whether a sentence may use the word.
    """
    kept: list[tuple[int, str]] = []
    in_docstring = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        fences = len(re.findall(r'"""|\'\'\'', line))
        opened = in_docstring
        if fences % 2 == 1:
            in_docstring = not in_docstring
        if opened or fences > 0 or line.lstrip().startswith("#"):
            continue
        kept.append((number, line))
    return kept


@pytest.mark.parametrize("mount_type", MOUNT_NODE_TYPES)
def test_no_module_restates_a_mount_type_id(mount_type: str) -> None:
    offenders = [
        f"{path.relative_to(PACKAGE)}:{number}: {line.strip()[:80]}"
        for path in sources()
        for number, line in code_lines(path)
        if f'"{mount_type}"' in line or f"'{mount_type}'" in line
    ]

    assert offenders == [], (
        "import `validation.MOUNT_NODE_TYPES` instead — one fact, one declaration"
    )


def test_the_readers_agree_with_the_declaration() -> None:
    """The three that used to hold their own copy, asked directly."""
    from openstategraph.api.mount_resolution import MOUNT_TYPES as api_types
    from openstategraph.examples import MOUNT_TYPES as example_types
    from openstategraph.prebuilt_architect import KNOWN_NODE_TYPES

    assert api_types == frozenset(MOUNT_NODE_TYPES)
    assert tuple(example_types) == tuple(MOUNT_NODE_TYPES)
    assert set(MOUNT_NODE_TYPES) <= KNOWN_NODE_TYPES


def test_the_walk_is_not_vacuous() -> None:
    """A census over an empty set passes while asserting nothing — which is
    how the four copies survived a repository full of tests in the first
    place."""
    walked = sources()

    assert len(walked) > 30
    assert any(path.name == "prebuilt_architect.py" for path in walked)
    assert any(path.parts[-2] == "compile" for path in walked)
    assert any(path.parts[-2] == "api" for path in walked)
