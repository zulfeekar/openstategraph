# The MCP layer — capabilities out, authorship stays with the customer

**Status: accepted (owner + implementation, 2026-08-10).**
**Verdict: expose OpenStateGraph's capabilities over MCP as a stateless
compiler service. The customer's own LLM composes; we are ground truth and
artifact factory. Hosting workflows is optional and drafts-only.**

Implementation: `backend/openstategraph/mcp_server.py` (the only file that
knows the strings `FastMCP`, `stdio`, `streamable-http`), plus
`backend/openstategraph/api/services.py`, the shared runtime assembly that
FastAPI and MCP both hold.

## 1. The deployment story

OpenStateGraph runs on a server inside a company. **Only the MCP layer is
exposed** — no editor, no `/api`, no `/chat` necessarily. A team connects
their existing MCP clients (Claude, Cursor, an in-house agent) and uses them
to generate StateGraphs.

The primary flow is **stateless**, and this is the part worth being precise
about, because the obvious design is the wrong one. The obvious design has
workflows living on our server: the client creates one, we store it, they come
back to it. The actual demand is the opposite —

```
their MCP client
   │  1. get_node_vocabulary()          ← mandatory first call
   │  2. compose a document (their LLM)
   │  3. compile_workflow(document) ────► findings?  ──► revise, go to 3
   │                                 └──► artifacts
   ▼
their git repository        workflow.json + tools/ + skills/ + knowledge/
```

The artifact's home is **their repository**, not our disk. `compile_workflow`
returns the normalized `workflow.json` envelope, the compiled Mermaid
topology, a run snippet and the package skeleton, and saves nothing. That is
the compiler-not-runtime rule (CLAUDE.md) carried all the way out to the wire:
our output is a standard Python object that runs anywhere Python runs, and now
the *authoring* of it is portable too.

**The verdict → revise → verdict loop IS the product.** A workflow is data, and
the compiler validates data without running anything, so a client's model can
iterate against deterministic evidence rather than its own confidence. That is
the same rule the Workflow Architect follows internally (`prebuilt_architect.py`);
MCP just points it outward.

### Deterministic and model-free

Everything in the core loop — vocabulary, validate, compile, Mermaid — calls
**no model**. `NodeRuntime(model=None)` compiles the whole topology because
the compiler owns topology and knows nothing about models. Consequences worth
stating plainly:

- **A deployment needs no provider key** to be a complete product.
- `run_workflow` is the **only** tool that touches a model, and
  `OPENSTATEGRAPH_MCP_ALLOW_RUNS=0` removes it from the registry entirely.
  The remaining eight tools stay fully functional.
- Nothing in the core loop can be slow, non-deterministic, or expensive, so
  the iteration loop is cheap enough for a client to run many times.

## 2. The tools

| Tool | What it wraps | Writes? |
| --- | --- | --- |
| `get_node_vocabulary` | the generated `compile/port_specs.json` + `KNOWN_NODE_TYPES` + the ladder classes' locked prompt sections | no |
| `compile_workflow` | `ValidateWorkflowTool` + `WorkflowCompiler.build` + `draw_mermaid(xray=True)`, which expands nothing — mounts and agents are closures, not subgraphs | **no** |
| `validate_workflow` | `ValidateWorkflowTool` | no |
| `list_workflows` | `WorkflowStore.list` | no |
| `describe_workflow` | `WorkflowStore.load` + `validate_package` | no |
| `get_knowledge` | `PackageKnowledge.topics()` / `.lookup()` | no |
| `export_plugin` | `plugin_interop.export_plugin` | no |
| `save_workflow_draft` | `WorkflowStore.create` (no slug) / `.save` (named slug) | **draft only** |
| `run_workflow` | the `/api/runs` path | no |

Every one is a **thin wrapper over an existing seam**. No business logic was
added — a second implementation of validation or of the runtime assembly is
exactly the drift this repo has already paid for once (three run endpoints
that disagreed about capabilities, fixed by pulling them onto one
`runtime_for`). `api/services.py` exists so MCP gets that same assembly
without starting FastAPI, and so neither transport can grow its own copy.

### `get_node_vocabulary` is mandatory, and its description says so

