# OpenStateGraph

> **Who this page is for:** you are adding OpenStateGraph to a project you already have,
> from a package index. This is the distribution's own page; there is no
> checkout in it.

**A compiler from a vendor-neutral `workflow.json` to a LangGraph
`StateGraph`.** Not an execution engine — the thing it produces is a plain
compiled LangGraph object that runs, streams, checkpoints and deploys
anywhere Python runs, with or without this package's editor.

```bash
pip install "openstategraph[ollama]"
```

That is the line that works today, and it names no index because it needs
none: **this is on PyPI**. Nothing to pin — `0.3.0` is the first final
release, so an unpinned install resolves it. [`../docs/releasing.md`](../docs/releasing.md)
is the page that says how a version gets here.

You can install the identical artifact from a checkout —
`pip install -e "backend[ollama]"` from the repository root, or build the
wheel with `python3 -m build backend` — which is what CI's `clean-install`
job does, into an empty virtualenv outside the repository.

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

The core is four dependencies — `langgraph`, `langchain`, `langchain-core`,
`pydantic`. Never "four packages": **package** is a settled word here for
`workflows/<slug>/` (CLAUDE.md's lexicon), and `backend/pyproject.toml` names
this line as the place the other sense kept being copied to. Everything else is an extra, because a consumer of `load_workflow`
should not install a web server or three provider SDKs to run a graph in
their own process.

| Extra | Install it for |
| --- | --- |
| `[anthropic]` / `[openai]` / `[ollama]` | a `model` string starting `anthropic:` / `openai:` / `ollama:` |
| `[deep]` | a document containing an `agent.deep` node |
| `[sqlite]` | `settings.checkpointer: "sqlite"`, or `OPENSTATEGRAPH_MEMORY_PATH` |
| `[server]` | the editor's HTTP API (`openstategraph.api.main`) — the **web layer only**, so pair it with a provider extra (`[server,ollama]`) or the editor opens onto workflows it cannot run. Includes `[mcp]`, so `openstategraph mcp` works after this extra alone |
| `[mcp]` | the MCP transport (`openstategraph.mcp_server`) on its own, with no web server |
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
