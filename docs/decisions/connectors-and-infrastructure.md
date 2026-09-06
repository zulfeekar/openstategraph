# A connector is a resource, and a resource is not on the canvas

**Status: in force from 2026-08-30.** Design only — nothing was built. Two
concrete requests arrived together and are answered together, because either
one answered alone produces the wrong abstraction: a **Hermes Agent**
connector (a self-hosted agent *service*, reached over RPC) and a
**Databricks** connector (a warehouse client with credentials and a session).

It settles `the-atom-has-no-context` ticket 06 and the deciding half of ticket
05, states plainly which of that map's other open questions it does *not*
settle, and answers the question `decisions/hermes-agent.md` left standing at
its own last line.

---

## 0. What was already decided, and what this may not re-open

`.scratch/the-atom-has-no-context/` charted this on 2026-08-18 with a
Databricks connector as its named worked example. Its tickets carry their own
status, `scripts/ticket_ledger.py` reports where those and git disagree, and
neither count is restated here — a tally in prose has no way to fail and this
one moves. What follows names the tickets it builds on and the tickets it takes
a position on, individually.

**Settled, and built into `skills/atom-forge/` by `4d0fb6c` — this document
builds on these rather than re-arguing them:**

| Ticket | What it settled |
| --- | --- |
| 07 | Two named gate sets, not one merged sixteen. Set B is the outside-contact set: a vendor reached through something revocable (12), a credential value never stored (13), running twice is harmless or handled (14), content that leaves says so where a person places the node (15), **a pooled resource is scoped to a call, never a run (16)** |
| 09 | The interview asks what a module needs from outside the process — *what is it called, who sets it, how do they revoke it* — and the three redirects, of which *"it works without one on my machine"* is the one a connector trips |
| 10 | Repeats. `retry_policy` is graph-wide and a resumed `interrupt()` re-enters, so *"it won't run twice"* is never an answer |
| 11 | Leaks, three-way: nothing leaves / leaves to a vendor the **user** configured / leaves to a vendor the **author** chose. Only the third needs surfacing, and a downstream guardrail redacts but **cannot unsend** |
| 12 | Cost is not tokens only; a per-call charge is a failure mode with a `Send` fan-out multiplier |
| 15 | Stalls. A thirty-second module has a second read side — what it can say *while* running |
| 06, in part | Phase 0 **routes** before the interview, an infrastructure route exists with its own four-point card, and **binding** (a wire that adds no step) and **resource** (the pool behind it) are kept as two words |

**Open, and this document takes a position on two of them:** 01 (what a module
is entitled to see, merged with 04), 02 (workflow-scoped versus
installation-wide: one contract or two), 03 (may a module write state), 05 (who
may add to the context, and how a third party gets typed), 06 (the tier
decision that Phase 0 did not make).

**And one thing the chart says that has since stopped being true, corrected
here rather than inherited.** The map's *"what is actually true today"*
section states that `workflow_compiler.py` passes no `context_schema` at all
and that the socket is empty. It is not empty any more. `organisms-first-class`
67–73 and 76–79 landed the whole chain (`docs/decisions/runtime-context.md`): a
document declares its context as JSON descriptors, the compiler mints a
dataclass and passes it (`backend/openstategraph/compile/workflow_compiler.py:2291`
and `:2298`), a validator refuses bad values at all three supply doors, and a
tool reads values through the Tier-1 accessor
`backend/openstategraph/compile/run_context.py:718`. **The immutable third of
the owner's `ctx / state / memory` is shipped.** That changes this design
materially, and section 4 is where it changes it.

---

## 1. What a connector *is*, defined against what exists

Five constructs in this repository could be mistaken for one, and the way to
tell them apart is not what they do but **how long they live and what they
hold**.

| Construct | Lifetime | Holds a credential? | Holds a socket? | In `workflow.json`? |
| --- | --- | --- | --- | --- |
| Tool atom (`abc/tool.py`) | one call | no | no | as a node type id |
| Node family (`abc/node_family.py`) | one build, then per-superstep | no | no | as a node type id |
| `ProviderSpec` (`providers.py:119`) | process (it is data) | **names** one | no | no — a model string does |
| A package's `tools/` | one call | no | no | as a node type id |
| An entry-point plugin tool | one call | no | no | as a node type id |
| **A connector** | **process** | **names** one | **yes** | **no** |

> **A connector is a named, process-lifetime holder of a connection and the
> credentials that open it, which is never placed on the canvas, has no ports
> and no compile target, and exists only to be *declared by name* by something
> that is on the canvas.**

Three properties do the work, and each of them is what separates it from the
row above:

