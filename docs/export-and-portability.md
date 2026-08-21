# Exporting a workflow: what leaves this project, and what doesn't

Three questions that keep coming up together, because they're all "how much
of `openstategraph` do I actually have to carry": can I get pure LangGraph
with zero `openstategraph` dependency, what does the MCP layer let me do
today, and what would a portable Python or Node/TypeScript export look like.
Short answers first, mechanics after.

| Question | Today |
| --- | --- |
| Zero-dependency pure-LangGraph export | **No.** `openstategraph` compiles a `StateGraph` in memory; nothing writes that construction out as source. See [§1](#1-exporting-with-zero-openstategraph-dependency). |
| An MCP layer | **Yes, shipped.** `openstategraph mcp`, 9 tools, documented in [`mcp.md`](mcp.md) / [`decisions/mcp-layer.md`](decisions/mcp-layer.md). See [§2](#2-the-mcp-layer-status-and-roadmap). |
| Node/TypeScript plug-and-play export | **No, and not planned.** No LangGraph.js anywhere in this repo; TypeScript here never executes a graph. See [§3](#3-output-shape-python-vs-nodetypescript). |

---

## 1. Exporting with zero `openstategraph` dependency

**Not achievable today, and it's an unaddressed gap rather than a documented
non-goal** — no decision record argues against it, it has simply never been
built.

### What actually happens at compile time

`backend/openstategraph/compile/workflow_compiler.py` turns a document into a
graph by calling the real `langgraph.graph.StateGraph` builder API directly —
`StateGraph()`, `.add_node()`, `.add_edge()`, conditional edges for routers,
`Send` for fan-out. That construction happens in memory, once, inside a
Python process that has `openstategraph` imported. Nothing in the backend
serializes it back out as a `.py` file: a repo-wide search for the usual
codegen verbs (`to_source`, `generate_module`, `ast.unparse`, `write_python`)
finds nothing that writes source. (`ast.unparse` does appear, three times, in
`backend/tests/test_data_key_contract.py` — quoting an expression back into an
assertion message. That is the opposite direction.) The one **export** in this
codebase that produces an artifact — `plugin_interop.export_plugin()`, also
reachable as the MCP `export_plugin` tool and
`GET /api/workflows/{slug}/plugin-export` — renders `skills/` and
extension metadata as an **Agent Plugins v1** bundle (`plugin.json` +
`SKILL.md` files) for tools like Claude/Cursor/Copilot. It explicitly does
**not** touch the graph: it even writes a note into its own output saying so
(`"No mcp.json emitted: this runtime models no MCP servers…"`). It's a
different kind of export than the one these questions are asking about.

Since `export-and-eject/06` that bundle also carries a generated `README.md`,
and it is the one place the two halves of this page meet a stranger: the
`pip install` line naming exactly the extras *that document* asks for —
derived from its own model strings (both spellings), its `tier: deep` nodes and
its `settings.checkpointer` — and a "what did not come with it" section that is
the export's own `notes` rendered as Markdown rather than prose written beside
them. When the bundle carries `tools/`, `functions/`, `middlewares/`,
`knowledge/` or `skills/`, the README says the paragraph below in the reader's
own terms, because that is exactly the reader who is about to lose the wiring.
A package carrying none of them is told none of it.

It also prints the recipe that actually works rather than the obvious one:
`org.openstategraph/` holds the payload but cannot be loaded under its own name
— `load_workflow` refuses a directory name that is not a slug, and a reverse
domain has a period in it — so the README says to copy it out under the
plugin's name first.

### What you get instead, and what it costs

```python
from openstategraph import load_workflow

workflow = load_workflow("workflows/my-thing")
workflow.graph   # a genuine langgraph CompiledStateGraph
```

Quoting [`what-is-this.md`](what-is-this.md#what-needs-us-at-run-time-precisely):

> **The compiled graph does not [need us].** It is a plain LangGraph object.
> `CompiledWorkflow.graph` hands it over, and every LangGraph capability
> works on it with nothing of ours in the call stack.

That's real — once you're holding `.graph`, every LangGraph feature
(checkpointing, `interrupt()`, streaming, time travel) works with no
OpenStateGraph code in the call stack. The caveat is *getting there*:
producing that object still means calling `load_workflow()`, which means
`openstategraph` is installed and imported. There's no way to hand someone a
`.py` file that reconstructs the same graph using only `langgraph`/
`langchain` imports.

If your goal is minimizing the dependency rather than eliminating it, that's
what [adoption.md's mode (b), "Artifact"](adoption.md) already gives you: you
commit `workflow.json` + the package folder to your own repo and
`pip install openstategraph[<providers>]` — the measured core is **4
packages / 36 distributions** (measured 2026-08-10; see `adoption.md`) (`langgraph`, `langchain`, `langchain-core`,
`pydantic`, plus transitive deps), 38 with one provider extra
([`decisions/framework-packaging.md`](decisions/framework-packaging.md)). No
`[server]`, no `[mcp]`, no editor. That's the floor today, not zero.

One more reason hand-compiling the JSON yourself isn't a real workaround:
`tools/`, `functions/`, `middlewares/`, `skills/` and `knowledge/` are wired
by OpenStateGraph's own discovery conventions. Skip `load_workflow` and
compile the document by hand, and — per the same page — "the agent is drawn
with three tools, bound to none, and confidently answers from parametric
memory." `load_workflow` exists specifically to report that failure on
`.warnings` instead of silently producing a broken agent — and, since
`production-ready/79`, `openstategraph validate` answers the same question for
free, before a run costs anything: a bound tool with no implementation in this
installation is a PROBLEM and exit 1, naming the node, the type and the
`tools/` folder that is missing.

### Roadmap

Nothing. Not in `.scratch/fullstack-langgraph/map.md`, not in
[`decisions/gap-register.md`](decisions/gap-register.md), not in any
`decisions/` file. `what-is-this.md` rejects "a second **runtime** target"
(§3 below), but a source-code generator targeting the *same* LangGraph API
is a different idea and hasn't been proposed or rejected either way — it's
simply not built.

## 2. The MCP layer: status and roadmap

**Shipped and reasonably mature.** Full docs live at [`mcp.md`](mcp.md) (a
worked session) and [`decisions/mcp-layer.md`](decisions/mcp-layer.md) (the
decision record) — this section is the status summary, not a replacement for
either.

### What it is

`backend/openstategraph/mcp_server.py`, built on `FastMCP`
(`mcp.server.fastmcp`), behind the `[mcp]` extra. Run it with
`openstategraph mcp [--transport stdio|streamable-http]` or
`python -m openstategraph.mcp_server`. `stdio` is the default — what a local
client (Claude Desktop, Cursor) spawns directly. `streamable-http` is for a
shared deployment; set `OPENSTATEGRAPH_API_TOKEN` (the same variable the HTTP
API uses) to gate it, or it starts anyway and **logs a warning** that it's
listening unauthenticated — deliberate, so a local experiment costs nothing
and a shared one can't go unauthenticated silently.

The framing, from `mcp.md`: *"Your LLM composes. This server is the ground
truth and the artifact factory."* Compile and validate are stateless and
model-free — that half needs no provider key at all.

### The 9 tools

| Tool | Does |
| --- | --- |
| `get_node_vocabulary` | **mandatory first call.** The node/port catalogue, generated from the same TypeScript source of truth the editor uses (`npm run generate:ports`, CI-gated against drift) |
| `compile_workflow` | validates + returns the compiled topology as Mermaid, plus `warnings`/`findings` |
| `validate_workflow` | findings only, no compile |
| `list_workflows` | the catalogue, editor or `/chat` surface |
| `describe_workflow` | one workflow's shape |
| `get_knowledge` | a package's second-brain docs |
| `export_plugin` | the Agent Plugins bundle from §1 — not the graph |
| `save_workflow_draft` | writes a draft. **No publish, no delete tool exists** — "a human clicks publish in the editor," enforced, not just documented |
| `run_workflow` | the only tool that spends model budget; removable entirely via `OPENSTATEGRAPH_MCP_ALLOW_RUNS=0`, which the other 8 don't need |

### Roadmap — the real open items, from `decisions/mcp-layer.md` §5–6

- **Auth is admission, not identity.** A shared bearer token gates
  `streamable-http`; `stdio` isn't gated at all (the spawning process already
  has whatever OS access it has). Every token holder is the same principal —
  re-open when per-user authorization is needed; the MCP spec's own
  authorization story is the stated answer, not yet adopted.
- **Single worker.** State now survives a restart (`SqliteSaver`, shared with
  the HTTP transport), but concurrency doesn't: a second worker **fails at
  startup** rather than corrupting a paused approval. `[postgres]` doesn't
  lift this yet.
- **No `resume_workflow` tool.** `run_workflow` is synchronous, unstreamed,
  and a `human.approval` pause reports its `thread_id` but nothing here can
  continue it — that's the HTTP API's `/api/runs/resume` or the editor today.
  Tracked as **PF-04**; the durable-checkpointer prerequisite it was blocked
  on (ticket 05) is already done, so this is the next unblocked piece.
- **No rate limiting, quotas, or audit log.** Called out as "the largest
  remaining gap on this layer" — tracked as **SEC-02**.
- **No MCP client.** The server can't consume someone else's MCP tools, and
  importing a client's `mcp.json` stays an explicit, reported gap (see
  [`decisions/agent-plugins.md`](decisions/agent-plugins.md) §7).
- **Compile is stateless**, so it can't resolve a `workflow.subgraph` child or
  a package-local `tool.*` — reported as a
  `warnings` field, never silently dropped, but a client has to read it.

## 3. Output shape: Python vs. Node/TypeScript

**Python today: a live object, not a file. Node/TypeScript: doesn't exist,
and isn't on the roadmap.**

### Python

What `workflow.graph` gives you is an in-memory
`langgraph.graph.StateGraph` → `CompiledStateGraph`, built by real builder
calls against the document (see §1). It behaves exactly like a hand-written
LangGraph graph, because it *is* one — but it's a runtime value, not
something you `git commit` as a module. What you commit is `workflow.json` +
the package folder; "compiling" it again means calling `load_workflow()` at
process start, every time. There is no flow anywhere in this project that
ends with handing you a `workflow.py`.

### Node/TypeScript

Doesn't exist at any layer, and isn't a stated future item — it's closer to
a stated **non**-goal, once you follow the reasoning one step further than
it's written. `package.json` carries no `@langchain/langgraph` dependency;
per `CLAUDE.md`, TypeScript in this repo is editor-only — it authors
`workflow.json` and never executes a graph. `what-is-this.md`'s "What it
deliberately does not own" is explicit about the adjacent case:

> **A second runtime target.** No `IOrchestrator` abstraction: no competing
> framework accepts a serialisable graph, so the interface would be
> unbindable rather than merely leaky.

LangGraph.js is exactly that second runtime target, so a genuinely
"plug-and-play in the current LangGraph.js architecture" export is working
against a design decision already made here, not just a missing feature.

---

*Sources: `backend/openstategraph/compile/workflow_compiler.py`,
`backend/openstategraph/mcp_server.py`, `backend/openstategraph/plugin_interop.py`,
[`adoption.md`](adoption.md), [`what-is-this.md`](what-is-this.md),
[`mcp.md`](mcp.md), [`decisions/mcp-layer.md`](decisions/mcp-layer.md),
[`decisions/framework-packaging.md`](decisions/framework-packaging.md).*
