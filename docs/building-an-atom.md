# Building an atom

An **atom** is a tool node: one capability, one card, one thing an agent can
call. The palette says so out loud — every section heading carries its
atomic-design tier, declared once in
[`src/nodes/vocabulary.ts`](../src/nodes/vocabulary.ts) and locked by
`vocabulary.test.ts`:

| Section | Holds |
| --- | --- |
| `Inputs · atoms` | `input.text`, `input.skill`, `input.markdown` |
| `Tools · atoms` | every tool node — the built-ins, the platform family, and anything a workflow or a plugin adds |
| `Output · atoms` | `output.formatted` |
| `Reasoning & control · molecules` | `agent.llm`, `route.classifier`, `route.grader`, `guard.check`, `guard.policy`, `human.approval`, `orchestrate.supervisor`, `orchestrate.worker`, `function.format_report` |
| `Memory · molecules` | `memory.segment` — its own section on purpose: a segment decides what is *remembered*, not what happens next, so filing it under `Reasoning & control` would have made that heading false |

A check decided by **code** — a schema conformance rule, a lookup against a
known set, anything with a deterministic pass/fail — belongs on
`guard.check`. `route.grader` is for a verdict a **model** must reach by
judgement; routing a deterministic check through it means a model relays
(and can leak) internal detail meant to stay internal, which is exactly how
this project's own SQL validator ended up surfacing internal check names in
a user-facing answer before that was fixed.
| `Composition · organisms` | `workflow.subgraph` — the only organism *node type* (schema v3 collapsed `team.workflow` into it). The section also carries the shipped **assemblies**, which are drag-out arrangements of several nodes rather than a type: the revision loop and the starter flow |
| `Annotate · no tier` | `group`, `note` — canvas furniture, deliberately tier-less |

Atoms sort first, then molecules, then organisms, with the tier-less `Annotate`
section after all of them; the test asserts that ordering, so the palette
cannot drift from the vocabulary. **This page is about adding to the
first row: a tool.**

> An agent can run this process end to end via
> [`skills/atom-forge`](../skills/atom-forge/SKILL.md) — the interview that
> settles what the atom *is* before this page's pipeline builds it.

An atom has two halves that meet at a single seam:

| Half | Lives in | Owns |
| --- | --- | --- |
| **TypeScript** | `src/nodes/tools/` or a workflow's own node module | the card: fields, ports, palette entry, and a browser-preview executor |
| **Python** | `backend/openstategraph/` or `workflows/<slug>/tools/` | the implementation the compiled graph actually runs |

The seam is `node_type`: the Python tool declares which canvas node it answers
to, and the runtime registry keys off that one declaration. Nothing is
hand-mirrored across the boundary.

---

## Part 1 — anatomy of a node definition

Everything the app needs to know about a node *type* is one
`INodeDefinition`. The palette, canvas, inspector, serializer and execution
engine all read from it, so none of them needs a branch per node type.
Registering one is the entire cost of adding a node.

### Fields drive card, inspector, defaults and validation

Declare configuration **once** as a field schema. Nothing else re-states it.

```ts
fields: [
  {
    kind: 'slider',
    key: 'maxRows',
    label: 'Max rows',
    min: 10,
    max: 1000,
    step: 10,
    defaultValue: 100,
    format: (value) => `${value}`,
  },
],
```

*(from [`ChinookDatabaseNode.ts`](../src/nodes/tools/ChinookDatabaseNode.ts))*

Available kinds: `text`, `textarea`, `select`, `combobox`, `slider`, `toggle`,
`file`, `readonly`, `repeatable-group` — the union in
[`src/core/model/contracts/fields.ts`](../src/core/model/contracts/fields.ts)
is the list, and it is the one to check rather than this sentence. Three flags
shape where a field appears rather
than what it holds:

- `onCard: false` — inspector only. Use it when the card is already showing
  something more useful than a control.
- `group: 'Prompt'` — an inspector section.
- `advanced: true` — folded away until asked for.

A field can carry its own `validate`, and the schema supplies the defaults a
new instance is created with. That is the DRY rule in its most load-bearing
form: *node configuration is declared once as a field schema; card, inspector,
defaults and validation all derive from it.*

#### A key your Python factory reads must be a key some field declares

The field schema is the **only** way a value gets into a node's `data`. So a
factory in `node_runtime.py` that reads `data["x"]` when no field is keyed `x`
is reading a value nothing can ever write — and it does not fail, it reads `""`
forever. That defect shipped three times: the model picker (declared on
`agent.llm` only, read for six types), the Worker's rules mode (read nowhere,
so `replace` was hardcoded), and the supervisor's rules (read from
`"instruction"`, which is that node's input **port** id — a port id is not a
data key).

`backend/tests/test_data_key_contract.py` now makes the fourth instance
impossible: `port_specs.json` carries each node type's `field_keys`, and the
test extracts the literal keys every factory reads — following `_text(data,
"k")`, `data.get("k")` and any helper handed the data dict — and fails on any
key no field declares. Two consequences when you write a factory:

- **keep the key a string literal, or a module constant**, at the point of use.
  A key assembled at run time fails the contract's own honesty check, because
  an extractor that shrugs at what it cannot parse stops guarding anything.
- **a port id and a field key are different namespaces.** They may not be given
  the same name on one node: it reads as one thing and behaves as two.

The reverse direction is deliberately not asserted — a declared field the
factory ignores is often correct, since `maxRetries`, `timeoutSeconds` and
`cacheTtlSeconds` are read by the compiler's graph assembly and a worker's
`role` is read by the *supervisor's* factory. Those three are injected onto
every standard node type by `defineNode` and are not any atom's to declare or
to mirror — `EXECUTION_OVERRIDE_KEYS` is the one list, exported so a field
contract subtracts it rather than retyping it.

### Ports carry types and cardinality