- **It outlives a call.** That is the whole reason it is a thing at all. A
  connection opened and closed inside `_execute` needs no design; it is a local
  variable. `backend/openstategraph/mcp_sessions.py`'s own header measures what
  that costs — a re-opened MCP session pays ≈0.8 s of handshake per tool call,
  four times in a four-tool turn.
- **It names a credential.** `ProviderSpec` is the only construct today that
  does (`providers.py:150–172`: `env_vars`, `endpoint_env`,
  `default_endpoint`), and it is **model-shaped** — its own docstring says it is
  deliberately data and never a class, *"a vendor that needed behaviour would
  need a client, and shipping vendor clients is explicitly out of scope"*. A
  connector is exactly the case that sentence excluded.
- **It is not a node type.** Nothing places it, nothing wires it, nothing
  compiles from it. This is what makes the tier question (§7) answerable and
  the portability question (§6) almost empty.

### The first connector already exists and was never named one

`backend/openstategraph/mcp_sessions.py` is a process-lifetime pool of live
sessions, keyed by connection identity, with credential-aware keys, lazy open,
transport-failure reconnect, and an `atexit` shutdown (`:332`, `:336`, `:374`,
`:416`). It has every property in the definition above. It was built for one
vendor protocol, in one module, because there was nowhere else to put it.

That is the evidence this design rests on, and it is stronger than the
Databricks request: **the second connector will be built the same way unless
something exists to build it into**, and then there will be two pools, two
shutdown paths, two credential-key conventions and two answers to *"is it safe
to run twice"*. `mcp_sessions.py` is also the reference implementation — every
mechanism below is something it already does correctly, generalised.

What it is *not* is a registry. `_POOL` is a module-level `dict` with a lock: a
duplicate key silently returns the incumbent, there is no `list()`, and a test
resets it through `close_all_sessions()` rather than by constructing a fresh
one. Those are the four properties `CLAUDE.md` requires of an extension point,
and the pool has none of them — correctly, because it is one vendor's pool and
not an extension point. Section 5 is where they arrive.

---

## 2. Lifetime and ownership — the hardest question, answered first

> **A connector is owned by the process. A handle is resolved per call.
> Nothing is ever owned by a run.**

The middle scope is the trap, and it is the one a web-framework analogy hides.
The chart names it and atom-forge's gate 16 enforces it:

| Scope | Lives for | What belongs to it |
| --- | --- | --- |
| Process | the process | the connector: the pool, the client, the loop |
| Run (thread) | one conversation, **possibly days** | thread id, run context values — data only |
| Superstep / call | one node execution or one tool call | the handle, the cursor, the transaction |

`human.approval` compiles to `interrupt()` and the checkpointer is durable on
purpose, so a run genuinely pauses until a person returns. A connection held
"for the run" is a connection held for however long that person takes. In a web
application request-scope and run-scope are the same thing, which is why the
FastAPI-lifespan analogy the chart started from is right about the first row
and silent about the second.

### What a handle is, and why it is not the connection

A module never receives a socket. It receives a **narrow façade that resolves
the live resource when called**, which is `McpSessionProxy`'s shape and its
recorded reason: handing the adapters a raw session would capture it inside
every bound tool, so one dead socket poisons an agent for the rest of the run
with no way back. Generalised:

- a handle exposes the two or three verbs the consumer actually uses, never the
  vendor client;
- it opens lazily and reconnects **once** on a transport failure, never on a
  protocol failure — a call that failed because its arguments were wrong will
  fail again, and a silent second attempt turns one wrong answer into two;
- it is never stored on `self` as a value. Ticket 04 already recorded the small
  version of this defect: one shared tool instance per type let two SQL nodes
  clobber each other's row cap, which is why `configure(data)` returns a fresh
  instance (`backend/openstategraph/abc/tool.py:319`).

### What happens on a checkpoint restore

**Nothing, and that is the design rather than a gap.** No part of a connector
is checkpointed, because no part of it is serialisable, and portability
guardrail 1 forbids a host-language object in a document in any case. What
survives a restore is entirely data:

- the **name** the module declared (`"databricks"`);
- the **variable names** the connector reads its credential and endpoint from.

On resume, in a process that has the connector registered, the handle resolves
and re-opens. In a process that does not, the module fails at bind, naming both
(§4). A restore therefore has exactly two outcomes and neither is a `None`
that behaves like a working connection.

### Two consequences a connector author does not get to opt out of

