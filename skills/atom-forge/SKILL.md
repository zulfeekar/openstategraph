---
name: atom-forge
description: Interview-then-build procedure for adding a new module to OpenStateGraph — a tool atom, a node family, a guard, a memory construct, a function, or infrastructure such as a connector or a pool, workflow-specific or generic. Routes first (is this on the canvas, or does something on the canvas use it?), then grills, verifies each answer against this installation rather than taking it on trust, recommends a shape, and says plainly when the platform cannot do what was asked. Grills the developer one question at a time across nine dimensions (trigger, payload, scope and lifetime, read side, failure modes, tier and family, ports and cardinality, compile target, outside contact), runs both honesty-gate sets, scores the readiness card for the route taken, and only then builds TDD through this repository's real pipeline. Use it whenever anyone wants a new node, tool, atom, guardrail, memory segment, cache, summariser or capability on the canvas — including phrasings like "can we have an X node", "build a tool that…", "add memory to this workflow", "I want the graph to remember" — and use it even when they ask only for the code, because the interview is what stops a node being built that compiles to nothing.
---

# Atom forge

Build a new module by finding out what it *is* before writing a line of it.

This is a repository skill, not an agent feature. It assumes nothing but the
ability to read files and run shell commands. Every path below is real; check
one if you doubt it.

## Why an interview and not a spec form

Three modules in this repository were designed this way, and each one's design
turned on an answer nobody would have volunteered:

- **The Guardrail atom** — asking *where does the policy apply* rather than
  *which flags do you want* produced "position is the scope": two of the
  library's three boolean scopes are simply where the node sits, and the third
  has no wire to sit on. (`.scratch/guardrails/map.md`)
- **The youtube-transcript atom** — asking *how does this fail* first produced
  seven distinguishable failure messages, one of which (HTTP 200 with zero
  bytes) is the difference between an agent saying "no transcript" and an agent
  describing a video it never read. (`.scratch/workflow-gallery/research/01-youtube.md`)
- **The tollbooth memory segment** — asking *what writes it, and when* produced
  a deterministic node instead of a second memory tool. See
  `references/worked-example-tollbooth.md`, the interview this skill ships with.

A spec form collects fields. An interview finds the one answer that decides the
design, and it usually arrives two questions after the one you were tempted to
skip.

## The three phases

0. **Route** — one question, before the interview: *is this thing on the
   canvas, or does something on the canvas use it?* It costs one turn and it is
   what makes the rest of the questions honest.
1. **Interview** — the dimensions for the route taken, one focused question at
   a time, each with a redirect that ends the build early when the answer says
   "this is not a new module".
2. **Build** — only after the readiness card is full, and only through the
   pipeline in the checklist below.

Do not interleave 1 and 2. Writing code mid-interview is how a dimension goes
unasked and reappears as a rewrite.

## Ask, verify, recommend — and be willing to say "not here"

The interview is four verbs, not one, and three of them are easy to skip:

- **Ask** — one question per turn, wording from `references/interview-questions.md`.
- **Verify** — do not take an answer on trust. *"It reads `DATABRICKS_TOKEN`"* is
  checkable: is the variable named anywhere in this repository, is there a
  `ProviderSpec` shape for it, is it set in this shell? *"It needs the graph
  state"* is checkable: `grep` whether that family is given state at all —
  a **function** is deliberately not (`fn(text: str) -> str`, ticket 35). An
  unverified answer is a hypothesis, and this repository has the recorded case:
  a validator justified by a confident argument admitted the exact value it
  existed to refuse.
- **Recommend** — a redirect that only says *"this is a tool, not a node"* has
  done half the job. Say what you would build: the rung, the ports, the two or
  three fields, and why. The developer can then disagree with something
  concrete.
- **Say "not here"** — the most likely honest outcome, and the one an interview
  is most tempted to route around. If the design needs a capability this
  platform does not have, **stop and name it, with a pointer**. A run that ends
  *"your module needs a typed `db` handle; this platform has no such thing —
  see `.scratch/the-atom-has-no-context/`"* is a **correct** outcome, not a
  failed interview. The law is *do not promise which is not possible*, and it
  binds the interview as hard as it binds the build.

---

## Phase 0 — route, in one question

> **"Is this thing on the canvas, or does something on the canvas use it?"**

