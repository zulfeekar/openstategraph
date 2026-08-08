# Research 65 — Memory system on LangGraph/LangChain best practices

Sources: docs-langchain MCP server only (docs.langchain.com). Cited by page path
(browse at `https://docs.langchain.com/<path without .mdx>`). Researched 2026-08-08.

## 1. Mapping table: memory kind → exact LangGraph construct

| Memory kind | Docs term | Construct | Concrete API | Doc page |
| --- | --- | --- | --- | --- |
| Working / short-term | short-term memory | graph **state** + **checkpointer**, scoped to a `thread_id` | `builder.compile(checkpointer=InMemorySaver())`; `config={"configurable": {"thread_id": ...}}`; production: `PostgresSaver` (`langgraph-checkpoint-postgres`) | `/oss/python/langchain/short-term-memory`, `/oss/python/langgraph/checkpointers` |
| Long-term: **semantic** (facts) | semantic memory — "profile" (single updated doc) or "collection" (many small docs) | **LangGraph Store**: `InMemoryStore` (dev), `PostgresStore` / `MongoDBStore` / `RedisStore` (prod) | `store.put(namespace, key, {json})`, `store.get(ns, key)`, `store.search(ns, query=..., filter=..., limit=...)`; wire via `builder.compile(store=store)` or `create_agent(..., store=store)`; access in nodes/tools via `runtime.store` (`Runtime` / `ToolRuntime`) | `/oss/python/concepts/memory`, `/oss/python/langgraph/stores`, `/oss/python/langchain/long-term-memory`, `/oss/python/langgraph/add-memory` |
| Long-term: **episodic** (experiences) | episodic memory | Store documents used as **few-shot examples** selected per input; the checkpointer thread itself is the raw episode record; optionally a LangSmith Dataset instead of the Store | same Store API; retrieval = semantic `store.search` over past input→output examples | `/oss/python/concepts/memory#episodic-memory` |
| Long-term: **procedural** (how-to) | procedural memory | (a) agent's **system prompt stored in the Store** and rewritten via "Reflection"/meta-prompting: a `call_model` node reads `store.get(("agent_instructions",), "agent_a")`, an `update_instructions` node rewrites and `put`s it back; (b) deepagents **skills** (see §4) | pseudo-code in the concepts page uses exactly that two-node pattern | `/oss/python/concepts/memory#procedural-memory`, `/oss/python/deepagents/skills` |
| Conversation compaction | summarization | `SummarizationMiddleware` in `create_agent` middleware list; for raw StateGraph, `langmem.short_term.SummarizationNode` | `SummarizationMiddleware(model=..., trigger=("tokens", 4000), keep=("messages", 20))` — trigger also accepts `("fraction", ...)`, list = OR | `/oss/python/langchain/short-term-memory#summarization`, `/oss/python/langgraph/add-memory` |

### Semantic search config (Store)

```python
store = InMemoryStore(index={"embed": init_embeddings("openai:text-embedding-3-small"),
                             "dims": 1536, "fields": ["food_preference", "$"]})
```
- Per-item control: `store.put(..., index=["field"])` embeds only those fields; `index=False` stores without embedding (retrievable, not searchable).
- `search` combines `filter={...}` (content equality) with `query=` (vector similarity), plus `limit`.
- `PostgresStore.from_conn_string(DB_URI, index=IndexConfig(...))` + `store.setup()`.

## 2. Namespace recommendations (ticket 64 identity keys)

Docs conventions observed:
- `("memories", user_id)` — canonical example in `/oss/python/langgraph/add-memory` (also seen `(user_id, "memories")` and `(user_id, application_context)`; the docs say "namespaces often include user or org IDs"). Cross-namespace search works via content filters.
- Deepagents scoping: **agent-scoped** memory = namespace `(assistant_id,)`; **user-scoped** = `(rt.server_info.user.identity,)` i.e. `(user_id,)` — `/oss/python/deepagents/memory`.
- `thread_id` is **not** a Store namespace component in core docs — it is the checkpointer scope. (Only the AWS AgentCore integration shows `(actor_id, thread_id)`.)

Recommended Dyflow mapping:

