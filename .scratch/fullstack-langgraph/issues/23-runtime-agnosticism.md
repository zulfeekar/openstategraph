Type: research
Status: resolved
Blocked by: —

## Question

Establish what runtime-agnosticism would actually cost.

The requirement: LangGraph now, but later Google, Microsoft or Vercel SDKs should be possible — so the design must be agnostic.

The working hypothesis to test: **`workflow.json` is already the vendor-neutral layer.** Agnosticism then comes from having multiple *compilers* (JSON → `StateGraph`, JSON → something else), not from wrapping LangGraph's API in an `IOrchestrator` interface. Wrapping the runtime API produces a lowest-common-denominator abstraction that leaks.

Research the current landscape and answer:
- What are the actual competing orchestrators (Google ADK, Microsoft Agent Framework / Semantic Kernel, Vercel AI SDK, others)? Licences, maturity, and their core execution model — graph, loop, actor, or something else.
- Which LangGraph concepts have **no equivalent** elsewhere? Candidates from prior tickets: `Send` fan-out, checkpoint namespacing, `interrupt`/HITL resume, `Command(update=..., goto=...)`, reducer-based state merging. Each one that does not port is a feature we either give up or must reimplement per runtime.
- Do the competitors offer a serialisable graph format, or are they all code-first like LangGraph? If none serialise, our JSON is genuinely the portable layer and the hypothesis holds.
- What does a realistic second compiler cost — a week, or a rewrite?

Deliverable: a blunt recommendation. Either (a) the definition is portable and the feature set is the intersection, (b) go deep on LangGraph and accept a documented port cost, or (c) a capability-flag model where a workflow declares which runtime features it uses. State which LangGraph features we would be giving up under (a).

## Answer

Researched 2026-08-04 against primary sources (official docs, GitHub, PyPI/npm, LICENSE files).

### Verdict on the hypothesis: SUPPORTED, with one amendment that makes it *more* true than stated

`workflow.json` is the vendor-neutral layer, and agnosticism does come from multiple compilers rather than an `IOrchestrator` wrapper. The decisive evidence: **no competitor accepts an authorable, serialisable graph.** Every target requires either generated source code or in-process builder calls — which is a compiler by definition, not an interface implementation.

The amendment: the wrapper idea is not merely "leaky", it is **unbindable**. An `IOrchestrator` with `addNode`/`addEdge` has nothing to bind to on two of the five targets, because Vercel and OpenAI have no topology object at all — control flow there *is* the imperative source text. You cannot wrap an API that does not exist. And the compiler count is understated: for Vercel/OpenAI a compiler emits **source plus a build step**, not runtime objects.

### The field as of 2026-08

