Type: research
Status: resolved
Blocked by: —

## Question

What is the boundary between the TS editor and the Python runtime?

Establish:
- What **LangGraph Server / Platform** provides out of the box (endpoints, streaming, thread management, its own persistence) and its licence — versus hand-rolling FastAPI.
- The streaming interface: `stream_mode` values, how token-level and node-level events arrive, and whether it is SSE or websocket over HTTP.
- Whether the editor should talk to LangGraph Server directly or through our own API.
- What the wire format for "run this workflow" is, and how run/node status maps back onto canvas cards.

This decides the repo topology and whether we own an API layer at all — so it blocks the topology decision.

## Answer

**Verdict: we own a FastAPI layer.** LangGraph's server product is not open source (Elastic License 2.0 + a mandatory commercial licence key for production), so it cannot be adopted by an OSS-only project. We build our own HTTP/SSE layer on the MIT-licensed `langgraph` library, but we deliberately copy the *shape* of LangGraph's own API (assistants / threads / runs, `stream_mode`, SSE frames) so the wire format is a known-good design and a future swap stays cheap.

Note on naming: what the ticket calls "LangGraph Server / LangGraph Platform" has been renamed **Agent Server**, and now lives under the **LangSmith Deployment** product rather than as a standalone LangGraph product. All current docs use that name.

---

### 1. What Agent Server (ex-LangGraph Server) gives out of the box

