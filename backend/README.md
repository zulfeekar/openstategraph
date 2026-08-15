# OpenStateGraph

**A compiler from a vendor-neutral `workflow.json` to a LangGraph
`StateGraph`.** Not an execution engine — the thing it produces is a plain
compiled LangGraph object that runs, streams, checkpoints and deploys
anywhere Python runs, with or without this package's editor.

```bash
pip install "openstategraph[ollama]"
```

```python
from openstategraph import load_workflow

workflow = load_workflow("path/to/my-workflow")
print(workflow.ask("How many invoices are there?"))
```

`load_workflow` takes the one thing an adopter actually has — the package
folder holding `workflow.json` — and wires the package's own `tools/`,
`functions/`, `middlewares/`, `skills/` and `knowledge/` before compiling.
Anything it could not resolve lands on `.warnings` and logs a WARNING, because
the alternative failure mode is a workflow that answers confidently without
the tools it was drawn with.

`workflow.graph` is the escape hatch: the compiled LangGraph object, with
nothing of ours in the way.

## Install footprint

The core is four packages — `langgraph`, `langchain`, `langchain-core`,
`pydantic`. Everything else is an extra, because a consumer of `load_workflow`
should not install a web server or three provider SDKs to run a graph in
their own process.

| Extra | Install it for |
| --- | --- |
| `[anthropic]` / `[openai]` / `[ollama]` | a `model` string starting `anthropic:` / `openai:` / `ollama:` |
| `[deep]` | a document containing an `agent.deep` node |
| `[sqlite]` | `settings.checkpointer: "sqlite"`, or `OPENSTATEGRAPH_MEMORY_PATH` |
| `[server]` | the editor's HTTP API (`openstategraph.api.main`) — the **web layer only**, so pair it with a provider extra (`[server,ollama]`) or the editor opens onto workflows it cannot run |
| `[mcp]` | the MCP transport (`openstategraph.mcp_server`) |
| `[all]` | everything above — what a checkout of this repo wants |
| `[dev]` | contributors (pytest, ruff) |

Each of those is imported lazily at its one call site, and a missing one
raises an `ImportError` naming the exact `pip install` line rather than
degrading quietly.

## Public surface and stability

`openstategraph.__all__` and `openstategraph.abc.__all__` are the semver-public
surface, plus `openstategraph.errors` and the `workflow.json` schema itself.
Everything under `openstategraph.api.*` and `openstategraph.mcp_server` is
internal and carries no stability guarantee. See
[`docs/stability.md`](../docs/stability.md) for the deprecation policy — the
short version is that pre-1.0, a breaking change bumps the **minor**, never the
patch.

MIT licensed. Full documentation lives in the repository's `docs/`.