**No transaction may span a call.** The library's rule is that side effects
called before `interrupt` re-run, because interrupts work by re-running the
node they were called from (`/oss/python/langgraph/interrupts`, "Side effects
called before `interrupt` must be idempotent"). A transaction opened in one
superstep and committed in another is a transaction that a resume replays half
of. A transaction lives inside one `_execute` or it does not exist.

**A connector that can change something declares it.** `acts_outside_the_run`
(`backend/openstategraph/compile/side_effects.py:42`) already asks this of
tools and defaults to the conservative answer. A read-only warehouse handle is
free of it; a handle that can run DML is not, and gate 14 is the interview half.

---

## 3. The recommended shape, in one page

```python
# openstategraph/connectors.py — the seam. No implementations live here.

@dataclass(frozen=True)
class ConnectorSpec:
    """One external resource, as much as the framework needs to know."""
    name: str                              # "databricks" — a bare identifier
    env_vars: tuple[str, ...] = ()         # any one of these makes it usable
    endpoint_env: tuple[str, ...] = ()     # most significant first
    default_endpoint: str = ""
    extra: str = ""                        # the pip extra supplying the client
    label: str = ""
    open: Callable[[], Any] = ...          # returns a handle; called lazily

class ConnectorCatalogue:
    def register(self, spec: ConnectorSpec) -> "ConnectorCatalogue": ...
    def get(self, name: str) -> ConnectorSpec | None: ...
    def list(self) -> tuple[ConnectorSpec, ...]: ...
    def handle(self, name: str) -> Any: ...          # pooled, per identity
    def credential_names(self) -> frozenset[str]: ...
    def close_all(self) -> None: ...                 # atexit, and tests
```

```python
# a package's tools/warehouse.py — the consumer

class RevenueByRegion(BaseTool):
    node_type = "acme-reports/tools.RevenueByRegion"
    requires: ClassVar[tuple[str, ...]] = ("databricks",)

    def _execute(self, args: Args) -> ToolResult:
        rows = self.resources["databricks"].query(SQL, args.region)
        return ToolResult(content=render(rows))
```

Four claims, each of which is a decision:

1. **`ConnectorSpec` mirrors `ProviderSpec`'s credential vocabulary exactly**
   — same field names, same "any one of `env_vars` is enough", same
   tuple-order endpoint precedence. That is not tidiness: it is `CLAUDE.md`'s
   Ollama correction generalised, and re-spelling it would give this
   repository two shapes for *name the variable somebody can set, see and
   revoke*.
2. **`open` is a callable on the spec, not a method on a base class.** A
   connector needs behaviour, which is what `ProviderSpec`'s docstring
   excluded, so the behaviour is one field rather than a ladder. There is no
   `AbstractConnector` in this proposal and §9 says what would create one.
3. **`requires` is a `ClassVar` on the module**, resolved at bind, so
   `_execute(self, args)` is byte-identical for every atom that declares
   nothing — Liskov, which ticket 01 names as the acceptance test.
4. **`self.resources` is a mapping, not a member per connector.** One narrow
   collaborator on the bound instance, keyed by the names the module itself
   declared. This is ticket 04's *directory, not a container* applied at the
   smallest possible width: an installation with nine connectors adds nine
   dictionary keys and no public members anywhere.

---

## 4. Declaration and injection

### Where the handle is attached

`configure(data)` already exists, already returns a **fresh instance** rather
than mutating, and is already the one place a tool is bound to one node
(`abc/tool.py:319`). That is the seam. The base resolves `requires` against
the catalogue during `configure`, sets `resources` on the copy, and returns it.

Three properties fall out for free, and each of them is a rule this repository
already holds:

- **The model never sees a handle.** `Args` is the schema `as_langchain_tool`
  hands the model (`abc/tool.py:378`); `resources` is not in it and cannot be.
  The library hides `runtime` from the tool schema for the same reason.
- **Two nodes of one tool type cannot clobber each other**, because each holds
  its own configured copy.
- **Nothing new raises.** A connector failure is `ToolResult.failure` — errors
  are data, and `asyncio.CancelledError` is a `BaseException` so a stopped run
  still unwinds through a handler that catches `Exception` (`abc/tool.py:357`).

### Where it fails, and why there are two answers rather than one

**At import, for the shape.** `BaseTool.__init_subclass__` (`abc/tool.py:252`)
already refuses a wrong subclass shape loudly at class creation. A `requires`
that is not a tuple of bare identifiers is refused there.

**At bind, for the availability.** A module *cannot* know at import whether
this installation has registered anything, because entry-point discovery is
deliberately not done at module scope — `openstategraph/extensions.py` says so
and gives the reason: `import openstategraph` is on every adopter's critical
path. So a declared name that resolves to nothing is caught when the registry
is built, and it lands on the sink that already exists:
`build_tool_registry(..., warnings=...)`
(`backend/openstategraph/api/registries.py:161`) carries it to
`NodeRuntime.capability_warnings`, `CompiledWorkflow.warnings`, the run
response and the CLI. The sentence names **both** the module and the
connector, and the module is not bound — so the node reports an unresolved
capability rather than running against a `None`.

The map's production-ready bar is *"a component that asks for something this
run will not provide fails at import, naming the component"*. This is that bar
met at the only place it can honestly be met, and the split is stated rather
than blurred: **shape is a property of the code and fails at import;
availability is a property of the installation and fails at bind.**

### What a connector may *see* — and what settles it

Nothing. A connector receives no state, no store, no messages and no run
context. It is constructed from environment variables and returns a handle.

That is not modesty, it is ticket 01's question answered in the direction that
costs nothing later: a connector that could read state would have to be
resolved per superstep, which would put it back inside the run scope §2 spends
its length excluding. **A connector is the one thing in this platform that is
entitled to see less than a function.**

The consumer is where entitlement lives, and the consumer is already served:
`run_context()` (`compile/run_context.py:718`) hands a tool this run's declared
values as a plain dict, so a tool that needs a per-run tenant reads it there
and passes it to the handle as an argument. Handle in, tenant as a parameter —
never a per-run connector.

---

## 5. Registration — which layer owns it, and why the editor does not

**The backend owns it, in `openstategraph/connectors.py`, with a fourth
entry-point group `openstategraph.connectors` in `extensions.py`.**

`CLAUDE.md`'s rule is that a registry is owned by *its own layer*, not by a
common address: four hang off the `Workbench` because they are model-level,
canvas features hang off `PaperController` because a `IPaperFeature` is
JointJS, card bodies live in `view/` because they are React. A connector is
Python, opens sockets, and reads process environment variables. There is no
TypeScript half of it at all, and that is worth stating positively rather than
as an omission: **the editor never learns that a connector exists**, because
nothing about one is placeable, drawable, or present in a document (§6).

The behaviour contract is the one `CLAUDE.md` fixes and `Registry<T>` spells
(`src/core/kernel/Registry.ts:35` throws on a duplicate id; `upsert` is how you
say you meant it; `list()` enumerates; a fresh one is constructible). The
Python precedent is `ProviderCatalogue` (`providers.py:538`), and this design
**deviates from it on one point deliberately**: `ProviderCatalogue.register`
silently replaces, because a plugin overriding a bundled provider is what
installing a plugin is *for*. A connector has no bundled set to override, so
the first registration of a name wins and a second is refused by name. Layering
is therefore two rows, not three: built-in (none) < installed distribution.

### The dispatch census

`backend/tests/test_a_dispatch_table_does_not_hold_its_targets.py` counts the
distinct implementations a module registers into its own registry, ceiling
zero. `connectors.py` must score zero: no `DatabricksConnector` class in it, no
`_open_databricks` beside the catalogue. A bundled connector, if one is ever
bundled, lives in its own module and hands over a spec — which is what
`builtin_specs()` does for providers, returning data.

The `open` callable on the spec is what makes that possible and is the reason
it is a field rather than a method: a registry whose entries carry their own
constructor has nothing to dispatch on.

### And it does not widen `NodeCapabilities`

`abc/node_family.py:62` publishes three named fields to plugins with an
explicit *"the presumption is against a fourth"*, and the reason is recorded:
the field it replaced was `services: Any` carrying thirteen compiler internals
through one name nothing diffed. A fourth field `resources: Mapping[str, Any]`
is the argued exception this design asks for, and the argument is that it is
**the same three-word test the other three pass** — it is what building a step
legitimately needs, it is a façade over nothing wider than itself, and it is
one named field rather than a widening nobody sees. If that argument is not
accepted, the alternative is a module-level accessor beside `run_context()`,
and it is strictly worse: ambient reach with no declaration, which is the
`get_store()` pattern the chart's own table marks as reachable-but-undiscoverable.

---

## 6. Portability — a connector is not a fifth channel

`CLAUDE.md`'s four-channel table is about **node type ids**: what a document may
name, and where the implementation behind that name lives. The table's settled
test is two properties — the id is **data**, and it is **resolved against a
known set and named when it resolves to nothing**.

A connector is not a fifth row of that table because **it does not appear in a
document at all**. A `workflow.json` written against this design contains no
connector name, no endpoint, no variable name and no credential. The
declaration is Python-side: the tool that needs a warehouse is the thing that
knows it needs one.

That is a decision with a cost and the cost is stated: **you cannot re-point a
workflow at a different warehouse from the canvas.** You re-point the
connector's environment variable, which is where an operator's controls belong,
and the document is unchanged — which is also what makes the same document run
against a staging warehouse and a production one with no diff between them.

The alternative — a `"connector": "databricks"` field on a node's card — was
considered and rejected for the shape `say-it-on-the-surface/03` records: a
required field asking for a machine name nobody introduced. It remains
reachable later if a genuine need appears, and it would be safe, because the
string would be data resolved against `ConnectorCatalogue.list()` and named
when it resolved to nothing. Adding it is additive; removing it would not be.

The three other guardrails: expressions stay a JSON AST because nothing new is
expressed; reducers stay a named enum because a connector writes no state
(§8); the compile seam stays one-directional because nothing reads a handle
back into the model.

---

## 7. The tier question — settled: **outside the tier system**

`the-atom-has-no-context/06` left this open and recorded a position to argue
with. This document adopts it, with the argument stated so it can fail.

> **Infrastructure is outside the tier system, and the two ladders get two
> names: the *canvas tier* (atom / molecule / organism, declared in
> `src/nodes/vocabulary.ts`) and the *code ladder* (the rungs under
> `backend/openstategraph/abc/`).**

The argument is not "a pool is not composed by a user", which is true and
insufficient — plenty of things a user does not compose still need a word. It
is that **the canvas tier is a rendered value**. `vocabulary.ts` is read by the
palette to group cards; a fourth tier would be a value with no cards in it,
forever, by construction. A vocabulary row that can never be rendered is a row
that will be deleted by the next person who tidies, or worse, filled.

So there is **no `CLAUDE.md` lexicon row for a fourth tier**, and no edit to
`vocabulary.ts`. What there is instead is the second ladder acquiring a name,
because that is the half of ticket 06's defect 1 that was real: one word
covering two taxonomies is how a connector came to be scored against the canvas
card in the first place.

**"Outside" must not mean "invisible"** — that is the clause that keeps this
honest, and it is what §5's `list()` and §3's `resources` mapping are for. The
palette is the discovery surface for canvas modules; `ConnectorCatalogue.list()`
and the module's own `requires` declaration are the discovery surface for
infrastructure. A developer asking *what can I reach from here* gets an answer
from an enumeration rather than from a codebase search, which is the goal the
whole map was chartered on.

---

## 8. Worked example one — Databricks

### Credentials, and the standing rule

`DATABRICKS_HOST` and `DATABRICKS_TOKEN` for a personal access token;
`DATABRICKS_CLIENT_ID` / `DATABRICKS_CLIENT_SECRET` for a service principal;
`DATABRICKS_HTTP_PATH` selecting the SQL warehouse. Declared as
`env_vars=("DATABRICKS_TOKEN", "DATABRICKS_CLIENT_ID")`,
`endpoint_env=("DATABRICKS_HOST",)`, `default_endpoint=""` — empty, because
there is no address that is right for everybody and declaring one would be a
guess presented as a default.

**Who can revoke them**: a workspace token is revocable by whoever issued it,
in the account console, without touching this machine. That sentence is the
whole test. `CLAUDE.md`'s Ollama correction records what it costs when it is
skipped — a spec that declared `env_vars=()` and presented itself as keyless
while the client reached the vendor through a local daemon signing with an
on-disk key that *"never passes through the environment and cannot be seen,
moved or revoked from one"*.

Databricks has exactly that failure available, and the shape is the one to
design against whether or not it is the default: a vendor SDK that falls
through to a config file in the home directory or to cloud instance metadata
will work on the author's machine and be unrevocable everywhere. *(Which
fall-throughs this vendor's client performs in which order was **not** checked
against an installation here — there is no Databricks client in this tree and
no endpoint to measure. The build ticket must establish it before the connector
is written, not after.)* **This connector must
therefore construct its client from values it read by name, and refuse to fall
through to ambient discovery** — or, if it cannot refuse, declare on
`readiness` that it is reaching the vendor through something nobody named. Gate
12, and the interview's third redirect: *"it works without one on my machine"*
is an ambient daemon or a cached login.