Two routes, and the nine dimensions below assume the first. Asking them of the
second produces four meaningless answers and a readiness card that cannot pass
— which reads as *unbuildable* rather than *out of scope*. Recorded case: a
database connector run through the canvas interview scores about 3/10 and is
refused at dimension 8 with the wrong reason ("it is configuration"); a
connection pool is not configuration.

| Route | What it is | Where it goes |
| --- | --- | --- |
| **On the canvas** | a node, a tool, a function, a guard, a memory construct — something a person places or wires | dimensions 1–9 below |
| **Used by something on the canvas** | **infrastructure**: a connector, a pool, a client, a cache backend. App-lifetime, no ports, no compile target | dimension 9 and the infrastructure gates, then **stop** — see below |

**Infrastructure has no authoring path in this repository yet, and that is the
honest thing to say.** There is no tier for it, no ladder, and no registry it
can join; whether it becomes a fourth tier or is recorded as outside the tier
system is an open decision
(`.scratch/the-atom-has-no-context/tickets/06-*`). So the correct outcome for
route two today is: run dimension 9, write the answers down as a ticket, and
say what is missing. Do not build it into a tool — a pool welded inside a tool
is unshareable, unmockable, and reopened per node.

**Two words, kept apart**, because both were in play at once while this was
worked out:

| Word | Means | Never means |
| --- | --- | --- |
| **Binding** | a wire that plugs a capability into a node with **no step added** — what `tool` and `skill` ports already are | control flow |
| **Resource** | the pool or client behind it — app-lifetime, off-canvas | anything drawn |

---

## Phase 1 — the dimensional interview

Ask **one** question, wait for the answer, then decide the next question from
what you just heard. Do not paste all eight at once: the point is that answer 3
changes question 4. Full wordings, the reasoning each question carries, and
follow-ups are in `references/interview-questions.md` — read it before the
first question.

| # | Dimension | The question, in one line | Redirect if the answer is… |
| --- | --- | --- | --- |
| 1 | **Trigger** | What makes this happen — the flow reaching a point, a condition on the data, or a model deciding? | *a model deciding* → it is a **tool an agent calls**, not a node. Bind the existing one (`save_memory` for memory) or write a `BaseTool`. Stop here. |
| 2 | **Payload** | What exactly moves — which bytes, produced by whom, and does producing them cost tokens? | *"the model summarises it first"* → that is a second node (an agent), not a field on this one. |
| 3 | **Scope & lifetime** | Who else can see this, and when is it gone — this step, this run, this thread, this workflow forever, every workflow? | This **decides the backend**. Never ask "checkpointer or Store or file" — that is asking the developer to pick your implementation. Answers map in `references/interview-questions.md`. |
| 4 | **Read side** | Who reads it back, and how does it reach them — a port, a prompt section, the card, a tool result? | *"the developer edits the injected text"* → prompt machinery is not editable. It is a **Context** section; only Rules are editable. |
| 5 | **Failure modes** | List the ways it fails, and give each one a sentence a *model* can act on. Two failures that share a sentence are one failure. | *"it just fails"* → keep going. Ask specifically: refused vs answered-with-nothing. That distinction is the youtube atom's whole design. |
| 6 | **Tier & family** | Is it an atom, a molecule, or an organism — and which existing family does it join? | *a new family with one member* → check the ladder earns itself. Shared across two families → **composition**, never a common ancestor. |
| 7 | **Ports & cardinality** | What comes in, what goes out, what type, how many links each? | *"sometimes one, sometimes a list"* → vary the **number of ports** with config, never a port's type at runtime. |
| 8 | **Compile target** | Name the LangGraph construct this becomes. | *nothing new* → it is **configuration, a template, or a package to mount** — not a node type. This is the Loop-node refusal, twice recorded: *"A Loop node would compile to nothing new."* (`.scratch/production-ready/tickets/01-a-loop-template.md`) |
| 9 | **Outside contact** | Does this touch anything beyond the process — and what does that cost, leak, repeat or stall? | *"nothing leaves, nothing is needed"* → **record it as a property**, not as silence. It is often the feature. |

**Dimension 9 is one question with five follow-ups, not five dimensions.** They
are one subject — what happens at the boundary of the process — and asking them
as five would turn an interview into a form, which is the failure the top of
this file describes. Every one of the five was found by running this skill
against ten concepts on 2026-08-18
(`.scratch/the-atom-has-no-context/research/01-ten-concepts-through-the-skill.md`);
two of them came from the two most ordinary atoms anybody writes next — *a tool
that sends something* and *a tool that calls a vendor*.