A client's model cannot invent our node types or port ids. Worse, it cannot
guess the thing that actually matters: **not every edge is a graph edge.** An
edge onto a `tool` or `skill` port is a *binding*; an edge onto `text`/`result`
is control flow; `feedback` is half a conditional loop; `worker` declares
fan-out. Wiring a tool as control flow makes the tool run once on its own
*before* the agent calls it, and then the agent calls it too. The vocabulary
payload states this in prose, alongside the machine-readable port table, and
also carries the **locked** preamble/output-contract per model-driven node type
so a client does not restate — or contradict — what the runtime already says.

## 3. The trust boundary

**Drafts in, humans publish.** Stated as rules, each enforced in code and
pinned by a test:

1. **No publish tool exists.** `set_published` is not reachable over MCP. A
   human flips the flag in the editor, having looked at the graph.
2. **No delete tool exists.** MCP cannot remove a workflow.
3. **No credentials cross the wire.** `run_workflow` takes no credentials
   parameter; the model resolves from the server's own environment.
4. **Writes are validated server-side, not on the client's honour.** A
   `save_workflow_draft` of a document that does not compile is *refused* with
   findings and nothing is written — there is no `force`. The library can
   therefore never accumulate documents that do not compile.
5. **A published workflow is never overwritten.** Including the back-compat
   default where a missing `published` flag means published. MCP does not get
   to change what customers are already talking to.
6. **Writes are jailed to `workflows/`.** `WorkflowStore.directory_for`
   rejects any slug that is not a clean slug or that escapes the root.
7. **`recursion_limit` is bounded server-side** (200). It counts *supersteps,
   not iterations*, so an unbounded value from an untrusted client is a
   denial-of-service knob, not a convenience.

`EXPOSED_TOOLS` is the reviewed surface; a test asserts the registered tool
names equal it exactly, and that no tool name contains publish/delete/
credential/secret/key. Adding a tool means editing that tuple, which means the
diff shows up in review.

## 4. Transport and entry point

```bash
python -m openstategraph.mcp_server            # stdio (a client spawns it)
OPENSTATEGRAPH_MCP_TRANSPORT=streamable-http \
  python -m openstategraph.mcp_server          # the server deployment
OPENSTATEGRAPH_MCP_ALLOW_RUNS=0 ...            # close the only model-touching tool
```

stdio is the default because that is what a local MCP client spawns. The
server deployment this decision is about wants `streamable-http`, which is one
environment variable — the SDK exposes both from the same `FastMCP.run`, so
there is no second code path to maintain.

The `mcp` SDK is a declared dependency (`backend/pyproject.toml`), imported
**lazily** inside `build_mcp_server` so the FastAPI runtime still starts on a
deployment that chose not to install it, and fails with a sentence naming the
fix rather than an ImportError traceback.

## 5. Honest limits

- **Authentication: a shared token, off by default (scale-and-adopt ticket
  06).** This bullet used to say the layer authenticates nobody and that v1
  delegates to the deployer's reverse proxy. Two things were wrong with that.
  The proxy was not in the repository, so "put a proxy in front" was advice
  rather than a product; and the commonest deployment of an MCP server is a
  laptop or a team VM where there is no proxy and never will be one. So both
  shipped: `deploy/Caddyfile` / `deploy/nginx.conf` (committed and checked
  against the real routes by `backend/tests/test_reverse_proxy.py`) for
  anything public, and `OPENSTATEGRAPH_API_TOKEN` — the **same** variable the
  HTTP API uses, because it is the same deployment and two secrets would mean
  one of them unset — gating the `streamable-http` transport. Machine-only
  there: `Authorization: Bearer <token>`, no login form, because an MCP client
  cannot fill one in. **`stdio` is deliberately not gated**: the client is the
  process that spawned this one and already has whatever access the OS gives
  it; a token on a pipe is theatre.

  What is still **not** faked is the part the earlier text was right about. A
  shared secret is not identity: every holder is the same principal, nothing is
  attributed to a person, and the MCP specification's own authorization story
  is still the answer when this needs per-user authorization. The token is the
  floor, not the ceiling — see `docs/deploying.md` for the threat model in
  full, and note that unauthenticated is still *possible* (it is the default),
  just never silent: the transport logs what an open port exposes.