**No value ever enters a document.** `SECRET_VALUE_PREFIXES`
(`backend/openstategraph/config_file.py:128`) already refuses a pasted
credential into the committed config file, and it is a maintained literal list
that will always be incomplete and is the right answer anyway.

### The session

One pool per process, keyed by connection identity, using
`mcp_sessions.pool_key`'s rule verbatim (`:336`): **names, never values**. The
key is host plus HTTP path plus the *name of the variable the credential was
read from* — never the credential, and never a digest of it, because a digest
is still a stable identifier for a secret in every repr, log line and traceback
a key appears in. Two tools reading `DATABRICKS_TOKEN` and
`DATABRICKS_ANALYST_TOKEN` against one host are two rows, and the second does
not run on the first one's account.

A rotation adopts the new value into the live entry rather than opening a
second one — `session_proxy`'s `adopt` (`:374`), for the same reason.

### Rows crossing into graph state

A query result is data entering the run, which puts two existing rules in play:

- **The reducer rule.** If a row set lands on a state key more than one node
  type can write, it needs `Annotated[T, reducer]` from the named enum. Found
  live: a router plus `Send` fan-out plus multiple tool-using workers scheduled
  two `answer`-writing nodes in one superstep and LangGraph raised
  `InvalidUpdateError` on a field every single-writer test had passed. In this
  design a connector writes nothing, so the rule binds the *tool*, not the
  connector — which is why §4 leaves ticket 03 untouched and does not need it.
