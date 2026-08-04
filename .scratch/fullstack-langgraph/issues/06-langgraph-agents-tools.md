Type: research
Status: resolved
Blocked by: —

## Question

How are tools, standalone function-calling, and subagents expressed?

From primary sources:
- `create_agent` — full signature: model, tools, middleware, state schema, structured output, and how instructions/system prompt are supplied.
- `ToolNode` — a *standalone* tool-executing node, i.e. function calling without a surrounding agent loop. The user requires a node that is a tool/function call on its own.
- `@tool` definition, args schema, error handling, and returning `Command` from a tool.
- **Subagents**: the supported multi-agent patterns (supervisor, swarm, agent-as-tool) and how an agent is given the ability to spawn one. Which is the right primitive for "spawn subagents if necessary"?
- Middleware relevant to production: summarisation, HITL, retries, PII.

Answer determines the distinct node types the catalogue needs and what each exposes as configuration.

## Answer

Sources (docs-langchain MCP server; Python-first, TS noted where it differs):
[Agents](https://docs.langchain.com/oss/python/langchain/agents) ·
[Tools](https://docs.langchain.com/oss/python/langchain/tools) ·
[Workflows and agents — ToolNode](https://docs.langchain.com/oss/python/langgraph/workflows-agents#toolnode) ·
[Graph API — return from tools](https://docs.langchain.com/oss/python/langgraph/graph-api#return-from-tools) ·
[Use the Graph API — use inside tools](https://docs.langchain.com/oss/python/langgraph/use-graph-api#use-inside-tools) ·
[Multi-agent overview](https://docs.langchain.com/oss/python/langchain/multi-agent/) ·
[Subagents](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents) ·
[Handoffs](https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs) ·
[Router](https://docs.langchain.com/oss/python/langchain/multi-agent/router) ·
[Skills](https://docs.langchain.com/oss/python/langchain/multi-agent/skills) ·
[Migrate from langgraph-supervisor](https://docs.langchain.com/oss/python/migrate/langgraph-supervisor) ·
[Prebuilt middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in) ·
[Deep Agents subagents](https://docs.langchain.com/oss/python/deepagents/subagents) ·
[`create_agent` reference](https://reference.langchain.com/python/langchain/agents/factory/create_agent) ·
[`ToolNode` reference](https://reference.langchain.com/python/langgraph.prebuilt/tool_node/ToolNode) ·
[`@tool` reference](https://reference.langchain.com/python/langchain-core/tools/convert/tool) ·
[`SubAgentMiddleware` reference](https://reference.langchain.com/python/deepagents/middleware/subagents/SubAgentMiddleware)

---

### 1. `create_agent` — full current signature

`from langchain.agents import create_agent`

```python
create_agent(
    model: str | BaseChatModel,
    tools: Sequence[BaseTool | Callable[..., Any] | dict[str, Any]] | None = None,
    *,
    system_prompt: str | SystemMessage | None = None,
    middleware: Sequence[AgentMiddleware[StateT_co, ContextT]] = (),
    response_format: ResponseFormat[ResponseT] | type[ResponseT] | dict[str, Any] | None = None,
    state_schema: type[AgentState[ResponseT]] | None = None,
    context_schema: type[ContextT] | None = None,
    checkpointer: Checkpointer | None = None,
    store: BaseStore | None = None,
    interrupt_before: list[str] | None = None,
    interrupt_after: list[str] | None = None,
    debug: bool = False,
    name: str | None = None,
    cache: BaseCache[Any] | None = None,
    transformers: Sequence[TransformerFactory] | None = None,
) -> CompiledStateGraph[AgentState[ResponseT], ContextT, InputAgentState, OutputAgentState[ResponseT]]
```

Per-parameter notes worth putting in the catalogue:

- **`model`** — either a provider string (`"anthropic:claude-sonnet-4-5-20250929"`, `"openai:gpt-5.5"`) resolved via `init_chat_model`, or a `BaseChatModel` instance.
- **`tools`** — list of `BaseTool`, plain callables, or dicts (provider/server-side tool specs). **If `None` or empty, the agent is just a model node with no tool-calling loop.** That is the doc-sanctioned way to build a "pure LLM" node.
- **`system_prompt`** — *this is how instructions are supplied.* `str` (converted to a `SystemMessage`) or a `SystemMessage` instance; it is prepended to the message list on every model call. There is **no `prompt=` parameter in the current Python signature** — some doc examples still show `prompt=`, but the reference signature is `system_prompt`. **For dynamic/runtime-computed prompts, use middleware**: a `@wrap_model_call` hook calling `request.override(system_prompt=..., tools=...)`. That is the documented mechanism (the Handoffs page builds a whole state machine out of it).
- **`response_format`** — structured output. Accepts a Pydantic model class, a raw schema dict, or an explicit strategy (`ToolStrategy`, `ProviderStrategy`); raw schemas get auto-wrapped based on model capability. Result lands in `structuredResponse` / the `response` state field.
- **`state_schema`** — a `TypedDict` extending `AgentState`, used as the base merged with middleware state schemas. The reference explicitly *recommends* adding custom state via middleware instead, to keep extensions scoped to the hooks/tools that use them.
- **`context_schema`** — schema for per-run (non-state) context, read inside tools via `ToolRuntime.context`.
- **`checkpointer`** / **`store`** — thread-scoped persistence (chat memory) vs. cross-thread persistence.
- **`interrupt_before` / `interrupt_after`** — static node-level interrupt lists (coarse HITL). Tool-level HITL should use `HumanInTheLoopMiddleware` instead.
- **`name`** — used automatically when the compiled agent is embedded as a **subgraph node** in a larger graph. Relevant to the canvas: an agent *is* a node.
- Returns a **`CompiledStateGraph`** — so an agent composes as a node anywhere a node is accepted.

**TypeScript differs meaningfully**: `createAgent({ model, tools, systemPrompt, middleware, responseFormat, stateSchema, contextSchema, checkpointer, ... })` takes a single options object with camelCase keys and returns a `ReactAgent`. The TS docs also accept a **function** for the prompt (dynamic prompt) and accept a configured `ToolNode` in place of a `tools` array.

### 2. `ToolNode` used STANDALONE — **yes, this is supported and is the documented use case**

`from langgraph.prebuilt import ToolNode`

```python
ToolNode(
    tools: Sequence[BaseTool | Callable],
    *,
    name: str = "tools",
    tags: list[str] | None = None,
    handle_tool_errors: bool | str | Callable[..., str] | type[Exception] | tuple[type[Exception], ...] = <default>,
    messages_key: str = "messages",
    wrap_tool_call: ToolCallWrapper | None = None,
    awrap_tool_call: AsyncToolCallWrapper | None = None,
)
```

The reference docstring is unambiguous: *"Use `ToolNode` when building custom workflows that require fine-grained control over tool execution — for example, custom routing logic, specialized error handling, or non-standard agent architectures. For standard ReAct-style agents, use `create_agent` instead. It uses `ToolNode` internally."* The Tools page says the same from the other direction: agents use tools via `create_agent`; "for LangGraph workflows, tool execution is handled by `ToolNode`."

So a "function call as its own node, no agent loop" is a first-class pattern. Add it with `builder.add_node("tools", ToolNode([search, calculator]))` and wire ordinary edges around it. **There is no requirement for a model node, a `tools_condition` edge, or a loop back.** The docs include a working example whose graph is literally `START → ToolNode` and nothing else — invoked by passing state whose last message is a hand-constructed `AIMessage(content="", tool_calls=[{"name": ..., "args": {...}, "id": ...}])`.

**Three accepted input formats** (this is what makes standalone use viable):
1. **Graph state** with a `messages` key — the normal agentic case; key name configurable via `messages_key`.
2. **A message list** — `[AIMessage(..., tool_calls=[...])]`.
3. **Direct tool calls** — `[{"name": "tool", "args": {...}, "id": "1", "type": "tool_call"}]`. This *bypasses message parsing entirely* and is the closest thing to "invoke this function with these arguments, no LLM involved."

**Output formats:** dict input → `{"messages": [ToolMessage(...)]}`; list input → `[ToolMessage(...)]`. Tools returning `Command` → `[Command(...)]` (or a mixed list), and `ToolNode` **automatically propagates those `Command`s to graph state** — the docs recommend `ToolNode` specifically for this reason, noting that a hand-written tool-calling node must propagate `Command`s manually.

Other standalone-relevant behaviour:
- Handles **parallel** tool execution and state injection automatically.
- **`handle_tool_errors`** is the error-handling knob: `True` (catch all, default template), a `str` (catch all, custom message), an exception type or tuple of types (catch only those), a callable (`Exception -> str`), or `False` (disable, let exceptions propagate). The default callable catches *invocation* errors (bad model-generated args) and returns a descriptive message, while letting *execution* errors re-raise.
- Tools read graph state/context via the injected **`ToolRuntime`** argument (Python) / the second argument (JS). Important caveat: tools only see what was passed to the `ToolNode`. Adding it as a `StateGraph` node passes the full state; if you invoke it manually from another node, pass the whole state (`tool_node.invoke(state)`), not just `{"messages": ...}`.
- If you want the classic loop, the prebuilt helper is **`tools_condition`** (`langgraph.prebuilt`): routes to the tool node if the last `AIMessage` has `tool_calls`, else to `END`. Optional — not needed for standalone use.

TS: `import { ToolNode } from "@langchain/langgraph/prebuilt"; new ToolNode([search, calculator])`.

### 3. `@tool` — definition, args schema, errors, returning `Command`

`from langchain.tools import tool` (re-exported; canonical `langchain_core.tools.convert.tool`)

```python
tool(
    name_or_callable: str | Callable[..., Any] | None = None,
    runnable: Runnable[Any, Any] | None = None,
    *args: Any,
    description: str | None = None,
    return_direct: bool = False,
    args_schema: ArgsSchema | None = None,
    infer_schema: bool = True,
    response_format: Literal["content", "content_and_artifact"] = "content",
    parse_docstring: bool = False,
    error_on_invalid_docstring: bool = True,
    extras: dict[str, Any] | None = None,
) -> BaseTool | Callable[[Callable | Runnable], BaseTool]
```

- Usable bare (`@tool`) or with args (`@tool("research", description="...")`). `name_or_callable` and `runnable` must be **positional**. A `Runnable` requires an explicit string name.
- **Args schema**: inferred from type hints by default (`infer_schema=True`). Override with `args_schema` (Pydantic / `ArgsSchema`). `parse_docstring=True` pulls per-parameter descriptions from a Google-style docstring (`error_on_invalid_docstring=True` raises on malformed ones).
- **Description precedence**: explicit `description=` > function docstring > `args_schema` description.
- `response_format="content_and_artifact"` means the tool returns a `(content, artifact)` 2-tuple mapped onto the `ToolMessage`.
- `return_direct=True` returns the tool output directly instead of continuing the agent loop.
- `extras` carries provider-specific fields (the reference names Anthropic's `cache_control`, `defer_loading`, `input_examples`).
- **Error handling** is *not* on `@tool`. In agents it comes from middleware (`ToolErrorMiddleware`, `ToolRetryMiddleware`); in graph workflows it comes from `ToolNode(handle_tool_errors=...)`.
- **Returning `Command` from a tool** — supported, and the mechanism behind handoffs and tool-driven state writes:

  ```python
  @tool
  def set_user_name(new_name: str, runtime: ToolRuntime[None, CustomState]) -> Command:
      """Set the user's name in the conversation state."""
      return Command(update={
          "user_name": new_name,
          "messages": [ToolMessage(content=f"User name set to {new_name}.",
                                   tool_call_id=runtime.tool_call_id)],
      })
  ```
  Rules: you **must** include the message-history key and it **must** contain a `ToolMessage` with the right `tool_call_id`, or the history is invalid for the provider. `goto` also works from a tool, but it adds a *dynamic* edge — static edges on the calling node still fire, so don't mix. Define reducers for any state key that parallel tool calls might both write.

### 4. Subagents / multi-agent — the supported patterns

**Terminology check: the current docs do not ship `supervisor` or `swarm` as primitives.** `langgraph-supervisor` (`create_supervisor`) is documented as **no longer actively maintained**, with a dedicated migration guide pointing at the subagents pattern. There is **no swarm pattern in the current docs at all**. The five named patterns are:

| Pattern | Mechanism | Distributed dev | Parallel | Multi-hop | Direct user interaction |
|---|---|---|---|---|---|
| **Subagents** (a.k.a. supervisor) | main agent calls subagents **as tools** | ★★★★★ | ★★★★★ | ★★★★★ | ★ |
| **Handoffs** | tools return `Command(update=...)` changing a state var; middleware re-reads it to swap prompt/tools | – | – | ★★★★★ | ★★★★★ |
| **Skills** | one agent loads specialized prompts/knowledge on demand | ★★★★★ | ★★★ | ★★★★★ | ★★★★★ |
| **Router** | one classification step dispatches to specialized agents; results synthesized | ★★★ | ★★★★★ | – | ★★★ |
| **Custom workflow** | bespoke `StateGraph`, mixing deterministic and agentic nodes; other patterns embed as nodes | — | — | — | — |

**Supervisor vs. Router** (the docs call this out explicitly): a supervisor is a *full agent* that keeps conversation context and decides across turns which subagents to call; a router is a *single classification step* with no ongoing state.

**For "let this agent spawn subagents if necessary" the correct primitive is the Subagents (agent-as-tool) pattern.** Three implementation levels, in increasing order of batteries-included:

**(a) Hand-rolled — tool per agent.** Minimal, explicit, no extra deps:
```python
subagent = create_agent(model=..., tools=[...])

@tool("research", description="Research a topic and return findings")
def call_research_agent(query: str):
    result = subagent.invoke({"messages": [{"role": "user", "content": query}]})
    return result["messages"][-1].content

main_agent = create_agent(model=..., tools=[call_research_agent])
```

**(b) Hand-rolled — single dispatch `task` tool.** One parameterized tool (`agent_name`, `description`) over a registry dict; the description is passed as a human message and the subagent's final message is returned as the tool result. Better when agents are added without touching the coordinator, or teams ship agents independently. Subagent discovery via system-prompt enumeration, an enum constraint on the dispatch arg, or progressive disclosure through a discovery tool.

**(c) Prebuilt — `SubAgentMiddleware` from `deepagents`.** This is the "spawn subagents" capability as a drop-in, and it is what the prebuilt-middleware table describes as *"Add the ability to spawn subagents."*
```python
SubAgentMiddleware(
    *,
    backend: BackendProtocol,
    subagents: Sequence[SubAgent | CompiledSubAgent],
    system_prompt: str | None = None,          # appended to main agent's prompt, explains the task tool
    task_description: str | None = None,       # custom description for the task tool
    private_state_keys: frozenset[str] | None = None,
    state_schema: type | None = None,
)
```
It **injects a `task` tool** into the main agent. A `SubAgent` spec is `{name, description, system_prompt, model, tools}` plus optional `middleware` and `interrupt_on`; a `CompiledSubAgent` lets you hand it an arbitrary prebuilt LangGraph graph. Pass it via `create_agent(..., middleware=[SubAgentMiddleware(...)])`. `create_deep_agent` pre-assembles this (plus filesystem, summarization, prompt caching). In Deep Agents the harness also provides a **`general-purpose` subagent by default**, inheriting the main agent's instructions and tools, whose entire point is context isolation. TS: `createSubAgentMiddleware({ defaultModel, defaultTools, subagents })` from `deepagents`.

Subagent semantics to expose in the catalogue: **stateless** (fresh context per invocation, no memory of past calls — all conversation memory lives in the main agent), **autonomous** (runs its own loop to completion), **single handoff** (returns one final report, cannot send multiple messages back), and **parallelizable** (the main agent can issue multiple subagent tool calls in one turn, executed in parallel by the runtime). Cost profile from the docs: subagents spend one extra model call vs. handoffs/skills/router on a one-shot request (4 vs. 3), and are stateless so repeat requests don't get cheaper — but they win on multi-domain fan-out (~9K tokens vs. ~14K+ for handoffs) because each subagent works in an isolated context.

Related: **`AsyncSubAgentMiddleware`** (background subagents; gives the supervisor `start_async_task`, `check_async_task`, `update_async_task`, `cancel_async_task`, `list_async_tasks`), and **dynamic subagents** where an interpreter middleware exposes a `task()` global callable from generated code, taking `description`, `subagentType`, and optional `responseSchema`.

Nested hierarchies: with the subagents pattern, "nested supervisors" is just a subagent wrapped as a tool that itself calls other subagents. No special primitive.

### 5. Production middleware

Passed as `create_agent(..., middleware=[...])`; classes from `langchain.agents.middleware`. Middleware is the documented extension point (dynamic prompts, dynamic tools, retries, guardrails, early termination) — and it also works standalone inside a plain LangGraph workflow.

Full provider-agnostic list from the docs: Summarization, Human-in-the-loop, Model call limit, Tool call limit, Model fallback, PII detection, To-do list, LLM tool selector, Tool error, Tool retry, Model retry, LLM tool emulator, Context editing, Provider tool search, Shell tool, File search, Filesystem, Subagent, Rubric grading (beta). Plus provider-specific `AnthropicPromptCachingMiddleware` / `BedrockPromptCachingMiddleware`.

The four the ticket asks about, with exact signatures:

**Summarization** — `SummarizationMiddleware(model, *, trigger=None, keep=("messages", 20), token_counter=count_tokens_approximately, summary_prompt=DEFAULT_SUMMARY_PROMPT, trim_tokens_to_summarize=<default>)`. `trigger` takes `ContextSize` tuples — `("messages", 50)`, `("tokens", 3000)`, `("fraction", 0.8)` — or a `TriggerClause` dict for AND semantics (`{"tokens": 4000, "messages": 10}`); a **list** is OR. `keep` is a single `ContextSize`. Preserves AI/Tool message pairing when it cuts.

**HITL** — `HumanInTheLoopMiddleware(interrupt_on: dict[str, bool | InterruptOnConfig], *, description_prefix="Tool execution requires approval")`. Per tool: `True` = all four decisions allowed, `False` = auto-approve, or an `InterruptOnConfig` naming the allowed decisions plus an optional `description` (str or callable) and a `when` predicate for conditional interrupts. Tools with no entry are auto-approved. Resume with `Command(resume={"decisions": [{"type": ...}]})`, one decision per action, in order. Decision types: **`approve`**, **`edit`** (supply `edited_action` with `name`/`args`), **`reject`** (optional `message` as feedback; tool not executed), **`respond`** (the human's `message` becomes the tool result — for "ask the user" tools).

**Retries** — `ToolRetryMiddleware(*, max_retries=2, tools=None, retry_on=(Exception,), on_failure="continue", backoff_factor=2.0, initial_delay=1.0, max_delay=60.0, jitter=True)`. `tools=None` applies to all; `retry_on` accepts an exception tuple or an `Exception -> bool` callable; `on_failure` is `"continue"` (return an error `ToolMessage` so the model can recover), `"error"` (re-raise and stop), or a callable formatting the message. Delay is `initial_delay * backoff_factor ** n`, capped at `max_delay`, ±25% jitter. Counterparts: `ModelRetryMiddleware`, `ModelFallbackMiddleware`, `ToolErrorMiddleware`, `ModelCallLimitMiddleware`, `ToolCallLimitMiddleware`.

**PII** — `PIIMiddleware(pii_type, *, strategy="redact", detector=None, apply_to_input=True, apply_to_output=False, apply_to_tool_results=False)`. **One instance per PII type**, so compose several. Built-in types: `email`, `credit_card` (Luhn-validated), `ip`, `mac_address`, `url`; any other string is a custom type requiring a `detector` (regex string or callable returning `list[PIIMatch]`). Strategies: `block` (raises `PIIDetectionError`), `redact` (`[REDACTED_TYPE]`), `mask` (partial, e.g. `****-****-****-1234`), `hash` (deterministic, identity-preserving, `<email_hash:...>`). With `apply_to_output=True` a stream transformer is also installed so streamed text deltas, tool-call args, tool events, and `values`-channel snapshots are redacted in flight.

### 6. Implications for the node catalogue

Distinct node types this establishes, each with its own config surface:

1. **Agent node** — a compiled `create_agent(...)`. Config: `model`, `tools`, `system_prompt`, `response_format`, `state_schema`, `context_schema`, `middleware[]`, `checkpointer`/`store`, `name`. Composes as a subgraph node.
2. **Model-only node** — same as above with `tools=None`/`[]`; documented to produce a model node with no tool loop.
3. **Standalone tool node** — a `ToolNode([...])`. Config: `tools`, `name`, `handle_tool_errors`, `messages_key`, `tags`. No LLM required; accepts direct tool-call dicts.
4. **Tool definition** (a resource, not a node) — `@tool` with name, description, args schema (inferred or explicit), `return_direct`, `response_format`, and whether it returns a `Command` (→ mark it a state-writing / handoff tool).
5. **Subagent-capable agent node** — agent node + `SubAgentMiddleware`, exposing a list of `SubAgent` specs (`name`, `description`, `system_prompt`, `model`, `tools`, optional `middleware` / `interrupt_on`) and surfacing a `task` tool. This is the answer to "spawn subagents if necessary".
6. **Middleware** — a per-agent-node list, not a node. Each entry is a typed config block (see §5).
