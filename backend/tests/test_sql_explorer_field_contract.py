"""Every key the SQL explorer cards declare is a key the tools read, and back.

**Why this file has to exist** — `skills/atom-forge` build step 9 says it, and
`test_data_key_contract.py`'s own docstring says it: the general guard walks the
*compiler's* factories and **does not cover a tool's `configure()`**, which is
exactly where a tool atom's keys live. So a tool with real configuration passes
the general guard with a misspelling in every one of its keys, and produces a
node that looks configured and connects to nothing.

These three tools are the case that proves it. They were registered on the
Python side with no editor card at all (production-ready 61) — so `database`
was unreachable, and `_refusal()` fired on every call with *"No readable
database at '(unset)'"*. Cards exist now; this stops the two halves drifting
apart again.

Read off the generated `port_specs.json`, never a hand-kept list, for the reason
`test_mcp_field_contract.py` records: a list somebody maintains is a list that
disagrees with the editor the first time either side changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SPECS = REPO / "backend" / "openstategraph" / "compile" / "port_specs.json"

#: Keys `defineNode` injects into every standard node — graph-assembly
#: overrides available to every node of every family, and not this tool's
#: configuration. Excluded on both sides rather than silently tolerated.
#:
#: Hand-typed as two names until `organisms-first-class/34` added a third
#: (`cacheTtlSeconds`) and this file, plus four TypeScript ones, failed for a
#: field none of them is about. It is still written out — the point of the
#: exclusion is that a reader can see what is excluded — but
#: `test_the_injected_set_is_what_the_generated_catalogue_shows` below derives
#: the same set from `port_specs.json` and fails if the two part company. A
#: list in a comment has no way to fail; this one now does.
INJECTED = frozenset({"maxRetries", "timeoutSeconds", "cacheTtlSeconds"})


def test_the_injected_set_is_what_the_generated_catalogue_shows() -> None:
    """`INJECTED` must be exactly the keys every standard node type carries.

    "Standard" is read off the catalogue rather than asserted: a node type
    that carries `maxRetries` is one `defineNode` treated as executable, and
    the keys *all* of those share are precisely the injected ones.
    """
    import functools

    catalogue = json.loads(SPECS.read_text())["node_types"]
    standard = [
        set(entry["field_keys"])
        for entry in catalogue
        if "maxRetries" in (entry.get("field_keys") or [])
    ]
    assert len(standard) > 1, "expected many standard node types in the catalogue"
    assert functools.reduce(set.intersection, standard) == set(INJECTED)

#: What each tool's `configure()` actually reads. Taken from the source, not
#: from the card, so the two are independent statements that must agree.
READS = {
    "tool.sql-list-tables": {"database"},
    "tool.sql-get-schema": {"database"},
    "tool.sql-query": {"database", "maxRows"},
    # The T-SQL sibling (`osg-agent-experience/34`). It joins this file rather
    # than opening its own because it joins the same base class: the guard is
    # about a family's `configure()`, and there is now one more member of it.
    # `connection` is the *name* of an environment variable, so a misspelling
    # here would produce a tool that refuses every query naming a variable
    # nobody set — the silent-configuration failure this file exists for,
    # wearing the one disguise that reads as correct behaviour.
    "tool.mssql-query": {"connection", "allowlist", "maxRows"},
}


def _declared(node_type: str) -> set[str]:
    """The card's own field keys, off the generated artifact.

    `type` and `field_keys` are the artifact's own names — read rather than
    assumed, because the first version of this guessed `id`/`fields`, found
    nothing, and produced seven confident failures about types that were
    present all along.
    """
    specs = json.loads(SPECS.read_text(encoding="utf-8"))
    entry = next(n for n in specs["node_types"] if n.get("type") == node_type)
    return set(entry.get("field_keys") or []) - INJECTED


@pytest.mark.parametrize("node_type", sorted(READS))
class TestBothDirections:
    def test_the_tool_reads_every_key_the_editor_declares(self, node_type: str) -> None:
        extra = _declared(node_type) - READS[node_type]
        assert not extra, (
            f"{node_type}'s card declares {sorted(extra)}, which `configure()` never "
            "reads — a control that looks configured and changes nothing."
        )

    def test_the_editor_declares_every_key_the_tool_reads(self, node_type: str) -> None:
        missing = READS[node_type] - _declared(node_type)
        assert not missing, (
            f"{node_type}'s `configure()` reads {sorted(missing)} and no field declares "
            "it, so nobody can set it. That is exactly how these three shipped: "
            "`database` was read and unreachable, and every call refused."
        )


class TestTheGuardItself:
    def test_the_generated_artifact_knows_these_types(self) -> None:
        # A guard whose lookup silently returns nothing passes vacuously. If
        # `npm run generate:ports` was skipped, this is the assertion that says
        # so rather than three green tests over an empty set.
        for node_type in READS:
            assert _declared(node_type), f"{node_type} is absent from port_specs.json"