| Follow-up | Ask | Redirect | Ticket |
| --- | --- | --- | --- |
| **Needs** | "What does this need that the process does not already have — a credential, an endpoint, a binary, a file? For each: what is it **called**, who sets it, how do they revoke it?" | *"it's in the config"* → **which named variable?** *"the user pastes it in the card"* → refused, the document is committed; a field holds the **name**. *"it works without one on my machine"* → that is an ambient daemon, which is the Ollama defect from the other side | 09 |
| **Repeats** | "What happens if this runs twice with the same input — because it will?" | *"it won't"* → it will. `retry_policy` is graph-wide with per-node override, and a resumed `interrupt()` re-enters. A **send** is not idempotent; a **read** is, and that is a real answer worth recording | 10 |
| **Leaks** | "Does any user content leave this machine? What, to whom, and does the user know?" | *content leaving to a vendor **the module author** chose* is the one that must be said on the card — nobody picked it and nobody will find out. This is `draw_mermaid_png()`'s shape, and that rule is enforced today in exactly one place | 11 |
| **Costs** | "What does one call cost that is **not** a token — money, a metered quota, a rate limit? What happens at the limit?" | the limit is a **failure mode**: route the answer into dimension 5 with a sentence a model can act on. A `Send` fan-out multiplies calls, and a per-second cap turns that into a wall nobody simulated | 12 |
| **Stalls** | "How long does one call take, and what can the user see while it is happening?" | *"about thirty seconds"* → that is a different product from a sub-second one and needs an answer to *"is it stuck?"*. Do not invent a progress channel; `stream_writer` is on the runtime seam | 15 |

**Verify each of these rather than recording it.** A named variable is
`grep`-able. A vendor endpoint is in the code or it is not. "It's idempotent" is
a claim about a remote system and usually needs its docs read, not its author's
recollection.

**The three refusals worth knowing by heart**, because they are the ones a
developer will push back on:

- A **model-decided trigger** is a tool. The canvas is where deterministic
  structure lives; a decision the model makes belongs in the model's hands.
- A capability needed by **two different families** (retry, timeout, caching,
  logging) is a graph-assembly parameter or a collaborator — never pushed up
  into a shared ancestor. `retry_policy`, `timeout`, `error_handler` and
  `cache_policy` are `StateGraph.add_node` parameters and live on the workflow.
- A **second tier that calls a model** needs to name the judgement it makes that
  a grader downstream would not. The Guardrail node lost its second tier to
  exactly this question (`.scratch/guardrails/map.md`).

---

## The honesty gates

Run these *before* promising anything, and again before the commit. The
owner's phrasing is the law here: **do not promise which is not possible.**

**There are two sets, and running the wrong one returns a false green.** Until
2026-08-18 there was one list of eleven, presented as *the* gates and in fact
entirely about packaging, serialisation and compile targets. Run against a
database connector, **not one of the eleven fires** — so an author could pass
every gate having been asked nothing that applies to what they are building. A
checklist that is complete for one shape and empty for another, while being
named as though it were complete for both, is worse than no checklist.

The full checklist with the evidence behind each gate is
`references/honesty-gates.md`.

The gates decide whether a design is **possible**. What the built module must
**be** is a separate list and a checkable one —
`references/generated-module-contract.md`, published from the same clause data
that `check_generated_module()` enforces. Read it before writing, and run the
checker before accepting. Its own first gate is the reason it exists: every
clause names symbols in *this* installation, because the rule it replaced named
`ToolRuntime`, which this platform does not surface, and nothing noticed for a
day.

### Set A — the canvas gates

For anything that is placed or wired. A design fails if it:

1. **writes into the installed package at run time** — the wheel is read-only,
   shared, and replaced on upgrade;
2. **rewrites a package as it is copied** — copy is verbatim, byte for byte;
3. **puts `Infinity` or `NaN` in a serialisable field** — `int | None`, `None`
   meaning unbounded;
4. **adds a node class with no new compile target** — see dimension 8;
5. **assumes pip can do more than it can** — no live push of a new card into an
   open session, no `openstategraph.functions` entry-point group, an entry point
   that raises is jailed and warned about rather than fatal;
