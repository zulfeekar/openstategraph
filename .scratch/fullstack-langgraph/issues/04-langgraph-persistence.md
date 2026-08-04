Type: research
Status: resolved
Blocked by: —

## Question

What does LangGraph provide for statefulness, and what must we build ourselves?

Distinguish two different needs and answer both:
1. **Runtime state** — checkpointers (which implementations exist: memory / SQLite / Postgres), threads and `thread_id`, resuming, time-travel, and the `Store` for cross-thread memory.
2. **Authoring state** — persisting *workflow configuration* so a user can keep many workflows and edit them. Establish whether LangGraph has any opinion here at all, or whether this is entirely ours.

Also: how a checkpointer is scoped when subgraphs are involved (the docs flag per-invocation vs per-thread), and what identity/versioning a compiled graph carries.

## Answer

All facts below come from the official LangChain/LangGraph docs (Python variants), via the docs MCP server. Links at the bottom.

### Headline verdict

LangGraph is a **runtime-state** system and nothing more. It has a rich, opinionated, pluggable persistence layer for *execution* state (checkpointers) and *cross-thread application data* (stores). It has **zero opinion about authoring state** — i.e. persisting the *configuration of a workflow* so a user can keep and edit many workflows. In open-source LangGraph a graph is Python code, compiled in-process; there is no API to serialise a graph's topology, no schema for a graph definition, and no store for graph definitions. That layer is entirely ours to build.

---

### 1. Runtime state — what LangGraph gives us

#### Two systems, cleanly separated

[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) defines exactly two:

|                | Checkpointer | Store |
| --- | --- | --- |
| Persists | Graph state snapshots | Application-defined key-value data |
| Scope | A single thread | Across threads |
| Memory type | Short-term, thread-scoped | Long-term, cross-thread |
| Use for | Conversation continuity, HITL, time travel, fault tolerance | User preferences, facts, shared knowledge |
| Access | Pass `thread_id` in graph config | Read/write items from nodes or app code |

Both are wired at compile time:

```python
graph = builder.compile(checkpointer=checkpointer, store=store)
result = graph.invoke({...}, {"configurable": {"thread_id": "thread-1"}})
```

#### Checkpointer implementations, with package names