- **The grounding guard.** `every-workflow-green/44` is the diagnostic already
  in force: an Output reachable from a step holding a capability that *answers
  from outside this run's own data*, with no check between them, is reported at
  load time with no model and no run.

**A warehouse connector is on the grounded side, and the reason is precise.**
`answers_from_outside_the_run` (`backend/openstategraph/compile/grounding.py:29`)
asks whether a tool's results are **open-world text rather than records**. Rows
from a warehouse are records: falsifiable, re-queryable, and traceable to a
table. The rule the guard defends — *a model may supply a word, it may never
supply a number* — is satisfied because the numbers came from the warehouse and
not from the model.

**Two things would put it on the wrong side, and an author has to choose
against both:**

1. **A natural-language endpoint.** A warehouse assistant API that takes a
   question and answers in prose is open-world text wearing a warehouse's name.
   Its numbers are indistinguishable from retrieved ones and nothing downstream
   can tell them apart. Such a capability declares
   `answers_from_outside_the_run = True` and belongs behind a `guard.check`.
2. **Write access.** A handle that can run DML is `acts_outside_the_run`, and
   `retry_policy` is graph-wide, so the platform will re-run the node by
   design. Undeclared, a retry duplicates a write.

---

## 9. Worked example two — Hermes Agent, and the question left standing