| Dyflow key | Role | Where |
| --- | --- | --- |
| `user_email` | user identity | Store namespace 2nd element: `("memories", user_email)`, `("episodes", user_email)`; procedural agent-scoped: `("instructions", workflow_id)` |
| `session_id` / `thread_id` | one conversation/run | `config["configurable"]["thread_id"]` for the checkpointer; never in long-term namespaces (long-term = cross-thread by definition) |
| workflow/agent id | agent-scoped memory (shared across users) | first/only namespace element, mirroring deepagents `(assistant_id,)` |

## 3. Episodic details

- Short-term memory = state persisted per `thread_id` by a checkpointer; resuming the same `thread_id` continues the conversation; a new `thread_id` starts fresh (`/oss/python/langchain/short-term-memory`).
- Cross-thread = Store only; in-thread = checkpointer. The deepagents memory page has the same picture: "short-term memory is scoped to a single thread via checkpoints; long-term memory persists across threads via the store".
- Writing memories: **hot path** (agent decides to remember before responding, e.g. a `save_memory` tool using `runtime.store`) vs **background** (async job generates memories after the run) — tradeoffs in `/oss/python/concepts/memory#writing-memories`.
- Documented episodic pattern = few-shot examples retrieved by similarity, not replaying transcripts.

## 4. Procedural details (skills / deepagents)

- **Skills**: directory of `SKILL.md` files (YAML frontmatter `name` + `description`, then instructions; optional scripts/references/assets; follows the Agent Skills spec). Progressive disclosure: only summaries loaded at startup, full file read on demand. Passed as `skills=["/skills/"]` to `create_deep_agent`; backed by `FilesystemBackend`, `StateBackend`, or `StoreBackend` (skills in the LangGraph Store, namespaced per agent or per user). `/oss/python/deepagents/skills`.
- **Memory files**: `memory=["/memories/AGENTS.md"]`; agent edits them with its own `edit_file` tool; `CompositeBackend` routes `/memories/` and `/skills/` paths to `StoreBackend(namespace=lambda rt: ...)`. Read-only vs writable is per-route; developer skills/org policies typically read-only. `/oss/python/deepagents/memory`.
- **Middleware ordering constraint (confirmed)**: in `create_deep_agent`'s full stack (`/oss/python/deepagents/customization`), order is Skills → Filesystem → SubAgent → Summarization → PatchToolCalls → user middleware → profile extras → excluded-tool filtering → **PromptCaching (Anthropic/Bedrock)** → **MemoryMiddleware** → HumanInTheLoop. Doc note: "`MemoryMiddleware` is placed **after** ... the prompt caching middleware so updates to injected memory are less likely to invalidate the cache prefix." Skills are injected **before** filesystem middleware "so skill metadata is available before file tools run." This validates Dyflow's slot-table design.

## 5. langmem

The docs cover `langmem` only marginally: `/oss/python/langgraph/add-memory` imports `langmem.short_term.SummarizationNode` / `RunningSummary` for summarizing history in a raw StateGraph. No broader langmem API (memory managers, prompt optimizers) appears on the docs site — do not build on it.

## 6. Prebuilt vs workflow-supplied (Dyflow split)

**Prebuilt by the Dyflow compiler/runtime (infrastructure):**
- The Store instance (InMemoryStore dev / PostgresStore prod) and its embedding `index` config; passed once at `compile(store=...)` / `create_agent(store=...)`.
- The checkpointer and `thread_id` plumbing (ticket 47/64 work).
- Namespace construction from runtime context (`user_email`, workflow id) — nodes never hard-code identity.
- `SummarizationMiddleware` as a named slot on the agent middleware table.
- Prebuilt `save_memory` / `search_memory` tools reading `runtime.store` (docs' recommended tool pattern).

**Workflow-supplied (developer configuration):**
- Whether a node uses memory at all; which namespaces/labels beyond identity (`application_context`).
- Memory schema/content (profile fields, what to remember), hot-path vs background writing.
- Skills content (`SKILL.md` files) and memory-file seeds; read-only vs writable designation.
- Summarization thresholds (`trigger`, `keep`) and embedding model choice.

**Exposure points:** nodes via `runtime.store` (Python `Runtime`), tools via `ToolRuntime.store`; agent middleware slots `summarization`, `memory` (after `prompt-caching`), `skills` (before filesystem).
