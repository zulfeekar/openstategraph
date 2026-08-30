# A Hermes agent: which Hermes, and where it goes

**Status: in force from 2026-08-30.** Research and design only — nothing was
built. Resolves `providers-and-credentials` ticket 17.

The request was for *"a Hermes agent as one of the agents"*, offered as either a
third concrete beside the existing tiers, or a native `hermes-agent` that uses
Hermes *instead of* the LangChain harness. The answer to both is below, and it
turns entirely on the first section: **which Hermes**.

---

## What Hermes is — and there are two of them

Two distinct things carry the name, both published by the same organisation,
and the request is ambiguous between them. Ruling one out was the whole design
step; everything downstream changes depending on the answer.

### Hermes 4 — a model family

A family of open-weight hybrid reasoning models. Primary sources: the model
cards (`huggingface.co/NousResearch/Hermes-4-70B` and its siblings) and the
*Hermes 4 Technical Report* (`arxiv.org/abs/2508.18255`).

What matters here is the wire format, and it is unusual in exactly two places:

- **Tool calls are delimited text, not a protocol field.** Tools are declared
  as JSON schema inside the system message, and the model answers with the call
  wrapped in `<tool_call>` … `</tool_call>`. The model card's own words: *"The
  model will then generate tool calls within `<tool_call> {tool_call}
  </tool_call>` tags, for easy parsing."* The tags are added tokens, so a
  streaming parser can find them without buffering.
- **Reasoning is delimited text too.** Deliberation arrives inside `<think>`
  … `</think>` ahead of the answer, in the same content stream.

Both are **normalised for us already** where the model is served properly:
vLLM ships a tool parser named `hermes` and SGLang one named `qwen25`, and both
expose an OpenAI-compatible Chat Completions surface. A server with the parser
enabled returns ordinary `tool_calls`; a server without it returns a string
containing angle brackets.

### Hermes Agent — a self-hosted agent framework

A separate, later project from the same publisher (`hermes-agent.org`,
`github.com/NousResearch/hermes-agent`, MIT). It is a **self-hosted service**:
per-agent profiles on disk, a SQLite memory store, a messaging gateway process,
a cron scheduler, subagent spawning. It is model-agnostic — *"Use any model you
want"* — so it is not a way to run Hermes 4, and it is not a library. Its
published surfaces are an installer, a CLI and a gateway; there is no
documented Python import surface, and no documented one-shot *prompt in, answer
out* invocation. The nearest thing it offers is scripts calling its tools over
RPC.

### Which one the request means, and why it does not matter

The phrasing *"instead of Lang\*\*\* you will use Hermes"* points at the
framework; *"as one of the agents"*, beside `create_agent` and the deep agent,
points at the model. **Both readings resolve to the same place**, by different
roads:

- If Hermes means the **model**, this is a provider question, not a node
  question. See below.
- If Hermes means the **framework**, it is a peer of this product, not a
  component of it. It owns its own process, its own memory store and its own
  scheduler, and it has no embeddable call. Wiring it into a node would mean
  driving a service over RPC from inside a superstep — which is a *connector*,
  the route with no authoring path in this repository
  (`.scratch/the-atom-has-no-context/`), for a service that duplicates the
  runtime we already compile to.

The rest of this document takes the model reading, because it is the only one
with a design.

---

## The routing answer: this is not a node

`skills/atom-forge/` routes before it interviews, and its dimension 8 is the
one that decides:

> **Compile target** — Name the LangGraph construct this becomes. *nothing
> new* → it is **configuration, a template, or a package to mount** — not a
> node type.

A Hermes agent compiles to `create_agent` with a different `model` object. That
is the same construct `agent.llm` already compiles to, reached through the same
`BaseAgentNode.build()`. There is no new LangGraph construct, so there is no
new node type — the same refusal `.scratch/production-ready/tickets/01` records
for a Loop node.

**And the model is already selectable in principle.** `chat_model.py` is the
single seam from a `provider:model` string to a callable model, and it defers
to `init_chat_model`. LangChain's own guidance for a Hermes-serving vLLM or
gateway endpoint is `model_provider="openai"` with a `base_url` — which the
bundled `openai` spec's integration already supports. Typing
`openai:Hermes-4-405B` against a `OPENAI_API_BASE` pointed at such an endpoint
runs today, with no code change anywhere in this tree.

