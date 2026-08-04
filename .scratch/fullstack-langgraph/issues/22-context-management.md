Type: research
Status: resolved
Blocked by: —

## Question

Establish what LangChain/LangGraph provide for managing an agent's context over a long run, so a node can be configured as a shallow or a deep agent.

From the docs-langchain MCP only:
- **Summarization**: the middleware or mechanism that condenses history. Trigger conditions (token threshold? message count?), what it replaces, and what is preserved.
- **Autocompaction**: whether an automatic compaction exists, how it is enabled, and how it differs from summarization.
- **Context editing**: clearing or pruning old tool results and thinking blocks — what strategies exist and what each removes.
- **`Store`** for cross-thread long-term memory versus the checkpointer for within-thread state (ticket 04 covered the checkpointer; this is the memory half).
- **Deep agents**: what `deepagents` provides beyond `SubAgentMiddleware` — planning, filesystem, and whatever else. Is "deep agent" a defined construct or a composition of middleware?
- The full middleware list relevant to production: HITL, PII redaction, retries, guardrails.

Deliverable: the set of knobs an Agent node must expose so a user can dial from "plain create_agent" to "deep agent" without leaving the visual builder — expressed as concrete config fields, since ticket 20 has to render them.

## Answer

All facts below come from the official LangChain docs MCP server (Python pages preferred). Where the docs do not
document something, that is stated explicitly rather than guessed.

### 0. The two factories (the ends of the dial)

| Factory | Import | What it is |
| --- | --- | --- |
| `create_agent` | `from langchain.agents import create_agent` | Bare tool-calling loop. Every capability below is opt-in via `middleware=[...]`. |
| `create_deep_agent` | `from deepagents import create_deep_agent` | Same loop with a **pre-assembled middleware stack**. |