6. **promises coverage the platform cannot reach** — a node cannot act on what
   left before it ran (the live token stream is the recorded example);
7. **reads a `data` key no field declares** — that reads `""` forever, silently;
   `backend/tests/test_data_key_contract.py` now fails it;
8. **claims "zero tokens" while calling a model** anywhere in the path;
9. **lets two node types write one state key with no named reducer**;
10. **registers no browser executor** — a `standard` node without one is
    *silently skipped* in preview. Refuse honestly instead;
11. **cites a measurement without the version it ran on** — and the build must
    re-verify on the version it pins.

### Set B — the outside-contact gates

For anything that touches the world beyond the process — which includes most
tools, every connector, and any node that calls a vendor. A design fails if it:

12. **reaches a vendor without naming something a person can set, see and
    revoke.** `CLAUDE.md`'s Ollama correction, recorded because it was broken
    **by omission** for a release: the spec declared `env_vars=()` and read as
    keyless while the client reached the cloud through a local daemon signing
    with an on-disk key that never passes through the environment. Name the
    variable, in the `ProviderSpec` shape (`env_vars`, `endpoint_env`,
    `default_endpoint`) — do not restate the rule in a second place.
13. **stores a credential value anywhere** — a document is committed. A field
    holds the **name** of a variable; `SECRET_VALUE_PREFIXES` in
    `config_file.py` refuses pasted values, and it is a maintained literal list
    because the elegant rule that replaced it once was false: `ghp_aaaa…` is a
    GitHub token *and* a legal environment-variable name.
14. **is not safe to run twice, and does nothing about it.** `retry_policy` is a
    `StateGraph.add_node` parameter applied graph-wide, and a resumed
    `interrupt()` re-enters a step. A send that duplicates is a defect the
    author never chose; a read that repeats harmlessly is a property worth
    recording. The fix is never a per-node `retry` field — that is the
    cross-family violation `CLAUDE.md` names by example.
15. **sends user content to a vendor the module author chose, silently.**
    `CLAUDE.md`: never send a user's graph to a third party. Enforced today in
    exactly one place, the mermaid preview, because that was a wrong *default*
    — a tool an author wrote deliberately has no default to catch it. If content
    leaves, the node's own description says so where a person places it.
16. **holds a pooled resource across a pause.** `human.approval` compiles to
    `interrupt()` and the checkpointer is durable on purpose, so a run can sit
    for days waiting for a person. In a web application request-scope and
    run-scope are the same thing, so an experienced developer will not be
    looking for this. Scope a session to a **call**, never to a run.

**Gate 9 belongs to both sets.** Two node types writing one state key with no
named reducer is a state-schema hazard, not a canvas one, and it binds anything
that can write. That it is the only shared gate is the evidence the split is
real rather than tidy.

---

## The readiness card

Score before building. Each line is 1 point, awarded when the answer is
**concrete** — or when it is explicitly deferred *with a stated reason*, which
is a different thing from unanswered and must be written down as such.

```
CANVAS ROUTE                                            (11 points)
 1. Trigger            — deterministic / predicate / (model-decided → redirected)
 2. Payload            — the exact bytes, and their token cost
 3. Scope & lifetime   — and therefore the backend it implies
 4. Read side          — the surface, and who may edit it
 5. Failure modes      — each with its own sentence
 6. Tier & family      — and the ladder rung it occupies
 7. Ports & cardinality— types, directions, maxConnections
 8. Compile target     — a named LangGraph construct
 9. Outside contact    — needs / repeats / leaks / costs / stalls, each answered
10. Honesty gates      — Set A and Set B run, none tripped (or the design changed)
11. Smoke plan         — the one run that proves it, and what it must show
                                                        TOTAL: __/11

INFRASTRUCTURE ROUTE                                     (4 points)
 1. What it is         — the resource, its lifetime, who constructs it
 2. Outside contact    — needs / repeats / leaks / costs / stalls
 3. Honesty gates      — Set B, plus 9 if it can write state
 4. The blocker        — named, with a ticket. There is no authoring path yet
                                                         TOTAL: __/4
```

**Score the card for the route you took.** Scoring an infrastructure design
against the canvas card is how a connector reaches 3/11 and reads as
*unbuildable* rather than *out of scope* — the card misfiring rather than being
silent.