That is the honest headline: **a Hermes agent is an Agent node with a Hermes
model selected.** What follows is what actually breaks on that path, because
none of it is nothing.

---

## What breaks today, and each one is a real defect

Established by reading the code, not by reasoning from the principle.

### The endpoint is not named, so the platform cannot see where the request went

`builtin_specs()` declares `openai` with its credential variable and **no**
`endpoint_env` and **no** `default_endpoint`. So `chat_model.model_kwargs()`
returns nothing for it, no `base_url` is passed — and `ChatOpenAI` resolves
`OPENAI_API_BASE` from the environment in its own validator regardless. The
request goes to the Hermes endpoint; every surface in this tree that reports
provider readiness says *OpenAI*.

This is `CLAUDE.md`'s recorded Ollama correction with the sign flipped. There
the spec named no credential while the client reached a vendor through an
ambient daemon; here the spec names the credential and not the address, and the
address is read behind the catalogue's back. It trips atom-forge's Set B gate
12 by the same reading — *name the variable, in the `ProviderSpec` shape* — and
the gate's own words are that the fix is the shape, not a second statement of
the rule.

The fix is one line of data: `endpoint_env=("OPENAI_API_BASE", "OPENAI_BASE_URL")`
on the `openai` spec. Nothing about Hermes. It is a defect the Hermes question
*found*, not one it creates.

### Model discovery filters Hermes out by name

`src/core/providers/OpenAIProvider.ts`'s `listModels()` replaces its seed list
from the account's `/v1/models` — the right idea, and its own docstring says
why: *"Hardcoding a model catalogue is how an LLM integration goes stale."* It
then filters the result with `/^(gpt|o\d|chatgpt)/i`.

Against `api.openai.com` that filter separates chat models from embeddings and
audio. Against a Hermes-serving OpenAI-compatible endpoint it removes **every**
model the endpoint offers, and the picker silently falls back to a seed list of
OpenAI names none of which that endpoint can serve. The seam built to keep the
catalogue honest is the seam that hides the catalogue.

### The declared escape hatch has no reader

`OpenAIProvider` declares `allowsCustomModel = true`, and the class docstring
promises *"the agent node also accepts a free-text model id"*. Nothing reads
the flag. `src/nodes/modelField.ts` declares `kind: 'select'` with a closed
option list built from `providers.modelOptions()`, so a model id that is not in
the list cannot be typed into a card.

`configurableEndpoint` is the same shape one step better off: it *is* read, by
`CredentialsDialog`, and only `OllamaProvider` declares it — so there is no
endpoint field for OpenAI in the editor either.

Both are the failure `CLAUDE.md` names about `TopBar.tsx`: an absence has no
signature. A flag with no consumer and a flag with one consumer read identically
from the flag's own file.

### The reasoning trace has nowhere to go

Nothing in this tree reads a reasoning channel: `reasoning.py` is about the
`reasoning_effort` *parameter*, and no module mentions `<think>` or
`reasoning_content`. LangChain's own warning is that `ChatOpenAI` against a
custom `base_url` *"targets official OpenAI API specifications only"* and that
non-standard response fields — it names `reasoning_content`, `reasoning`,
`reasoning_details` — **are not extracted or preserved**.

So a Hermes deployment that emits reasoning as a separate field loses it
entirely, and one that emits it inline in content publishes it as the answer.
The second is `launch-readiness/27` exactly: *"a customer-audience answer opened
'Perfect. I now have the official documentation.' — the model's inner monologue
about its own tool loop, published verbatim."* `content_text` on the final
message **is** the answer; there is no scratchpad channel to strip it from
downstream.

### Ollama is not the way in

Ollama's library carries Hermes builds, and none of them is a cloud model. Under
`CLAUDE.md`'s standing instruction — *"Never benchmark, demo or debug against a
local model and treat the result as representative"* — the Ollama route reaches
Hermes only as the exact thing that instruction forbids treating as evidence.
Any Hermes verification has to go through a served endpoint.

---

## The two options the request named

### Option A — a third concrete under `AbstractAgentNode`

`HermesAgentNode` beside `ReactAgentNode` and `DeepAgentNode`, with
Hermes-specific middleware.

**Verdict: rejected, and the ladder is what rejects it.** `abc/agent.py` states
the rule its own shape enforces:

