"""`docs/prebuilt-tools.md` names fields, and a field name can go stale silently.

`docs-onramp/12`. The page exists to say the three things a one-line brief
cannot — what a card is **configured with**, what it **refuses**, and what it
**costs**. The first of those three is the only one a machine can hold, and it
is also the one that rots: a field renamed in `port_specs.json` leaves a page
telling a reader to fill in a box that is no longer there, and nothing says so.

So this file pins the *configured with* half, derived twice over:

- **which types the page must cover** comes from `DEEPER` in
  `scripts/build_module_index.py` — every row routed at `prebuilt-tools.md` —
  not from a list typed here. Route an eleventh card at the page and the page
  owes it a section;
- **which field names are legal** comes from that type's own `field_keys` in
  `compile/port_specs.json`, the same data the editor builds the inspector
  from.

What is deliberately **not** pinned: the prose, the refusal quotations and the
cost sentences. A refusal is a sentence in `prebuilt_*.py` and a test that
restated it here would be a second copy of the thing it is checking — the
defect `CLAUDE.md` names twice. Those claims are held by the reader and by the
ticket's own traceability table, and this file says so rather than implying a
coverage it does not have.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
PAGE = REPO / "docs" / "prebuilt-tools.md"
PORT_SPECS = REPO / "backend" / "openstategraph" / "compile" / "port_specs.json"

#: The line a section carries when it lists the boxes a developer fills in.
CONFIGURED_WITH = "**Configured with:**"


def _generator():
    """`scripts/build_module_index.py`, loaded by path — it is not a package."""
    path = REPO / "scripts" / "build_module_index.py"
    spec = importlib.util.spec_from_file_location("build_module_index", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def routed_here() -> list[str]:
    """Every node type whose "Read more" cell points at this page."""
    generator = _generator()
    types = [n["type"] for n in generator.node_types()]
    return [
        type_id
        for type_id in types
        if re.fullmatch(r"\[.+\]\(prebuilt-tools\.md\)", generator.deeper_for(type_id))
    ]


def field_keys() -> dict[str, set[str]]:
    catalogue = json.loads(PORT_SPECS.read_text(encoding="utf-8"))["node_types"]
    return {node["type"]: set(node.get("field_keys") or []) for node in catalogue}


def sections() -> dict[str, str]:
    """Each `###` block of the page, keyed by the type id its heading names.

    A heading may name one type only. That is not a style rule: a section
    covering two cards cannot say which of them a field belongs to, which is
    exactly the confusion this pin exists to prevent.
    """
    found: dict[str, str] = {}
    current: str | None = None
    for line in PAGE.read_text(encoding="utf-8").splitlines():
        if line.startswith("### "):
            ids = re.findall(r"`([a-z]+\.[a-z0-9-]+)`", line)
            current = ids[0] if len(ids) == 1 else None
            if current:
                found[current] = ""
            continue
        if current:
            found[current] += line + "\n"
    return found


def test_the_page_is_routed_at_from_the_module_index() -> None:
    """A sweep over nothing passes. `docs-onramp/11` left exactly ten rows
    with no page to read more on, and this page is their answer."""
    assert PAGE.is_file()
    assert len(routed_here()) >= 10, (
        "nothing routes at docs/prebuilt-tools.md any more — either DEEPER lost "
        "its rows or this pin is measuring an empty set"
    )


def test_every_routed_card_has_a_section_on_the_page() -> None:
    """The promise `docs-onramp/11`'s pin makes at the row level, at the
    section level: a reader who clicked *this* card lands on *that* card."""
    covered = sections()
    missing = [type_id for type_id in routed_here() if type_id not in covered]
    assert missing == [], (
        "docs/modules.md sends these rows to docs/prebuilt-tools.md and the page "
        f"has no `### ` section naming them: {missing}"
    )


def test_every_section_says_what_its_card_is_configured_with() -> None:
    without = [
        type_id
        for type_id, body in sections().items()
        if CONFIGURED_WITH not in body
    ]
    assert without == [], (
        f"these sections never answer the first of the page's three questions "
        f"({CONFIGURED_WITH}): {without}"
    )


def test_every_field_the_page_names_exists_on_that_card() -> None:
    """The rot this file was written for: a renamed field reddens the page.

    Only the `Configured with:` line is read. Prose elsewhere in a section may
    quote a refusal, a label or an environment variable, and none of those are
    field keys — a check over the whole section would be a check that fails for
    reasons other than the one it names.
    """
    keys = field_keys()
    wrong: dict[str, list[str]] = {}
    for type_id, body in sections().items():
        if type_id not in keys:
            continue
        for line in body.splitlines():
            if not line.strip().startswith(CONFIGURED_WITH):
                continue
            named = re.findall(r"`([A-Za-z][A-Za-z0-9_]*)`", line)
            unknown = [name for name in named if name not in keys[type_id]]
            if unknown:
                wrong[type_id] = unknown
    assert wrong == {}, (
        "docs/prebuilt-tools.md tells a reader to fill in fields that are not on "
        f"the card's descriptor in port_specs.json: {wrong}"
    )


def test_a_section_that_names_no_field_would_not_pass_silently() -> None:
    """The pin above is vacuous for a section whose line names nothing, so the
    line has to name something. Every one of these cards has at least the three
    graph-assembly overrides every card carries."""
    empty = []
    for type_id, body in sections().items():
        for line in body.splitlines():
            if line.strip().startswith(CONFIGURED_WITH) and not re.findall(
                r"`([A-Za-z][A-Za-z0-9_]*)`", line
            ):
                empty.append(type_id)
    assert empty == [], f"these sections list no field name at all: {empty}"