`docs/decisions/hermes-agent.md` (`255aca0`) closes by saying the framework
reading becomes live when this repository has an authoring path for
infrastructure, and asks for **an argument for why a self-hosted agent
service's scheduler, memory store and gateway belong inside a graph that
already has a checkpointer**. This section answers it. The answer is that they
do not, and here is what to do instead.

### What talking to it costs, stated honestly

Established in `hermes-agent.md` from primary sources and not re-derived here:
Hermes Agent is a self-hosted service with per-agent profiles on disk, a SQLite
memory store, a messaging gateway process, a cron scheduler and subagent
spawning; it is model-agnostic; its published surfaces are an installer, a CLI
and a gateway; **there is no documented Python import surface and no documented
one-shot prompt-in / answer-out invocation**, the nearest thing being scripts
calling its tools over RPC.

So, concretely:

| | |
| --- | --- |
| **Transport** | HTTP to a gateway process. Not an import, not a subprocess |
| **Who runs it** | the operator, on their own machine, as a peer service. Never us, and never a process this compiler spawns |
| **What a node would send** | a task and a profile name |
| **What it receives** | whatever the gateway returns when that agent has finished, at a time it chooses |
| **How a failure surfaces** | `ToolResult.failure` — errors are data, so a refusal, a timeout or an auth failure hands text back to the calling agent rather than aborting the node |
| **Cancellation** | our side unwinds: `asyncio.CancelledError` is a `BaseException`, so an `async def` body is cancelled and a handler catching `Exception` does not swallow it (`abc/tool.py:357`). **The remote agent does not stop.** A connector that cannot send a cancel must say so, and this one has no documented cancel |
| **`interrupt()`** | **there is none, and there cannot be.** `interrupt()` pauses *our* graph at a node boundary. A remote agent mid-turn is not at one of our boundaries and holds no checkpoint we can resume from. Any human gate has to be on our side of the call, before it |

That last row is the one that decides the rest.

### Which side is authoritative — four answers, and three of them are ours