A port descriptor declares its `direction`, its `type`, and — when it differs
from the default — its capacity:

```ts
{
  id: 'tools',
  direction: 'in',
  type: PORT.tool,
  label: 'agent tools',
  side: BINDING_SIDE.consumer, // 'bottom' — the constant, never the literal
  appearance: 'pill',
  // Unlimited. `null`, not `Infinity`, so the descriptor survives JSON.
  maxConnections: null,
  description: 'Tools the agent may call.',
}
```

*(from [`AgentNode.ts`](../src/nodes/agent/AgentNode.ts))*

**Cardinality belongs to the port, not the node.** There is no node-level
"allows multiple edges" flag, because one node has ports of different
cardinality at the same time. Inputs default to 1, outputs to unlimited; see
[ports and edges](ports-and-edges.md) for the full reference.

A tool node's single output port is supplied for you by `defineToolNode` — you
never declare it.

### The executor, and honest refusal

An executor is registered against the node type id and returns a `Result`.
Tool nodes get theirs from `createToolExecutor(id, { describeTool, invokeTool })`:
`describeTool` produces the `ToolSpec` the model is shown, `invokeTool` does
the work.

The dataflow half is uniform — running a tool node just publishes its handle
so the link carries a callable up to the agent — which is why only those two
functions differ per tool.

Some atoms **cannot** run in the browser: their implementation only exists on
the backend. Say so, plainly:

```ts
invokeTool: () =>
  Promise.resolve(
    Err(
      `"${capability.name}" only runs on the backend — use Chat, not the canvas Run button, to call a discovered tool.`,
    ) as Result<string, string>,
  ),
```

*(from [`DiscoveredToolNode.ts`](../src/nodes/tools/DiscoveredToolNode.ts))*

This pattern matters more than it looks. A `standard` node with **no**
registered executor is *silently skipped* by the preview engine — the run
appears to succeed and quietly did less than you think. A refusal is a
registered executor that returns an error, so the preview tells the truth. Do
not fabricate a plausible result to keep the canvas green; the Router, Grader
and Orchestrator all refuse for the same reason (they compile to graph
constructs, not to steps).

---

## Part 2 — the Python half

The ladder is `ITool` (a `Protocol`) → `BaseTool` (ABC, usable default) →
your concrete tool. A concrete tool declares four things and implements one
method:

```python
class GetTableSchemaTool(BaseTool):
    """Columns, types, primary key and foreign keys for one table."""

    name = "chinook_get_table_schema"
    node_type = "tool.chinook-get-schema"
    description = (
        "Get the columns, types, primary key and foreign keys of one Chinook table. "
        "Use the foreign keys to work out how to join tables."
    )
    Args = GetTableSchemaArgs
```

*(from [`workflows/chinook-assistant/tools/chinook.py`](../workflows/chinook-assistant/tools/chinook.py))*

- `name` — what the model calls.
- `node_type` — the canvas node this tool answers to. Empty means "not
  placeable on a canvas", which is legitimate for a tool only ever handed to
  an agent programmatically.
- `description` — the model reads this to decide *whether* to call you. It is
  prompt engineering, not a docstring.
- `Args` — a Pydantic model, and **the single source of truth for the tool's
  arguments**. It is what the model sees, what validates a call, and what the
  MCP layer publishes. Do not restate it in TypeScript: the card declares the
  node's *configuration* fields, which is a different thing from the arguments
  the model passes at call time. If you find yourself writing the same shape
  twice in two languages, the design has gone wrong.

`BaseTool.run()` validates the arguments, calls your `_execute`, and converts
any raised exception into a result. That is declared once on the base, so no
concrete tool writes its own try/except.

> **The one method you implement is `_execute(self, args)` — never `run`.**
> `ITool` advertises `run(**kwargs)` because that is the shape *callers*
> depend on, and `BaseTool` already implements it for you. Overriding `run`
> leaves `_execute` abstract, which makes your class uninstantiable and
> therefore invisible to discovery — a tool that installs cleanly and is
> simply absent. Python now refuses that class at import with a message
> naming it and this fix, and discovery says the same thing in the run's
> warnings if it ever reaches that far.

### Errors are data

```python
def _execute(self, args: BaseModel) -> ToolResult:
    ...
    try:
        cursor = conn.execute(sql)
    except sqlite3.Error as exc:
        # Handed back for the agent to read and retry, not raised.
        return ToolResult.failure(f"SQL error: {exc}")
```

A model writing SQL will get it wrong, and the useful response is to hand the
error back so it can read and retry. Raising aborts the graph node instead of
letting the agent recover. `ToolResult.failure(message)` is the whole
mechanism.

**Two failures that share a sentence are one failure.**
[`prebuilt_youtube.py`](../backend/openstategraph/prebuilt_youtube.py) is the
worked example: seven conditions, seven distinguishable messages, and a test
(`test_every_failure_says_something_different`) whose only job is to fail if
anyone collapses two of them. The one that decides the design is a caption URL
answering **HTTP 200 with zero bytes** — measured on every URL the *web*
client issues. Reported as "no transcript", it makes an agent describe a video
it never read, from the title, with complete confidence. Reported as a failed
download, the agent retries or says what it does not know. Whenever your tool
can be *refused*, check whether your code can tell that apart from being
*answered with nothing*. `web_search` had the same defect through a different
door — DuckDuckGo's 202 challenge page parsed to zero results and was reported
as `No results for '…'` — and
[`prebuilt_web.py`](../backend/openstategraph/prebuilt_web.py) carries that
story in its module docstring.

### A bounded view of an unbounded result must say so in the text

A model consumes the **text**, not the integers beside it. So an atom that
renders only part of a result has to make the bound visible inside what it
renders — a sibling return value carrying the true count is not disclosure,
because nothing the model reads mentions it.

