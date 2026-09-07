"""`docs/ports-and-edges.md` — the page whose subject is the type system.

`docs-and-gaps` 26 found it wrong about the type system in five places, and
they are all one defect: the page's tables were typed by hand from a catalogue
that is *generated*. `compile/port_specs.json` knows every port of every node
type, and `src/core/validation/ConnectionValidator.ts` registers its own rules
in a list — so both tables are derivable, and neither was derived.

The load-bearing one is `feedback`. That table is the **argument** for why the
type system is the cycle gate: "nothing else accepts `feedback`, so there is no
wire you can drag by mistake that closes a cycle". An argument that enumerates
two of three producers is not a weaker argument, it is an argument a reader can
check and find false.

Coverage only, in one direction: every port the catalogue declares must appear
on the page. The page may say more — it explains what each type *carries*, and
prose around a table is not a list this test gets to police.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PAGE = REPO / "docs" / "ports-and-edges.md"
SPECS = REPO / "backend" / "openstategraph" / "compile" / "port_specs.json"
VALIDATOR = REPO / "src" / "core" / "validation" / "ConnectionValidator.ts"


@pytest.fixture(scope="module")
def page() -> str:
    return PAGE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ports() -> list[tuple[str, str, str, object]]:
    """`(qualified id, direction, port type, max_connections)`, every one."""
    spec = json.loads(SPECS.read_text(encoding="utf-8"))
    return [
        (f"{node['type']}.{port['id']}", port["direction"], port["type"],
         port.get("max_connections", "unset"))
        for node in spec["node_types"]
        for port in node.get("ports", [])
    ]


def _of_type(ports: list[tuple[str, str, str, object]], type_: str, direction: str) -> list[str]:
    return sorted(name for name, dir_, t, _ in ports if t == type_ and dir_ == direction)


class TestTheFeedbackArgumentEnumeratesEveryPort:
    """The cycle gate, and the sentence that says it is one."""

    def test_every_producer_is_named(self, page: str, ports: list) -> None:
        missing = [p for p in _of_type(ports, "feedback", "out") if f"`{p}`" not in page]
        assert not missing, (
            f"{missing} produce `feedback` and the page never names them. This "
            "page argues that the type system is the cycle gate by enumerating "
            "the ports — an enumeration that is short is the argument being "
            "false, not merely incomplete."
        )

    def test_every_consumer_is_named(self, page: str, ports: list) -> None:
        missing = [p for p in _of_type(ports, "feedback", "in") if f"`{p}`" not in page]
        assert not missing, f"{missing} consume `feedback` and the page never names them."

    def test_the_sets_are_not_empty(self, ports: list) -> None:
        # So the sweep above cannot pass by matching nothing.
        assert _of_type(ports, "feedback", "out")
        assert _of_type(ports, "feedback", "in")


class TestTheResultRowIsWholeToo:
    @pytest.mark.parametrize("direction", ["out", "in"])
    def test_every_result_port_is_named(
        self, page: str, ports: list, direction: str
    ) -> None:
        missing = [p for p in _of_type(ports, "result", direction) if f"`{p}`" not in page]
        assert not missing, f"{missing} carry `result` and the page never names them."


class TestABusIsAnInputThatTakesMany:
    def test_every_unbounded_input_is_named(self, page: str, ports: list) -> None:
        buses = sorted(
            name for name, dir_, _, cap in ports if dir_ == "in" and cap is None
        )
        assert buses
        missing = [p for p in buses if f"`{p}`" not in page]
        assert not missing, (
            f"{missing} declare `max_connections: null` on an input and the "
            "page's bus list does not have them. An output is unbounded "
            "without declaring anything, so only inputs belong on that list."
        )


class TestTheRulesTableIsTheRegistry:
    """Seven registered rules; the table listed six for as long as there were seven."""

    @staticmethod
    def _registered() -> list[str]:
        source = VALIDATOR.read_text(encoding="utf-8")
        block = source[source.index("DEFAULT_CONNECTION_RULES") :]
        # `= [` and not the first `]`: the type annotation is
        # `readonly IConnectionRule[]`, whose bracket pair comes first.
        block = block[block.index("= [") :]
        block = block[: block.index("]")]
        names = re.findall(r"(\w+Rule),", block)
        ids = []
        for name in names:
            match = re.search(
                rf"export const {name}: IConnectionRule = \{{\s*\n\s*id: '([^']+)'", source
            )
            assert match, f"{name} is registered and declares no id."
            ids.append(match.group(1))
        return ids

    def test_every_registered_rule_has_a_row(self, page: str) -> None:
        rows = [
            line for line in page.splitlines()
            if re.match(r"^\| \d+ \| `[a-z-]+` \|", line)
        ]
        listed = [line.split("`")[1] for line in rows]
        assert listed == self._registered(), (
            f"The rules table lists {listed}; `ConnectionValidator` registers "
            f"{self._registered()}, in that order. A rule missing from this "
            "table is a refusal a user meets with no documented reason."
        )
