"""Tests for the tabular data tools, against the real data directory.

Two deliberate choices, both learned the hard way elsewhere in this repo:

- **Loaded by file path, not by package import.** The workflow directory is a
  hyphenated slug (`tabular-analytics`), so it can never be a Python package —
  and putting a second workflow on `pytest.ini`'s `pythonpath` recreates the
  `tools` collision its own comment warns about. `importlib` under a synthetic
  module name is the approach that comment prescribes.

- **Assertions read the actual content.** An earlier draft asserted
  `hasattr(result, "content") or hasattr(result, "failure")` — true of every
  `ToolResult` including failures — and duly stayed green while every success
  path raised `AttributeError`. A test that cannot fail is worse than none.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

WORKFLOW_DIR = Path(__file__).resolve().parent.parent


def _load_tabular_module():
    """Import `tools/tabular.py` under a synthetic, collision-free name."""
    name = "dyflow_workflow_tabular_analytics_tools_tabular"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, WORKFLOW_DIR / "tools" / "tabular.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tabular = _load_tabular_module()


class TestListDataFiles:
    def test_lists_the_shipped_dataset(self) -> None:
        result = tabular.ListDataFilesTool().run()
        assert result.error is None
        assert "vgsales.csv" in result.content

    def test_a_missing_subdirectory_is_a_failure_not_a_crash(self) -> None:
        result = tabular.ListDataFilesTool().run(directory="no-such-dir")
        assert result.error is not None
        assert "no-such-dir" in result.error or "not found" in result.error.lower()


class TestGetTableSchema:
    def test_reports_real_columns_from_the_csv(self) -> None:
        result = tabular.GetTableSchemaTool().run(file_name="vgsales.csv")
        assert result.error is None
        for column in ("Rank", "Name", "Platform", "Global_Sales"):
            assert column in result.content

    def test_a_missing_file_is_a_failure_naming_the_file(self) -> None:
        result = tabular.GetTableSchemaTool().run(file_name="nope.csv")
        assert result.error is not None
        assert "nope.csv" in result.error

    def test_an_unsupported_extension_is_refused(self) -> None:
        result = tabular.GetTableSchemaTool().run(file_name="vgsales.xlsx")
        assert result.error is not None


class TestQueryData:
    def test_a_real_select_returns_real_rows(self) -> None:
        result = tabular.QueryDataTool().run(
            query="SELECT Name, Global_Sales FROM vgsales ORDER BY Global_Sales DESC LIMIT 3"
        )
        assert result.error is None
        # The markdown table must contain the top row of the actual file.
        assert "Wii Sports" in result.content

    def test_an_aggregation_is_computed_not_echoed(self) -> None:
        result = tabular.QueryDataTool().run(
            query="SELECT COUNT(*) AS n FROM vgsales"
        )
        assert result.error is None
        assert "50" in result.content  # the shipped sample has 50 data rows

    def test_non_select_statements_are_refused(self) -> None:
        result = tabular.QueryDataTool().run(query="DROP TABLE vgsales")
        assert result.error is not None

    def test_an_empty_query_is_refused(self) -> None:
        result = tabular.QueryDataTool().run(query="   ")
        assert result.error is not None

    def test_the_row_cap_bounds_what_the_model_asked_for(self) -> None:
        capped = tabular.QueryDataTool(row_cap=5)
        result = capped.run(query="SELECT Name FROM vgsales", max_rows=1000)
        assert result.error is None
        # Header + rule + at most 5 data rows (+ truncation note).
        data_rows = [line for line in result.content.splitlines() if line.startswith("| ")]
        assert len(data_rows) <= 5 + 2

    def test_sql_errors_come_back_as_data_not_exceptions(self) -> None:
        result = tabular.QueryDataTool().run(query="SELECT nonsense FROM nowhere")
        assert result.error is not None


class TestSampleData:
    def test_returns_real_first_rows(self) -> None:
        result = tabular.SampleDataTool().run(file_name="vgsales.csv", n_rows=5)
        assert result.error is None
        assert "Wii Sports" in result.content

    def test_an_oversized_n_rows_is_rejected_as_data(self) -> None:
        """Pydantic's `le=50` refuses it; the refusal must arrive as a
        `ToolResult` the model can read, never as an exception."""
        result = tabular.SampleDataTool().run(file_name="vgsales.csv", n_rows=500)
        assert result.error is not None
        assert "n_rows" in result.error

    def test_a_missing_file_is_a_failure(self) -> None:
        result = tabular.SampleDataTool().run(file_name="ghost.csv")
        assert result.error is not None


class TestCatalogue:
    def test_four_tools_with_unique_names(self) -> None:
        names = [tool.name for tool in tabular.TOOLS]
        assert len(names) == 4
        assert len(set(names)) == 4

    def test_every_tool_publishes_a_manifest(self) -> None:
        for tool in tabular.TOOLS:
            manifest = tool.manifest()
            assert manifest["name"] == tool.name
            assert manifest["args_schema"]