> **`DeepAgentNode` is a sibling of `ReactAgentNode`, never a subclass.**
> `create_deep_agent` is `create_agent` plus a fixed middleware slot assembly —
> the relationship is *data*, so it is expressed as a constructor swap.

A tier in this ladder is *which constructor it calls*, and that is the only
abstract member (`build_agent`). Hermes calls the same constructor. A tier that
differs from `ReactAgentNode` by nothing except configuration is not a tier —
and the tier field is a data value in `workflow.json` read by
`agent_node_for_tier`, so a fourth value would name a class whose whole content
is a middleware default.

It also collides with the agent-tier table, which is not ours: it mirrors
LangChain's own framework/runtime/harness layering. `hermes` is not a fourth
tier of that publication. It is a *model*, orthogonal to all three — which is
the tell that it belongs on a different axis entirely.

There is a smaller, real cost too. `agent_node_for_tier` is a dispatch table
whose targets are defined in its own module, and
`backend/tests/test_a_dispatch_table_does_not_hold_its_targets.py` exists
because that pattern is how `node_runtime.py` came to hold twenty families
behind one lookup. A fourth entry is a fourth reason for that module to change,
bought for a middleware default.

### Option B — a native `hermes-agent` with its own loop

**Verdict: rejected — but the slogan is not what rejects it, and the difference
matters.**

`CLAUDE.md` says *"never write an execution engine"*, and that rule is about the
**graph**: checkpointing, time-travel, `interrupt()`, `Send` fan-out, reducer
merging. A loop inside one node is a narrower question, and read against the
code the graph-level argument is much weaker than it sounds:

- **Checkpointing is already not there.** `compile/nodes/agent.py` records it
  in its own comment — the built agent *"is a bare `Runnable`, invoked here with
  no config and no checkpointer of its own"*. The node hand-threads what must
  survive (`agent_files`, the async-task roster) onto the outer `RunState`,
  which the workflow's checkpointer does persist.
- **Supersteps are already not shared.** The inner loop has its own counter;
  `step_budget.py` says the same of a mounted child. The step budget bounds the
  *graph*, and the inner loop is bounded by its own means.
- **`Send`, reducers and time-travel are graph-level** and untouched by what a
  node does inside itself.
- **Cancellation survives** if the loop is written `async def`, which is the
  property `async-first/06` established for this node body.

So four of the slogan's five nouns do not apply. What a native loop actually
forfeits is different, larger, and specific to this repository:

- **The middleware slot table, entirely.** Every slot in
  `AbstractAgentNode.SLOT_ORDER` is a LangChain `AgentMiddleware`. A loop that
  does not call `create_agent` inherits none of them — including
  `injection-screening`, which the base's own comment marks as *"the one hard
  constraint in this list"* and security-sensitive. A native tier would ship an
  agent with the screening slot silently empty.
- **Token streaming.** The live token stream reaches the wire because a
  LangChain chat model emits callbacks that LangGraph's `messages` stream mode
  picks up. A loop driving an SDK or `httpx` directly emits nothing, and the
  failure looks like `launch-readiness/110` — *"a blank panel, nothing in the
  logs, both suites green."*
- **The message shape everything downstream reads.** `tool_report`,
  `text_or_ask_again`, the usage accounting in `messages.py`, the audience fold
  — all read LangChain message objects off `result["messages"]`. A native loop
  either reproduces them exactly or breaks every one of those readers.

That is the honest rejection: not *"you would reimplement LangGraph"*, but
*"you would reimplement `AbstractAgentNode` and inherit an agent with no
injection screening and no token stream."* And the thing being bought is a
tool-call format that vLLM and SGLang already normalise for free.

---

## Option C — a provider, plus one middleware slot

The option the request did not name, and the one the evidence supports.

**Hermes reaches the canvas as a model, through the provider layer, with no new
node family and no new tier.** Concretely, and in the order the costs justify:

1. **Name the endpoint on the `openai` spec.** `endpoint_env` and, if a
   deployment wants one, `default_endpoint`. This is Set B gate 12 satisfied,
   and it is worth doing whether or not anybody ever runs Hermes.
2. **Stop discovery filtering by vendor name** when the endpoint is not the
   vendor's own. A filter that means *"chat models, not embeddings"* has to be
   expressed as something other than *"names beginning `gpt`"* once the
   endpoint is configurable.
