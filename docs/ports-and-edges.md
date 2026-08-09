# Ports and edges

Reference for the type system that decides what you are allowed to draw.

A port *type* is a first-class registered concept, not a string on a node,
because three separate concerns must agree about it: whether a connection is
valid, what glyph and colour appear beside the port, and how the engine
coerces the value flowing across the link.

---

## Port types

Declared in [`src/nodes/vocabulary.ts`](../src/nodes/vocabulary.ts); a plugin
can register more without touching the editor.

| Type | Accent | Carries | Produced by | Consumed by |
| --- | --- | --- | --- | --- |
| `text` | amber | a prompt or question | `input.text`, each `route.classifier` branch | `agent.llm.prompt`, `orchestrate.supervisor.instruction`, `route.classifier.question` |
| `skill` | orange | a system instruction that shapes behaviour | `input.markdown` | `agent.llm.skill`, `orchestrate.worker.skill` |
| `tool` | violet | a callable handle | every tool node's `tool` port | `agent.llm.tools`, `orchestrate.worker.tools` |
| `result` | green | a finished answer | `agent.llm.result`, `orchestrate.worker.result`, `route.grader.pass`, `function.format_report.report` | `route.grader.candidate`, `function.format_report.candidate`, `human.approval.candidate`, `output.formatted.result` |
| `feedback` | red | a rejection, travelling **upstream** | `route.grader.revise`, `human.approval.rejected` | `agent.llm.feedback`, `orchestrate.supervisor.feedback` |
| `worker` | blue | a fan-out *declaration* | `orchestrate.supervisor.workers` | `orchestrate.worker.dispatch` |

### Compatibility, at two granularities

A connection is legal if **either** holds:

1. **The type accepts the type.** `IPortTypeDefinition.accepts` defaults to
   "only itself". `result` declares `accepts: [PORT.result, PORT.text]`, so a
   plain text input can be wired straight to an output node while a graph is
   being sketched.
2. **The individual port opts in.** `IPortDescriptor.accepts` widens *one*
   port without widening its type for everyone. `agent.llm.prompt`,
   `route.classifier.question` and `orchestrate.supervisor.instruction` each
   declare `accepts: [PORT.text, PORT.result]` — which is what makes prompt
   chaining drawable without every `text` input in the catalogue silently
   gaining the same affordance.

Both are **consumer-declared and additive only**: a port may open itself up,
never close down what its type already allows.

`'*'` accepts anything, and is meant for pass-through and debug nodes.

---

## Cardinality belongs to the port

There is no node-level "allows multiple edges" flag, because a single node has
ports of different cardinality at once: an agent's `prompt` takes exactly one
link, its `tools` bus takes many, its `result` fans out to many.

```
maxConnections omitted  →  in: 1,  out: unlimited
maxConnections: null    →  unlimited, explicitly
maxConnections: 3       →  three
```

`null`, never `Infinity`: a port descriptor is data that reaches
`workflow.json`, and `JSON.stringify(Infinity)` is `"null"` — the value would
not survive its own round trip and nothing would report the loss. The resolver
checks `=== undefined` rather than `!= null`, so an explicit `null` (unlimited)
and an explicit `0` both mean what they say.

Buses today: `agent.llm.tools`, `orchestrate.worker.tools`,
`orchestrate.supervisor.workers`, `function.format_report.candidate`.

**Prefer varying the number of ports over toggling one port's cardinality.**
`ports` is a function of node data, so a node whose port *count* depends on
config just returns a different list — that is how `route.classifier` turns its
branch field into branch ports. If one port sometimes carried a scalar and
sometimes a list, its type would change at runtime and every executor would
have to branch, which is exactly what typed ports exist to prevent.

### Full inputs swap rather than reject

Dropping a link on an occupied **single-slot** input replaces the incumbent —
re-wiring is the gesture users reach for, and making them delete first is
friction with no safety benefit. A genuinely full **multi-slot** input rejects,
because there is no obvious incumbent to displace.

