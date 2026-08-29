"""`docs/on-the-canvas.md` is where a user meets this product's lexicon.

`CLAUDE.md` says so by name. So a node type a user can drag out of the palette
and wire into the shape that page's section 3 is *about* has to appear on it,
and until docs-and-gaps/20 one did not: `guard.check` shipped in
`launch-readiness/65`, appears in six runtime modules, and was mentioned on
that page **zero** times.

**The first half of that ticket was deciding whether it belonged there at all**
— an internal mechanism named on a user page is its own defect, and closing as
"correctly absent" was a real outcome. It is not internal. The evidence is
`compile/port_specs.json`, which is the editor's contract: `guard.check` is
`scope: "app"`, labelled **Guard**, carries three ports and five configurable
fields, and has a card in `src/nodes/guard/GuardCheckNode.ts`. A user drags it.

**The property pinned here is narrower and more durable than "mention the
guard".** A revision loop is closed by a **port type**, not a node type — any
node declaring an outbound `feedback` port is a way out of a cycle, which is
the same fact `launch-readiness/177` relied on when it read escapes off the
compiled plan rather than from a list of type names. Section 3 tells a reader
that a loop always has a way out; if the set of ways out grows and the page
does not, the page is teaching a smaller product than the one that shipped.

So: **every `feedback`-producing node type is named on that page**, and the set
is read from `port_specs.json` rather than restated here. A fourth one tomorrow
fails this until the page carries it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

REPO = Path(__file__).resolve().parents[2]
PAGE = REPO / "docs" / "on-the-canvas.md"
PORT_SPECS = REPO / "backend" / "openstategraph" / "compile" / "port_specs.json"


def specs() -> Iterator[dict[str, Any]]:
    def walk(node: Any) -> Iterator[dict[str, Any]]:
        if isinstance(node, dict):
            if "type" in node and "ports" in node:
                yield node
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)

    yield from walk(json.loads(PORT_SPECS.read_text()))


def loop_closers() -> list[dict[str, Any]]:
    return [
        spec
        for spec in specs()
        if any(p["direction"] == "out" and p["type"] == "feedback" for p in spec["ports"])
    ]


class TestGuardCheckIsUserFacing:
    """The determination the ticket asked for, recorded so it is not re-argued."""

    def test_it_is_a_node_a_user_can_place(self) -> None:
        (guard,) = [s for s in specs() if s["type"] == "guard.check"]
        assert guard["scope"] == "app", "a scoped-out node would not be in the palette"
        assert guard["label"] == "Guard"
        assert {p["id"] for p in guard["ports"]} == {"candidate", "pass", "revise"}
        assert guard["drives_model"] is False, (
            "the whole point of the family — a grader's verdict without a model call"
        )

    def test_it_has_configuration_a_user_types_into(self) -> None:
        (guard,) = [s for s in specs() if s["type"] == "guard.check"]
        assert "check" in guard["field_keys"]

    def test_the_editor_carries_a_card_for_it(self) -> None:
        assert (REPO / "src" / "nodes" / "guard" / "GuardCheckNode.ts").is_file()


class TestEveryWayOutOfALoopIsOnThePage:
    def test_the_set_is_not_empty(self) -> None:
        """Guards the guard: an empty set would make the test below vacuous."""
        assert len(loop_closers()) >= 3

    def test_each_one_is_named(self) -> None:
        page = PAGE.read_text()
        missing = [
            f"{spec['type']} ({spec['label']})"
            for spec in loop_closers()
            if spec["type"] not in page and spec["label"] not in page
        ]
        assert missing == [], (
            "docs/on-the-canvas.md's section 3 promises a reader that a loop "
            "always has a way out, and these are ways out it does not "
            f"mention: {missing}"
        )

    def test_the_page_says_which_of_them_needs_no_model(self) -> None:
        """The distinction is the reason to reach for one rather than the other.

        A deterministic check routed through a model is not merely wasteful:
        the model relays what it was told, which is how internal check names
        reached a customer's answer in this product before.
        """
        page = PAGE.read_text()
        assert "no model" in page
        assert "guard.check" in page


class TestTheBuiltInChecksArePublishedWhereTheyAreTyped:
    """A field whose three magic values live only in a hint is a hidden feature."""

    def test_the_page_names_every_check_that_needs_no_package_function(self) -> None:
        from openstategraph.compile.node_runtime import _BUILT_IN_CHECKS

        page = PAGE.read_text()
        missing = [name for name in _BUILT_IN_CHECKS if name not in page]
        assert missing == [], (
            "these checks are wired by typing their name into a Guard's Check "
            f"field and need no functions/ file, and the page omits: {missing}"
        )