| Capability | Hermes brings | We already have | Authoritative |
| --- | --- | --- | --- |
| Scheduler (cron) | its own | the graph's superstep clock, `step_budget.py`, and `retry_policy`/`timeout` as graph-assembly parameters | **neither, and that is the point** — see below |
| Memory store | SQLite on its own disk | the checkpointer (short-term) and the Store (long-term), bound once at `compile()` | **ours** |
| Subagent spawning | its own | `Send` fan-out, mounts, and deepagents' subagents | **ours** |
| Gateway | a messaging front door | our own run doors — HTTP, CLI, library, MCP | **ours** |

The three marked *ours* are not close calls. A second memory store is an answer
that depends on which store was written last, with no key and no reducer. A
subagent spawned inside Hermes is invisible to `mermaid(xray=True)`, to the
timeline, to the token accounting in `messages.py`, and — the one that matters
— to the `injection-screening` middleware slot, which `AbstractAgentNode`'s own
comment marks as *"the one hard constraint in this list"*. A second gateway is a
second front door onto the same conversation with none of `principal.py`'s
identity rules on it.

**The scheduler is the interesting one, because neither side can own it.** A
cron inside a node fires on wall-clock time that the graph cannot see, cannot
checkpoint against, and cannot cancel; a superstep has no way to represent "and
then, tomorrow". The graph cannot own it either — it has no clock beyond the
run. What that says is not *"pick one"* but **that a scheduler is a property of
a process, and a process that owns a schedule is a peer, not a step.**

### The verdict

> **The composition is wrong. Hermes Agent is a peer of this product, not a
> component of it, and a connector does not make it one.**

A node that drove Hermes and used *none* of its scheduler, memory store,
subagent spawning or gateway would be a request/response call to a model
wrapped in someone else's loop — which is `hermes-agent.md`'s Option B with an
extra network hop, rejected there for reasons this design does not weaken: no
middleware slot table, no token stream, and none of the message shapes
`tool_report`, `text_or_ask_again` and the audience fold all read.

And a node that *did* use them would be running a second scheduler, a second
memory and a second subagent tree inside one superstep of a graph that owns
all three — which is not composition, it is two runtimes sharing a stack frame.

**What a connector legitimately buys, and it is not nothing.** The narrow case
is Hermes as a **remote tool provider**: reach its tools over RPC, expose them
as `tool.*` capabilities on the canvas, and let *our* agent do the looping. That
is a connector in exactly this document's sense — an endpoint, a credential, a
pooled session — and it is the shape `tool.mcp` already has. So the practical
recommendation is one sentence: **if Hermes speaks MCP, this repository already
has the connector and the answer is a `tool.mcp` row; if it does not, a Hermes
connector is worth building only for its tools, never for its agent.**

### What would have to become true to reconsider

- **Hermes publishes an embeddable, one-shot invocation** — an import surface,
  or a documented stateless HTTP call that runs no scheduler and writes no
  memory. Then it is a model-shaped thing, and `hermes-agent.md`'s provider
  route already handles it.
- **This platform grows a place for a peer process.** A scheduler that outlives
  a run is a real product idea and it is not a node; if it ever exists here it
  is a deployment concept beside the checkpointer, and Hermes would be a
  candidate implementation of it rather than a node type.

---

## 10. Security and the blast radius

A connector holds credentials and opens sockets, which is more entitlement than
anything else in this tree has. The four questions the chart asks, with the
settled answers where they exist:

**What may it see (01)?** Nothing. §4: no state, no store, no messages, no run
context. Its whole input is a set of environment variables it named. This is
the strictest possible answer and it is available only because the consumer —
the tool — is where entitlement was already being decided.

**May it write state (03)?** No, and this design does not need 03 answered. A
connector returns a handle; the tool returns `ToolResult`; the node decides
what that means. `ToolResult` stays the single output shape and the reducer
surface does not grow.

**Is it safe to run twice (10)?** The connector, yes — `handle()` is idempotent
and returns the pooled entry. The **call** is the tool's declaration, not the
connector's, and gate 14 asks it: `retry_policy` is graph-wide and a resumed
`interrupt()` re-enters, so the answer is never *"it won't run twice"*.

**Does user content leave the machine (11)?** For a warehouse: the query text
does, which is content the model composed from the user's question. That is
gate 15's third case — a vendor the **author** chose — and it surfaces on the
node's own description where a person placing the card will read it, not in a
policy page. The ticket's sharpest line applies unchanged: a downstream
guardrail redacts, and **cannot unsend**.

**One more, which is this design's own and belongs beside them:** a connector's
credential must never be settable by a request. `apply_credentials`
(`backend/openstategraph/api/model_resolution.py:218`) records what that costs
— on a server with no key configured, the first request to arrive fills the
process environment and *becomes the configuration*, so every later run
authenticates as that browser until restart. `ProviderCatalogue.credential_names()`
is the allow-list that bounds it. **A connector's variables do not join that
allow-list.** A warehouse is deployment configuration, and the editor has no
business supplying one.

