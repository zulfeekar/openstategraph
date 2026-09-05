"""One allowlist file, two mounted packages, and neither may read the other's.

`osg-agent-experience/61`. `references/shapes.md` recommends *one tool family +
allowlist* for many tables behind one credential, and *router → N specialist
mounts* when the specialists multiply. A concept that has both — fifteen
specialist packages, one credential, one hand-curated YAML — got a tool whose
`allowlist` field names a **file**, and a file is the whole file. So every
specialist's SQL tool could read every other specialist's tables, and the
refusal a specialist saw offered another one's tables by name:

    Rewrite the SELECT against the allowed tables: <every table in the file>

The per-specialist narrowing existed only in the agent's system prompt, which
is a request rather than a gate.

The rejected repair was fifteen allowlist files, one per package: fifteen
copies of a hand-curated file is the drift the file exists to prevent. So the
binding names a **subset** — `pins`, a list of resolver keys inside the shared
file — and both the gate and the schema the model is offered are narrowed to
it.

Written at the family base (`_WarehouseExplorerBase`) and parametrised by
dialect for `40`'s reason: a behaviour that needs a per-dialect version of its
test is a behaviour that did not belong on the rung.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph.prebuilt_databricks import DatabricksQueryTool
from openstategraph.prebuilt_mssql import MssqlQueryTool

#: Two specialists behind one credential, in one file, the way the shape
#: recommends. Neutral names: this repository refuses a client engagement's
#: vocabulary in a tracked file.
SHARED = """
version: 1
resolvers:
  cargo:
    description: Cargo movements.
    pin:
      dbo.cargo: dbo.cargo_v1r0
      dbo.vessel: dbo.vessel_v1r0
  gas:
    description: Gas balances.
    pin:
      dbo.flow: dbo.flow_v1r0
      dbo.country: dbo.country_v1r0
"""

MAKE = {
    "mssql": lambda **kw: MssqlQueryTool(**kw),
    "databricks": lambda **kw: DatabricksQueryTool(**kw),
}


@pytest.fixture()
def shared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    root = tmp_path / "workflows"
    (root / "concept").mkdir(parents=True)
    (root / "concept" / "lenses.yaml").write_text(SHARED, encoding="utf-8")
    monkeypatch.setenv("OPENSTATEGRAPH_WORKFLOWS_ROOT", str(root))
    return "concept/lenses.yaml"


@pytest.fixture(params=sorted(MAKE), ids=sorted(MAKE))
def make(request: pytest.FixtureRequest):
    return MAKE[request.param]


class TestABindingIsGatedToItsOwnPins:
    def test_the_other_specialist_s_table_is_refused(self, make, shared: str) -> None:
        cargo = make(allowlist=shared).configure({"allowlist": shared, "pins": "cargo"})
        result = cargo.run(query="SELECT * FROM dbo.flow_v1r0")
        assert result.error is not None
        assert "dbo.flow_v1r0" in result.error

    def test_the_refusal_names_only_this_binding_s_tables(self, make, shared: str) -> None:
        cargo = make(allowlist=shared).configure({"allowlist": shared, "pins": "cargo"})
        error = cargo.run(query="SELECT * FROM dbo.flow_v1r0").error or ""
        assert "dbo.cargo_v1r0" in error
        assert "dbo.country_v1r0" not in error, error

    def test_each_binding_keeps_its_own_table(self, make, shared: str) -> None:
        gas = make(allowlist=shared).configure({"allowlist": shared, "pins": "gas"})
        # Its own table gets past the allowlist and is refused later, for want
        # of a connection — the order the refusals happen in is the assertion.
        error = gas.run(query="SELECT * FROM dbo.flow_v1r0").error or ""
        assert "Not in the allowlist" not in error, error

    def test_the_schema_offered_to_the_model_names_only_this_scope(
        self, make, shared: str
    ) -> None:
        cargo = make(allowlist=shared).configure({"allowlist": shared, "pins": "cargo"})
        gas = make(allowlist=shared).configure({"allowlist": shared, "pins": "gas"})
        assert "dbo.cargo_v1r0" in cargo.description
        assert "dbo.flow_v1r0" not in cargo.description, cargo.description
        assert "dbo.flow_v1r0" in gas.description
        assert "dbo.cargo_v1r0" not in gas.description, gas.description


class TestTheSelectorItself:
    def test_a_scope_naming_no_resolver_is_refused_with_the_ones_that_exist(
        self, make, shared: str
    ) -> None:
        tool = make(allowlist=shared).configure({"allowlist": shared, "pins": "crude"})
        error = tool.run(query="SELECT * FROM dbo.cargo_v1r0").error or ""
        assert "crude" in error
        assert "cargo" in error and "gas" in error, error

    def test_no_scope_is_the_whole_file_as_before(self, make, shared: str) -> None:
        tool = make(allowlist=shared).configure({"allowlist": shared})
        error = tool.run(query="SELECT * FROM dbo.nothing").error or ""
        assert "dbo.cargo_v1r0" in error and "dbo.flow_v1r0" in error, error
