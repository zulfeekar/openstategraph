# The honesty gates

**Do not promise which is not possible.** That is the owner's phrasing and this
skill's law. These eleven gates are the feasibility checklist — run them before
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

## 11. A measurement is a fact about one version

**Gate:** every number, API shape and behaviour you measured cites the version
it ran on, and the build **re-verifies on the version it pins**.

Research and build happen on different days and, often, in different
environments. The recorded case: the `tool.mcp` research read
`langchain-mcp-adapters` **0.2.1** line by line — transports, error handling,
the `load_mcp_tools` signature — while the doc page it was checked against
described `>=0.3.0`, and the ship floor became `>=0.3.0`. Two of the measured
facts had drifted:

- errors. On 0.2.1 a tool error raises `ToolException` and
  `handle_tool_errors` does not exist; on 0.3.2 it exists, defaults to `True`,
  and the error comes back **as data**. The atom was scoped to own error
  conversion and did not need to.
- signatures. `tool_name_prefix` moved from the loader to the client
  **constructor**. A build following the research literally would have passed
  an unexpected keyword.

Only the first was caught in advance, and only because the research author
happened to notice and raised it as a grill flag; the second was flagged by
nobody and found by the re-verification. That asymmetry is the whole argument
for a gate: the catch must be structural, not attentive.

So — record the versions beside the measurements (`.scratch/mcp-connect/research/01-adapters.md`
is the format: a version line at the top, a caveat where the doc and the
install disagree, and an **amendment** section written after re-verifying).
Re-verify in a clean environment on the pinned version before the build trusts
a single number. What holds, say so; what drifted, name.

The corollary a build will want to skip: *"the docs say X"* is not a
measurement. The docs describe some version, usually the newest. Pin, install,
run it.

---

## Running the gates

Read the design against every gate in the sets that apply — Set A below for anything placed or wired, Set B at the end of this file for anything that touches the world beyond the process — and write the outcome down. The two legitimate
outcomes are *passes* and *the design changed*. "We'll deal with it later" is
neither, and it is what gate 6 exists to catch.

Where a gate is tripped, the fix is almost always a smaller promise rather than
a bigger mechanism.


---

# Set B — the outside-contact gates

Added 2026-08-18, after running this skill against ten concepts
(`.scratch/the-atom-has-no-context/research/01-ten-concepts-through-the-skill.md`).
The eleven gates above are **the canvas gates**: every one is about packaging,
serialisation or compile targets. Against a database connector **not one of them
fires**, so an author could pass the whole list having been asked nothing that
applies to what they are building — a false green, which is worse than no
checklist.

Gate 9 above (two writers, one state key, no named reducer) belongs to both
sets. It is about the state schema rather than the canvas, and it binds anything
that can write. That it is the only shared gate is the evidence that this split
is real rather than tidy.

## 12. A vendor is reached through something a person can revoke

**The evidence.** `CLAUDE.md`'s Ollama correction, and it is the strongest in
this file because the rule was **broken by omission**, not by decision, and
shipped: `ProviderSpec` declared `env_vars=()` and presented itself as keyless,
while nothing passed an endpoint at all — so `ollama.Client` dialled
`127.0.0.1:11434` and the cloud was reached, when it was reached, through a
local daemon signing with `~/.ollama/id_ed25519`. That credential *"never passes
through the environment and cannot be seen, moved or revoked from one"*, and on
a machine with no daemon running `/api/health` still reported
`model_configured: true`.

**The gate.** Name the variable, in the shape that already exists —
`env_vars`, `endpoint_env`, `default_endpoint`. Do not restate the rule in a
second place; two spellings drift.

**The redirect that catches the subtle case:** *"it works without one on my
machine"* is not evidence of a keyless design. It is an ambient daemon or a
cached login. The test is a machine that has only what the answer named.

## 13. A credential value is never stored

A document is committed. A field holds the **name** of a variable.

**The evidence, and it is a lesson about validators generally.** `tool.mcp`'s
`authTokenEnv` refuses a pasted credential, and the first rule was justified by
a confident argument: *every credential shape contains a hyphen or starts with a
digit, and neither is legal in a variable name.* It reads as a proof. It is
false — `ghp_aaaa…` is a GitHub token **and** a legal environment-variable name,
so the rule admitted exactly the value it existed to refuse. The fix is
`SECRET_VALUE_PREFIXES` in `config_file.py`: a literal list of known prefixes
(`sk-`, `ghp_`, `AKIA`, `Bearer `, …), inelegant and correct where the elegant
argument was neither.

**Do not replace it with a rule again.** The list will always be incomplete;
that is the trade it was chosen for.

## 14. Running twice is either harmless or handled

`retry_policy` is a `StateGraph.add_node` parameter, applied graph-wide by
`set_node_defaults` with per-node override — so **the platform will re-run a
node, by design**. A resumed `interrupt()` re-enters a step for the same reason.

- A **read** repeating is harmless. Record that; it is an answer, not silence.
- A **send** repeating is a duplicate message to a customer. The design that
  prevents it — an idempotency key, a dedupe window, opting this node out of the
  graph's retry default — exists before the module is written or it does not
  exist at all.

**The fix is never a per-node `retry` field.** That is the cross-family
violation `CLAUDE.md` names by example: retry is graph assembly, and a duplicate
on a node base produces two spellings of one feature.

Note that a tool's own failures are **data** (`ToolResult`), so a failing tool
does not raise and does not trip the graph's retry. The hazard is the retry
around the *agent*, and the resumed checkpoint — both outside the tool's sight,
which is why the author will not think of it unasked.

## 15. Content that leaves says so where a person places the node

**The evidence.** `CLAUDE.md`: never send a user's graph to a third party —
written because `draw_mermaid_png()` defaults to posting the graph to the
Mermaid.Ink API. That is enforced in exactly one place, the preview, because it
was a wrong **default**. A tool an author wrote deliberately has no default to
catch it.

Three answers, three different products, and only one of them needs surfacing:

- **nothing leaves** — often the feature (`draw_mermaid()`, the YouTube atom);
- **content leaves to a vendor the user configured** — their model provider,
  ordinary, already covered by the credential they set;
- **content leaves to a vendor the module author chose** — this is the mermaid
  shape. Nobody picked it and nobody will find out. It goes in the node's own
  description, where a person deciding to place it will read it.

A downstream guardrail is **not** an answer here. It redacts; it cannot unsend.

## 16. A pooled resource is scoped to a call, never to a run

`human.approval` compiles to `interrupt()` and the checkpointer is durable on
purpose, so a run genuinely pauses until a person returns — possibly for days.
A session scoped "per run" holds a pooled connection for that whole time.

**Why an experienced developer will miss this**: in a web application,
request-scope and run-scope are the same thing, so the distinction never arises.
Here they are hours apart. The three scopes are app/lifespan, run/thread, and
superstep/call; a session belongs to the third.

The small version of this hazard is already recorded in the codebase: one shared
tool instance per type let two SQL nodes clobber each other's row cap, which is
why `configure(data)` returns a *fresh* instance. A pooled resource has the same
shape with worse consequences.
