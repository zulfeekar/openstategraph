"""Every built-in tool the runtime can bind is a tool the editor can draw.

**The mirror case nothing caught** (`workflow-gallery/30`). `unresolved_tools`
fires when a document binds a tool with no *Python* half. Nothing fired for the
opposite: a Python tool registered in `api/registries.py` with no TypeScript
declaration, and therefore no palette card, no port spec, and — for a family
whose `configure()` reads per-node keys — no way to configure it at all.

`openstategraph validate` cannot be the guard. Its `KNOWN_PREFIXES` waves any
`tool.*` id through on purpose, because a workflow-scoped tool
(`tool.chinook-*`) is discovered at run time and cannot sit in a compile-time
list. The cost is that a **platform** tool with no declaration is
indistinguishable from a package tool that will resolve later.

So the check is here instead, and it is a **sweep, not a list**: it walks the
registry the runtime actually builds, rather than naming the families that exist
today. A list of families is a list somebody has to remember to extend, and the
whole defect was that nobody remembered — the SQL Explorer family shipped, ran,
and scored 100% on its eval while being undrawable, for months.

Read off the generated `port_specs.json` for the reason
`test_sql_explorer_field_contract.py` records: a hand-kept mirror of the editor
disagrees with the editor the first time either side moves.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SPECS = REPO / "backend" / "openstategraph" / "compile" / "port_specs.json"


def _declared_node_types() -> set[str]:
    specs = json.loads(SPECS.read_text())
    return {entry["type"] for entry in specs["node_types"]}


def _registered_tool_types() -> set[str]:
    from openstategraph.api.registries import process_tool_layer

    builtin, _discovered = process_tool_layer()
    return set(builtin)


class TestEveryBuiltInToolIsDrawable:
    def test_the_registry_is_not_empty_so_a_pass_means_something(self) -> None:
        # A sweep over nothing passes silently. This is the sentinel that stops
        # an import failure inside `_process_tool_layer` reading as success.
        assert len(_registered_tool_types()) >= 10

    def test_every_registered_tool_has_a_typescript_declaration(self) -> None:
        missing = sorted(_registered_tool_types() - _declared_node_types())
        assert not missing, (
            "These tools are registered in `api/registries.py` and have no entry in "
            f"port_specs.json, so nothing in the palette can draw them: {missing}. "
            "Declare each one in `src/nodes/` and run `npm run generate:ports`."
        )

    def test_the_sql_explorer_family_is_covered_by_that_sweep(self) -> None:
        # The family the ticket was filed about, named so the regression is
        # legible rather than merely absent from a set difference.
        registered = _registered_tool_types()
        declared = _declared_node_types()
        for node_type in ("tool.sql-list-tables", "tool.sql-get-schema", "tool.sql-query"):
            assert node_type in registered, f"{node_type} left the Python registry"
            assert node_type in declared, f"{node_type} has no editor declaration"