---

## 11. What the *n*th connector costs

This is the maintainability claim, and it is the reason to build the seam
rather than the connector.

**Today, with no seam**, a second connector costs what the first one cost: a
module with its own pool, its own lock, its own key convention, its own
`atexit`, its own reconnect policy and its own answer to *is it safe to run
twice* — the `mcp_sessions.py` shape, re-derived. Five of those is five places
a rotation has to be handled correctly and five chances to put a token in a
dict key.

**With the seam**, the second and the fifth cost the same thing:

| | |
| --- | --- |
| a module in the author's own distribution | theirs, not ours |
| one `[project.entry-points."openstategraph.connectors"]` stanza | four lines |
| a `ConnectorSpec` naming its variables | data |
| an `open` callable returning a handle | the only real work |
| a row in the docs | one line |

And what it must **not** cost, stated so a future ticket can be refused: no
edit to `core/`, no new node type, no new field on `workflow.json`, no
`NodeCapabilities` field per connector, no branch in the compiler, no case in
`agent_node_for_tier`, no entry in `vocabulary.ts`. That asymmetry — constant
against the linear-with-multipliers cost `hermes-agent.md` prices for a new
agent tier — is the recommendation.

---

## 12. What this settles, and what it does not

| Ticket | Outcome |
| --- | --- |
| **06** — the tier decision | **Settled.** Outside the tier system; two ladders named; no `vocabulary.ts` edit; the discovery surface is the catalogue's enumeration and the module's own declaration |
| **05** — who may add to the context | **Settled in the deciding half.** Registration is an entry-point group with a catalogue; typing is candidate 2, a resolve-by-name handle, over candidate 1 (the library generic, which carries JSON scalars and cannot carry a socket) and candidate 3 (a generated stub, rejected on `typescript-runtime-types.md`'s argument, which transfers: a generator is a build step and a second source of truth for a set that changes with `pip install`). **Partially**, because the ticket's *done when* requires a third party to actually be able to do it, and nothing is built |
| **01** — what a module is entitled to see | **Untouched, deliberately.** This document answers it for the connector handle only, and the connector's answer is *nothing*. State and store reads are still the open question, and the seam here does not pre-empt them: a `resources` mapping and a `state` handle are independent |
| **02** — one contract or two | **Not settled**, and one datum for whoever takes it: a connector is installation-wide only, because a package's `tools/` travels with the package and a connection pool cannot. That is evidence about entitlement, not a resolution |
| **03** — may a module write state | **Not settled, and not needed.** A connector writes nothing |

---

## 13. What would have to become true for the rejected shapes

Recorded so each rejection can be overturned by evidence rather than by
re-argument.

**A connector as a node on the canvas** becomes right when a connection needs
*per-node* configuration a user must see and vary. It does not today: a
warehouse address is deployment configuration and a per-node one would be five
cards that can disagree about which warehouse the workflow talks to. If the
need appears, the honest shape is a **field on the tool's card**, not a node —
a node with no compile target is the refusal atom-forge's dimension 8 already
makes.

**A connector carried in run context** — `context.db_connection`, which is
literally the library's own documented example (`/oss/python/concepts/context`,
which lists database connections as static runtime context, and passes a
connection *string*) — becomes right when a genuine per-run credential exists,
such as a per-tenant warehouse token. Rejected today for three reasons and the
third is the decisive one: our descriptors carry three scalar types and no
object by design (`runtime-context.md`), so a socket cannot ride there anyway; a
handle in a prompt-visible field is a leak the `"prompt": true` opt-in exists to
prevent; and a connection supplied by the *caller* rather than the operator is
`apply_credentials`' recorded defect with a different noun. On the day it lands,
the shape is that **run context carries a key that selects among registered
connectors** — data, resolved against a known set — and never the connection.

**A `Base` / `Abstract` connector ladder** becomes right when two connectors
share behaviour that is genuinely theirs. Today they would share a pool, a key
convention and a reconnect policy — which are the *catalogue's* job, not a
superclass's, and `CLAUDE.md`'s boundary rule is explicit that a concern needed
by two different families is a collaborator rather than a superclass. A ladder
whose only shared member is `open()` is a ladder that exists to have a ladder.

**A single wide `ctx` handed to every module** stays rejected on ticket 04's own
fork. The `resources` mapping is deliberately the narrowest thing that answers
the driver: a developer types `requires` and reads an enumeration, rather than
receiving eighteen members they did not ask for.