| Framework | Licence | Version | Execution model | Serialisable definition? |
|---|---|---|---|---|
| [LangGraph](https://github.com/langchain-ai/langgraph/blob/main/LICENSE) | MIT | `langgraph` 1.2.10 / `@langchain/langgraph` 1.4.9 | Pregel/BSP superstep graph, channel state | **No** (see below) |
| [Microsoft Agent Framework](https://github.com/microsoft/agent-framework/blob/main/LICENSE) | MIT | `agent-framework` 1.13.0 (1.0 GA Apr 2026) | "[modified Pregel](https://deepwiki.com/microsoft/agent-framework/4-workflows-and-orchestration)" BSP superstep graph — [`WorkflowBuilder`, executors, edges](https://learn.microsoft.com/en-us/agent-framework/workflows/) | **Partial — but not a graph** |
| [Google ADK](https://github.com/google/adk-python/blob/main/LICENSE) | Apache-2.0 | `google-adk` 2.6.2 (2.0 GA May 2026; [ADK Go 2.0](https://developers.googleblog.com/announcing-adk-go-20/) Jun 2026) | [Graph engine](https://adk.dev/graphs/) + agent loop + imperative `DynamicNode` escape hatch | **No** (graphs excluded from YAML) |
| [Vercel AI SDK](https://github.com/vercel/ai/blob/main/LICENSE) | Apache-2.0 | `ai` 7.0.51 | Tool loop + [durable imperative code](https://vercel.com/blog/ai-sdk-7) (`'use workflow'` / `'use step'`, SWC build-time transform) | **No** |
| [OpenAI Agents SDK](https://github.com/openai/openai-agents-python/blob/main/LICENSE) | MIT | 0.19.3 / 0.14.2 — still 0.x | [Model-driven loop](https://openai.github.io/openai-agents-python/running_agents/) + handoffs; topology decided by the LLM | **No** |
| [Mastra](https://github.com/mastra-ai/mastra/blob/main/LICENSE.md) | Apache-2.0 (+`ee/` carve-out) | `@mastra/core` 1.55.0 | [Fluent step graph](https://mastra.ai/en/docs/workflows/control-flow) (`.then/.parallel/.branch/.foreach/.dountil`) | **No** — `serializedStepGraph` is run-snapshot output, not authoring input |
| [AWS Strands](https://github.com/strands-agents/sdk-python) | Apache-2.0 | 1.50.2 | [Agent loop](https://strandsagents.com/docs/user-guide/concepts/agents/agent-loop/) + `GraphBuilder`/Swarm | **No** |
| [CrewAI](https://github.com/crewAIInc/crewAI/blob/main/LICENSE) | MIT | 1.15.10 | Crews (sequential/hierarchical) + [Flows](https://docs.crewai.com/en/concepts/flows) (`@start`/`@listen`/`@router`) | **Roster only** — `agents.yaml`/`tasks.yaml` do not express Flow topology |
| [Temporal](https://github.com/temporalio/temporal/blob/main/LICENSE) / [Restate](https://github.com/restatedev/restate/blob/main/LICENSE) / [DBOS](https://github.com/dbos-inc/dbos-transact-py/blob/main/LICENSE) | MIT / BSL-1.1→Apache / MIT | 1.31.2 / 1.7.2 / 2.29.0 | Deterministic replay of workflow *code* | **No** — "[A Workflow Definition is the code that defines the Workflow](https://docs.temporal.io/workflow-definition)" |

All permissively licensed. **There is no licence trap forcing a migration** — which is itself an argument against pre-paying for portability.

### The two YAML formats that exist, and why neither rescues (a)

**[Microsoft Declarative Workflows 1.0](https://learn.microsoft.com/en-us/agent-framework/workflows/declarative)** is the strongest counter-example to "everyone is code-first" — and it collapses on inspection. It is a **sequential action list**, not a graph: `actions:` executes top-to-bottom with `If`, `ConditionGroup`, `Foreach`, `BreakLoop`, `GotoAction`. The [Actions Quick Reference](https://learn.microsoft.com/en-us/agent-framework/workflows/declarative) has **no parallel or fan-out action of any kind** — `Foreach` is sequential. It is strictly weaker than Microsoft's own code-first `WorkflowBuilder`. Expressions are **Power Fx** (`=Concat(Local.greeting, Workflow.Inputs.name)`), so a JSON→YAML compiler must emit Power Fx. Python support ships as `pip install agent-framework-declarative --pre` and Python 3.14 is unsupported "due to PowerFx compatibility". Agent invocation in the Python action set is `InvokeAzureAgent` — Azure-bound.

**[ADK Agent Config](https://adk.dev/agents/config/)** is explicitly experimental, **Gemini-only**, covers `LlmAgent`/`SequentialAgent`/`ParallelAgent`/`LoopAgent`, and **cannot express graph workflows at all** (`LangGraphAgent` and `A2aAgent` are explicitly unsupported types).

**LangGraph has no round-trip either**, confirming our JSON is doing real work: [`langgraph.json`](https://docs.langchain.com/oss/python/langgraph/application-structure) maps a name to a code entrypoint (`"./your_package/your_file.py:agent"`) — a pointer, not topology. [`Graph.to_json()`](https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/runnables/graph.py) is one-way for visualisation; **there is no `from_json`**.

### Feature parity matrix — the five probes

Legend: **✅ equivalent** / **⚠️ workaround** / **❌ nothing**

| LangGraph concept | MAF (code-first) | MAF (YAML) | ADK 2.x | Vercel AI SDK 7 | OpenAI Agents SDK |
|---|---|---|---|---|---|
| [`Send` fan-out](https://docs.langchain.com/oss/python/langgraph/graph-api#send) — N unknown at build time, each with its own per-invocation state | ⚠️ executor loops `SendMessageAsync` per item + [`AddFanInBarrierEdge`](https://learn.microsoft.com/en-us/agent-framework/workflows/edges). **Not** `AddFanOutEdge` — that `targetSelector` returns *indices into a statically declared target list*, so N is bounded at build time | ❌ | ⚠️ `DynamicParallelGroup` / `DynamicNode` + `RunNode` — but expressed as Go/Python control flow, not graph data | ⚠️ `Promise.all` in hand-written code | ⚠️ `asyncio.gather`/`Promise.all` |
| [Reducer state merging](https://docs.langchain.com/oss/python/langgraph/use-graph-api#conditional-branching) (`Annotated[list, operator.add]`, `ReducedValue`) | ❌ `QueueStateUpdateAsync`/`ReadStateAsync` are scope-aware queued writes visible next superstep — **no per-key merge function** | ❌ `SetVariable` overwrites; `EditTableV2` is manual | ❌ [`ctx.Session().State().Set(k,v)`](https://adk.dev/graphs/data-handling/) — plain KV with `app:`/`user:`/`temp:` prefixes; **parallel-branch write merging is not addressed in the docs at all** | ❌ `runtimeContext` replaced by return value | ❌ |
| [`interrupt`/HITL resume](https://docs.langchain.com/oss/javascript/langgraph/interrupts#resuming-interrupts) | ✅ different semantics — `RequestInfoExecutor` / `ctx.request_info()`; LangGraph **re-runs the node from its start** on resume, MAF does not | ⚠️ `Question`, `RequestExternalInput` only | ✅ **arguably better** — durable HITL primitive, two resume modes (*handoff* and *re-entry*), resumes "after a process restart, or even across different runtimes" | ⚠️ approvals only — `needsApproval` + suspend; no interrupt-anywhere | ⚠️ JS only, approvals only — serialise whole `RunState` to a string |
| [Checkpoint namespacing](https://docs.langchain.com/oss/python/langgraph/checkpointers#checkpoint-namespace) (`checkpoint_ns`, `"outer:uuid\|inner:uuid"`, per-subgraph checkpointer, [time-travel inside a subgraph](https://docs.langchain.com/oss/python/langgraph/use-time-travel#subgraph-checkpointer)) | ⚠️ [sub-workflows](https://learn.microsoft.com/en-us/agent-framework/workflows/advanced/sub-workflows) via `WorkflowExecutor` keep independent state; superstep-boundary checkpoints — but **no namespace addressing, no fork, no time travel**, and an open bug re-sends already-answered HITL requests after restore ([#3255](https://github.com/microsoft/agent-framework/issues/3255)) | ❌ | ❌ "reconstruct a paused workflow by **scanning session history**" — no addressable checkpoint tree | ❌ durable step journal, not an addressable tree | ❌ |
| [`Command(update=, goto=)`](https://docs.langchain.com/oss/python/langgraph/graph-api#update-and-goto) | ⚠️ `SendMessageAsync` + `QueueStateUpdateAsync` in one handler gets the effect; no single primitive. `graph=Command.PARENT` cross-graph handoff: ❌ | ⚠️ `SetVariable` + `GotoAction` — closest declarative match anywhere, but action-ID scoped | ⚠️ emitting node sets `event.Routes` and writes state; `Command.PARENT`: ❌ | n/a — it is just code | n/a — handoffs swap `current_agent`, chosen by the model |

**LangGraph-only with no equivalent anywhere:** time-travel fork from an arbitrary checkpoint with `update_state(as_node=...)`; per-`Send` timeout override (`Send(..., timeout=TimeoutPolicy(...))`).

### Precedent: does anyone actually run one JSON against many runtimes?

Almost nobody. [n8n](https://docs.n8n.io/workflows/export-import/) (JSON), [Dify](https://docs.dify.ai/en/guides/management/app-management) (YAML DSL), [Langflow](https://docs.langflow.org/concepts-flows-import) (JSON), [Flowise](https://github.com/FlowiseAI/Flowise) (JSON) all store vendor-neutral workflow documents — and **all four execute against their own engine**. None compiles to a third-party orchestrator.

The one real exception is [Oracle Open Agent Specification](https://github.com/oracle/agent-spec) (Apache-2.0/UPL, [arXiv:2510.04173](https://arxiv.org/abs/2510.04173)): a JSON/YAML framework-agnostic language with adapters for LangGraph, AutoGen and CrewAI, plus Oracle's WayFlow reference runtime. ~400 stars, no canvas. So: the multi-compiler idea is *tractable* — demonstrated once, at small scale. The combination we are attempting (visual builder + neutral JSON + multiple runtime compilers) is essentially unoccupied. That is opportunity and risk in the same fact. Note MCP/A2A are runtime **interop wire protocols**, not workflow compilation — they do not help here.

### What a second compiler actually costs

Not a week. Not a rewrite of the builder. Honest breakdown for one additional target:

| Layer | Cost | Notes |
|---|---|---|
| Topology + node kinds → target builder | 1–2 wk (MAF/ADK), 3–5 wk (Vercel/OpenAI) | Graph-shaped targets are cheap. Loop/durable-code targets mean **emitting source text and owning a build step** |
| Expression & callback emission | 3–6 wk | Conditional predicates, reducers, `Send` producers, tool binding, structured-output mapping. **Each target needs its own emitter** — Python/TS, Power Fx, Go |
| Runtime services parity | 4–8 wk | Checkpoint store, thread/run addressing, resume protocol, stream event normalisation, per-node observability. All five differ |
| Test matrix | ongoing | every workflow × every runtime × interrupt/resume/crash paths |

**≈1 engineer-quarter for the first second compiler.** The real cost is not that figure — it is the **permanent multiplier**: after the second compiler, every new node type must be implemented N times, and `workflow.json` is pinned to the intersection unless you introduce flags. The initial build is the cheap part.

### Recommendation: **(b) — go deep on LangGraph and accept a documented port cost.**

**(a) intersection is the worst option and it is not close.** The genuine intersection across LangGraph / MAF / ADK / Vercel / OpenAI is: sequential steps, static conditional branch, static parallel branch with a join, bounded loop, step-scoped KV state with last-write-wins, and approval-style HITL. That is roughly n8n. Under (a) we would **surrender, today and permanently**:

1. **`Send` / dynamic map-reduce** — no fan-out over a runtime-length list with per-item state. This is the single most valuable primitive for document-batch, per-row and per-file workflows, and it is the reason people outgrow n8n.
2. **Reducer-based state merging** — no accumulator patterns, no append-only message channels, no safe concurrent writes to one key. Every parallel branch becomes a merge you must hand-code into a join node.
3. **Checkpoint namespacing, time travel and fork** — no "re-run this run from step 7", no branching a run to compare outcomes, no per-subgraph state inspection. This is debuggability, and it is the hardest thing for a visual builder to give up.
4. **`interrupt()` anywhere** — HITL degrades to approve/reject gates at tool boundaries.
5. **`Command(goto=..., graph=Command.PARENT)`** — no cross-graph handoff; multi-agent routing must be flattened.
6. **Per-`Send` timeout/retry policy** — no per-item fault-tolerance tuning.

We would pay that in product differentiation *now*, for a portability event that may never occur, against runtimes we do not have a customer asking for.

**(c) capability flags is the seductive wrong answer.** It does not remove work, it defers and multiplies it: every flag becomes a conditional in every compiler and a cell in the test matrix — 2^n behaviours. Worse, it is dishonest by construction. The flags that would matter (dynamic fan-out, reducers, checkpoint forking) are precisely the ones **no second runtime satisfies**, so we would ship a portability feature that is false for every interesting workflow, and users discover it only at migration time.

**(b) is right for three reasons:**

1. **The definition is already the portable layer**, so the port cost is real, bounded (≈1 quarter, quantified above) and *deferrable*. Nothing about choosing LangGraph today makes the port harder tomorrow, provided the seam is kept clean.
2. **No licence or pricing gun to our head** — LangGraph MIT, ADK Apache-2.0, MAF MIT, Vercel Apache-2.0. Migration will be a business decision, not an emergency.
3. **The field is converging on LangGraph's model, not diverging from it.** MAF is explicitly a modified-Pregel superstep engine with executors, edges, fan-in barriers and checkpoints. ADK 2.0 *added* a graph engine with join strategies and durable HITL where it previously had only agent loops. Betting `workflow.json` on graph + checkpoint + HITL is a bet on the direction everyone is already moving. **The intersection will be wider in 18 months than it is today** — which is an argument for keeping the JSON expressive now and paying later, not for crippling it in advance.

### Guardrails that make (b) safe (do these; they are cheap now and expensive later)

1. **Keep `workflow.json` graph-shaped and free of LangGraph type names.** No `Annotated[...]` strings, no Python import paths, no `langgraph` package names in the document. Reducers become a **named enum** (`append`, `add`, `merge`, `last_write_wins`) resolved by the compiler — never a callback reference.
2. **Expressions must be a small declared sublanguage with its own AST in JSON**, not host-language snippets. This is the single highest-leverage portability decision in the whole design: it is what makes a Power Fx or Go emitter feasible *at all*. If `workflow.json` carries Python lambdas, it is not a portable format — it is a LangGraph project file with a `.json` extension.
3. **The compiler is a module, not an interface.** One direction only: `compile(workflow.json) -> CompiledStateGraph`. Nothing outside that module imports `langgraph`. Enforce it with a lint/import rule. This — not an `IOrchestrator` — is the seam that makes a second compiler tractable.
4. **Give runtime services our own vocabulary at the API boundary** (run id, checkpoint ref, resume token, event stream), mapped to LangGraph's inside. The port cost concentrates here and it is cheap to abstract before there are consumers.
5. **This ticket is the port-cost document.** Revisit on a trigger — a named customer, a licence change, a pricing change — not on a schedule.
6. **Do not build a second compiler speculatively.** If cheap proof that the seam works is wanted, add an **export** of the intersection-only subset to [Oracle Agent Spec](https://github.com/oracle/agent-spec) JSON that fails loudly on unsupported nodes. That validates the seam in days rather than a quarter, and costs nothing if abandoned.
