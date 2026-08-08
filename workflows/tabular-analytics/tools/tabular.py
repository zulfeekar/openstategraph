"""Tabular data tools — generic CSV/Parquet analysis via DuckDB.

These tools provide a generic interface for querying tabular data files,
enabling agents to work with arbitrary datasets (Kaggle CSVs, Parquet files, etc.)
without being tied to a specific schema.

Unlike the Chinook tools which are hardcoded to one SQLite database, these tools:
- Auto-discover CSV/Parquet files in the workflow's data/ directory
- Infer schemas dynamically using pandas
- Execute SQL queries via DuckDB (SQL-on-DataFrames)
- Support multiple files and joins across them
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from pydantic import BaseModel, Field

from openstategraph.abc.tool import BaseTool, NoArgs, ToolResult

#: Default data directory — ships with the workflow
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

#: Row cap for query results — prevents context explosion
DEFAULT_MAX_ROWS = 200


def _safe_table_name(file_path: Path) -> str:
    """Convert a file path to a safe DuckDB table name.

    DuckDB table names must be valid identifiers. We use the stem (filename
    without extension) and replace problematic characters.
    """
    stem = file_path.stem.lower()
    # Replace spaces and problematic chars with underscores
    safe = "".join(c if c.isalnum() else "_" for c in stem)
    # Ensure it doesn't start with a digit
    if safe and safe[0].isdigit():
        safe = "t_" + safe
    return safe or "data_table"


def _load_file(file_path: Path) -> pd.DataFrame:
    """Load a CSV or Parquet file into a pandas DataFrame."""
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(file_path)
    elif suffix == ".parquet":
        return pd.read_parquet(file_path)
    else:
        raise ValueError(f"Unsupported file format: {suffix}. Use .csv or .parquet")


def _rows_to_markdown(columns: list[str], rows: list[tuple], truncated: bool) -> str:
    """Format results as a Markdown table for LLM consumption."""
    if not columns:
        return "_No rows._"
    head = f"| {' | '.join(columns)} |"
    rule = f"| {' | '.join('---' for _ in columns)} |"
    body = [f"| {' | '.join('' if c is None else str(c) for c in row)} |" for row in rows]
    out = [head, rule, *body]
    if truncated:
        out.append(f"\n_Truncated to {len(rows)} rows._")
    if not rows:
        out.append("\n_Query returned no rows._")
    return "\n".join(out)


def _df_to_markdown(df: pd.DataFrame, truncated: bool) -> str:
    """Format a pandas DataFrame as Markdown with schema info."""
    if df.empty:
        return "_No data._"

    # Schema section
    schema_lines = ["**Schema**:", "```"]
    for col, dtype in df.dtypes.items():
        schema_lines.append(f"  {col}: {dtype}")
    schema_lines.append("```")

    # Data section. Rendered with our own formatter rather than
    # `DataFrame.to_markdown`, which quietly requires the `tabulate` package.
    head = df.head(10)
    data_lines = ["\n**Data (first {} rows):**".format(len(head))]
    data_lines.append(
        _rows_to_markdown(
            [str(col) for col in head.columns],
            [tuple(row) for row in head.itertuples(index=False, name=None)],
            False,
        )
    )

    out = schema_lines + data_lines
    if truncated:
        out.append(f"\n_Showing first 10 of {len(df)} rows._")

    return "\n".join(out)


class ListDataFilesArgs(BaseModel):
    model_config = {"extra": "forbid"}
    directory: str = Field(
        default=".",
        description="Subdirectory within data/ to search (default: '.' for root)"
    )


class ListDataFilesTool(BaseTool):
    """List all CSV/Parquet files available for analysis."""

    name = "tabular_list_data_files"
    node_type = "tool.tabular-list-files"
    description = (
        "List all CSV and Parquet files available in the workflow's data directory. "
        "Call this first to discover what datasets are available for analysis."
    )
    Args = ListDataFilesArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, ListDataFilesArgs)

        search_dir = DEFAULT_DATA_DIR / args.directory if args.directory != "." else DEFAULT_DATA_DIR

        if not search_dir.exists():
            return ToolResult.failure(
                f"Data directory not found: {search_dir}. "
                f"Ensure your dataset files are in {DEFAULT_DATA_DIR}"
            )

        files = []
        for ext in ["*.csv", "*.parquet"]:
            files.extend(search_dir.glob(ext))

        if not files:
            return ToolResult(content=
                f"No CSV or Parquet files found in {search_dir}.\n"
                f"Supported formats: .csv, .parquet"
            )

        # Get file sizes for context
        rows = []
        for f in sorted(files):
            size_kb = f.stat().st_size / 1024
            rows.append((f.name, f"{size_kb:.1f} KB", f.suffix))

        return ToolResult(content=
            _rows_to_markdown(["File", "Size", "Type"], rows, False)
        )


class GetTableSchemaArgs(BaseModel):
    model_config = {"extra": "forbid"}
    file_name: str = Field(
        description="Name of the CSV/Parquet file (e.g., 'vgsales.csv')"
    )


class GetTableSchemaTool(BaseTool):
    """Infer and return the schema of a tabular data file."""

    name = "tabular_get_schema"
    node_type = "tool.tabular-get-schema"
    description = (
        "Get the column names, data types, and sample values for a CSV or Parquet file. "
        "Use this to understand the structure of a dataset before querying it."
    )
    Args = GetTableSchemaArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, GetTableSchemaArgs)

        file_path = DEFAULT_DATA_DIR / args.file_name

        if not file_path.exists():
            available = [f.name for f in DEFAULT_DATA_DIR.glob("*.csv")] + \
                       [f.name for f in DEFAULT_DATA_DIR.glob("*.parquet")]
            return ToolResult.failure(
                f"File not found: {args.file_name}\n"
                f"Available files: {', '.join(sorted(available)) or '(none)'}"
            )

        try:
            # Load a sample to infer schema
            df = pd.read_csv(file_path, nrows=100) if file_path.suffix == ".csv" else pd.read_parquet(file_path).head(100)
        except Exception as e:
            return ToolResult.failure(f"Error reading file: {e}")

        # Build schema info
        schema_rows = []
        for col, dtype in df.dtypes.items():
            non_null = int(df[col].notna().sum())
            sample = df[col].dropna().iloc[0] if len(df[col].dropna()) > 0 else None
            sample_str = str(sample)[:50] if sample is not None else "NULL"
            schema_rows.append((col, str(dtype), non_null, sample_str))

        schema_md = _rows_to_markdown(["Column", "Type", "Non-Null", "Sample Value"], schema_rows, False)

        # Add basic stats for numeric columns
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        if numeric_cols:
            stats_lines = ["\n**Numeric column stats:**"]
            for col in numeric_cols[:5]:  # Limit to first 5
                stats = df[col].describe()
                stats_lines.append(f"- {col}: min={stats['min']:.2f}, max={stats['max']:.2f}, mean={stats['mean']:.2f}")
            schema_md += "\n".join(stats_lines)

        return ToolResult(content=schema_md)


class QueryDataArgs(BaseModel):
    model_config = {"extra": "forbid"}
    query: str = Field(
        description="SQL query to execute. Use file name (without extension) as table name."
    )
    max_rows: int | None = Field(
        default=None,
        ge=1,
        le=1000,
        description="Maximum rows to return. Omit to use default (200)."
    )


class QueryDataTool(BaseTool):
    """Execute SQL queries against tabular data files using DuckDB."""

    name = "tabular_query_data"
    node_type = "tool.tabular-query"
    description = (
        "Execute a SQL query against CSV/Parquet files using DuckDB. "
        "Use the file name (without extension) as the table name. "
        "Example: SELECT * FROM vgsales WHERE Genre = 'Action' LIMIT 10"
    )
    Args = QueryDataArgs

    def __init__(self, *, row_cap: int = DEFAULT_MAX_ROWS) -> None:
        self.row_cap = row_cap

    def configure(self, data):
        """The bound node's "Max rows" field becomes this instance's ceiling.

        A fresh instance, never a mutation — two nodes of this type with two
        different caps in one document must not clobber each other.
        """
        configured = data.get("maxRows")
        if isinstance(configured, (int, float)) and configured > 0:
            return type(self)(row_cap=int(configured))
        if isinstance(configured, str) and configured.strip().isdigit():
            return type(self)(row_cap=int(configured.strip()))
        return self

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, QueryDataArgs)

        query = args.query.strip().rstrip(";").strip()
        if not query:
            return ToolResult.failure("Query is empty")

        # Security: only allow SELECT queries
        query_upper = query.upper().strip()
        if not (query_upper.startswith("SELECT") or query_upper.startswith("WITH")):
            return ToolResult.failure(
                "Only SELECT queries are allowed. INSERT, UPDATE, DELETE, DROP are forbidden."
            )

        # Resolve file references in query to actual paths
        # DuckDB can read CSV/Parquet directly with read_csv_auto()
        conn = duckdb.connect(":memory:")

        # Register each data file as a table
        for file_path in DEFAULT_DATA_DIR.glob("*.csv"):
            table_name = _safe_table_name(file_path)
            try:
                conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM read_csv_auto('{file_path}')")
            except Exception:
                pass  # Skip files that can't be read

        for file_path in DEFAULT_DATA_DIR.glob("*.parquet"):
            table_name = _safe_table_name(file_path)
            try:
                conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM read_parquet('{file_path}')")
            except Exception:
                pass

        effective_max = min(args.max_rows, self.row_cap) if args.max_rows is not None else self.row_cap

        try:
            # Add LIMIT if not present and result might be large
            if "LIMIT" not in query_upper:
                query = f"{query.rstrip(';')} LIMIT {effective_max + 1}"

            cursor = conn.execute(query)
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
        except duckdb.Error as e:
            conn.close()
            return ToolResult.failure(f"SQL error: {e}")
        except Exception as e:
            conn.close()
            return ToolResult.failure(f"Query error: {e}")

        conn.close()

        truncated = len(rows) > effective_max
        return ToolResult(content=
            _rows_to_markdown(columns, rows[:effective_max], truncated)
        )


class SampleDataArgs(BaseModel):
    model_config = {"extra": "forbid"}
    file_name: str = Field(
        description="Name of the CSV/Parquet file to sample"
    )
    n_rows: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Number of rows to sample (default: 10, max: 50)"
    )


class SampleDataTool(BaseTool):
    """Return a sample of rows from a data file for exploration."""

    name = "tabular_sample_data"
    node_type = "tool.tabular-sample"
    description = (
        "Get a preview sample of rows from a CSV or Parquet file. "
        "Use this to quickly see what the data looks like before writing queries."
    )
    Args = SampleDataArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, SampleDataArgs)

        file_path = DEFAULT_DATA_DIR / args.file_name

        if not file_path.exists():
            available = [f.name for f in DEFAULT_DATA_DIR.glob("*.csv")] + \
                       [f.name for f in DEFAULT_DATA_DIR.glob("*.parquet")]
            return ToolResult.failure(
                f"File not found: {args.file_name}\n"
                f"Available files: {', '.join(sorted(available)) or '(none)'}"
            )

        try:
            n = min(args.n_rows, 50)
            df = pd.read_csv(file_path, nrows=n) if file_path.suffix == ".csv" else pd.read_parquet(file_path).head(n)
        except Exception as e:
            return ToolResult.failure(f"Error reading file: {e}")

        truncated = len(df) == n and len(df) >= 50
        return ToolResult(content=
            _df_to_markdown(df, truncated)
        )


#: The workflow's tool catalogue
TOOLS = [
    ListDataFilesTool(),
    GetTableSchemaTool(),
    QueryDataTool(),
    SampleDataTool(),
]

__all__ = [
    "TOOLS",
    "ListDataFilesTool",
    "GetTableSchemaTool",
    "QueryDataTool",
    "SampleDataTool",
    "DEFAULT_DATA_DIR",
    "DEFAULT_MAX_ROWS",
]