Below full marks, keep grilling. Do not build a 10 of 11 — the missing point is
the one that rewrites the other ten. **An honest "the platform cannot do this
yet, here is the ticket" is a full card**, not a failure: the answer is
concrete, and the reason for the deferral is written down.

**Write the card down before building.** The ten settled answers, in the
developer's own words where possible, become a spec — in this repository a
ticket under `.scratch/<map>/tickets/`, elsewhere whatever the project uses.
`.scratch/install-experience/tickets/17-the-tollbooth-memory-segment.md` is
exactly this artefact for the worked example, and
`.scratch/workflow-gallery/research/01-youtube.md` §"Spec" is the same thing for
the youtube atom. An interview whose result lives only in a chat log has to be
run again by the next person, and the second run gets different answers.

---

## Phase 2 — the build checklist

Every path here exists today. Work top to bottom; tests genuinely come first.

**1. Red, in Python.** `backend/tests/test_<thing>.py` — the four canonical
assertions from `docs/building-an-atom.md` (happy path, config determinism,
invalid arguments come back as data, `configure` returns a fresh instance),
plus one test per failure mode from dimension 5. Never let a test hit the
network.

If the design contains a validator, a parser or a refusal, this is where
dimension 5's adversarial input list gets spent: assert the rule against the
inputs it must refuse, one at a time, rather than against the argument for why
it holds. See `references/interview-questions.md` §5, "The second use of the
failure list" — the recorded case is a rule that was reasoned about, shipped,
and admitted exactly the value it existed to refuse.

**2. Green, in Python.** Either:
- a prebuilt platform module — `backend/openstategraph/prebuilt_<thing>.py`,
  the `prebuilt_web.py` / `prebuilt_youtube.py` shape: keyless where possible,
  works with no configuration; or
- a new rung on an existing ladder under `backend/openstategraph/abc/`
  (`tool.py`, `agent.py`, `grader.py`, `guardrail.py`, `router.py`,
  `orchestrator.py`, `middleware.py`, `prompt.py`). Implement `_execute`, never
  `run`; or

- **a function**, which has a family and a palette tier and **no ladder** —
  and needs none. `function.` is a declared census term and
  `function.format_report` is a molecule in *Reasoning & control*, but `abc/`
  holds no `function.py` because there is nothing to share: the whole contract
  is one signature.

  ```
  fn(text: str) -> str
  ```

  Three facts, all load-bearing, all recorded in `_discovered_function`'s
  docstring in `compile/node_runtime.py` and nowhere an author would look:

  - it transforms **the node's upstream text**, nothing else;
  - it gets **no model and no state** — deliberately, ticket 35: *code is
    referenced by name, never given the raw state to hide control flow in*.
    Do not widen the signature to `fn(state)` as a convenience; that is the
    exact thing that was refused;
  - a raised exception becomes **readable output**, the same errors-are-data
    rule `BaseTool.run` applies — retrying a deterministic function reproduces
    the same failure, so the useful move is to carry the message downstream.

  Discovered functions live in `workflows/<slug>/functions/` and arrive by the
  same `code → canvas` channel as discovered tools.

**3. Did you widen a shared base?** If step 2 added a member to a base class
rather than to your leaf, three things moved and none of them are in your diff
yet:

- **The census.** `backend/tests/test_public_surface_ceiling.py` counts
  *inherited* members, so one method on `BaseTool` charges all fourteen tools.
  The recorded case: `as_langchain_tools()` — declared once on the base so
  `tool.mcp` inherits the plural binding seam instead of re-declaring it — moved
  every tool's count by one and broke the ceiling test **in three places** at
  once. Two of those were tools sitting exactly at ten, which crossed on that
  single commit having gained nothing of their own.
- **The ceiling pins.** Update the recorded-exception notes with the new number
  *and the argument*, not just the number. A pin that says "twelve" and not why
  is a number the next person will edit rather than defend.
- **The call sites.** Sweep them. A base member with a default
  (`[self.as_langchain_tool()]`) silently works everywhere and is *wrong*
  somewhere — the point of widening is that one leaf overrides it.

A census that moves is the anti-duplication rule working, not failing: the
alternatives here were a special case in the compiler's binding loop or a
parallel interface every consumer must check for, and both are worse. Say that
in the pin. If you cannot make the argument, put the member on the leaf.

**4. Red, in TypeScript.** `src/nodes/**/<Thing>.test.ts` — assert the seam: the
node id string the Python `node_type` declares, the ports, the field defaults.