3. **Give the model field the escape hatch it already claims** — read
   `allowsCustomModel`, or delete the flag and its docstring. Either is honest;
   the present state is not.
4. **If a Hermes deployment turns out to emit `<think>` inline, that is a
   middleware slot**, contributed by name into the existing table — not a class.
   It is the ordinary shape: a `wrap_model_call` that splits the trace from the
   answer, replaceable by slot name, inheriting position from the base.

A dedicated `ProviderSpec` — a plugin registering `nous` or a gateway — is the
tidier long-term form and needs no core change either: `PROVIDERS_GROUP` is an
entry point a third party writes into their own `pyproject.toml`, and
`providers.py` states that built-in and third-party are indistinguishable *"by
construction rather than by our remembering to expose it"*. The one constraint
is that the spec's `name` must be a prefix `init_chat_model` resolves, or the
spec must point `integration_module` at a package that supplies one.

### The plumbing requirement, answered

`input -> [hermes-agent] -> out` is satisfied by `agent.llm` unchanged, which is
the point:

- **Ports and cardinality** are already declared on `agent.llm`'s port
  descriptors, with `maxConnections` on the port and not on the node.
- **`retry_policy`, `timeout`, `cache_policy`** stay graph-assembly parameters
  on the workflow. A Hermes-specific retry field would be the cross-family
  violation `CLAUDE.md` names by example.
- **No `core/` file changes**, because nothing new is registered: the model is a
  string in a field that already exists.
- **No host-language code in `workflow.json`** — the model selection is data,
  resolved against a known set, and named when it resolves to nothing.
- **No new state key**, so no reducer question arises.

### What the *n*th agent family costs

This is the maintainability argument, and it is why Option C is not merely
smaller. Each tier added to the ladder costs, permanently and per-tier: an
entry in `agent_node_for_tier`; an option in the editor's tier select; a
`tier_kwargs` branch in `compile/nodes/agent.py`, which already branches on
`DeepAgentNode` in several places; a row in the slot-table reasoning; and a case
in every test that exercises tiers. The fourth is worse than the third because
the branches multiply against the existing ones, and the fifth worse again.

A model added through the provider layer costs a row of data and nothing else.
That asymmetry — linear-with-multipliers against constant — is the whole
recommendation.

---

## Overhead and bottlenecks

Split honestly into what was established and what was not.

**Established.**

- **Reasoning tokens are generated and therefore billed.** The technical report
  describes training the model to terminate a trace by inserting `</think>` at a
  fixed token count during synthesis, and reports the length-contraction
  experiments in its own appendix. A hybrid reasoning model's trace is output
  tokens on the same stream as the answer; there is no configuration in this
  tree that would make them free.
- **Tool-call overhead is the schema, once per call.** Tools are declared as
  JSON schema in the *system message*, so the cost is the schema plus the
  delimiter tokens — and the delimiters are added tokens, so they are cheap.
  This is the same order as any tool-calling model and is not the bottleneck.
- **Streamed token counts go missing on a custom endpoint.** In the
  `langchain-openai` this tree pins (`backend/uv.lock`), `ChatOpenAI` enables
  `stream_usage` by default *only* when no base URL is configured and
  `OPENAI_BASE_URL` is unset. Point it at a Hermes endpoint and streamed
  responses carry no `usage_metadata`. This degrades correctly rather than
  lying — `messages.py` returns `None`, and its comment is exactly the reason:
  *"'this message cost nothing' and 'nobody said' are different claims"* — but
  the run reports no token count, and `chat_model.model_kwargs()` has no way to
  pass `stream_usage` today.
- **The parse is not our bottleneck when the server is configured, and is a
  cliff when it is not.** With the vLLM or SGLang parser enabled, tool calls
  arrive as ordinary structured calls and nothing here parses angle brackets.
  Without it, every tool call arrives as prose and every one fails.

**Not established, and stated as such.**

- **Latency and time-to-first-token.** These are properties of the serving
  deployment — which engine, which quantisation, which hardware — not of the
  model family, and this tree has no Hermes endpoint to measure. Any figure
  written here would be a number with no way to fail. Atom-forge's Set A gate
  11 forbids citing a measurement without the version it ran on; there is no
  run to cite.
- **Reasoning trace length in practice.** The report gives a training-time
  termination budget, not a serving-time distribution. What a given deployment
  emits per call is unmeasured here.