Every checkpointer conforms to `BaseCheckpointSaver` and ships as a **standalone installable library** ([Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers#checkpointer-libraries), [Checkpointer integrations](https://docs.langchain.com/oss/python/integrations/checkpointers/index)):

| Backend | Package | Classes |
| --- | --- | --- |
| In-memory | `langgraph-checkpoint` (bundled with `langgraph`) | `InMemorySaver` (a.k.a. `MemorySaver`), from `langgraph.checkpoint.memory` |
| SQLite | `langgraph-checkpoint-sqlite` | `SqliteSaver` / `AsyncSqliteSaver` |
| PostgreSQL | `langgraph-checkpoint-postgres` | `PostgresSaver` / `AsyncPostgresSaver` — "used in LangSmith… ideal for production" |
| AWS (DynamoDB, Bedrock AgentCore, Valkey) | `langgraph-checkpoint-aws` | e.g. `AgentCoreMemorySaver` |
| MongoDB | `langgraph-checkpoint-mongodb` | — |
| Azure Cosmos DB NoSQL | `langchain-azure-cosmosdb` | `CosmosDBSaverSync` / `CosmosDBSaver` |
| Redis | `langgraph-checkpoint-redis` | — |
| CockroachDB | `langchain-cockroachdb` | — |
| Aerospike | `langgraph-checkpoint-aerospike` | — |
| ScyllaDB | `langgraph-checkpoint-scylladb` | — |
| Tigris | `langgraph-checkpoint-tigris` | — |
| TypeDB | `langgraph-checkpoint-typedb` | — |

Custom backends implement four methods: `.put`, `.put_writes`, `.get_tuple`, `.list` (async variants `.aput`, `.aput_writes`, `.aget_tuple`, `.alist` are used when the graph is driven via `ainvoke`/`astream`/`abatch`). There is a conformance test suite, `langgraph-checkpoint-conformance` (`from langgraph.checkpoint.conformance import checkpointer_test, validate`).

Serialization is via `SerializerProtocol`; default is `JsonPlusSerializer` (ormsgpack + JSON), with `JsonPlusSerializer(pickle_fallback=True)` for types msgpack can't handle. Optional encryption of persisted state is supported.

**For our stack: `SqliteSaver` for local dev, `PostgresSaver`/`AsyncPostgresSaver` for production.** Explicit doc warning: `MemorySaver`/`InMemorySaver` keep checkpoints in RAM and lose everything on process restart. Also: `PostgresSaver` stores `thread_id` in a length-limited column — keep it under 255 chars (use a UUID).

#### Threads and `thread_id`

- A thread is "a unique ID… assigned to each checkpoint saved by a checkpointer" holding "the accumulated state of a sequence of runs".
- `thread_id` is **mandatory** when invoking a checkpointed graph: `{"configurable": {"thread_id": "1"}}`.
- "The checkpointer uses `thread_id` as the primary key… Without it, the checkpointer cannot save state or resume execution after an interrupt."

#### Checkpoints and super-steps

- A checkpoint is a `StateSnapshot` written at each **super-step** boundary (one graph "tick"; parallel nodes share a super-step).
- Storage is two tables: **checkpoints** (one row per super-step: `channel_values`, `channel_versions`, `versions_seen`, parent link) and **writes** (one row per node output within a super-step: `(task_id, channel, value)`).
- `StateSnapshot` fields: `values`, `next` (tuple of node names to run next; `()` = complete), `config` (`thread_id`, `checkpoint_ns`, `checkpoint_id`), `metadata` (`source` ∈ `input`/`loop`/`update`, `writes`, `step`), `created_at`, `parent_config`, `tasks` (`PregelTask` with `id`, `name`, `error`, `interrupts`, optional nested `state`).
- **Pending writes**: per-task writes are durable as each node finishes, so if a sibling node in the same super-step fails, the successful nodes are *not* re-run on resume. Time travel, however, only resumes from full super-step checkpoints.

#### Reading, resuming, time travel

- `graph.get_state(config)` → latest `StateSnapshot`; pass `checkpoint_id` in config for a specific one.
- `graph.get_state_history(config)` → all snapshots, reverse-chronological. This is our "run history / debug" data source.
- **Replay**: `graph.invoke(None, snapshot.config)` with a prior `checkpoint_id`. Nodes *before* the checkpoint are skipped; nodes *after* genuinely **re-execute** — LLM calls, API calls and `interrupt()`s all fire again. Replaying from the final checkpoint is a no-op.
- **Fork**: `graph.update_state(prior_config, values={...})` returns a new config, then `graph.invoke(None, fork_config)`. `update_state` **does not roll back** — it appends a new branching checkpoint; original history stays intact. Values go through reducers, so reducer-backed channels *accumulate* rather than overwrite. `as_node=` controls which node the update is attributed to (and hence what runs next); needed explicitly for parallel branches, fresh threads, or deliberately skipping nodes.
- **Interrupts / HITL**: `interrupt()` suspends; resume with `Command(resume=value)` as the *input* to `invoke`/`stream`/`stream_events`. The node **restarts from its beginning**, so code before the `interrupt()` runs again. `Command(resume=...)` is the only `Command` form intended as graph input.

#### Durability modes

Per-call `durability=` on any execution method:
- `"exit"` — persist only when execution exits (best perf, no mid-run crash recovery).
- `"async"` — persist while the next step runs (good balance; small crash window).
- `"sync"` — persist before the next step starts (highest durability, some overhead).

Storage optimisation: `DeltaChannel` (`langgraph>=1.2`, **beta**) stores per-step deltas instead of full channel values, with `snapshot_frequency=K` to bound read latency. Caveats: bulk reducer must be associative and pure; downgrading LangGraph after using it leaves checkpoints unreadable.

#### Store — cross-thread memory

- `from langgraph.store.memory import InMemoryStore`; `AsyncSqliteStore` lives at `langgraph.store.sqlite`. Production options named in the docs: `PostgresStore`/`AsyncPostgresStore`, `MongoDBStore`, `RedisStore`. All extend `BaseStore` (the type to annotate node params with). Note: the docs have a checkpointer-integrations index but **no equivalent store-integrations index**, so store package names are less crisply documented than checkpointer ones.
- API: namespaces are arbitrary-length tuples (e.g. `(user_id, "memories")`); `store.put(ns, key, value)`, `store.search(ns_prefix, query=..., filter=..., limit=, offset=)`, `store.list_namespaces(prefix=, max_depth=)` (+ `a*` async variants). Items carry `value`, `key`, `namespace`, `created_at`, `updated_at`.
- Gotchas: `namespace_prefix` matches by **prefix, not exactly**; results past `limit` are **silently truncated** (no overflow signal); default ordering differs per backend (Postgres → `updated_at` desc, InMemory → insertion order) — sort client-side if order matters.
- Optional semantic search via `index={"embed": ..., "dims": ..., "fields": [...]}`.

#### If we ever deploy on LangSmith Agent Server

Repeated note across the persistence pages: "**Agent Server handles persistence automatically** — you do not need to implement or configure checkpointers or stores manually." A custom store can be swapped in via a `store` key in `langgraph.json` pointing at an async context manager yielding a `BaseStore` ([custom store](https://docs.langchain.com/langsmith/custom-store), **alpha**).

---

### 2. Authoring state — LangGraph has no opinion. This is 100% ours.

Definitive, from primary sources:

1. **Graphs are code, registered statically.** [Application structure](https://docs.langchain.com/oss/python/langgraph/application-structure): an app is "one or more graphs, a configuration file (`langgraph.json`)…". The `graphs` key maps a name to *an import path* — `"my_agent": "./your_package/your_file.py:agent"` — pointing at either a compiled graph or a factory function. Nothing here reads a workflow definition from a database.

2. **There is no serialise/deserialise for graph topology.** Nothing in the Graph API, Pregel, or persistence docs exposes a graph *definition* format. `graph.get_graph()` (used with `.draw_mermaid()` / `.draw_mermaid_png()`) is a **visualisation** projection of an already-built graph, not a round-trippable authoring document. Checkpoints persist channel *values*, not topology — and the docs state outright that "**Edge topology itself is not persisted in the checkpoint**".

3. **The closest thing — Assistants — is (a) not OSS and (b) config only, not structure.** [Assistants](https://docs.langchain.com/langsmith/assistants) let you "manage configurations (e.g. prompts, LLM selection, tools) separately from your graph's core logic… **Through configuration variations (rather than structural graph changes)**". And explicitly: "Assistants are a LangSmith Deployment concept. **They are not available in the open source LangGraph library.**" An assistant "is just an *instance* of a graph with a specific configuration." Assistants *do* give versioning (each edit creates a new version; promote/rollback; full-payload replace, no merge) — a good design reference for our own authoring store, but not a substitute for it.

4. **Building a different graph per run is actively discouraged.** [Rebuild graph at runtime](https://docs.langchain.com/langsmith/graph-rebuild) permits a factory function, but: "In most cases, customization is best handled by conditioning on the config within individual nodes rather than dynamically changing the whole graph structure." And crucially, across all server access contexts "the returned graph should have the **same topology** (nodes, edges, state schema). A mismatched topology in write contexts… can cause incorrect state updates."

5. **LangChain's own no-code/visual answer is a separate hosted product**, [LangSmith Fleet](https://docs.langchain.com/langsmith/fleet/index) (formerly Agent Builder) — which confirms that "user edits many workflows in a UI" lives *above* the library, not inside it.

**Consequence for us:** we own the entire authoring layer — a workflow-definition schema, its own tables, its own IDs, its own versioning/draft/publish semantics, and a compiler from our stored definition to a `StateGraph` + `.compile()`. Two persistence systems, not one: our workflow-definition DB (authoring) and LangGraph's checkpointer + store (runtime). Do not try to smuggle authoring data into the checkpointer or the Store — Store is "application-defined key-value data" scoped to the *runtime* app, with prefix-matched namespaces, silent `limit` truncation, and backend-dependent ordering; it is a poor fit for a queryable, relational workflow catalogue.

---

### 3. Checkpointer scoping with subgraphs

The `checkpointer` argument to a **subgraph's** `.compile()` selects one of three modes ([Subgraph persistence](https://docs.langchain.com/oss/python/langgraph/use-subgraphs#subgraph-persistence)):

| Mode | `checkpointer=` | Interrupts (HITL) | Multi-turn memory | Multiple calls, different subgraphs | Multiple calls, same subgraph | State inspection |
| --- | --- | --- | --- | --- | --- | --- |
| Per-invocation (default) | `None` | ✅ | ❌ | ✅ | ✅ | ⚠️ current invocation only, while interrupted |
| Per-thread | `True` | ✅ | ✅ | ⚠️ namespace conflicts possible | ❌ | ✅ |
| Stateless | `False` | ❌ | ❌ | ✅ | ✅ | ❌ |

- **Per-invocation (default, recommended):** each call starts fresh but *inherits the parent's checkpointer* for the duration of that call, so `interrupt()`/resume and durable execution work **within a single invocation**. Nothing accumulates between calls.
- **Per-thread (`True`):** state accumulates across calls on the same `thread_id`. Warning: **does not support parallel invocation** — parallel calls write the same namespace and conflict (the docs use `ToolCallLimitMiddleware` to prevent it; with raw `StateGraph` we must prevent it ourselves).
- **Stateless (`False`):** "runs like a plain function call". No interrupts, and explicitly **no durable execution** — "if the process crashes mid-run, the subgraph cannot recover and must be re-run from the beginning."
- **Precondition:** "The parent graph **must** be compiled with a checkpointer for subgraph persistence features (interrupts, state inspection, per-thread memory) to work."

Namespacing: each checkpoint carries `checkpoint_ns` — `""` for the root graph, `"node_name:uuid"` for a subgraph invoked as that node, nested namespaces joined with `|`. Readable from inside a node via `config["configurable"]["checkpoint_ns"]`. Nested state is read with `graph.get_state(config, subgraphs=True)`, then `.tasks[0].state`.

**Namespace-stability gotcha (matters a lot for a visual editor):** subgraphs **added as nodes** get *name-based, stable* namespaces automatically. Subgraphs **invoked inside a node function** get namespaces assigned "based on call order (first call, second call, etc.)" — so reordering calls can make a subgraph load the wrong saved state. The documented fix is to wrap each child in its own `StateGraph` with a unique node name.

Also flagged: "When a subgraph updates state, the parent graph may not see the changes immediately… each subgraph manages its own checkpoint namespace."

**Resumability consequences for us:** any child workflow we want to be pausable/HITL-capable or crash-recoverable must be per-invocation (default) or per-thread — never `checkpointer=False`. Our node names must be **stable identities**, because they are baked into `checkpoint_ns` and into resume dispatch; a UI rename that changes a node name breaks in-flight threads.

---

### 4. Identity and versioning of a compiled graph

- **In OSS LangGraph a compiled graph carries essentially no version identity.** It has a `name` (surfaced as `subgraph.graph_name` in [event streaming](https://docs.langchain.com/oss/python/langgraph/event-streaming) — "the `name` of the compiled graph or agent"), plus node names. That's it. No version field, no content hash, no definition ID.
- **Checkpoints are not pinned to a graph version.** From [Backward compatibility](https://docs.langchain.com/oss/python/langgraph/backward-compatibility): "**Unlike workflow engines that pin a run to the version of code it started with, LangGraph applies the latest graph immediately to *every* thread**, both new threads and threads that resume from a checkpoint." Every code change is therefore a backward-compatible API change with respect to existing checkpoints.
- What *is* versioned inside a checkpoint is per-channel bookkeeping (`channel_versions`, `versions_seen`) plus sortable `checkpoint_id`s and `parent_config` links — an execution lineage, not a definition version.
- **Documented migration rules** ([Graph migrations](https://docs.langchain.com/oss/python/langgraph/graph-api#graph-migrations)):
  - Threads that have finished (not interrupted): you may change **the entire topology** freely.
  - Threads currently **interrupted**: all topology changes are supported **except renaming or removing nodes** (the thread may be about to enter a node that no longer exists).
  - State keys: full backward/forward compatibility for **adding and removing** keys; **renamed keys lose their saved state**; incompatible type changes can break old threads.
  - Adding/removing/rerouting **edges** between still-existing nodes is safe (edges aren't persisted).
- **Recommended patterns we should adopt:** add new state fields as `NotRequired`/`Optional[...] = None`; treat removals as deprecations held for at least one drain cycle; rename via add-then-remove with a dual-write window; keep nodes tolerant of unknown keys. For semantic ("business") changes, stamp a `flow_version` onto the state at thread start and branch on it with a conditional edge, so in-flight threads keep the old path.
- **Detecting in-flight threads:** "LangGraph itself does not maintain a search index over thread state." Options are the Agent Server thread search (`status` ∈ `idle`/`busy`/`interrupted`/`error`), LangSmith tracing, or `get_state`/`get_state_history` for a known `thread_id`. If we self-host, **we must build that index ourselves** if we want to answer "which threads are parked on the version I'm about to change?".
- **In deployment**, identity does exist but at the platform layer: `graph_id` (the `langgraph.json` key), an optional `description`, `assistant_id` (UUID) and assistant **versions**.

**Design implication:** because LangGraph will happily run the newest compiled graph against an old checkpoint, our authoring layer must own version identity: stamp a workflow-definition version into thread metadata (or into graph state, per the `flow_version` pattern) at thread start, and enforce our own rules about which edits are safe while threads are live. Renaming/removing a node in the editor is the one edit that can hard-break an interrupted thread.

### Doc pages used

- [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)
- [Checkpointer integrations](https://docs.langchain.com/oss/python/integrations/checkpointers/index)
- [Stores](https://docs.langchain.com/oss/python/langgraph/stores)
- [Use time travel](https://docs.langchain.com/oss/python/langgraph/use-time-travel)
- [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)
- [Graph API overview](https://docs.langchain.com/oss/python/langgraph/graph-api) (incl. [Graph migrations](https://docs.langchain.com/oss/python/langgraph/graph-api#graph-migrations))
- [Backward compatibility](https://docs.langchain.com/oss/python/langgraph/backward-compatibility)
- [LangGraph runtime (Pregel)](https://docs.langchain.com/oss/python/langgraph/pregel)
- [Event streaming](https://docs.langchain.com/oss/python/langgraph/event-streaming)
- [Application structure](https://docs.langchain.com/oss/python/langgraph/application-structure)
- [Assistants (LangSmith)](https://docs.langchain.com/langsmith/assistants)
- [Rebuild graph at runtime](https://docs.langchain.com/langsmith/graph-rebuild)
- [How to use a custom store](https://docs.langchain.com/langsmith/custom-store)
- [LangSmith Fleet](https://docs.langchain.com/langsmith/fleet/index)