`create_deep_agent` full signature ([Customize Deep Agents](https://docs.langchain.com/oss/python/deepagents/customization)):

```
create_deep_agent(
    model, tools=None, *, system_prompt=None, middleware=(), subagents=None,
    skills=None, memory=None, permissions=None, backend=None, interrupt_on=None,
    response_format=None, state_schema=None, context_schema=None,
    checkpointer=None, store=None, debug=False, name=None, cache=None,
)
```

**Is "deep agent" a defined construct or a composition of middleware? Both, precisely:** the docs call Deep Agents an
["agent harness"](https://docs.langchain.com/oss/python/deepagents/overview#core-capabilities) — a real library
(`deepagents` on PyPI, MIT) with its own factory, state type (`DeepAgentState`), backends and profiles. But its
*behaviour* is entirely a middleware composition: the [default stack](https://docs.langchain.com/oss/python/deepagents/customization#default-stack-main-agent)
is an ordered list of middleware, and [Build a deep agent from scratch](https://docs.langchain.com/oss/python/langchain/deep-agent-from-scratch)
reconstructs it step-by-step out of `create_agent` + the same middleware. So the builder can legitimately model the
Agent node as `create_agent` + a middleware set, and treat "deep agent" as a preset of that set.

**Default middleware stack of `create_deep_agent`, in order** ([source](https://docs.langchain.com/oss/python/deepagents/customization#default-stack-main-agent)):

1. `SkillsMiddleware` — only when `skills=` is passed.
2. `FilesystemMiddleware` — always (required scaffolding; cannot be excluded).
3. `SubAgentMiddleware` — only when at least one synchronous subagent exists (the auto-added `general-purpose` one counts).
4. `SummarizationMiddleware` — always (built via `deepagents.middleware.summarization.create_summarization_middleware`).
5. `PatchToolCallsMiddleware` — always; repairs dangling/malformed tool calls after an interrupt or resume.
6. `AsyncSubAgentMiddleware` — only when async subagents are configured.
7. Your `middleware=` argument — merged here; **an instance whose `.name` matches a default replaces that default in place**.
8. Harness-profile extras, then excluded-tool filtering.
9. `AnthropicPromptCachingMiddleware` + `BedrockPromptCachingMiddleware` — always registered, no-op on unsupported models.
10. `MemoryMiddleware` — only when `memory=` is passed.
11. `HumanInTheLoopMiddleware` — only when `interrupt_on=` is passed.

Note: **task planning is NOT in the default stack.** Since deepagents v0.7 `TodoListMiddleware` is opt-in
([Task planning](https://docs.langchain.com/oss/python/deepagents/overview#task-planning)) and it lives in
**langchain**, not deepagents: `from langchain.agents.middleware import TodoListMiddleware`.

---

### 1. Summarization — `SummarizationMiddleware`

There are **two distinct middlewares with this class name**. Do not conflate them.

#### 1a. LangChain's `SummarizationMiddleware`
* Import: `from langchain.agents.middleware import SummarizationMiddleware`
* API ref: [`SummarizationMiddleware`](https://reference.langchain.com/python/langchain/agents/middleware/summarization/SummarizationMiddleware)
* Docs: [Prebuilt middleware → Summarization](https://docs.langchain.com/oss/python/langchain/middleware/built-in#summarization-10),
  [Context engineering → Example: Summarization](https://docs.langchain.com/oss/python/langchain/context-engineering#example-summarization)

**What it does to message history:** makes a **separate LLM call** to summarize older messages, then
**persistently replaces them in graph state** with a single summary message; recent messages are kept intact.
The docs are explicit that this "persistently updates state — permanently replacing old messages with a summary
that's saved for all future turns." It is **text-only** compression: it does not resize or downsample
image/audio/video payloads; older multimodal messages survive only as generated text.

**Parameters (form fields):**

| Param | Type | Default | Notes |
| --- | --- | --- | --- |
| `model` | `str \| BaseChatModel` | **required** | Model used to write the summary; `'openai:gpt-5.4-mini'`-style string is fine. |
| `trigger` | `ContextSize \| TriggerClause \| list[...] \| None` | `None` | **If omitted, summarization never fires automatically.** |
| `keep` | `ContextSize` | `("messages", 20)` | Exactly one of `fraction` / `tokens` / `messages`. |
| `token_counter` | `Callable` | character-based | |
| `summary_prompt` | `str` | built-in template | Must contain `{messages}`. |
| `trim_tokens_to_summarize` | `int` | `4000` | Cap on tokens fed into the summarizing call. |
| `summary_prefix` | `str` | — | **Deprecated**, use `summary_prompt`. |
| `max_tokens_before_summary` | `int` | — | **Deprecated**, use `trigger=("tokens", N)`. |
| `messages_to_keep` | `int` | — | **Deprecated**, use `keep=("messages", N)`. |

**Trigger condition semantics** (this is the part the UI has to get right):
* A `ContextSize` tuple = exactly one threshold, e.g. `("tokens", 4000)`.
* A `TriggerClause` dict = several thresholds ANDed, e.g. `{"tokens": 4000, "messages": 10}`.
* A **list** of either form = ORed, e.g. `[("tokens", 3000), ("messages", 6)]`.
* Threshold kinds: `fraction` (float 0–1 of the model's context size), `tokens` (absolute int), `messages` (int count).
* `fraction` for `trigger`/`keep` depends on the chat model's [model profile](https://docs.langchain.com/oss/python/langchain/models#model-profiles)
  (`langchain>=1.1`); if profile data is missing, `fraction` is unusable and you must supply `tokens`/`messages`
  or pass a custom `profile={"max_input_tokens": ...}` to `init_chat_model`.

#### 1b. deepagents' `SummarizationMiddleware` (the deep-agent default)
* Import: `from deepagents.middleware import SummarizationMiddleware`, constructed as `SummarizationMiddleware(model=model, backend=backend)`;
  the factory used internally is [`create_summarization_middleware`](https://reference.langchain.com/python/deepagents/middleware/summarization/create_summarization_middleware).
* Docs: [Deep Agents → Context engineering → Summarization](https://docs.langchain.com/oss/python/deepagents/context-engineering#summarization),
  [Agents → Context management](https://docs.langchain.com/oss/python/langchain/agents#context-management)

Adds a `backend=` parameter, and does **two** things instead of one:
* **In-context summary** — an LLM-generated *structured* summary (session intent, artifacts created, next steps)
  replaces the conversation history in working memory.
* **Filesystem preservation** — a text rendering of the original messages is written to the backend filesystem as a
  canonical record, so the agent can `grep`/`read_file` the detail back.

**Baked-in trigger/defaults (not exposed as user params in the docs):**
* Fires at **85% of the model's `max_input_tokens`** from its model profile, and only when nothing is left eligible
  for offloading.
* Keeps **10% of tokens** as recent context.
* **Fallback when no model profile is available: 170,000-token trigger / 6 messages kept.**
* If any model call raises [`ContextOverflowError`](https://reference.langchain.com/python/langchain-core/exceptions/ContextOverflowError),
  it immediately summarizes and retries with summary + recent preserved messages.
* Summarization tokens appear in the `messages` stream tagged `metadata["lc_source"] == "summarization"` — useful if
  the builder renders a live transcript.

---

### 2. "Autocompaction" — what actually exists

**There is no LangChain or deepagents API named "autocompaction."** A full-text search of the docs finds no
`AutoCompactionMiddleware`, no `autocompact` parameter, and no "autocompaction" concept page. What exists is:

1. **Automatic compression, always on inside `create_deep_agent`** — the docs call this
   [Context compression](https://docs.langchain.com/oss/python/deepagents/context-engineering#context-compression)
   and it has exactly **two** built-in halves: **offloading** and **summarization**. "Every `create_deep_agent` call
   includes built-in context compression. You do not need to add middleware for offloading or summarization to work."
   This is the thing people mean by "autocompaction," and it is *not separately configurable* — it is the
   deepagents `SummarizationMiddleware` defaults from §1b plus offloading from §3.

2. **Offloading** ([docs](https://docs.langchain.com/oss/python/deepagents/context-engineering#offloading)) — the
   *other* automatic half, and distinct from both summarization and context editing:
   * Threshold: tool call **inputs or results exceeding 20,000 tokens** (default).
   * Large **tool results** → written to the configured backend, replaced in history by a **file path reference plus a
     preview of the first 10 lines**.
   * Large **tool call inputs** (e.g. `write_file`/`edit_file` args) → once session context crosses **85%** of the
     model's window, older tool calls are truncated and replaced with a **pointer to the file on disk**.
   * No LLM call involved. Works through `FilesystemMiddleware` + the backend. Docs surface **no parameter** to change
     the 20,000-token threshold.

3. **On-demand compaction (the `compact_conversation` tool)** — the explicitly *model-triggered* counterpart:
   * `from deepagents.middleware.summarization import create_summarization_tool_middleware`
   * `create_summarization_tool_middleware(model, backend)`, passed via `middleware=` on `create_deep_agent`.
   * API refs: [`SummarizationToolMiddleware`](https://reference.langchain.com/python/deepagents/middleware/summarization/SummarizationToolMiddleware),
     [`create_summarization_tool_middleware`](https://reference.langchain.com/python/deepagents/middleware/summarization/create_summarization_tool_middleware).
   * Gives the agent a `compact_conversation` tool so **it** decides when to compact (e.g. between tasks) rather than
     waiting for 85%. **Trigger condition: a model-issued tool call, not a threshold.**
   * Adding it **does not disable** automatic summarization; both share the same summarization engine and state.
   * Inserted into the default stack after `PatchToolCallsMiddleware`.

4. Not first-party: a community package [`compact-middleware`](https://github.com/emanueleielo/compact-middleware) is
   *listed* in [Middleware integrations](https://docs.langchain.com/oss/python/integrations/middleware) as
   "Claude Code's compaction engine as LangChain middleware. Multi-level context compaction." It is third-party;
   do not treat it as a LangChain-maintained mechanism.

**Summarization vs. autocompaction, stated cleanly:** summarization is the *mechanism*
(`SummarizationMiddleware`, one LLM call, replaces a span of messages with a summary message in state).
"Autocompaction" is not an API — it is the deep-agent *policy* of running that mechanism (plus offloading)
automatically at 85% of the context window with no configuration. In plain `create_agent`, the same mechanism exists
but is inert until you supply a `trigger`.

---

### 3. Context editing — `ContextEditingMiddleware`

* Import: `from langchain.agents.middleware import ContextEditingMiddleware, ClearToolUsesEdit`
* API refs: [`ContextEditingMiddleware`](https://reference.langchain.com/python/langchain/agents/middleware/context_editing/ContextEditingMiddleware),
  [`ContextEdit`](https://reference.langchain.com/python/langchain/agents/middleware/context_editing/ContextEdit),
  [`ClearToolUsesEdit`](https://reference.langchain.com/python/langchain/agents/middleware/context_editing/ClearToolUsesEdit)
* Docs: [Prebuilt middleware → Context editing](https://docs.langchain.com/oss/python/langchain/middleware/built-in#context-editing)

**What it does to message history:** deterministic, **no LLM call**. Monitors token count; when the threshold is hit
it **replaces the content of older `ToolMessage`s with a placeholder string**, keeping the message structure and the
N most recent tool results intact. Optionally also blanks the originating tool-call arguments on the `AIMessage`.

`ContextEditingMiddleware` params:

| Param | Type | Default |
| --- | --- | --- |
| `edits` | `list[ContextEdit]` | `[ClearToolUsesEdit()]` |
| `token_count_method` | `'approximate' \| 'model'` | `'approximate'` |

`ClearToolUsesEdit` params — **this is the only `ContextEdit` strategy the docs document**:

| Param | Type | Default | Effect |
| --- | --- | --- | --- |
| `trigger` | `int` (tokens) | `100000` | Conversation token count at which the edit runs. |
| `clear_at_least` | `int` | `0` | Minimum tokens to reclaim; `0` = clear only as much as needed. |
| `keep` | `int` | `3` | Most recent tool results that are never cleared. |
| `clear_tool_inputs` | `bool` | `False` | When `True`, tool-call arguments on the AI message are replaced with empty objects. |
| `exclude_tools` | `list[str]` | `()` | Tool names whose outputs are never cleared. |
| `placeholder` | `str` | `'[cleared]'` | Text substituted for a cleared tool output. |

**Thinking / reasoning blocks:** the docs describe **no** context-editing strategy that clears thinking or reasoning
blocks. `ClearToolUsesEdit` is the only documented `ContextEdit`, and it targets tool outputs (and optionally tool
inputs) only. Reasoning blocks appear in these docs solely as a *rendering* concern
([reasoning tokens](https://docs.langchain.com/oss/python/langchain/frontend/reasoning-tokens)), not as a prunable
context-editing target. Do not build a "clear thinking blocks" field — there is nothing in the documented API behind it.

**Three mechanisms side by side — do not blur these:**

| | Summarization | Context editing | Offloading |
| --- | --- | --- | --- |
| Class | `SummarizationMiddleware` | `ContextEditingMiddleware` | built into `FilesystemMiddleware` / deep-agent harness |
| Package | `langchain` (and a `deepagents` variant) | `langchain` | `deepagents` |
| Extra LLM call | **Yes** | **No** | **No** |
| Trigger | `trigger` tokens/messages/fraction (deep agents: 85% of `max_input_tokens`) | `trigger` token count, default 100,000 | tool input/result > 20,000 tokens (inputs also gated on 85% of window) |
| What is removed | a span of older messages | the *content* of older `ToolMessage`s | the large tool payload |
| What replaces it | one LLM-written summary message | `'[cleared]'` placeholder, structure preserved | file path reference + first 10 lines |
| Recoverable? | only in the deepagents variant (originals written to filesystem) | No — content is gone from state | Yes — re-read/grep the file |

---

### 4. `Store` (cross-thread) vs checkpointer (within-thread)

* [Short-term memory](https://docs.langchain.com/oss/python/langchain/short-term-memory): pass
  `checkpointer=` to `create_agent` / `create_deep_agent` (e.g. `from langgraph.checkpoint.memory import InMemorySaver`).
  Scoped to a **thread**; conversation history lives in graph state and is persisted so the thread can be resumed.
  Selected per-invocation with `config={"configurable": {"thread_id": "..."}}`. **Required** for
  human-in-the-loop and for `ModelCallLimitMiddleware`'s `thread_limit`.
* [Long-term memory](https://docs.langchain.com/oss/python/langchain/long-term-memory): pass `store=` (a
  `BaseStore`, e.g. `from langgraph.store.memory import InMemoryStore`, or
  `from langgraph.store.postgres import PostgresStore`). Built on
  [LangGraph stores](https://docs.langchain.com/oss/python/langgraph/stores); saves **JSON documents** addressed by
  `namespace` (tuple, often `(user_id, context)`) and `key`. Tools read/write it via `runtime.store`
  (`store.put/get/search`). Optional semantic search via `IndexConfig(embed=..., dims=...)`, then
  `store.search(namespace, filter=..., query=...)`. Persists **across threads and sessions**.
* Deep-agent bridge between the two: the filesystem backend. `StateBackend` = thread-scoped (state, persisted by the
  checkpointer). `StoreBackend` = cross-thread (the `Store`). `CompositeBackend(default=StateBackend(), routes={"/memories/": StoreBackend()})`
  routes paths, so any file under `/memories/` survives across threads while everything else stays ephemeral
  ([Long-term memory](https://docs.langchain.com/oss/python/deepagents/context-engineering#long-term-memory),
  [Backends](https://docs.langchain.com/oss/python/deepagents/backends),
  [Short-term vs long-term filesystem](https://docs.langchain.com/oss/python/langchain/middleware/built-in#short-term-vs-long-term-filesystem)).
  Backends available: `StateBackend`, `StoreBackend`, `FilesystemBackend` (local disk), `CompositeBackend`, sandbox
  backends, or custom.

---

### 5. What `deepagents` provides beyond `SubAgentMiddleware`

Everything in this list is imported from `deepagents`, **not** `langchain`:

| Thing | Import / API | What it adds |
| --- | --- | --- |
| `create_deep_agent` | `deepagents` | The pre-assembled harness + `DeepAgentState`. |
| `FilesystemMiddleware` | `deepagents.middleware.filesystem` | Virtual filesystem tools: `ls`, `read_file`, `write_file`, `edit_file`, `delete`, `glob`, `grep`, `execute` (sandbox backends only). Params: `backend`, `system_prompt`, `custom_tool_descriptions: dict[str,str]`, `tools: list[str]` allowlist (`read_file` mandatory; requires deepagents>=0.7). Also the substrate for offloading, skills, memory. Cannot be removed via `excluded_middleware`. |
| Backends | `deepagents.backends` | `StateBackend`, `StoreBackend`, `FilesystemBackend`, `CompositeBackend`, sandbox backends (`LangSmithSandbox`, …). |
| `SkillsMiddleware` | `deepagents.middleware` | `SkillsMiddleware(backend=..., sources=["/skills/"])`. [Agent Skills standard](https://agentskills.io/) `SKILL.md` dirs, loaded by **progressive disclosure** — frontmatter at startup, full body only on demand. `create_deep_agent(skills=[...])`. ([Skills](https://docs.langchain.com/oss/python/deepagents/skills)) |
| `MemoryMiddleware` | `deepagents.middleware` | `MemoryMiddleware(backend=..., sources=["./AGENTS.md"])`. [`AGENTS.md`](https://agents.md/) files, **always loaded** into the system prompt (contrast skills). `create_deep_agent(memory=["/AGENTS.md"])`. Agent can update them. |
| `create_summarization_middleware` | `deepagents.middleware.summarization` | The deep-agent summarization variant (§1b). |
| `create_summarization_tool_middleware` / `SummarizationToolMiddleware` | `deepagents.middleware.summarization` | The `compact_conversation` on-demand tool (§2.3). |
| `PatchToolCallsMiddleware` | `deepagents.middleware.patch_tool_calls` | Repairs dangling tool calls when a run resumes after an interrupt, and malformed tool-call args. |
| `AsyncSubAgentMiddleware` | `deepagents.middleware.async_subagents` | Fire-and-forget subagent tasks tracked in a dedicated `async_tasks` state channel (deliberately *outside* message history so task IDs survive compaction), with `list_async_tasks`. |
| `RubricMiddleware` (**beta**, deepagents>=0.6.5) | `deepagents.middleware.rubric` | LLM-as-a-judge self-evaluation: declare what "done" looks like; the agent iterates until the rubric passes or an iteration cap is hit. |
| Filesystem permissions | `create_deep_agent(permissions=[FilesystemPermission(...)])` | Declarative path-level read/write access control. ([Permissions](https://docs.langchain.com/oss/python/deepagents/permissions)) |
| Harness profiles (**beta**) | `HarnessProfile`, `HarnessProfileConfig`, `register_harness_profile` | Per-provider/model bundles: `system_prompt_suffix`, tool-description overrides, `excluded_tools: frozenset[str]`, `excluded_middleware: frozenset[type\|str]`, extra middleware, `general_purpose_subagent=GeneralPurposeSubagentProfile(...)`. YAML/JSON-loadable. **`excluded_tools` is the documented way to shrink tool schemas before compression runs.** Listing `FilesystemMiddleware`, `SubAgentMiddleware` or the permission middleware in `excluded_middleware` raises `ValueError`. ([Profiles](https://docs.langchain.com/oss/python/deepagents/profiles)) |
| Automatic prompt caching | — | `create_deep_agent` auto-applies `AnthropicPromptCachingMiddleware` / `BedrockPromptCachingMiddleware` to static prompt sections. **No configuration required**, no-ops elsewhere. |
| Interpreters / sandboxes | [Interpreters](https://docs.langchain.com/oss/python/deepagents/customization#interpreters), [Sandboxes](https://docs.langchain.com/oss/python/deepagents/sandboxes) | Shell `execute` and in-process JS interpreter. |
| `CompiledSubAgent`, dynamic subagents | `deepagents` | Use an arbitrary compiled LangGraph graph as a subagent. |

**Planning is the notable exception:** the `write_todos` tool comes from **langchain**'s `TodoListMiddleware`
(`from langchain.agents.middleware import TodoListMiddleware`, no config options), is **opt-in since deepagents v0.7**,
and statuses are `'pending' | 'in_progress' | 'completed'` persisted in agent state.

**Subagent config surface** ([SubAgent spec](https://docs.langchain.com/oss/python/deepagents/subagents#subagent-dictionary-based)) —
`SubAgentMiddleware(default_model=..., default_tools=[...], subagents=[...])` exposes a `task` tool. Each dict subagent:
`name` (str, req), `description` (str, req), `system_prompt` (str, req, does **not** inherit),
`tools` (inherits by default; overrides entirely when set), `model` (inherits), `middleware` (does not inherit),
`interrupt_on` (inherits), `skills` (does not inherit), `response_format`, `permissions` (replaces parent's entirely).
A `general-purpose` subagent is auto-added unless you supply one by that name; disable it with
`general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)` on the harness profile **and** pass no
synchronous subagents — `SubAgentMiddleware` (and the `task` tool) is only attached when at least one exists.

---

### 6. Full production middleware list (provider-agnostic)

From [Prebuilt middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in), all
`from langchain.agents.middleware import ...` unless noted:

| Middleware | Key params (type, default) |
| --- | --- |
| `SummarizationMiddleware` | §1a |
| `HumanInTheLoopMiddleware` | `interrupt_on: dict[str, bool \| InterruptOnConfig]`. `True` = default decisions (`approve`, `edit`, `reject`, `respond`), `False` = never interrupt, or `{"allowed_decisions": [...]}`. **Requires a checkpointer.** On deep agents use `create_deep_agent(interrupt_on={...})`. ([HITL](https://docs.langchain.com/oss/python/langchain/human-in-the-loop)) |
| `ModelCallLimitMiddleware` | `thread_limit: int` (no limit), `run_limit: int` (no limit), `exit_behavior: 'end' \| 'error'` (`'end'`). `thread_limit` needs a checkpointer. |
| `ToolCallLimitMiddleware` | `run_limit`, `thread_limit`, `exit_behavior: 'continue' \| ...` (`'continue'` = block exceeded calls with error messages and keep going). Global or per-tool. |
| `ModelFallbackMiddleware` | positional list of fallback models, e.g. `ModelFallbackMiddleware("gpt-5.5")`. |
| `PIIMiddleware` | `pii_type: str` (req; built-ins `email`, `credit_card`, `ip`, `mac_address`, `url`, or a custom name), `strategy: 'block'\|'redact'\|'mask'\|'hash'` (`'redact'`), `detector: regex \| Callable`, `apply_to_input: bool` (`True`), `apply_to_output: bool` (`False`), `apply_to_tool_results: bool` (`False`). One instance **per PII type**. `redact` → `[REDACTED_EMAIL]`; `mask` → `****-****-****-1234`; `hash` → deterministic; `block` → raises. With `apply_to_output=True` (langchain>=1.3.2) it also redacts streamed wire output. |
| `TodoListMiddleware` | none. |
| `LLMToolSelectorMiddleware` | LLM picks relevant tools before the main model call. |
| `ToolErrorMiddleware` (langchain>=1.3.14) | `on_error: Callable[[Exception, ToolCallRequest], str \| list[ContentBlock] \| None]`, `aon_error` (async). Return content → converts to `ToolMessage(status="error")`; return `None` → exception propagates. |
| `ToolRetryMiddleware` | `max_retries: int` (`2`), `tools: list[BaseTool\|str] \| None` (all), `retry_on: tuple[type[Exception],...] \| Callable` (`(Exception,)`), `on_failure: 'continue'\|'error'\|Callable` (`'continue'`), `backoff_factor: float` (`2.0`), `initial_delay: float` (`1.0`), `max_delay: float` (`60.0`), `jitter: bool` (`True`, ±25%). Delay = `initial_delay * backoff_factor**n`. |
| `ModelRetryMiddleware` | identical set minus `tools`; `on_failure='continue'` returns an `AIMessage` with error details. |
| `LLMToolEmulatorMiddleware` | emulate tool execution with an LLM (testing). |
| `ContextEditingMiddleware` | §3 |
| Provider tool search | defers tool schemas behind provider-side server tool search to cut context bloat. |
| Shell tool | persistent shell session; `redaction_rules: tuple[RedactionRule,...]` (e.g. `RedactionRule(pii_type="api_key", detector=r"sk-[a-zA-Z0-9]{32}")`) applied **post**-execution — explicitly *not* an exfiltration control under `HostExecutionPolicy`. |
| File search | `Glob` / `Grep` tools over filesystem files. |
| `FilesystemMiddleware` | §5 (from `deepagents`) |
| `SubAgentMiddleware` | §5 (from `deepagents`) |
| `RubricMiddleware` (beta) | §5 (from `deepagents`) |

**Guardrails** are not a separate class — [Guardrails](https://docs.langchain.com/oss/python/langchain/guardrails)
says guardrails are *implemented as middleware*, split into **deterministic** (regex/keyword/explicit checks) and
**model-based** (LLM/classifier). Built-in guardrails = `PIIMiddleware` + `HumanInTheLoopMiddleware`; anything else
(prompt-injection detection, content policy, output validation) is [custom middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom)
using `before_agent` / `after_agent` / `wrap_model_call` / `wrap_tool_call` hooks. Provider-specific moderation exists
as integrations (OpenAI content moderation, Microsoft Foundry text/image moderation + prompt shield + groundedness) —
see [Middleware integrations](https://docs.langchain.com/oss/python/integrations/middleware).

**Fault-tolerance mapping** ([Fault tolerance](https://docs.langchain.com/oss/python/deepagents/fault-tolerance)):
transient → `ModelRetryMiddleware`/`ToolRetryMiddleware`; LLM-recoverable → `ToolErrorMiddleware`;
user-fixable → HITL `interrupt()`; provider outage → `ModelFallbackMiddleware`;
runaway loops → `ModelCallLimitMiddleware`/`ToolCallLimitMiddleware`; unexpected → let it propagate.

---

### 7. The Agent node must expose these fields

Grouped by panel. `type` is the form-control type; `default` is what the node should ship with;
"drives" names the exact mechanism the field configures. Fields marked **(deep only)** are only meaningful when
`harness = "deep_agent"`.

**Core**

| Field | Type | Default | Drives |
| --- | --- | --- | --- |
| `harness` | enum `create_agent` \| `deep_agent` | `create_agent` | Which factory is emitted. The master dial: `deep_agent` pre-enables filesystem + summarization + subagents + prompt caching. |
| `model` | string (`provider:model`) | — (required) | `model=` |
| `system_prompt` | multiline text | `""` | `system_prompt=` |
| `tools` | tool-ref list | `[]` | `tools=` |
| `response_format` | schema ref \| null | `null` | `response_format=` |
| `agent_name` | string | `""` | `name=` |

**Persistence**

| Field | Type | Default | Drives |
| --- | --- | --- | --- |
| `checkpointer` | enum `none` \| `memory` \| `postgres` | `memory` | `checkpointer=` — within-thread short-term memory. Must be non-`none` if HITL or `model_call_thread_limit` is set. |
| `store` | enum `none` \| `memory` \| `postgres` | `none` | `store=` — cross-thread long-term memory (`BaseStore`). |
| `store_index_embeddings` | bool | `false` | `IndexConfig(embed=..., dims=...)` on the store → semantic `store.search`. |

**Summarization**

| Field | Type | Default | Drives |
| --- | --- | --- | --- |
| `summarization_enabled` | bool | `false` (`true`, locked on, when `harness=deep_agent`) | presence of `SummarizationMiddleware` |
| `summarization_model` | string \| "same as agent" | "same as agent" | `SummarizationMiddleware.model` |
| `summarization_trigger_mode` | enum `never` \| `simple` \| `advanced` | `never` | whether/how `trigger` is emitted; `never` = omit `trigger` (middleware present but inert) |
| `summarization_trigger_kind` | enum `fraction` \| `tokens` \| `messages` | `tokens` | `trigger` threshold kind |
| `summarization_trigger_value` | number | `4000` (or `0.8` for `fraction`) | `trigger` threshold value |
| `summarization_trigger_clauses` | list of `{fraction?, tokens?, messages?}` | `[]` | advanced mode: within a clause = AND, across clauses = OR |
| `summarization_keep_kind` | enum `messages` \| `tokens` \| `fraction` | `messages` | `keep` kind |
| `summarization_keep_value` | number | `20` | `keep` value |
| `summarization_summary_prompt` | multiline text \| null | `null` | `summary_prompt` (must contain `{messages}`) |
| `summarization_trim_tokens_to_summarize` | int | `4000` | `trim_tokens_to_summarize` |
| `compact_conversation_tool_enabled` | bool | `false` | **(deep only)** `create_summarization_tool_middleware(model, backend)` → `compact_conversation` tool; model-triggered, coexists with the automatic 85% threshold |

UI note: when `harness=deep_agent` and the user has not overridden it, show the deep-agent defaults as read-only
informational values (trigger 85% of `max_input_tokens`, keep 10% of tokens, fallback 170,000 tokens / 6 messages)
rather than editable fields — the docs expose no parameters for them. Also surface a warning when
`summarization_trigger_kind = fraction` and the selected model has no model profile.

**Context editing** (independent of summarization — both can be on)

| Field | Type | Default | Drives |
| --- | --- | --- | --- |
| `context_editing_enabled` | bool | `false` | presence of `ContextEditingMiddleware` |
| `context_edit_token_count_method` | enum `approximate` \| `model` | `approximate` | `token_count_method` |
| `context_edit_trigger_tokens` | int | `100000` | `ClearToolUsesEdit.trigger` |
| `context_edit_keep` | int | `3` | `ClearToolUsesEdit.keep` — recent tool results never cleared |
| `context_edit_clear_at_least` | int | `0` | `ClearToolUsesEdit.clear_at_least` |
| `context_edit_clear_tool_inputs` | bool | `false` | `ClearToolUsesEdit.clear_tool_inputs` |
| `context_edit_exclude_tools` | string list | `[]` | `ClearToolUsesEdit.exclude_tools` |
| `context_edit_placeholder` | string | `"[cleared]"` | `ClearToolUsesEdit.placeholder` |

Do **not** add a "clear thinking blocks" field — no such strategy is documented.

**Filesystem / offloading**

| Field | Type | Default | Drives |
| --- | --- | --- | --- |
| `filesystem_enabled` | bool | `false` (`true`, locked on, for `deep_agent`) | `FilesystemMiddleware` — also the substrate for offloading, skills, memory |
| `filesystem_backend` | enum `state` \| `store` \| `local` \| `composite` \| `sandbox` | `state` | `backend=` (`StateBackend` / `StoreBackend` / `FilesystemBackend` / `CompositeBackend` / sandbox) |
| `filesystem_memories_route` | string | `"/memories/"` | `CompositeBackend(routes={<value>: StoreBackend()})` — cross-thread file prefix |
| `filesystem_tools` | multi-select from `ls, read_file, write_file, edit_file, delete, glob, grep, execute` | all | `FilesystemMiddleware(tools=[...])` allowlist; `read_file` is mandatory |
| `filesystem_custom_tool_descriptions` | map str→str | `{}` | `custom_tool_descriptions` |
| `filesystem_permissions` | rule list | `[]` | `permissions=[FilesystemPermission(...)]` |
| `excluded_tools` | multi-select | `[]` | harness profile `excluded_tools` — shrinks tool schemas *before* any compression runs |

Offloading itself has **no field**: it is automatic in `create_deep_agent` at a fixed 20,000-token threshold.
Render it as a read-only capability badge, not a control.

**Input context**

| Field | Type | Default | Drives |
| --- | --- | --- | --- |
| `memory_sources` | path list | `[]` | `memory=` → `MemoryMiddleware(sources=...)`; `AGENTS.md`, **always loaded** |
| `skills_sources` | path list | `[]` | `skills=` → `SkillsMiddleware(sources=...)`; `SKILL.md` dirs, **loaded on demand** |

**Planning & delegation**

| Field | Type | Default | Drives |
| --- | --- | --- | --- |
| `todo_list_enabled` | bool | `false` | `TodoListMiddleware()` → `write_todos` tool (no options) |
| `general_purpose_subagent_enabled` | bool | `true` | `GeneralPurposeSubagentProfile(enabled=...)`; `false` + no subagents = no `task` tool at all |
| `subagents` | list of subagent objects | `[]` | `subagents=` / `SubAgentMiddleware(subagents=...)` |
| ↳ per subagent | `name` str (req), `description` str (req), `system_prompt` text (req), `tools` list (inherit), `model` str (inherit), `interrupt_on` map (inherit), `skills` path list (`[]`), `response_format` schema (null), `permissions` rule list (inherit), `middleware` list (`[]`) | — | `SubAgent` dict spec |
| `async_subagents_enabled` | bool | `false` | `AsyncSubAgentMiddleware` + `list_async_tasks` |

**Steering (HITL)**

| Field | Type | Default | Drives |
| --- | --- | --- | --- |
| `interrupt_on` | map: tool name → `false` \| `true` \| `{allowed_decisions: [...]}` | `{}` | `interrupt_on=` → `HumanInTheLoopMiddleware`. Decisions: `approve`, `edit`, `reject`, `respond`. **Validation: requires `checkpointer != none`.** |

**Fault tolerance**

| Field | Type | Default | Drives |
| --- | --- | --- | --- |
| `model_call_thread_limit` | int \| null | `null` | `ModelCallLimitMiddleware.thread_limit` (needs checkpointer) |
| `model_call_run_limit` | int \| null | `null` | `ModelCallLimitMiddleware.run_limit` |
| `model_call_exit_behavior` | enum `end` \| `error` | `end` | `ModelCallLimitMiddleware.exit_behavior` |
| `tool_call_run_limit` | int \| null | `null` | `ToolCallLimitMiddleware.run_limit` |
| `tool_call_exit_behavior` | enum `continue` \| `end` \| `error` | `continue` | `ToolCallLimitMiddleware.exit_behavior` |
| `model_fallbacks` | model-string list | `[]` | `ModelFallbackMiddleware(*models)` |
| `model_retry_enabled` | bool | `false` | `ModelRetryMiddleware` |
| `model_retry_max_retries` | int | `2` | `max_retries` |
| `model_retry_backoff_factor` | float | `2.0` | `backoff_factor` |
| `model_retry_initial_delay` | float (s) | `1.0` | `initial_delay` |
| `model_retry_max_delay` | float (s) | `60.0` | `max_delay` |
| `model_retry_jitter` | bool | `true` | `jitter` (±25%) |
| `model_retry_on_failure` | enum `continue` \| `error` | `continue` | `on_failure` |
| `tool_retry_enabled` | bool | `false` | `ToolRetryMiddleware` |
| `tool_retry_tools` | tool-name list (empty = all) | `[]` | `tools` |
| `tool_retry_max_retries` / `_backoff_factor` / `_initial_delay` / `_max_delay` / `_jitter` / `_on_failure` | as above | `2` / `2.0` / `1.0` / `60.0` / `true` / `continue` | `ToolRetryMiddleware` |
| `tool_error_enabled` | bool | `false` | `ToolErrorMiddleware(on_error=...)` (needs a code-valued handler; expose as an advanced/code field) |

**Guardrails**

| Field | Type | Default | Drives |
| --- | --- | --- | --- |
| `pii_rules` | list of `{pii_type, strategy, detector?, apply_to_input, apply_to_output, apply_to_tool_results}` | `[]` | one `PIIMiddleware(...)` per entry |
| ↳ `pii_type` | enum `email`\|`credit_card`\|`ip`\|`mac_address`\|`url` \| custom string | — | `pii_type` |
| ↳ `strategy` | enum `redact` \| `mask` \| `hash` \| `block` | `redact` | `strategy` |
| ↳ `apply_to_input` / `apply_to_output` / `apply_to_tool_results` | bool | `true` / `false` / `false` | same-named params |
| `custom_guardrails` | custom-middleware ref list | `[]` | `middleware=` (custom `before_agent` / `after_agent` hooks) |

**Advanced / read-only**

| Field | Type | Default | Drives |
| --- | --- | --- | --- |
| `rubric` | `{rubric: text, enabled: bool}` | disabled | `RubricMiddleware` (beta, deepagents>=0.6.5) |
| `prompt_caching` | read-only badge | auto | `AnthropicPromptCachingMiddleware` / `BedrockPromptCachingMiddleware`, automatic on Anthropic + Bedrock, no config |
| `extra_middleware` | middleware-ref list | `[]` | `middleware=`. Note the merge rule: an instance whose `.name` matches a default **replaces** it in place; `FilesystemMiddleware`, `SubAgentMiddleware` and the permission middleware may never be excluded (raises `ValueError`). |

**Preset mapping for the dial** — "plain" = `harness=create_agent`, everything off. "Managed context" = add
`summarization_enabled` + a `trigger`, optionally `context_editing_enabled`. "Filesystem agent" = add
`filesystem_enabled` + a backend. "Deep agent" = `harness=deep_agent`, which turns on filesystem + summarization
(85%/10%) + offloading (20k) + `general-purpose` subagent + prompt caching, and leaves `todo_list_enabled`,
`memory_sources`, `skills_sources`, `interrupt_on`, and `store` as the remaining opt-ins.

---

### Doc pages used

LangChain (Python) core:
* [Agents (`create_agent`)](https://docs.langchain.com/oss/python/langchain/agents) · [Configure the harness](https://docs.langchain.com/oss/python/langchain/agents#configure-the-harness) · [Context management](https://docs.langchain.com/oss/python/langchain/agents#context-management) · [Planning and delegation](https://docs.langchain.com/oss/python/langchain/agents#planning-and-delegation)
* [Prebuilt middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in) — [Summarization](https://docs.langchain.com/oss/python/langchain/middleware/built-in#summarization-10), [Human-in-the-loop](https://docs.langchain.com/oss/python/langchain/middleware/built-in#human-in-the-loop), [Model call limit](https://docs.langchain.com/oss/python/langchain/middleware/built-in#model-call-limit), [Tool call limit](https://docs.langchain.com/oss/python/langchain/middleware/built-in#tool-call-limit), [Model fallback](https://docs.langchain.com/oss/python/langchain/middleware/built-in#model-fallback), [PII detection](https://docs.langchain.com/oss/python/langchain/middleware/built-in#pii-detection), [To-do list](https://docs.langchain.com/oss/python/langchain/middleware/built-in#to-do-list), [Tool error](https://docs.langchain.com/oss/python/langchain/middleware/built-in#tool-error), [Tool retry](https://docs.langchain.com/oss/python/langchain/middleware/built-in#tool-retry), [Model retry](https://docs.langchain.com/oss/python/langchain/middleware/built-in#model-retry), [Context editing](https://docs.langchain.com/oss/python/langchain/middleware/built-in#context-editing), [Shell tool](https://docs.langchain.com/oss/python/langchain/middleware/built-in#shell-tool), [Filesystem middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in#filesystem-middleware), [Short-term vs long-term filesystem](https://docs.langchain.com/oss/python/langchain/middleware/built-in#short-term-vs-long-term-filesystem), [Subagent](https://docs.langchain.com/oss/python/langchain/middleware/built-in#subagent), [Rubric grading](https://docs.langchain.com/oss/python/langchain/middleware/built-in#rubric-grading)
* [Custom middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom) · [Middleware overview](https://docs.langchain.com/oss/python/langchain/middleware)
* [Context engineering](https://docs.langchain.com/oss/python/langchain/context-engineering) · [Example: Summarization](https://docs.langchain.com/oss/python/langchain/context-engineering#example-summarization)
* [Short-term memory](https://docs.langchain.com/oss/python/langchain/short-term-memory) · [Long-term memory](https://docs.langchain.com/oss/python/langchain/long-term-memory) · [LangGraph stores](https://docs.langchain.com/oss/python/langgraph/stores)
* [Guardrails](https://docs.langchain.com/oss/python/langchain/guardrails) · [Human-in-the-loop](https://docs.langchain.com/oss/python/langchain/human-in-the-loop)
* [Models / model profiles](https://docs.langchain.com/oss/python/langchain/models#model-profiles) · [Build a deep agent from scratch](https://docs.langchain.com/oss/python/langchain/deep-agent-from-scratch) · [Event streaming](https://docs.langchain.com/oss/python/langchain/event-streaming)
* [Middleware integrations](https://docs.langchain.com/oss/python/integrations/middleware)

Deep Agents (Python):
* [Overview / harness](https://docs.langchain.com/oss/python/deepagents/overview) — [Core capabilities](https://docs.langchain.com/oss/python/deepagents/overview#core-capabilities), [Virtual filesystem access](https://docs.langchain.com/oss/python/deepagents/overview#virtual-filesystem-access), [Context management](https://docs.langchain.com/oss/python/deepagents/overview#context-management), [Task planning](https://docs.langchain.com/oss/python/deepagents/overview#task-planning), [Prompt caching](https://docs.langchain.com/oss/python/deepagents/overview#prompt-caching)
* [Context engineering](https://docs.langchain.com/oss/python/deepagents/context-engineering) — [Context compression](https://docs.langchain.com/oss/python/deepagents/context-engineering#context-compression), [Offloading](https://docs.langchain.com/oss/python/deepagents/context-engineering#offloading), [Summarization](https://docs.langchain.com/oss/python/deepagents/context-engineering#summarization), [Context isolation with subagents](https://docs.langchain.com/oss/python/deepagents/context-engineering#context-isolation-with-subagents), [Long-term memory](https://docs.langchain.com/oss/python/deepagents/context-engineering#long-term-memory)
* [Customization](https://docs.langchain.com/oss/python/deepagents/customization) — [Middleware](https://docs.langchain.com/oss/python/deepagents/customization#middleware), [Default stack (main agent)](https://docs.langchain.com/oss/python/deepagents/customization#default-stack-main-agent), [Default stack (sync subagents)](https://docs.langchain.com/oss/python/deepagents/customization#default-stack-synchronous-subagents), [Override a default middleware instance](https://docs.langchain.com/oss/python/deepagents/customization#override-a-default-middleware-instance), [Backends](https://docs.langchain.com/oss/python/deepagents/customization#backends), [Human-in-the-loop](https://docs.langchain.com/oss/python/deepagents/customization#human-in-the-loop), [Skills](https://docs.langchain.com/oss/python/deepagents/customization#skills), [Memory](https://docs.langchain.com/oss/python/deepagents/customization#memory)
* [Subagents](https://docs.langchain.com/oss/python/deepagents/subagents) — [SubAgent spec](https://docs.langchain.com/oss/python/deepagents/subagents#subagent-dictionary-based), [Running without subagents](https://docs.langchain.com/oss/python/deepagents/subagents#running-without-subagents), [general-purpose subagent](https://docs.langchain.com/oss/python/deepagents/subagents#the-general-purpose-subagent)
* [Async subagents](https://docs.langchain.com/oss/python/deepagents/async-subagents) · [Backends](https://docs.langchain.com/oss/python/deepagents/backends) · [Profiles](https://docs.langchain.com/oss/python/deepagents/profiles) · [Permissions](https://docs.langchain.com/oss/python/deepagents/permissions) · [Sandboxes](https://docs.langchain.com/oss/python/deepagents/sandboxes) · [Skills](https://docs.langchain.com/oss/python/deepagents/skills) · [Fault tolerance](https://docs.langchain.com/oss/python/deepagents/fault-tolerance) · [Multimodal](https://docs.langchain.com/oss/python/deepagents/multimodal) · [Streaming](https://docs.langchain.com/oss/python/deepagents/streaming) · [Comparison with Claude Agent SDK](https://docs.langchain.com/oss/python/deepagents/comparison)

API reference:
[`SummarizationMiddleware`](https://reference.langchain.com/python/langchain/agents/middleware/summarization/SummarizationMiddleware) ·
[`ContextSize`](https://reference.langchain.com/python/langchain/agents/middleware/summarization/ContextSize) ·
[`TriggerClause`](https://reference.langchain.com/python/langchain/agents/middleware/summarization/TriggerClause) ·
[`ContextEditingMiddleware`](https://reference.langchain.com/python/langchain/agents/middleware/context_editing/ContextEditingMiddleware) ·
[`ContextEdit`](https://reference.langchain.com/python/langchain/agents/middleware/context_editing/ContextEdit) ·
[`ClearToolUsesEdit`](https://reference.langchain.com/python/langchain/agents/middleware/context_editing/ClearToolUsesEdit) ·
[`HumanInTheLoopMiddleware`](https://reference.langchain.com/python/langchain/agents/middleware/human_in_the_loop/HumanInTheLoopMiddleware) ·
[`PIIMiddleware`](https://reference.langchain.com/python/langchain/agents/middleware/pii/PIIMiddleware) ·
[`TodoListMiddleware`](https://reference.langchain.com/python/langchain/agents/middleware/todo/TodoListMiddleware) ·
[`ModelCallLimitMiddleware`](https://reference.langchain.com/python/langchain/agents/middleware/model_call_limit/ModelCallLimitMiddleware) ·
[`ToolCallLimitMiddleware`](https://reference.langchain.com/python/langchain/agents/middleware/tool_call_limit/ToolCallLimitMiddleware) ·
[`ModelFallbackMiddleware`](https://reference.langchain.com/python/langchain/agents/middleware/model_fallback/ModelFallbackMiddleware) ·
[`ModelRetryMiddleware`](https://reference.langchain.com/python/langchain/agents/middleware/model_retry/ModelRetryMiddleware) ·
[`ToolRetryMiddleware`](https://reference.langchain.com/python/langchain/agents/middleware/tool_retry/ToolRetryMiddleware) ·
[`ToolErrorMiddleware`](https://reference.langchain.com/python/langchain/agents/middleware/tool_error/ToolErrorMiddleware) ·
[`ContextOverflowError`](https://reference.langchain.com/python/langchain-core/exceptions/ContextOverflowError) ·
[`create_deep_agent`](https://reference.langchain.com/python/deepagents/graph/create_deep_agent) ·
[`create_summarization_middleware`](https://reference.langchain.com/python/deepagents/middleware/summarization/create_summarization_middleware) ·
[`create_summarization_tool_middleware`](https://reference.langchain.com/python/deepagents/middleware/summarization/create_summarization_tool_middleware) ·
[`SummarizationToolMiddleware`](https://reference.langchain.com/python/deepagents/middleware/summarization/SummarizationToolMiddleware) ·
[`FilesystemMiddleware`](https://reference.langchain.com/python/deepagents/middleware/filesystem/FilesystemMiddleware) ·
[`SkillsMiddleware`](https://reference.langchain.com/python/deepagents/middleware/skills/SkillsMiddleware) ·
[`MemoryMiddleware`](https://reference.langchain.com/python/deepagents/middleware/memory/MemoryMiddleware) ·
[`SubAgentMiddleware`](https://reference.langchain.com/python/deepagents/middleware/subagents/SubAgentMiddleware) ·
[`SubAgent`](https://reference.langchain.com/python/deepagents/middleware/subagents/SubAgent) ·
[`CompiledSubAgent`](https://reference.langchain.com/python/deepagents/middleware/subagents/CompiledSubAgent) ·
[`AsyncSubAgentMiddleware`](https://reference.langchain.com/python/deepagents/middleware/async_subagents/AsyncSubAgentMiddleware) ·
[`PatchToolCallsMiddleware`](https://reference.langchain.com/python/deepagents/middleware/patch_tool_calls/PatchToolCallsMiddleware) ·
[`RubricMiddleware`](https://reference.langchain.com/python/deepagents/middleware/rubric/RubricMiddleware) ·
[`StateBackend`](https://reference.langchain.com/python/deepagents/backends/state/StateBackend) ·
[`AnthropicPromptCachingMiddleware`](https://reference.langchain.com/python/langchain-anthropic/middleware/prompt_caching/AnthropicPromptCachingMiddleware) ·
[`BedrockPromptCachingMiddleware`](https://reference.langchain.com/python/langchain-aws/middleware/prompt_caching/BedrockPromptCachingMiddleware)