- **Tool-call reliability on the served format.** Unmeasured, and this is the
  one that matters most: see below.

### Where the parse risk actually bites

`CLAUDE.md`'s *read a model's answer tolerantly; trust it strictly* records four
production defects of exactly this shape, and the third is the closest analogue:
*"the prompt taught the model a format the parser could not read. When these
disagree, suspect the parser."*

Hermes is the same collision waiting, with the parser in a different process. If
the serving engine's tool parser is off or misnamed, `<tool_call>{...}</tool_call>`
arrives as **content**, and the agent looks like a model that will not use its
tools — the exact symptom `CLAUDE.md`'s Ollama finding warns about, where a
wiring gap and a capability gap produce one indistinguishable failure.

The rule's second half is what stops the obvious wrong fix. Tolerance here would
mean scanning assistant content for `<tool_call>` and executing what it finds —
and *"this product prints JSON as prose constantly"*, including a workflow
architect that answers with an entire workflow document. A content scanner that
executes bracketed JSON is a tool-call injection surface, reachable by any
upstream text. **The tolerance belongs in the serving engine, which has the
parser; ours stays strict.**

So the test any Hermes work must carry is not *"can we parse `<tool_call>`"*. It
is: an assistant message whose content contains `<tool_call>` **executes
nothing**, and the run says the endpoint's tool parser is not configured.

---

## The readiness card

Scored on the canvas route, because the request was for a node. It fails at the
route, which is the outcome atom-forge names as correct rather than as a failure.

| # | Dimension | Answer |
| --- | --- | --- |
| 1 | Trigger | The flow reaching the node — unchanged from `agent.llm` |
| 2 | Payload | The same messages `agent.llm` already carries |
| 3 | Scope & lifetime | Unchanged; no new state |
| 4 | Read side | The card's model field, which already exists |
| 5 | Failure modes | Endpoint unreachable; tool parser not configured; reasoning trace published as the answer; token counts absent |
| 6 | Tier & family | **None — it is not a family.** It is a model selection |
| 7 | Ports & cardinality | Unchanged |
| 8 | Compile target | **Nothing new.** `create_agent`, as today — the refusal |
| 9 | Outside contact | Needs a named endpoint variable, which the spec does not declare; content leaves to an endpoint the *operator* chose, which is the safe half of gate 15; repeats are the existing agent's; costs include billed reasoning tokens; stalls unmeasured |
| 10 | Honesty gates | Set B gate 12 **tripped** by the current `openai` spec — recorded as its own defect, not designed around |
| 11 | Smoke plan | See the ticket |

Dimension 8 is the one that ends it, and dimension 10 is the one worth keeping.

---

## Recommended shape

**Do not build a Hermes node, a Hermes tier, or a Hermes loop.** Treat Hermes as
a model, and spend the work on the four things that are broken on the path a
Hermes model would take — every one of which is broken for any non-OpenAI
OpenAI-compatible endpoint, and none of which mentions Hermes.

The ticket is `providers-and-credentials/17`.

---

## What would have to become true to reconsider

Recorded so the rejection can be overturned by evidence rather than by
re-argument.

**Option A becomes right when** Hermes needs a *different constructor* — not
different configuration. If a `create_agent` variant ships that is to Hermes
what `create_deep_agent` is to the deep tier, the ladder's own rule admits it as
a sibling on the same day, and the tier value is one row of data.

**Option B becomes right when** the middleware slot table and the token stream
can be had without `create_agent` — that is, when this repository's shared agent
capability is expressed against something narrower than a LangChain harness. It
is not today, and building the native loop first would be building the thing
that makes the answer *no*.

**Option C's provider spec becomes a dedicated one when** a Hermes-serving
vendor ships a LangChain integration package that preserves the reasoning
channel. LangChain's own guidance already prefers a dedicated integration over
`ChatOpenAI` with a base URL, for exactly the field-preservation reason that
costs us the trace today. On that day the spec is data, the entry point exists,
and nothing in `core/` changes — which is the property that made Option C the
recommendation in the first place.

**And the framework reading becomes live when** this repository has an authoring
path for infrastructure — a connector or a client with a lifetime and a
registry. That decision is open (`.scratch/the-atom-has-no-context/`). Even
then, driving a self-hosted agent service from inside a superstep would need an
argument for why its scheduler, memory store and gateway belong inside a graph
that already has a checkpointer — an argument nobody has made.
