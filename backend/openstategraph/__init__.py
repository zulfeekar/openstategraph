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
"""

from openstategraph.loader import CompiledWorkflow, load_workflow

__all__ = ["CompiledWorkflow", "load_workflow"]
