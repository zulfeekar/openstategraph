# Building an atom

An **atom** is a tool node: one capability, one card, one thing an agent can
call. The palette says so out loud — every section heading carries its
atomic-design tier, declared once in
[`src/nodes/vocabulary.ts`](../src/nodes/vocabulary.ts) and locked by
`vocabulary.test.ts`:

| Section | Holds |
| --- | --- |
| `Inputs · atoms` | `input.text`, `input.markdown` |
| `Tools · atoms` | every tool node — the built-ins, the platform family, and anything a workflow or a plugin adds |
| `Output · atoms` | `output.formatted` |
| `Reasoning & control · molecules` | `agent.llm`, `route.classifier`, `route.grader`, `human.approval`, `orchestrate.supervisor`, `orchestrate.worker`, `function.format_report` |
| `Composition · organisms` | `workflow.subgraph`, `team.workflow` — the only organisms |
| `Annotate · no tier` | `group`, `note` — canvas furniture, deliberately tier-less |

Atoms sort first, organisms last; the test asserts that ordering, so the
palette cannot drift from the vocabulary. **This page is about adding to the
first row: a tool.**

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

Available kinds: `text`, `textarea`, `select`, `slider`, `toggle`, `file`,
`readonly`, `repeatable-group`. Three flags shape where a field appears rather
than what it holds:

- `onCard: false` — inspector only. Use it when the card is already showing
  something more useful than a control.
- `group: 'Prompt'` — an inspector section.
- `advanced: true` — folded away until asked for.

A field can carry its own `validate`, and the schema supplies the defaults a
new instance is created with. That is the DRY rule in its most load-bearing
form: *node configuration is declared once as a field schema; card, inspector,
defaults and validation all derive from it.*

### Ports carry types and cardinality

A port descriptor declares its `direction`, its `type`, and — when it differs
from the default — its capacity:

```ts
{
  id: 'tools',
  direction: 'in',
  type: PORT.tool,
  label: 'agent tools',
  side: 'bottom',
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

*(from [`workflows/chinook-nl-to-sql/tools/chinook.py`](../workflows/chinook-nl-to-sql/tools/chinook.py))*

- `name` — what the model calls.
- `node_type` — the canvas node this tool answers to. Empty means "not
  placeable on a canvas", which is legitimate for a tool only ever handed to
  an agent programmatically.
- `description` — the model reads this to decide *whether* to call you. It is
  prompt engineering, not a docstring.
- `Args` — a Pydantic model. **Pydantic is the single source of truth**; the
  TypeScript types are generated from it. Never hand-mirror an argument schema
  across the boundary.

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
full catalogue — and register the Python tool in `build_tool_registry`
([`backend/openstategraph/api/registries.py`](../backend/openstategraph/api/registries.py)),
which keys every tool by its own `node_type`.

**Workflow-scoped (only while a workflow using it is open).** Add the family
to [`src/nodes/workflowScoped.ts`](../src/nodes/workflowScoped.ts), and set
`scope: 'workflow'` on each definition so the palette says where it came from.
This exists because the alternative is real: put one workflow's tools in the
shared catalogue and every future palette carries every past workflow's tools.

> **Load order matters.** `WorkflowSerializer.fromJSON` silently skips nodes
> whose type is not registered yet. Workflow-scoped types must be registered
> from the raw document *before* it is imported —
> `registerNodeTypesForRawDocument` does this, and every load path calls it.

**Discovered (no TypeScript at all).** Drop the tool in
`workflows/<slug>/tools/`, export it in a `TOOLS` list, and the backend finds
it by importing the package and collecting `BaseTool` subclasses.
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
dependencies = ["openstategraph>=0.3"]

[project.entry-points."openstategraph.tools"]
acme = "acme_osg_tools:TOOLS"          # a list of BaseTool subclasses
```

The right-hand side may resolve to any of three things, because a plugin
author should not have to guess which one we take:

```python
# acme_osg_tools/__init__.py
from openstategraph.abc import BaseTool, NoArgs, ToolResult

class Ping(BaseTool):
    name = "acme_ping"
    description = "Answers with a pong."
    node_type = "tool.acme-ping"       # required: this IS the wiring identity
    Args = NoArgs

    def _execute(self, args) -> ToolResult:
        return ToolResult(content="pong")

TOOLS = [Ping]        # a list — or `= Ping`, or `= Ping()`. All three work.
```

A second group exists for the knowledge layer, with the same rules:

```toml
[project.entry-points."openstategraph.knowledge_builders"]
acme = "acme_osg_knowledge:AcmeBuilder"   # an IKnowledgeBuilder concrete
```

Those two group names — `openstategraph.tools` and
`openstategraph.knowledge_builders` — are **Tier 1**: they are covered by
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
            kind="text",                          # text | textarea | select | toggle | number
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


TOOLS = [DiceRollTool()]
```

### Its test — `workflows/<slug>/tests/test_dice.py`

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
import { AbstractToolNodeModel, createToolExecutor, defineToolNode } from './AbstractToolNode';

export class DiceNodeModel extends AbstractToolNodeModel {
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
TypeScript card, add `DICE_NODES` to `syncWorkflowScopedNodes` in
[`workflowScoped.ts`](../src/nodes/workflowScoped.ts) — or, if the atom is
genuinely useful everywhere, to `registerNodeCatalogue` in
[`index.ts`](../src/nodes/index.ts) and to `build_tool_registry`.

Then drag it onto the canvas, wire its `tool` port to an agent's `tools` bus,
and ask the agent to roll something.