- **Single worker, and since scale-and-adopt ticket 06 it is refused rather
  than merely stated (see `openstategraph/deployment.py` and
  `docs/deploying.md`; Postgres is available via `[postgres]` and does *not*
  lift the limit).** State is no longer
  *in-process*: the checkpointer is a `SqliteSaver` on a file under the
  workflows root, held by `WorkflowServices` and shared with the HTTP
  transport, so a run paused here can be resumed there and both survive a
  restart. What is still single-process is *concurrency*: `SqliteSaver` and
  the sqlite-backed memory `Store` serialise with a per-instance
  `threading.Lock`, which two OS processes do not share — and the catalogue
  event fan-out is an in-process queue, which is the second cause and the one
  with no shipped fix. So the ceiling stays one worker, and a second one now
  fails at startup with both reasons named instead of corrupting a paused
  approval quietly.
  The stateless compile loop is unaffected — it holds no state at all.
- **`run_workflow` is synchronous and unstreamed.** No token streaming, and no
  resume *tool*. Since ticket 05 the run does compile with a checkpointer, so
  a `human.approval` workflow genuinely pauses rather than failing to build —
  and `run_workflow` reports the pause and names the durable `thread_id`
  instead of returning a blank answer. Continuing it means the HTTP API's
  `/api/runs/resume` or the editor. A resume tool here is the remaining work
  (register PF-04); the durable checkpointer it was blocked on now exists.
- **Compile is stateless, so it cannot resolve a document's children or its
  package.** A `workflow.subgraph` node naming a hosted slug,
  or an agent bound to a `tool.*` that lives in a package's `tools/` folder,
  resolves to nothing here. The topology is still valid, so this is a
  **warning, not a finding** — `compile_workflow` returns `warnings` distinct
  from `findings`, sourced from the runtime's existing
  `unresolved_subgraphs`/`unresolved_tools` loudness. It is never silent, but a
  client must read that field: "compiles" is not "will be fully capable when
  run". Compose against a deployment that hosts the children, or inline them.
- ~~**The port table is still hand-mirrored.**~~ **Closed (RC-01).**
  `DEFAULT_PORT_SPECS` now reads `compile/port_specs.json`, generated from the
  authoritative TypeScript catalogue by `npm run generate:ports` and gated by
  two CI checks. The mirror is gone, and serving the table over MCP is no
  longer a way to publish drift. What the move surfaced: the hand-written table
  was missing all but ten of the node types the editor actually registers, including
  `workflow.subgraph` and the then-still-extant `team.workflow` — which
  `get_node_vocabulary` advertised with **zero ports**, so a client had no way
  to wire a mounted workflow.
- **No rate limiting, no quotas, no audit log.** `run_workflow` in particular
  spends the deployer's model budget on any connected client's request — and
  the shared token does not change this, because it answers "may this stranger
  in" and says nothing about how much they may spend once they are in. Now the
  largest remaining gap on this layer (register SEC-02); the proxy is where a
  limit goes today.

## 6. Re-open this decision when…

- ~~The MCP layer leaves a trusted network — authentication stops being the
  proxy's job.~~ **Done (ticket 06)**: a shared token ships and the proxy is
  committed. **Update 2026-08-13: the owner concept shipped** — `openstategraph/principal.py`, resolved server-side on the HTTP transport. The MCP layer has **not** adopted it: `mcp_server.py` resolves no principal, so an MCP run is identity-less and user-scoped memory never binds over it. That is now a concrete, scoped piece of work rather than a missing concept.

Re-open when *identity* is needed rather than admission — the MCP
  specification's authorization story, and an owner concept this project does
  not yet have.
- We want interrupts over MCP — the persisted checkpointer prerequisite is met
  (ticket 05); what remains is a `resume_workflow` tool and a way for a client
  to carry the `thread_id` between calls.
- Ticket 02 lands generated port specs — the vocabulary tool should then be
  generated output rather than a read of a hand-maintained table.
- ~~We gain an MCP *client*~~ — **we have one** (`tool.mcp` over
  `prebuilt_mcp.py`'s `MultiServerMCPClient`). Being a server did not give us
  one; a node type did. `mcp.json` import is still an unsupported, reported
  gap, but for a narrower reason: nothing maps an entry in one onto a
  `tool.mcp` node.