Source: [Agent Server](https://docs.langchain.com/langsmith/agent-server), [Agent Server API reference](https://docs.langchain.com/langsmith/server-api-ref)

Three primitives — **assistants** (a graph + a pinned config, versioned), **threads** (persisted conversation/run state), **runs** (an invocation) — plus **crons** and a **store** (long-term cross-thread memory).

Full endpoint surface (from the [Agent Server OpenAPI spec](https://docs.langchain.com/langsmith/server-api-ref)):

```
POST   /assistants  /assistants/search  /assistants/count
GET    /assistants/{id}  /assistants/{id}/graph  /assistants/{id}/schemas
       /assistants/{id}/subgraphs  /assistants/{id}/versions  /assistants/{id}/latest
POST   /threads  /threads/search  /threads/count  /threads/prune
GET    /threads/{id}  /threads/{id}/state  /threads/{id}/history
POST   /threads/{id}/state  /threads/{id}/copy  /threads/{id}/commands
POST   /threads/{id}/runs            # background run, returns run_id immediately
POST   /threads/{id}/runs/stream     # create + stream (SSE)
POST   /threads/{id}/runs/wait       # create + block for final output
GET    /threads/{id}/runs/{run_id}/stream    # join an in-flight run's stream
POST   /threads/{id}/runs/{run_id}/cancel
GET    /threads/{id}/stream                  # thread-scoped stream, open indefinitely
POST   /threads/{id}/stream/events           # "Protocol v2" stream (SSE; also WebSocket)
POST   /runs  /runs/stream  /runs/wait  /runs/batch  /runs/cancel   # stateless (no thread)
POST   /runs/crons  /threads/{id}/runs/crons
       /store/items  /store/items/search  /store/namespaces
       /a2a/{assistant_id}   /mcp/
GET    /ok  /info  /metrics  /docs
```

Built-in persistence: **PostgreSQL** for core resource data (assistants, threads, runs, crons — always Postgres), checkpoints (short-term memory; optionally MongoDB or custom), and the store (long-term memory). **Redis** is required, used only as ephemeral pub/sub for streaming, cancellation signalling, and waking queue workers — no run data lives there.

Also built in: a **durable task queue** with exactly-once semantics, API/worker split with independent autoscaling, `durability` modes (`sync`/`async`/`exit`), `multitask_strategy` for concurrent input on one thread (`reject`/`rollback`/`interrupt`/`enqueue`), `on_disconnect` (`cancel`/`continue`), resumable streams, webhooks, cron jobs, custom auth hooks, and pluggable custom routes/middleware/lifespan.

Two constraints worth carrying into our own design:
- **The queue enforces at most one run per thread at a time.** Any per-thread concurrency model on the canvas has to respect that.
- **The server injects the checkpointer and store itself** — graphs must not configure their own. Docs are explicit: "Do not configure these in your graph code."

Assistants are explicitly *not* part of the OSS library: "Assistants are a LangSmith Deployment concept. They are not available in the open source LangGraph library." ([Assistants](https://docs.langchain.com/langsmith/assistants))

---

### 2. Licence — decisive, and it rules Agent Server out

| Package / artifact | Role | Licence |
|---|---|---|
| [`langgraph`](https://github.com/langchain-ai/langgraph/blob/main/LICENSE) | the graph library (Pregel engine, `StateGraph`, streaming) | **MIT** |
| [`langgraph-checkpoint-postgres`](https://pypi.org/pypi/langgraph-checkpoint-postgres/json) | Postgres checkpointer | **MIT** |
| [`langgraph-sdk`](https://pypi.org/pypi/langgraph-sdk/json) | *client* for talking to a server | **MIT** |
| [`langgraph-cli`](https://pypi.org/pypi/langgraph-cli/json) | CLI wrapper | **MIT** |
| **[`langgraph-api`](https://pypi.org/pypi/langgraph-api/json)** | **the actual server: HTTP, persistence, task queue, streaming** | **`Elastic-2.0`** |
| **[`langgraph-runtime-inmem`](https://pypi.org/pypi/langgraph-runtime-inmem/json)** | the runtime behind `langgraph dev` | **`Elastic-2.0`** |
| `langchain/langgraph-api` / `langgraph-server` Docker images | production server | commercial, licence-key gated |

So the moment you run `langgraph dev`, `langgraph up`, or `langgraph build`, you are running **Elastic License 2.0** code, not MIT code. ELv2 is source-available, **not** an OSI open-source licence. Its [Limitations](https://www.elastic.co/licensing/elastic-license) are the blockers:

> "You may not provide the software to third parties as a hosted or managed service, where the service provides users with access to any substantial set of the features or functionality of the software."

> "You may not move, change, disable, or circumvent the license key functionality in the software, and you may not remove or obscure any functionality in the software that is protected by the license key."

Licence enforcement is real and documented, not theoretical:
- [Licensing (data plane)](https://docs.langchain.com/langsmith/data-plane#licensing): Agent Server "is automatically configured to perform license key validation" in *every* deployment mode — Cloud/Hybrid validate a LangSmith API key against LangSmith SaaS; self-hosted needs an air-gapped licence key or a Platform Licence Key validated against LangSmith SaaS.
- [Self-host standalone servers](https://docs.langchain.com/langsmith/deploy-standalone-server) requires `LANGGRAPH_CLOUD_LICENSE_KEY` plus **egress to `https://beacon.langchain.com`** "for license verification and usage reporting if not running in air-gapped mode", and notes "Additional API calls are made to confirm that the server has a valid license and to track the number of executed runs and tasks."
- [Deploy to self-hosted](https://docs.langchain.com/langsmith/deploy-to-self-hosted-overview): "Self-hosted deployments require an **Enterprise plan** and the LangSmith license key delivered with that plan."
- [CLI](https://docs.langchain.com/langsmith/cli#up): `langgraph up` — "For local testing, requires a LangSmith API key with access to LangSmith. Requires a license key for production use."
- LangChain's own comparison table states the platform licence plainly: **"Platform license: Proprietary"** ([Fleet comparison](https://docs.langchain.com/langsmith/fleet/comparison#compare-capabilities)).

Even the free local path is not licence-clean: `langgraph dev` needs a LangSmith account/API key ([Local development & testing](https://docs.langchain.com/langsmith/local-dev-testing)), and the runtime it starts is ELv2.

**Two nuances worth recording:**
- The JS server package [`@langchain/langgraph-api`](https://registry.npmjs.org/@langchain/langgraph-api/latest) on npm *is* MIT — but it self-describes as "In-memory implementation of the LangGraph.js API", i.e. the dev-server equivalent, and our runtime is Python where the equivalent (`langgraph-runtime-inmem`) is ELv2. Not a usable loophole for us.
- Because our project is OSS and self-hostable by third parties, ELv2 fails twice over: we cannot ship/vendor it under an OSS licence, and our downstream users offering our editor as a service would themselves be inside the "hosted or managed service" prohibition.

**Conclusion: Agent Server / LangSmith Deployment is out. We keep only the MIT pieces (`langgraph`, `langgraph-checkpoint-postgres`, optionally `langgraph-sdk` as a client) and write the serving layer ourselves.**

---

### 3. Streaming interface

**Transport is SSE over plain HTTP.** Every streaming endpoint responds `Content-Type: text/event-stream` with `id:` / `event:` / `data:` frames. The [OpenAPI spec's Streaming tag](https://docs.langchain.com/langsmith/agent-server-api/streaming/protocol-v2-event-stream-sse) notes WebSocket is *additionally* supported on the newer protocol endpoint only: "WebSocket is also supported at `/threads/{thread_id}/stream/events` (not documented here — OpenAPI 3.1 does not describe WebSocket)." The classic run/thread streams are SSE-only.

Frame shape: `event:` is the stream-mode name, `data:` is that mode's JSON payload, `id:` is a monotonic sequence number. The first frame of a run is always `metadata`:

```
event: metadata
data: {"run_id": "1ef6746e-5893-67b1-978a-0f1cd4060e16", "attempt": 1}

event: updates
data: {"refine_topic": {"topic": "ice cream and cats"}}

event: updates
data: {"generate_joke": {"joke": "This is a joke about ice cream and cats"}}
```
(from [Streaming API](https://docs.langchain.com/langsmith/streaming) and [Configuration](https://docs.langchain.com/langsmith/configuration-cloud))

#### `stream_mode` values accepted over the wire

From the `RunCreateStateful` schema in the OpenAPI spec — a string or array of strings, default `["values"]`:

| `stream_mode` | Emits | Granularity |
|---|---|---|
| `values` | the **full graph state** after each super-step | step |
| `updates` | the **state delta per node**, keyed by node name (`{"node_name": {...}}`); parallel nodes in one step arrive as separate frames | **node** |
| `messages-tuple` | `(message_chunk, metadata)` — LLM output **token by token**, with `metadata` naming the graph node that made the call | **token** |
| `messages` | token stream, filterable by `metadata.langgraph_node` | **token** |
| `tasks` | Pregel **task start / finish** events: which node is running, its result, and any error. Requires a checkpointer | **node, incl. start** |
| `checkpoints` | checkpoint events, same shape as `get_state()`. Requires a checkpointer | step |
| `debug` | everything — `checkpoints` + `tasks` + extra metadata | node |
| `custom` | arbitrary payloads pushed from inside graph code (`get_stream_writer`) | app-defined |
| `events` | `astream_events` firehose; docs mark it as mainly for migrating LCEL apps | all |

Pass a list to multiplex; frames then carry `(mode, chunk)` and each SSE frame's `event:` field distinguishes them. `stream_subgraphs: true` adds subgraph output, tagged with a **namespace** path so you know which graph emitted it. `stream_resumable: true` persists chunks so a dropped connection can be replayed.

**Token-level vs node-level is distinguished by the `event:` field (= the stream mode), not by inspecting the payload.** `updates`/`tasks` frames are node-level; `messages`/`messages-tuple` frames are token-level and carry `metadata.langgraph_node` to attribute the token to a node. This is the key fact for the canvas: one multiplexed subscription with `stream_mode: ["updates", "tasks", "messages-tuple", "custom"]` yields node status and token counters on the same connection, separable by `event:`.

#### Resumability

- Classic thread stream (`GET /threads/{id}/stream`): SSE-native, resume with the `Last-Event-ID` header; `"-"` replays from the beginning. Since Agent Server v0.6.0 this follows the SSE spec strictly (returns events *after* the given id).
- Thread stream modes are a separate, coarser axis: `run_modes` (default, all run events), `lifecycle` (run start/end only — cheap status monitoring), `state_update` (thread state after each run).
- Protocol v2 (`POST /threads/{id}/stream/events`) is POST-only, so `EventSource` auto-resume does not apply; clients resume by passing the last `seq` as `since` in the body.
- `client.runs.join_stream(thread_id, run_id)` joins an in-flight run, but output is **not buffered** — anything emitted before joining is lost unless `stream_resumable` was set.

#### The newer "Protocol v2" channel model

LangGraph v1.2+ adds a typed event protocol ([event streaming](https://docs.langchain.com/oss/python/langgraph/event-streaming)) exposed over `/threads/{id}/stream/events` (SSE or WebSocket). Events are `{type, event_id, seq, method, params: {namespace, timestamp, data, node}}` where `method` is the channel. Channels: `values`, `updates`, `messages`, `tools`, `lifecycle`, `input`, `tasks`, `custom`, `custom:<name>`. (`debug` and `checkpoints` were removed as of `@langchain/protocol@0.0.10`; task-level debug info moved onto `tasks`, checkpoint pointers ride on `values`.)

The two channels that matter most for a canvas:
- **`lifecycle`** — run / subgraph / subagent status, `event` ∈ `started | running | completed | failed | interrupted`, optionally with `graph_name`, `error`, and `cause` (parent tool call, fan-out send, edge transition).
- **`messages`** — content-block model: `message-start`, `content-block-start`, `content-block-delta`, `content-block-finish`, `message-finish`. Explicit block boundaries make text vs reasoning vs tool-call deltas unambiguous, and **`message-finish` may carry token usage**.

**This channel set is the best model to copy for our own SSE layer** — it is strictly better designed than the legacy `stream_mode` union for driving per-node UI, and it is defined in the MIT library, not just the server.

---

### 4. Should the browser talk to the runtime directly?

**No — go through our own API.** LangChain's own docs say so, in the one place they ship a browser-direct example ([Deploy a Vite app](https://docs.langchain.com/langsmith/deploy-vite-langsmith)):

> "The demo exposes `LANGSMITH_API_KEY` to the browser bundle so the UI can call the LangSmith deployment directly. That is convenient for local testing, but not production-safe. For a real app, proxy requests through your own backend and keep the key server-side."

And in the same page's local-dev flow: "the Vite app uses its local proxy at `/api/langgraph`, which forwards requests to the LangGraph dev server and avoids CORS issues."

Reasons this holds for us independent of licensing:
1. **Credentials.** Agent Server authenticates with `X-Api-Key`; a browser holding it is a leaked key. Custom auth (`@auth.authenticate` / `@auth.on`) exists and the docs' reference architecture is explicitly IdP → *our* backend → server ([Authentication & access control](https://docs.langchain.com/langsmith/auth)) — the frontend holds a user token, not a runtime key.
2. **CORS.** Not a first-class config knob; the documented answer is a proxy.
3. **Self-hosted default is no auth at all.** "Self-hosted: No default authentication. Complete flexibility to implement your security model." A directly-exposed runtime is an open runtime.
4. **We need a translation layer anyway.** The editor's canvas graph must be compiled into a LangGraph `StateGraph`, validated, and mapped to a persisted workflow record. That is our domain logic; it has no home inside a third-party server.
5. **Multi-tenancy and authorization** over workflows/runs is ours to enforce, per-resource.

The editor **can** be a thin client of the streaming protocol though, and should be. LangChain ships MIT frontend SDKs (`@langchain/react` `useStream`, plus Vue/Svelte/Angular equivalents) built for exactly this UI ([Frontend overview](https://docs.langchain.com/oss/javascript/langgraph/frontend/overview)) — worth evaluating pointed at *our* endpoint, provided we mirror the wire protocol closely enough. **Open risk:** how tightly `useStream` couples to Agent Server's exact routes/frames is unverified; if it is too tight, we write our own EventSource client instead. Either way, mirroring the protocol is the low-regret move.

---

### 5. "Run this workflow" on the wire, and the canvas mapping

#### Request

```http
POST /threads/{thread_id}/runs/stream
Content-Type: application/json
X-Api-Key: <key>

{
  "assistant_id": "agent",                 // assistant UUID or graph name
  "input": { "messages": [ { "role": "human", "content": "..." } ] },
  "stream_mode": ["updates", "tasks", "messages-tuple", "custom"],
  "stream_subgraphs": true,
  "stream_resumable": true,
  "on_disconnect": "continue",             // or "cancel"
  "multitask_strategy": "enqueue",
  "durability": "async",
  "if_not_exists": "create",
  "config": { "configurable": {}, "tags": [], "recursion_limit": 25 },
  "context": {},
  "metadata": {},
  "interrupt_before": [], "interrupt_after": [],
  "checkpoint": null,                      // resume from a specific checkpoint
  "webhook": "https://.../done",
  "after_seconds": 0
}
```

Response is `200 text/event-stream`, plus a **`Content-Location`** header giving the URL of the created run so a client can rejoin the stream later. Drop `thread_id` from the path (`POST /runs/stream`) for a stateless run with no persistence. Use `POST /threads/{id}/runs` for fire-and-forget (returns `run_id` immediately), then `GET /threads/{id}/runs/{run_id}/stream` to attach. Resume after an interrupt by posting `command: { "resume": ... }` instead of `input`.

#### Event → canvas card mapping

| Canvas state | Best signal | Notes |
|---|---|---|
| node **running** | `tasks` task-start (node name) — or Protocol v2 `lifecycle` `started`/`running` | `updates` alone cannot express "started"; it only fires on completion. Needs a checkpointer for `tasks`. |
| node **success** | `updates` frame keyed by node name → its state delta; or `tasks` finish carrying a result | The natural "this node just produced output" signal, and it hands you the payload to render in the card. |
| node **error** | `tasks` finish carrying an error; Protocol v2 `lifecycle` `failed` with `error` | Node-scoped. |
| run **error** | terminal SSE error frame; run `status: "error"` | Run-scoped fallback if node-level attribution is missing. |
| node **awaiting input / paused** | `lifecycle` `interrupted`; Protocol v2 `input` channel; run `status: "interrupted"` | Also reachable via `interrupt_before` / `interrupt_after`. |
| **token counter** (per node) | `messages-tuple` / `messages` frames, attributed via `metadata.langgraph_node` | Count deltas as they arrive for a live counter. |
| **token totals** (authoritative) | `message-finish` usage on the `messages` channel; `usage_metadata` (`input_tokens`/`output_tokens`/`total_tokens`) on the final message | Docs: "`message-finish` may include token usage." |
| **token totals** (server-computed) | a `StreamTransformer` that accumulates `usage["output_tokens"]` and publishes via `StreamChannel`, surfacing as a `custom:<name>` event | Documented pattern (`StatsTransformer`) in [event streaming](https://docs.langchain.com/oss/python/langgraph/event-streaming). Cheaper and more trustworthy than counting deltas client-side. |
| **subgraph / nested node** | `namespace` array on each event: `[]` = root, each segment `"name:runtime_id"` | Lets one flat SSE stream drive a nested canvas without string parsing. |
| **run terminal status** | `GET /threads/{id}/runs?status=…` — enum `pending \| running \| error \| success \| timeout \| interrupted` | Six states; note `timeout` — the canvas needs a state for it. |

LangChain's own reference UI already reduces this to a four-state model we should adopt verbatim. [Graph execution cards](https://docs.langchain.com/oss/javascript/langgraph/frontend/graph-execution) discovers nodes at runtime — no hardcoded node list — and each `SubgraphDiscoverySnapshot` exposes `nodeName` plus `status ∈ "pending" | "running" | "complete" | "error"`:

```ts
const graphNodes = [...stream.subgraphs.values()];
graphNodes.forEach((node) => console.log(node.nodeName, node.status)); // "classify", "running"
```

**Recommendation: `pending | running | complete | error` as the canvas card status enum**, with `interrupted` and `timeout` as additional terminal states we must add (the reference UI's four states do not cover them). Our FastAPI layer's job is to emit exactly the events needed to drive that enum, sourced from `tasks` + `updates` + `messages` (or the Protocol v2 `lifecycle`/`tasks`/`messages` channels) on the MIT library.

---

### Follow-on decisions this unblocks

- Repo topology: we own `apps/api` (FastAPI + SSE) as a first-class component; the Python runtime is a library dependency, not a vendored server.
- Persistence is ours: Postgres via MIT `langgraph-checkpoint-postgres` for checkpoints, plus our own tables for workflows/assistant-equivalents/run records (Agent Server's Postgres schema for assistants/threads/runs is not available to us).
- Redis is optional for us initially — it exists in Agent Server only as pub/sub between API and worker processes. A single-process FastAPI app can stream directly from the graph and add Redis later when we split workers.
- Design the SSE contract now, copying Protocol v2's channel names and envelope, so the MIT frontend SDKs stay a live option.

### Sources

- [Agent Server](https://docs.langchain.com/langsmith/agent-server) · [API reference](https://docs.langchain.com/langsmith/server-api-ref) · [Assistants](https://docs.langchain.com/langsmith/assistants) · [Streaming API](https://docs.langchain.com/langsmith/streaming) · [Protocol v2 event stream](https://docs.langchain.com/langsmith/agent-server-api/streaming/protocol-v2-event-stream-sse)
- [Self-host standalone servers](https://docs.langchain.com/langsmith/deploy-standalone-server) · [Deploy to self-hosted](https://docs.langchain.com/langsmith/deploy-to-self-hosted-overview) · [Licensing (data plane)](https://docs.langchain.com/langsmith/data-plane#licensing) · [Data storage and privacy](https://docs.langchain.com/langsmith/data-storage-and-privacy) · [Fleet comparison (platform licence)](https://docs.langchain.com/langsmith/fleet/comparison#compare-capabilities)
- [LangGraph CLI](https://docs.langchain.com/langsmith/cli) · [Local development & testing](https://docs.langchain.com/langsmith/local-dev-testing) · [Custom routes](https://docs.langchain.com/langsmith/custom-routes) · [Authentication & access control](https://docs.langchain.com/langsmith/auth) · [Deploy a Vite app](https://docs.langchain.com/langsmith/deploy-vite-langsmith)
- [Streaming (OSS library)](https://docs.langchain.com/oss/python/langgraph/streaming) · [Event streaming (Protocol v2)](https://docs.langchain.com/oss/python/langgraph/event-streaming) · [Frontend overview](https://docs.langchain.com/oss/javascript/langgraph/frontend/overview) · [Graph execution cards](https://docs.langchain.com/oss/javascript/langgraph/frontend/graph-execution)
- Licences: [`langgraph` MIT](https://github.com/langchain-ai/langgraph/blob/main/LICENSE) · [`langgraph-api` Elastic-2.0](https://pypi.org/pypi/langgraph-api/json) · [`langgraph-runtime-inmem` Elastic-2.0](https://pypi.org/pypi/langgraph-runtime-inmem/json) · [`langgraph-cli` MIT](https://pypi.org/pypi/langgraph-cli/json) · [`langgraph-sdk` MIT](https://pypi.org/pypi/langgraph-sdk/json) · [`langgraph-checkpoint-postgres` MIT](https://pypi.org/pypi/langgraph-checkpoint-postgres/json) · [`@langchain/langgraph-api` MIT (npm)](https://registry.npmjs.org/@langchain/langgraph-api/latest) · [Elastic License 2.0 text](https://www.elastic.co/licensing/elastic-license)