**5. Green, in TypeScript.** The card and its field schema. Tool atoms use
`defineToolNode` from `src/nodes/tools/AbstractToolNode.ts`; a platform atom can
join `src/nodes/tools/PlatformToolsNode.ts` rather than opening a new file. An
empty `ToolNodeModel` subclass is a test failure — pass `ToolNodeModel` itself.
Declare configuration **once** as fields; card, inspector, defaults and
validation all derive from it.

**6. Register.** App-wide: `registerNodeCatalogue` in `src/nodes/index.ts`, and
`_process_tool_layer` in `backend/openstategraph/api/registries.py` — **not**
`build_tool_registry`, which assembles layers and holds no list. Workflow-scoped:
one line in `src/nodes/workflowScoped.ts`. Discovered: drop the tool in
`workflows/<slug>/tools/` and add the slug to `pythonpath` in `pytest.ini`.

**7. Tier.** If the palette gains a section or a member, `src/nodes/vocabulary.ts`
is the single declaration and `src/nodes/vocabulary.test.ts` locks the ordering.

**8. Regenerate the port table.** `npm run generate:ports` — it rewrites
`backend/openstategraph/compile/port_specs.json`, which is committed and gated
both by `npm run verify` and by CI. Skipping this is a guaranteed red build.

**9. Pin the field contract — and for a tool atom, nobody else will.** Honesty
gate 7 says every key a factory reads must be a key some field declares, and
`backend/tests/test_data_key_contract.py` enforces it over the *compiler's*
factories. It **does not cover a tool's `configure()`**, by deliberate design
and stated in its own docstring — and `configure()` is exactly where a tool
atom's keys live. So a tool with real configuration passes the general guard
with a misspelling in every one of its keys, and produces a node that looks
configured and connects to nothing.

Write the atom's own contract test, both directions, off the regenerated
`port_specs.json` rather than a hand-kept list.
`backend/tests/test_mcp_field_contract.py` is the shape to copy: it asserts the
tool reads every key the editor declares *and* the editor declares every key
the tool reads. One note it earned the hard way: keys inside a
`repeatable-group` never reach `field_keys`, so for those read the factory's
own constant instead of losing your grip on exactly the keys a misspelling
would silence. And if the atom validates anything, both languages validate —
see the half-a-guard rule under dimension 5.

**10. Package tests.** Use `assert_document_shape` from
`backend/openstategraph/package_testing.py` for any example or package that
carries the new node. A new example also needs its entry in
`backend/openstategraph/examples/index.json` and the counts that quote it.

**11. Gates.**
```bash
npm run verify          # typecheck, lint, format:check, vitest
python3 -m pytest -q    # backend + workflow tests
openstategraph validate workflows/<slug>
```

**12. Live smoke, on Ollama cloud.** `OLLAMA_API_KEY` plus a `-cloud` model
(`gpt-oss:120b-cloud`). Never smoke against a local model: a weak model turns a
wiring bug and a capability gap into the same symptom. Record what ran, what it
returned, and which rung answered — the youtube ticket's live-smoke table is the
format.

**13. Commit.** No prefix convention. One sentence saying what changed and why —
the log reads like `RC-01: generate the port table from TypeScript; the hand
copy held 10 of 38 node types`. Add a `CHANGELOG.md` entry for anything a user
can observe. A change under `src/` or `backend/` with genuinely no documentation
surface says `docs: not-needed — <reason>`.

---

## Reference files

| File | Read it when |
| --- | --- |
| `references/interview-questions.md` | before the first question — full wordings, the reasoning each carries, the scope→backend map, follow-ups |
| `references/honesty-gates.md` | before promising anything, and again before the commit |
| `references/generated-module-contract.md` | **before the first line of a module is written, and again before it is accepted** — the shape a built module must have, published from `openstategraph.generated_module_contract` and enforced by `check_generated_module()`. It is where the seams a tool can actually reach are named; a design that needs graph state fails there, not in review |
| `references/worked-example-tollbooth.md` | to see a real interview end to end: the 2026-08-15 memory-module session, each answer and what it decided, and the spec that came out — plus the honesty notes each live client has added since, which say what this skill did not have when they ran it |

The governing rules this skill enforces are in `CLAUDE.md` at the repository
root. Where this skill and `CLAUDE.md` disagree, `CLAUDE.md` wins and this skill
is wrong.
