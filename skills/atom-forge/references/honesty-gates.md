# The honesty gates

**Do not promise which is not possible.** That is the owner's phrasing and this
skill's law. These ten gates are the feasibility checklist — run them before
promising anything in the interview, and again before the commit.

Each gate carries the evidence that put it here, because a gate whose reason is
lost gets argued away by the next person.

---

## 1. The wheel is read-only

**Gate:** nothing written at run time into an installed package directory.

The wheel is read-only, shared between projects, and replaced on upgrade. A
design that stores state "next to the workflow" works in a git checkout and
fails in every install. This is why the tollbooth's memory does not go in a
markdown file inside the package, and why `eject` was rejected as a verb — half
of what it means is a promise a read-only wheel cannot keep
(`.scratch/install-experience/tickets/01-the-install-line-is-the-mental-model.md`).

Writable places: the Store, the checkpointer, an explicit path the user gave you.

## 2. Copy is verbatim

**Gate:** nothing rewrites a package as it is copied.

`examples copy` takes a finished package out of the wheel byte for byte —
no rename, no substitution, no envelope edit, all-or-nothing before the first
byte, exit 1 on any clash with nothing written. So a design that depends on
"we'll fix that value at copy time" is not available. Fix it in the source
document instead.

## 3. No non-finite number in a serialisable field

**Gate:** `int | None`, `None` meaning unbounded. Never `Infinity`, never `NaN`.

Neither is representable in JSON, and Pydantic and JSON Schema cannot express
them. `JSON.stringify(Infinity)` is `"null"` — the value does not survive its own
round trip and nothing reports the loss. `maxConnections` is the worked example,
with the reasoning recorded at the field itself in
`src/core/model/contracts/ports.ts`.

Retention limits, budgets and caps all land on this gate.

## 4. No new node class without a new mechanism

**Gate:** dimension 8 named a real `StateGraph` construct.

A node type that compiles to nothing new is a second way to draw something the
canvas already does, and it will drift from the first. *"A Loop node would
compile to nothing new."* The alternatives are configuration, a template, a
package to mount, or a middleware slot.

## 5. pip's actual limits

**Gate:** the plugin story promises only what entry points can do.

- Two entry-point groups exist — `openstategraph.tools` and
  `openstategraph.knowledge_builders` — and both are Tier 1 stability, because
  they live in *your* `pyproject.toml`.
- There is deliberately **no `openstategraph.functions` group**: a `function.<x>`
  node binds by a name written in the document, so a distribution able to inject
  one process-wide would change what a package's own node resolves to with
  nowhere in the document to see it. Publish a tool instead.
- An entry point that raises is **jailed**: one WARNING naming the distribution,
  the failure lands on `CompiledWorkflow.warnings`, every other plugin still
  registers.
- Precedence is built-in < installed plugin < the package's own `tools/`.
- **There is no push.** Capabilities are fetched when a workflow is opened or
  the palette's Refresh is pressed. Never promise that a card appears in an
  already-open blank session after `pip install`.
- `OPENSTATEGRAPH_DISABLE_PLUGINS=1` must keep working: a reproducible run never
  depends on a colleague's install.
- **Local preview cannot run a backend tool.** Say so honestly (gate 10).

## 6. No promise the platform cannot keep

**Gate:** the coverage claimed is the coverage that exists.

The recorded example: **a node cannot act on what left before it ran.** `token`
frames stream out of an agent while it is still typing; an outbound guard runs
afterwards. So the settled surfaces — `answer`, `outputs`, the stored transcript
— are covered and the live token stream is not, and the guardrail work says so
in as many words rather than papering over it
(`.scratch/guardrails/tickets/02-where-the-outbound-guard-lives.md`).

Where a limit exists, write it into the ticket and into the card copy. A limit
that is documented is a design; a limit that is discovered is a bug report.

## 7. A key your factory reads must be a key some field declares

**Gate:** every `data["k"]` a Python factory reads is declared by a field in the
TypeScript field schema.

The field schema is the only way a value gets into a node's `data`. A factory
reading an undeclared key does not fail — it reads `""` forever. That defect
shipped three times (the model picker, the Worker's rules mode, the
supervisor's rules read from a *port id*). `backend/tests/test_data_key_contract.py`
makes the fourth impossible: keep the key a string literal or a module constant
at the point of use, because a key assembled at run time defeats the extractor
and a guard that shrugs at what it cannot parse guards nothing.

## 8. "Zero tokens" means no model call anywhere in the path

**Gate:** if a claim of determinism or zero cost is made, no step in that path
calls a model.

A summarisation, classification or "smart" transform is a model call. Split it
into an agent node upstream and keep the deterministic node deterministic —
otherwise the card says free and the bill says otherwise, and a wiring bug and a
capability gap become the same symptom.

## 9. Multi-writer state keys need a named reducer

**Gate:** any state key more than one node type can write is
`Annotated[T, reducer]`, never a plain `LastValue` field.

Found live, not hypothetically: a graph combining a router, `Send` fan-out and
several tool-using workers scheduled two `answer`-writing nodes in the same
superstep, and LangGraph raised `InvalidUpdateError` on a field every scripted
single-writer test had exercised without incident. Reducers are a **named enum**,
not arbitrary functions, so the document stays portable.

## 10. Honest refusal beats silence

**Gate:** every node type registers a browser executor, even one that only
refuses.

A `standard` node with **no** registered executor is *silently skipped* by the
preview engine — the run appears to succeed and quietly did less than you think.
A refusal is a registered executor returning an error, so the preview tells the
truth:

```
"<name>" only runs on the backend — use Chat, not the canvas Run button.
```

Do not fabricate a plausible result to keep the canvas green. Router, Grader and
Orchestrator all refuse for the same reason.

---

## Running the gates

Read the design against all ten and write the outcome down. The two legitimate
outcomes are *passes* and *the design changed*. "We'll deal with it later" is
neither, and it is what gate 6 exists to catch.

Where a gate is tripped, the fix is almost always a smaller promise rather than
a bigger mechanism.