---

## The rules

Registered in order by `ConnectionValidator`, each independently testable; an
embedding app can drop one or insert its own.

| Order | Rule | Rejects |
| --- | --- | --- |
| 10 | `direction` | in→in and out→out; links run output → input |
| 20 | `self-loop` | a node feeding itself |
| 30 | `duplicate` | the same pair of ports linked twice |
| 40 | `type-compatibility` | *"Text output can't feed a Tool input"* |
| 50 | `capacity` | a full multi-slot input (a full single-slot input *replaces*) |
| 60 | `acyclic` | any cycle that does not close on a `feedback` edge |

---

## Edge categories

Four kinds of edge, distinguished by what the target port *means* — not by any
flag on the edge itself.

**Control** — `text` and `result` links. Ordinary dataflow, and the only
category that becomes a plain `workflow.json` graph edge and then a static
LangGraph edge. Router branches are control edges too, but compile to
`add_conditional_edges`.

**Binding** — `tool` and `skill` links. These do not sequence anything; they
attach a capability or an instruction to a node. A tool link means "this
callable is in that agent's toolbox", which is why the tool bus hangs below the
card rather than sitting in the flow.

**Worker** — `worker` links. A **fan-out declaration, not control flow**. An
edge landing on `orchestrate.worker.dispatch` becomes a LangGraph `Send`
dispatch target and is *never* a `workflow.json` graph edge. Each wire from the
supervisor declares one worker archetype; the supervisor labels every subtask
with the archetype it should reach.

**Feedback** — `feedback` links. The only edge that legally travels backwards.

---

## Why `feedback` is the only cycle-closer

`acyclicRule` permits a cycle **only** when the closing edge's source port is
`feedback`. Since the only `feedback` sources are `route.grader.revise` and
`human.approval.rejected`, and the only sinks are `agent.llm.feedback` and
`orchestrate.supervisor.feedback`, the type system *is* the gate:

- An **accidental** loop stays impossible to draw. Nothing else accepts
  `feedback`, so there is no wire you can drag by mistake that closes a cycle.
- A **deliberate** evaluator-optimizer loop is two clicks.

That is stricter than a permission flag and needs no escape hatch. It also
lands on the same constraint LangGraph reaches from the runtime side: a cycle
must contain at least one conditional edge, or it can never terminate — and a
grader is exactly that conditional edge.

The rejection message points at the supported route rather than just saying no:
*"That would create a loop. Route it through a Grader's 'revise' output
instead."*

---

## Reading the canvas

A link is tinted by the type of the port it **lands on**. The adapter stamps
the target port descriptor's accent and type onto the link, and that resolves
the same CSS variable the port dots use — which is why a link and its two
endpoints always agree.

Colour is never the only channel. Each type also carries a dash signature, so
the graph stays readable in greyscale and for colour-blind users:

| Type | Colour | Line |
| --- | --- | --- |
| `text` | amber | solid |
| `result` | green | solid |
| `skill` | orange | long dash (`7 3`) |
| `tool` | violet | fine dots (`1.5 3.5`) |
| `feedback` | red | short urgent dash (`3 3`) |
| `worker` | blue | dash-dot (`9 3 2 3`) |

During a run, an active link animates its dashes in the direction of flow.
Hovering deepens a typed link rather than washing it back to grey — losing the
type on hover would hide the one thing the colour is carrying.

Two appearances for the port itself: `row` (a labelled row in the card footer
with its dot on the card edge) and `pill` (a detached capsule below the card,
used for the tool bus where several links converge on one point).

### Flow direction

Ports carry a `side`, defaulting to `left` for inputs and `right` for outputs.
Switching the canvas to vertical flow rotates every effective side 90°
clockwise — one rule, no per-port annotations. Flow ports move from the
left/right edges to top/bottom, and the tool and worker buses swing from
top/bottom onto the card's flanks, with every existing `side` declaration still
meaning what it meant, relative to the reading direction.