The worked example is `cpl-nl2sql`'s `execute_sql`
(`launch-readiness/129`). It rendered the first 50 rows and returned
`len(rows)` alongside, so **a complete result and a truncated one rendered
identically** and the reader could not tell which they had. A live run wrote
the exact right SQL — 121 rows over 68 distinct ports — and answered "29
ports", the number of distinct ports in the first 50 rows.

Two rules, and the second is the one with the correctness in it:

1. **Never render a truncation without a marker** — and mark the complete case
   too. A marker only carries information if its absence means something.
2. **A truncated page must not be usable as an aggregate.** "Showing 50 of 121"
   fixes disclosure and leaves the answer wrong: no honesty about a page of
   rows makes a total readable off it. Either the marker states what may not be
   concluded *and* carries the totals computed over the whole result, or the
   atom refuses to render the page and pushes the aggregate to where the data
   is. Silence is not an option, and neither is a plausible-looking page.

`OffloadMiddleware` (`launch-readiness/102`) is the shape to copy: an
over-threshold result is replaced by a **pointer saying where the rest is**,
never by a quietly shortened version of itself.

### Configuration reaches the tool through `configure`

A node's field values arrive via `configure(data)`, which returns **the
instance to use** — a fresh one when config matters, never a mutation:

```python
def configure(self, data):
    configured = data.get("maxRows")
    if isinstance(configured, (int, float)) and configured > 0:
        return type(self)(row_cap=int(configured))
    ...
    return self
```

Two nodes of the same tool type with different config in one document must not
clobber each other. The default `configure` ignores config entirely, which is
correct for a stateless tool.

### What a tool can reach — and the checker that says so

Four seams, and no fifth:

| What | How |
| --- | --- |
| its node's config | `configure(data)`, reading the keys its `node_fields` declare |
| the run — user, session, thread, workflow slug | `langgraph.config.get_config()["configurable"]`, as `prebuilt_session.SessionIdentityTool` does |
| the run context the workflow declares | `openstategraph.run_context()`, the values a caller supplied for `settings.context` |
| memory | `langgraph.config.get_store()`, as `memory.py` does |
| **graph state** | **not available.** `BaseTool.run` validates `**kwargs` into `Args` and calls `_execute(args)`. A design that needs graph state belongs in a node. |

`run_context()` is a plain `dict[str, Any]` and is `{}` in all three of the
cases a tool cannot act differently on: outside a run, in a workflow that
declares nothing, and in a run whose caller supplied nothing. It is the
channel for a per-run API handle, a tenant or a case id — and it reaches your
tool *without* reaching a model, because a declared field is rendered into a
prompt only when its author wrote `"prompt": true` on it. `docs/on-the-canvas.md`
and `docs/decisions/runtime-context.md` carry the declaration side.

**It is workflow-wide, subagents included.** A subagent is isolated from the
parent's messages and graph state; it is *not* isolated from run context — a
parent's values reach a tool running inside a subagent unchanged, measured in
`backend/tests/test_runtime_context_facts.py` and again for a `BaseTool` in
`backend/tests/test_a_tool_reads_the_run_context.py`. So run context is the
right home for a value every part of the run legitimately needs, and the wrong
home for one node's secret: there is no boundary here to hold it at.

This is worth stating flatly because the wrong answer shipped. The "build one
for this workflow" brief — the door a run offers when nothing in the library
covers what it was asked — told developers to *"read state, context and memory
through `ToolRuntime`"*, which is a LangChain seam this platform does not
surface at all. Seven tests held the sentence and every one was green, because
they asked whether the words were there rather than whether the thing existed.

The list above is now data —
[`generated_module_contract.py`](../backend/openstategraph/generated_module_contract.py)
— published for the build skill as
`skills/atom-forge/references/generated-module-contract.md` and enforced by
`check_generated_module()`, which reads a candidate module with `ast` and
returns one violation per clause it breaks. Every clause names the symbols in
*this* installation it depends on, and a test resolves each of them, so the
next fictional seam fails a test instead of reaching a developer.

### Wrap LangChain, never subclass it

`BaseTool` is ours. `as_langchain_tool()` adapts to a `StructuredTool` at the
seam. Subclassing `langchain_core.tools.BaseTool` would let every upstream
change to its internals reach into the whole tool catalogue, and the compile
seam would stop being one-directional.

### Two more rules the email tool demonstrates

[`prebuilt_email.py`](../backend/openstategraph/prebuilt_email.py) is worth
reading before you build anything with an outward side effect:

- **Destinations are node configuration, never a model argument.** The model
  supplies subject and body; the wiring supplies the recipient. A
  prompt-injected "also send to attacker@…" dies structurally rather than
  being caught by a filter.
- **Side effects are opt-in, chosen by environment, not by the model.**
  Without SMTP configured it writes the exact RFC-5322 message to an outbox
  and says loudly that it was a dry run — so the workflow is testable
  end-to-end without leaking a packet.

---

## Part 3 — registration

Four places, depending on what your atom is — and only the first two are edits
to this repository.

