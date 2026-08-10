"""OpenStateGraph — a compiler from a vendor-neutral `workflow.json` to a
LangGraph `StateGraph`.

The public surface for *consuming* a workflow package you authored elsewhere
is deliberately one function:

    from openstategraph import load_workflow

    workflow = load_workflow("path/to/my-workflow")
    print(workflow.ask("How many invoices are there?"))

Everything else — the editor's HTTP API, the MCP transport, the compiler and
runtime internals — stays in its own module and is imported only when used.
This package's own import touches neither LangGraph, LangChain nor FastAPI.

**Three tiers, and `__all__` here is the top one.**

- **Tier 1, semver-public**: the names below, everything in
  `openstategraph.abc`, `openstategraph.errors`, `openstategraph.schema`,
  `openstategraph.extensions` (whose entry-point *group names* live in third
  parties' own `pyproject.toml` files), and
  the `workflow.json` document format itself — which is more public than any
  Python symbol we ship, because a document written against schema version *N*
  must load on every release that claims to support *N*.
- **Tier 2, provisional**: `openstategraph.compile`, `.knowledge`,
  `.plugin_interop`, `.prebuilt_*`. Importable and documented; may change in a
  minor release with a changelog note.
- **Tier 3, internal**: `openstategraph.api.*` and `openstategraph.mcp_server`.
  Surfaces we operate, not libraries others build on. No stability guarantee.

`docs/stability.md` is the contract, and `backend/tests/test_public_api.py`
enforces it against a checked-in signature snapshot — a test that merely
asserted `"load_workflow" in dir(...)` would never have caught the private
`_document_of` import that the public loader shipped with for months.
"""

from openstategraph.errors import (
    DocumentError,
    InvalidPackageName,
    OpenStateGraphError,
    PackageNotFound,
    SchemaVersionError,
    WorkflowPackageError,
)
from openstategraph.loader import (
    DEFAULT_RECURSION_LIMIT,
    CompiledWorkflow,
    load_workflow,
)
from openstategraph.results import RunResult


def _installed_version() -> str:
    """The version, from the installed distribution's own metadata.

    Single-sourced deliberately from **metadata rather than a literal here**:
    metadata is what an adopter can query about the thing they actually
    installed, and a literal in this file can disagree with the wheel that
    contains it. The fallback covers the case this repo's own test suite runs
    in — imported from a source tree via `PYTHONPATH`, never installed — and is
    the only place the number is written twice, so keep the two in step when
    releasing (`backend/pyproject.toml` is the source).
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("openstategraph")
    except PackageNotFoundError:  # source tree, not installed
        return "0.3.0+source"


__version__ = _installed_version()

__all__ = [
    "CompiledWorkflow",
    "DEFAULT_RECURSION_LIMIT",
    "DocumentError",
    "InvalidPackageName",
    "OpenStateGraphError",
    "PackageNotFound",
    "RunResult",
    "SchemaVersionError",
    "WorkflowPackageError",
    "__version__",
    "load_workflow",
]