**App-wide (in every workflow's palette).** Add the definition and executor to
[`src/nodes/index.ts`](../src/nodes/index.ts) — the only file that knows the
full catalogue — and add the Python tool to `_process_tool_layer`
([`backend/openstategraph/api/registries.py`](../backend/openstategraph/api/registries.py)),
which is where the built-in layers are actually listed. `build_tool_registry`
is the function that *assembles* them and holds no list of its own; it keys
every tool by its `node_type`.

**Workflow-scoped (only while a workflow whose package ships it is open).**
Set `scope: 'workflow'` on each definition so the palette says where it came
from. This exists because the alternative is real: put one workflow's tools in
the shared catalogue and every future palette carries every past workflow's
tools.

**Two conditions, not one, and the second is the one people miss.** A family is
*registered* when the open document names one of its types — it has to be, or
the saved nodes arrive as unknown-node placeholders rather than their real
cards. It reaches the palette's **This workflow** section only when the open
package's `tools/` folder actually backs it, which is the discovery endpoint's
answer and not the document's (production-ready/80). So a document copied out
of its package, without the `tools/` beside it, keeps every node exactly as
saved and offers you none of them to place — which is the honest reading, since
the runtime would warn on any you added.

Concretely: your Python `BaseTool` must declare `node_type = '<your card's
id>'`, or the card and the capability never meet.

A family is one entry in `workflowScopedFamilies`, the `Registry<T>` in
[`workflowScoped.ts`](../src/nodes/workflowScoped.ts):

```ts
workflowScopedFamilies.register({ id: 'dice', nodes: DICE_NODES });
```

That is the whole registration. Both call sites — the pre-import one and the
keep-in-sync one — iterate the registry, so neither needs to know your family
exists. Chinook is registered on exactly the same line and has no other
privilege.

> Until 2026-08-13 this section told you to add your family to
> `syncWorkflowScopedNodes`, which had nothing to add it to: it named
> `CHINOOK_NODES` in its own body, as did `registerNodeTypesForRawDocument`.
> Following it literally was impossible, and following it approximately meant
> editing the second site too — miss that and your nodes were dropped on every
> load, per the warning below. The guide could not be written correctly because
> the seam was missing (ship-it ticket 03); the seam above is the fix, and this
> paragraph is left here because a guide that was wrong should say when it
> stopped being wrong.

> **Load order still matters, but the penalty changed.** This said
> `WorkflowSerializer.fromJSON` "silently skips nodes whose type is not
> registered yet". There is no `fromJSON` — the method is
> `WorkflowSerializer.load` — and skipping is exactly what it stopped doing:
> an unregistered type is now **preserved**, wrapped in an unknown-node
> definition whose ports are recovered from the edges, and reported as a
> warning (`UnknownNode.ts`: *load then save must never lose a byte*). So
> forgetting to register no longer destroys a document; it gives you a node
> you cannot edit in this build. Register workflow-scoped types from the raw
> document *before* it is imported anyway —
> `registerNodeTypesForRawDocument` does this, and every load path calls it.

**Discovered (no TypeScript at all).** Drop the tool in
`workflows/<slug>/tools/` and the backend finds it by importing the package and
collecting `BaseTool` subclasses — `inspect.getmembers`, no list to maintain.
Two conditions it does not announce: a file whose stem starts with `_` is
skipped, and the class must be constructible with **no arguments**. (A `TOOLS`
list is a different mechanism — it belongs to the *entry-point* path in
`extensions.py`, for a tool shipped as an installable distribution.)
`GET /api/workflows/{slug}/capabilities` is the wire contract, and the
frontend turns each capability into a connectable card generically. A
discovered tool cannot run in the canvas preview — see honest refusal, above.

**Published (your own distribution, no fork).** Ship the tool in a package of
your own and declare an entry point. Anyone who `pip install`s it has your
atom in every workflow they run — palette card included — with no edit to this
repository and no merge to carry forever.

Same-`node_type` collisions resolve workflow-wins, mirroring the frontend's
local-shadows-global registry rule.

### Publishing an atom as your own distribution

The exact stanza, in **your** `pyproject.toml`:

```toml
[project]
name = "openstategraph-acme"          # convention: openstategraph-<you>
dependencies = ["openstategraph>=0.3"]   # see the note below on pre-releases

[project.entry-points."openstategraph.tools"]
acme = "acme_osg_tools:TOOLS"          # a list of BaseTool subclasses
```

> **`>=0.3` does not match today's version.** The shipped version is
> `0.3.0rc1`, and pip excludes pre-releases from a plain `>=` specifier — so a
> plugin declaring that dependency resolves to nothing until a final `0.3.0`
> is published. Until then use `openstategraph>=0.3.0rc1` (naming a
> pre-release in the specifier turns pre-release matching on) or install both
> from a checkout. The line above is written as the shape it takes after the
> first release, for the same reason `adoption.md`'s headline install is.

The right-hand side may resolve to any of three things, because a plugin
author should not have to guess which one we take:

```python
# acme_osg_tools/__init__.py
from openstategraph.abc import BaseTool, NoArgs, ToolResult

class Ping(BaseTool):
    name = "acme_ping"
    description = "Answers with a pong."
    node_type = "tool.acme-ping"       # required: this IS the wiring identity
    Args = NoArgs                      # required: NOT `args_schema` — see below

    def _execute(self, args) -> ToolResult:
        return ToolResult(content="pong")

TOOLS = [Ping]        # a list — or `= Ping`, or `= Ping()`. All three work.
```

> **`Args`, never `args_schema`.** The class attribute is `Args`; `args_schema`
> is the name on the *other* side of the seam — the capabilities payload's
> field, and the keyword `as_langchain_tool()` passes to LangChain — so
> writing it in a tool body reads right and leaves `Args` undeclared. It has
> no default, and a tool without it can be neither described nor bound.
> Both discovery paths name such a class and the fix, and drop that one tool:
> a package's own `tools/` folder reports it in the capabilities `warnings`
> (before `production-ready` 87 it answered the whole endpoint with a 500),
> and an entry-point plugin's is skipped by the loader with the distribution
> named (before `production-ready` 93 it registered, appeared in the palette,
> validated clean, and then killed the run — along with every other tool
> wired to the same agent).

Three more groups exist, with the same rules:

```toml
[project.entry-points."openstategraph.knowledge_builders"]
acme = "acme_osg_knowledge:AcmeBuilder"   # an IKnowledgeBuilder concrete

[project.entry-points."openstategraph.providers"]
acme = "acme_osg_provider:SPEC"           # a ProviderSpec

[project.entry-points."openstategraph.node_families"]
sentiment = "acme_osg:SentimentFamily"    # a BaseNodeFamily concrete
```

The last of those is how you ship a **node family** — a new archetype on the
canvas rather than a new capability inside an existing one:

```python
from openstategraph.abc import BaseNodeFamily, NodeBuildContext

class SentimentFamily(BaseNodeFamily):
    node_type = "analyse.sentiment"

    def respond(self, text: str, context: NodeBuildContext) -> str:
        return "positive" if ":)" in text else "negative"
```

`context` is what your family may see of the compiler: this node's id and its
saved card (`context.data`), the compiled plan, the runtime's collaborators,
and two callables — `upstream_text(state)` for what the node before yours
produced, `resolve_model(data)` for this node's own model. Override `build`
instead of `respond` when one string in and one string out is not enough.

**A built-in family cannot be shadowed**, which is the one place the plugin
order below is reversed. A bundled *tool* is a capability and replacing it is
what installing a plugin is for; a built-in *family* is part of what a document
*means*, so `input.text` resolving to your code would change every workflow in
the venv, including the ones that never heard of your package. Claiming one is
reported against your distribution and ignored — as is claiming a `function.*`
or `workflow.*` type, which are the compiler's own.

Those four group names are **Tier 1**: they are covered by
[the stability contract](stability.md) exactly like `load_workflow` is, because
they live in *your* `pyproject.toml` and a rename would un-register your plugin
silently, in your users' installs.

**There is deliberately no `openstategraph.functions` group.** A `function.<x>`
node binds a callable by the name written in the *document*, and the document
belongs to the package; a distribution able to inject `function.format_report`
process-wide would change what a package's own node resolves to, with nowhere
in the document to name the provider or even see that one exists. A tool does
not have that problem — it carries a namespaced `node_type` that is visible in
the document. Functions stay package-local; if you want to publish one, publish
a tool.

**What you can count on when your plugin is installed:**

| | |
| --- | --- |
| **Order** | built-in < your plugin < the workflow's own `tools/`. You may replace a bundled default — that is what installing a plugin is *for* — but a package's own tool always wins over whatever is in the venv. |
| **Failure** | Your entry point loads in its own jail. If it raises, one WARNING naming **your distribution** is logged, the failure lands on `CompiledWorkflow.warnings`, and every other plugin still registers. One half-installed package never takes the registry down. |
| **Silence** | A tool with no `node_type` is reported, not dropped — there would be nothing for a document to bind. |
| **Opt-out** | `OPENSTATEGRAPH_DISABLE_PLUGINS=1` excludes every entry point, so a reproducible run never depends on a colleague's `pip install`. |
| **Cost** | Nothing is enumerated at import. Discovery happens when a tool registry is built. |

### What you must declare to get a card

Your tool is bindable the moment it installs — but a capability nobody can
*wire* is half a promise, and until register PK-06 that was the situation: the
runtime resolved `tool.acme-ping` and no palette anywhere showed it. It does
now, and here is exactly what the editor reads.

**The minimum is `node_type`.** Declare one and your tool appears in the
palette under **Always available** (app-scoped — it is installed in the
environment, so unlike a workflow's own `tools/` it does not disappear when
another workflow is opened). The card takes its label from `name`, its body
text from `description`, and its argument schema from `Args`. Nothing else is
required, and there is no TypeScript to write.

**Add controls with `node_fields`.** A tool that needs configuration declares
it on the class, and the value the user types reaches your tool through
`configure()` — the same mechanism the bundled email tool's recipient uses:

```python
from openstategraph.abc import BaseTool, NoArgs, ToolField, ToolResult

class Ping(BaseTool):
    name = "acme_ping"
    description = "Answers with a pong."
    node_type = "tool.acme-ping"
    Args = NoArgs
    node_fields = (
        ToolField(
            key="endpoint",                       # where the value lands in node data
            label="Endpoint",
            kind="text",                          # text | textarea | select | toggle
            default_value="",
            placeholder="https://acme.example/ping",
            hint="Where the ping goes.",
        ),
    )

    def __init__(self, endpoint: str = "") -> None:
        self.endpoint = endpoint

    def configure(self, data: dict) -> "Ping":
        # A FRESH instance, never a mutation: two nodes of your tool with
        # different config in one document would otherwise clobber each other.
        return Ping(endpoint=str(data.get("endpoint", "")))

    def _execute(self, args) -> ToolResult:
        return ToolResult(content=f"pong from {self.endpoint or 'nowhere'}")
```

A `kind` this editor does not recognise degrades to a text control rather than
dropping the field, so a plugin built against a newer editor stays usable in an
older one. A field with no `key` has nowhere to store its value and is reported
rather than shown.

**Say whether your tool acts outside the run.** `side_effecting` is one class
attribute, and its default is `True`:

```python
class Ping(BaseTool):
    ...
    side_effecting = False        # this tool only reads
```

It is not a permission and it changes nothing about how your tool runs. The
compiler reads it to answer one question about the *graph*: can a node holding
this tool be run more than once? Two things say yes and neither is visible on
the canvas — every node is retried up to three times, and a grader's `revise`
edge draws a cycle the node sits inside — so a tool that sends a message or
writes a record does it again, with nothing remembering that it already did.
When both are true you get a sentence at compile time naming the node, the
capability and which mechanism applies.

**The default is `True` because an undeclared tool has to land on the safe
side.** A tool that only reads gets the sentence too until it says so, and one
line is what it costs to say so. A tool that genuinely acts keeps the default
and answers the sentence on the canvas instead: set that node's **Max retries**
to 1, keep it out of the loop, or make the action safe to repeat. Neither
finding can fail a build — the condition is a conservative default about a tool
nobody declared, and a guess may be loud but may not exit 1.

**If your tool's work is genuinely awaitable, write `_aexecute` instead.**
`_execute` stays the one required method — it is what all 26 bundled tools
implement, and nothing about it changed — and every tool also has an awaitable
door it inherits for free:

```python
class Ping(BaseTool):
    ...
    async def _aexecute(self, args) -> ToolResult:      # optional
        async with httpx.AsyncClient() as http:
            return ToolResult(content=(await http.get(self.endpoint)).text)
```

Write it **only** when there is something to `await`. The inherited default
runs your `_execute` in a worker thread, which is what LangChain already did
for a synchronous tool, and wrapping blocking work in `async def` is worse than
not writing it at all: it holds the event loop instead of a pool thread.

What you get by writing it is the one thing a thread cannot give: **a call that
actually stops.** When a run is cancelled — the person closed the tab — a
thread-bound tool keeps going and keeps billing until it finishes, while an
awaited one stops where it is. Both doors always work in both directions: a
tool with only `_execute` can be awaited, and a tool with only `_aexecute` can
be called synchronously, so nothing about your choice constrains who can use
your tool.

**The wire contract** is `GET /api/workflows/{slug}/capabilities`, whose
`plugin_tools` array carries `node_type`, `name`, `description`, `args_schema`,
`fields`, the `distribution` that shipped each tool (always displayed on the
card — a card that appeared because of an unrelated `pip install` has to be
explicable) and `replaces_builtin`. It is built from **the same registry layer
the runtime binds**, so the palette can never offer a tool the runtime lacks.

**If you replace a bundled tool**, precedence is the documented one — built-in
< your plugin < the workflow's own — so your card replaces the built-in card
and your tool is what runs. The payload says so on the tool and in a warning
naming your distribution, and uninstalling gives the bundled card back.

**When the card appears.** Capabilities are fetched when a saved workflow is
opened, and when the palette's Refresh is pressed — so after `pip install`,
open a workflow (or press Refresh) rather than expecting a card to appear in a
blank session. There is no push yet; that is the rest of RC-05.

**Local preview cannot run your tool.** Its implementation is on the backend;
the canvas Run button refuses honestly and points at Chat, exactly as a
workflow-discovered tool does.

> **The two-place authoring error, now loud.** A tool that exists in Python
> with *neither* an editor card in `src/nodes/tools/` nor a plugin declaration
> is bindable and invisible. The capabilities response now names every such
> node type, and the editor shows it at the top of the palette: *"N tools the
> runtime can bind have no editor card, so no one can wire them on a canvas:
> …"* — with both ways to fix it. Silence was the old behaviour, and it was
> the worst part of the gap.

---

## Part 4 — the TDD loop and the five gates

Tests land with — ideally before — the change. `core/` is pure TypeScript and
directly unit-testable; there is no excuse for untested logic there.

The loop:

1. **Red, in Python.** Write the tool's test first, against the real thing.
   The Chinook tests run against the actual shipped database on purpose: a
   double would happily have passed for the fabricated-rows implementation
   they replaced, and correctness is the entire risk in text-to-SQL.
2. **Green.** Implement `_execute`.
3. **Red, in TypeScript.** Assert the node's *contract* — its id, its fields'
   defaults, its ports. These are cheap and they catch the schema drifting
   away from what the backend expects.
4. **Green.** Write the definition.
5. **Wire it.** Register, open the workflow, run it.

The five gates, all of which CI runs:

```bash
npm run typecheck     # tsc -b
npm run lint          # eslint src
npm run format:check  # prettier --check
npm test              # vitest run
python -m pytest -q   # backend + workflow tests (live-API tests opt-in: -m live)
```

`npm run verify` chains the first four.

A sixth gate is documentation: CI's `docs-freshness` job fails a PR that
touches `src/` or `backend/` without touching `README.md`, `docs/` or
`openwiki/`. If a change genuinely needs no documentation, say `docs: not-needed`
in a commit message.

---

## Part 5 — worked example: `tool.dice-roll`

A complete atom, both halves, in about sixty lines. It is deliberately trivial
so the shape is the only thing you are reading.

### The Python half — `workflows/<slug>/tools/dice.py`

```python
"""Dice tool — the smallest complete atom."""

from __future__ import annotations

import random

from pydantic import BaseModel, Field

from openstategraph.abc.tool import BaseTool, ToolResult


class RollArgs(BaseModel):
    model_config = {"extra": "forbid"}
    sides: int = Field(default=6, ge=2, le=100, description="Faces on the die.")
    count: int = Field(default=1, ge=1, le=20, description="How many dice to roll.")


class DiceRollTool(BaseTool):
    """Rolls dice and reports each face plus the total."""

    name = "roll_dice"
    node_type = "tool.dice-roll"
    description = (
        "Roll one or more dice and return the individual faces and their total. "
        "Use this whenever a random outcome is needed; never invent one."
    )
    Args = RollArgs

    def __init__(self, *, seed: int | None = None) -> None:
        # A fresh instance per configured node, never a mutation of the
        # registry's shared one.
        self._random = random.Random(seed)

    def configure(self, data: dict) -> "DiceRollTool":
        seed = data.get("seed")
        return type(self)(seed=int(seed)) if isinstance(seed, (int, float)) else self

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, RollArgs)
        rolls = [self._random.randint(1, args.sides) for _ in range(args.count)]
        return ToolResult(
            content=f"Rolled {args.count}d{args.sides}: {rolls} — total {sum(rolls)}"
        )
```

> **No `TOOLS` list here, deliberately.** Workflow-scoped discovery imports the
> module and collects `BaseTool` **subclasses** via `inspect.getmembers` —
> classes, not instances, and no list is consulted
> ([`capability_discovery.py`](../backend/openstategraph/api/capability_discovery.py),
> `discover_tool_instances`). A `TOOLS = [DiceRollTool()]` line here would run
> nothing and read as the mechanism, which is the more expensive kind of
> wrong. `TOOLS` belongs to the *entry-point* path in `extensions.py`, for a
> tool shipped as an installable distribution — see **Published**, above.

### Its test — `workflows/<slug>/tests/test_dice.py`

> **`from tools.…` resolves for exactly one workflow today.** `pytest.ini`
> pins `pythonpath = backend workflows/chinook-assistant`, so the top-level
> `tools` package *is* Chinook's. In any other slug this import raises
> `ModuleNotFoundError: No module named 'tools.dice'`. Add your slug to that
> `pythonpath` line — and note `pytest.ini` says so itself: two workflows both
> shipping `tools/` will collide on the name. The package-local import path is
> a known rough edge, not a finished story.

```python
from tools.dice import DiceRollTool


class TestDiceRoll:
    def test_rolls_the_requested_number_of_dice(self) -> None:
        result = DiceRollTool(seed=1).run(sides=6, count=3)
        assert result.ok, result.error
        assert "Rolled 3d6" in result.content

    def test_seeded_rolls_are_reproducible(self) -> None:
        assert DiceRollTool(seed=7).run().content == DiceRollTool(seed=7).run().content

    def test_invalid_arguments_come_back_as_data(self) -> None:
        result = DiceRollTool().run(sides=1)
        assert not result.ok
        assert "Invalid arguments" in (result.error or "")

    def test_configure_returns_a_fresh_instance(self) -> None:
        base = DiceRollTool()
        assert base.configure({"seed": 3}) is not base
```

Note the third test: bad arguments come back as a failed `ToolResult`, not an
exception. That behaviour is inherited from `BaseTool.run` — you get it for
free, and you should assert it once so nobody "helpfully" adds a `raise`.

### The TypeScript half — `src/nodes/tools/DiceNode.ts`

```ts
import { Ok, type Result } from '@core/kernel/Result';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { ExecutionContext, IToolExecutor } from '@core/execution/INodeExecutor';
import type { ToolSpec } from '@core/providers/ILLMProvider';
import { ToolNodeModel, createToolExecutor, defineToolNode } from './AbstractToolNode';

export class DiceNodeModel extends ToolNodeModel {
  get sides(): number {
    return this.getNumber('sides', 6);
  }
}

export const diceNode: INodeDefinition = defineToolNode(
  {
    id: 'tool.dice-roll',
    scope: 'workflow',
    label: 'Roll Dice',
    description: 'Rolls dice and returns the faces and their total.',
    iconId: 'node-discovered-tool', // any id in view/icons/iconRegistry.ts
    accent: 'violet',
    keywords: ['random', 'dice', 'roll'],
    defaultSize: { width: 260, height: 140 },
    fields: [
      { kind: 'slider', key: 'sides', label: 'Sides', min: 2, max: 100, step: 1, defaultValue: 6 },
    ],
  },
  DiceNodeModel,
);
```

`DiceNodeModel` exists only to give `sides` a typed accessor. **A tool with no
accessors to add passes `ToolNodeModel` itself** rather than declaring an empty
subclass — that is what the Base rung of the ladder is for, and
`AbstractToolNode.test.ts` fails a `class X extends ToolNodeModel {}`. Five of
the shipped tool nodes do exactly that (reviews-2026-08-14 ticket 07).

```ts

const diceTool: IToolExecutor = {
  describeTool(node: AbstractNodeModel): ToolSpec {
    const dice = node as DiceNodeModel;
    return {
      name: 'roll_dice',
      description: 'Roll one or more dice and return the faces and their total.',
      parameters: {
        type: 'object',
        properties: {
          sides: { type: 'number', description: 'Faces on the die', default: dice.sides },
          count: { type: 'number', description: 'How many dice to roll' },
        },
        required: ['count'],
        additionalProperties: false,
      },
    };
  },

  async invokeTool(
    node: AbstractNodeModel,
    args: Record<string, unknown>,
    ctx: ExecutionContext,
  ): Promise<Result<string, string>> {
    const dice = node as DiceNodeModel;
    const sides = typeof args['sides'] === 'number' ? args['sides'] : dice.sides;
    const count = typeof args['count'] === 'number' ? args['count'] : 1;
    const rolls = Array.from({ length: count }, () => 1 + Math.floor(Math.random() * sides));
    ctx.log(`Rolled ${count}d${sides}`);
    return Ok(JSON.stringify({ rolls, total: rolls.reduce((a, b) => a + b, 0) }));
  },
};

export const diceExecutor = createToolExecutor(diceNode.id, diceTool);
export const DICE_NODES = [{ definition: diceNode, executor: diceExecutor }];
```

`defineToolNode` supplies the category, the palette keywords and the single
`tool` output port whose dot sits on the card's top edge — so what you wrote
above is only what is genuinely specific to dice.

### Its test — `src/nodes/tools/DiceNode.test.ts`

```ts
import { describe, expect, it } from 'vitest';
import { diceNode } from './DiceNode';

describe('dice node definition', () => {
  it('exposes exactly one out port: the tool bus connector', () => {
    const outs = diceNode.ports({}).filter((p) => p.direction === 'out');
    expect(outs).toHaveLength(1);
    expect(outs[0]?.id).toBe('tool');
  });

  it('declares the same node type id the Python tool answers to', () => {
    expect(diceNode.id).toBe('tool.dice-roll');
  });
});
```

That second assertion is the seam, tested. It is the one thing that, if it
drifts, produces a card that looks wired and answers nothing.

### Register it

`workflows/<slug>/tools/dice.py` is discovered automatically. For the
TypeScript card, register the family in
[`workflowScoped.ts`](../src/nodes/workflowScoped.ts):

```ts
workflowScopedFamilies.register({ id: 'dice', nodes: DICE_NODES });
```

Nothing else in the engine changes — that is what makes it a registration
rather than an edit. Or, if the atom is genuinely useful everywhere, add it to
`registerNodeCatalogue` in [`index.ts`](../src/nodes/index.ts) and to
`_process_tool_layer` in
[`registries.py`](../backend/openstategraph/api/registries.py) — the same pair
named at the top of this page. **Not** `build_tool_registry`: that function
assembles the layers and holds no list of its own, as the app-wide section
above already says. This sentence contradicted it until 2026-08-13.

Then drag it onto the canvas, wire its `tool` port to an agent's `tools` bus,
and ask the agent to roll something.


---

## Appendix — a function is not an atom, and has no ladder

This page is about **tools**. A **function** is the other thing a developer
writes in Python and places on the canvas, and until 2026-08-18 its contract
lived only in a compiler docstring — so an author looking for the function path
found this page, which is about something else.

`function.` is a declared census term in
[`vocabulary.ts`](../src/nodes/vocabulary.ts) and `function.format_report` is a
molecule in *Reasoning & control*. There is **no `abc/function.py`**, and there
should not be: the entire contract is one signature, so a
`IFunction → AbstractFunction → BaseFunction` ladder would exist to share
nothing, which this project's rules say to refuse and say so.

```python
def fn(text: str) -> str: ...
```

Three facts, all load-bearing, recorded at `_discovered_function` in
[`node_runtime.py`](../backend/openstategraph/compile/node_runtime.py):

- **It transforms the node's upstream text.** Nothing else reaches it.
- **It gets no model and no state — deliberately.** Ticket 35: *code is
  referenced by name, never given the raw state to hide control flow in.* Do
  not widen the signature to `fn(state)` as a convenience; that is precisely
  what was refused, and any future runtime-context work inherits this as a
  constraint rather than an oversight.
- **A raised exception becomes readable output**, the same errors-are-data rule
  `BaseTool.run` applies: retrying a deterministic function reproduces the same
  failure, so the useful move is to carry the message downstream where a grader
  or a person can read it.

Discovered functions live in `workflows/<slug>/functions/` and arrive by the
same `code → canvas` channel as discovered tools — the type id is data, and it
travels with the package.

### Putting one on a canvas

Drop a top-level, non-underscore `def` into `workflows/<slug>/functions/*.py`,
open the package (or press **Refresh** in the palette's *This workflow*
section), and it is there as a card with one `text` in-port and one `result`
out-port. Nothing to register, no TypeScript to write —
[`DiscoveredFunctionNode.ts`](../src/nodes/functions/DiscoveredFunctionNode.ts)
mints the type from what `discover_functions` reports, on the same seam
`DiscoveredToolNode` uses (`export-and-eject/01`; before it, the editor parsed
the endpoint's `tools` and dropped its `functions`, so the only way to run one
was to hand-edit `workflow.json`).

Two things about it that are not guesses:

- **The node type is `function.<name>`, not the capability id.** The backend
  *reports* `<slug>/functions.<name>`, but the compiler dispatches on a
  `function.` prefix and `discover_function_callables` keys its registry by the
  bare name — so that is what a document names. It is therefore **not**
  slug-qualified, unlike a discovered tool's; harmless in the editor, where only
  the open package's functions are ever registered, and a real property of the
  runtime rather than of the card. Two consequences of the flat namespace were
  measured for `export-and-eject/11` rather than reasoned about:
  a **mount** is safe — a child runtime is built with the child's own functions
  last and therefore highest, so a mounted package binds its own `shout` and
  never the parent's — and a name that collides with a **built-in**
  (`function.format_report`) loses to the built-in at both ends. That last one
  used to be silent; the compiler now says so on `runtime_warnings()`, naming
  the function and telling you to rename it, because the alternative is a
  developer's function that never runs and never explains itself.
- **Across a mount, a function registry is inherited; a skill or a knowledge
  folder is not.** The child runtime is built with
  `{**parent.functions, **child.functions}`, so the merge settles a *collision*
  and leaves a gap either side of it: a name **only the parent** ships is
  reached by the child anyway. The same document therefore answers differently
  depending on who mounted it — standalone it reports `UNRESOLVED_FUNCTION` and
  passes its input through, mounted it runs the parent's Python. That is real,
  and as of `export-and-eject/13` it is **reported**: the mount records a
  `runtime_warnings()` sentence naming the function and the mounted package,
  and telling you to move the function into that package. It is reported and
  not refused because it is a legal graph that answers questions, and because
  whether the inheritance should exist at all is a separate decision — skills
  and knowledge are explicitly isolated to the child a few lines below the
  merge, and functions and tools are the exception (`export-and-eject/14`).
- **The card has no fields.** The compiled step reads nothing from `data`, so a
  control here would be one the compiler ignores. The signature and the first
  line of the docstring become the card's subtitle instead, where they cannot
  lie about what gets passed. A field schema derived from the signature was
  considered for v1 and refused: the signature is fixed at `(text: str) -> str`,
  so there is nothing to derive.

The browser preview cannot run one — the implementation is Python on the
backend, and the executor says so rather than inventing a result. Press **Run**
(or use Chat) and it runs for real.

---

## Appendix — before you build any of this, run the interview

[`skills/atom-forge`](../skills/atom-forge/SKILL.md) is the procedure, and it
now **routes before it interviews**: *is this thing on the canvas, or does
something on the canvas use it?* Infrastructure — a connector, a pool, a client
— has no authoring path in this repository yet, and the skill says so rather
than taking it through nine questions of which four are meaningless.

Two things it asks that this page does not, both found by running it against
ten concepts and both from perfectly ordinary atoms:

- **Is it safe to run twice?** `retry_policy` is a `StateGraph.add_node`
  parameter applied graph-wide, so the platform *will* re-run your node. A read
  repeating is harmless and worth recording; a send repeating is a duplicate
  message to a customer.
- **Does user content leave the machine, and to whom?** If it leaves to a
  vendor *you* chose rather than one the user configured, that belongs in the
  node's description, where somebody deciding to place it will read it.
