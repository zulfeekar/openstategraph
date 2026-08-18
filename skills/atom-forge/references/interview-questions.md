# The question bank

Eight dimensions, in order. Each entry gives the question as you should ask it,
the reasoning it carries (why this wording and not the obvious one), the
follow-ups that earn their place, and the redirect that ends the build early.

Ask **one question per turn**. The order matters because each answer narrows the
next question — answer 3 decides which follow-ups in 4 are even sensible. A
developer who receives all eight at once answers the easy ones and skips the
one that decides the design.

Contents:

1. [Trigger](#1-trigger)
2. [Payload](#2-payload)
3. [Scope and lifetime](#3-scope-and-lifetime)
4. [Read side](#4-read-side)
5. [Failure modes](#5-failure-modes)
6. [Tier and family](#6-tier-and-family)
7. [Ports and cardinality](#7-ports-and-cardinality)
8. [Compile target](#8-compile-target)
9. [Grill technique](#grill-technique)

---

## 1. Trigger

> **"What makes this happen? Is it the flow reaching this point, a condition on
> the data, or the model deciding it is time?"**

Three answers, three different products:

| Answer | What it is | Where it lives |
| --- | --- | --- |
| The flow reaches it | **deterministic** — a node | a graph node, drawn |
| A condition on the data | **predicate** — a conditional edge | a router's route, or an edge condition |
| The model decides | **a tool** | bound to an agent's `tools` bus |

**Why not ask "should this be a node?"** Because that asks the developer to
already know the answer. "What makes it happen" is a question about their
problem; the mapping above is ours.

**Redirect — the model-decided one.** If the model decides, the answer is a
tool, and for memory that tool already exists: `save_memory` in
`backend/openstategraph/memory.py`. Say so and stop. Building a node for a
model-decided write produces two mechanisms for one job, and the drawn one will
be the one that lies — its position on the canvas implies a guarantee the model
was free to ignore.

**Follow-up when the answer is deterministic:** *"Does it fire every time flow
crosses it, or can it decline?"* A node that sometimes does nothing is a node
whose card must say which it did.

---

## 2. Payload

> **"What exactly moves through it — which bytes, produced by whom? And does
> producing them cost tokens?"**

The token question is not budgeting. It is a design question: if the answer is
"the model summarises it first", there is a **model call in the write path**,
which means the node is an agent wearing another node's costume. Split it: an
agent node that summarises, then this node that records.

**Follow-ups:**

- *"Verbatim, or transformed?"* Verbatim is free, testable, and honest.
  Transformed needs a rule, and the rule needs an owner.
- *"What is the biggest this can get?"* Anything accumulating needs a retention
  answer, and retention is a visible field, not a constant.
- *"If two of these run in the same superstep, what happens?"* If they write one
  state key, dimension 7 owes you a named reducer.

---

## 3. Scope and lifetime

> **"Who else can see this, and when is it gone? Only this step? The rest of
> this run? The next time the same person comes back? Every run of this
> workflow, forever? Every workflow?"**

**Never ask "checkpointer or Store or a markdown file".** That asks the
developer to choose your implementation from a menu whose consequences they
have no way to weigh, and it invites the answer that sounds simplest rather
than the one that is true. Ask about *visibility and expiry* — their problem —
and read the backend off the answer yourself:

| Their answer | The backend |
| --- | --- |
| just this step | node-local; nothing persists |
| the rest of this run | graph state — and if two node types write the key, `Annotated[T, reducer]` |
| the next time this person comes back | checkpointer thread (short-term), keyed by `thread_id` |
| every run of this workflow, forever | Store, `MemoryScope.WORKFLOW` |
| this person, across workflows | Store, `MemoryScope.USER` |
| everything, everywhere | Store, `MemoryScope.APP` |
| **something this platform does not have** | **stop. Name it, cite the ticket.** |
| written by hand, read by the workflow | package files in git — `skills/`, `knowledge/` |

`MemoryScope` is `backend/openstategraph/memory.py`. The Store is durable by
default; the checkpointer writes one sqlite file under the workflows root.

**The last row is the one this table was missing, and a missing row does not
fail — it misroutes.** Every other row maps to something that exists, so a
requirement that fits none of them gets a confident answer that fits none of it.
The live case is **episodic memory**: `memory.py` records it as *"absent,
deliberately, and the word is here so the absence is findable"* — we hold the
raw material (thread history, `evals/*.eval.json`) and no mechanism that turns a
past run into a prompt-time example, because that is a runtime concern and we
are a compiler. An author asking to *"replay what happened last time"* maps onto
the Store, which is the wrong backend, and builds something that quietly becomes
a different feature.

So: **grep for the word before concluding the platform lacks something** —
absences here are deliberately findable by name — and when it genuinely is
absent, stop with a **pointer**, not a refusal. A dead end is not a route.

**The gate this dimension trips most often:** if the answer is "it should write
itself into the package so I can read it later", that is the read-only wheel.
An installed package directory is not writable at run time. See
`honesty-gates.md` §1.

**Follow-up:** *"If the process restarts mid-run, what should still be there?"*
This separates a developer who means durable from one who means convenient.

---

## 4. Read side

> **"Who reads it back, and how does it reach them? Down a wire as data, into a
> prompt, onto the card, or as a tool result?"**

A write with no described read side is a feature nobody can observe. Push until
there is a named surface:

| Surface | What it implies |
| --- | --- |
| a port | typed data on a wire; dimension 7 owes it a type |
| a prompt section | **Context**, composed by the machinery — not editable |
| the card | it must be true at a glance, and true *before* the run |
| a tool result | back to dimension 1: this is a tool |

**The editability redirect.** If the developer wants to edit the injected text,
they are asking to edit the machinery. A prompt is composed of Preamble
(locked), Context (generated), Rules (theirs) and Output contract (locked, and
last). Only Rules are editable. Surface the locked sections read-only beside the
editable one — never ship the contract as a pre-filled editable field, which is
the original `RouterNode` bug.

**Follow-up:** *"What does the card say when nothing has happened yet?"* An
empty state that reads as an error trains people to ignore the card.

---

## 5. Failure modes

> **"List the ways this fails. For each one, give me the sentence a *model*
> reads — not a log line, not an exception type."**

Then the one that matters:

> **"Can your code tell the difference between being *refused* and being
> *answered with nothing*?"**

That question came from a measurement: YouTube's caption endpoint answers
HTTP 200 with **zero bytes**. Reported as "no transcript", it makes an agent
describe a video it never read, confidently, from the title. Reported as a
failed download, the agent retries or says what it does not know. The same
defect had already shipped through a different door in `web_search`, where a
challenge page parsed to zero results.

Rules that fall out of it:

- **Two failures that share a sentence are one failure.** Seven conditions want
  seven distinguishable messages, and a test whose only job is to fail if anyone
  collapses two of them.
- **Errors are data, not exceptions.** `ToolResult.failure(message)` hands the
  problem back for the agent to read and retry; raising aborts the graph node.
  A block is a value — `Screening` beside `Verdict` — for the same reason.
- **Never write a denial containing the phrase it denies.** The bot-check
  message deliberately does not contain the words "no transcript", because an
  agent reading that substring inside the sentence meant to deny it is exactly
  the failure the sentence exists to prevent.
- **A refusal is evidence about us, not about the thing.** When ranking which
  failure to report, an authoritative negative answer outranks a refusal.

**Follow-up:** *"Which of these is the one that would be reported as success?"*
There is usually exactly one, and it is the reason this dimension exists.

### The second use of the failure list: run it at your own validator

The list this dimension produces is an **adversarial input list**, and it is
worth more than the error messages it was collected for. So, once the design
has a validator, a parser or a refusal in it:

> **"Write the inputs that should be refused, then run them at the rule. Do not
> reason about whether it holds."**

**The recorded example — an env var name is not a secret value.** `tool.mcp`
lets a document name the environment variable holding a server's credential
(`authTokenEnv`), and must refuse a pasted credential outright, because the
document is committed. The validator was written, and documented with a
confident argument: *every credential shape contains a hyphen or starts with a
digit, and neither is legal in a variable name.* It reads as a proof.

It is false. `ghp_aaaa…` is a GitHub token **and** a legal environment-variable
name — underscores and letters, nothing else. The rule admitted exactly the
value it existed to refuse, and would have shipped, because nothing about
reading it suggests otherwise.

What found it was a test built from the failure-modes list: the pasted-shapes
inventory this dimension had already produced, fed to the rule one at a time.
The fix is a *value*-shaped check beside the *name*-shaped one —
`SECRET_VALUE_PREFIXES` in `backend/openstategraph/config_file.py`, a literal
list of known credential prefixes (`sk-`, `ghp_`, `AKIA`, `Bearer `, …), which
is inelegant and correct where the elegant argument was neither.

Three things to take, in the order they bite:

- **A validator justified by an argument rather than by inputs is a hypothesis.**
  The more confident the sentence, the less anyone re-runs it.
- **A refusal rule needs the list of things it must refuse, written down**, and
  the list belongs in the test, not in the prose.
- **Both halves, both languages.** The editor validates and so does the loader;
  a guard that runs in one is half a guard, and the missing half is always the
  one somebody hits.

---

## 6. Tier and family

> **"Is this an atom, a molecule, or an organism — and which existing family
> does it join?"**

The tiers are declared once in `src/nodes/vocabulary.ts` and locked by
`src/nodes/vocabulary.test.ts`:

| Section | Tier |
| --- | --- |
| Inputs, Tools, Output | atoms |
| Reasoning & control (agents, routers, graders, approval, orchestration) | molecules |
| Composition (`workflow.subgraph`) | organisms |
| Annotate (`group`, `note`) | no tier, deliberately |

**The ladder is `I*` → `Abstract*` → `Base*` → concrete, and every rung earns
its place.** A hierarchy that exists only to share two fields should be
composition, and say so.

**The boundary redirect — the one to know cold.** Sharing has two axes and only
one of them is inheritance:

- shared **within** a family → abstract base class;
- shared **across** families → composition: a collaborator, a middleware slot, a
  registry, a decorator.

Pushing a cross-family concern up into a common ancestor is how "OOP everywhere"
becomes a god base class. `retry_policy`, `timeout`, `error_handler` and
`cache_policy` are `StateGraph.add_node` parameters — they belong to the
**workflow**, never to an agent base or a tool base.

**Second redirect — the paying tier.** If someone proposes a tier that calls a
model, make them name the judgement it makes *that a grader downstream would
not*. The Guardrail node was sketched with two tiers and shipped with one on
exactly this question.

---

## 7. Ports and cardinality

> **"What comes in, what goes out, what type is each, and how many links can
> each hold?"**

- **Cardinality belongs to the port, not the node.** There is no node-level
  "allows multiple edges" flag. `maxConnections` on the port descriptor; inputs
  default to 1, outputs to unlimited.
- **`null`, never `Infinity`.** `JSON.stringify(Infinity)` is `"null"`, so the
  value would not survive its own round trip and nothing would report the loss.
  Same rule for any serialisable field: `int | None`.
- **Vary the number of ports, not one port's type.** If a port sometimes carries
  a scalar and sometimes a list, its type changes at run time and the executor
  must branch — which is what typed ports exist to prevent. Use
  `ports: (data) => IPortDescriptor[]`.
- **A cycle is gated by port type.** A loop is drawable only where a node
  declares a typed feedback input, and a cycle must contain at least one
  conditional edge.
- **A port id and a field key are different namespaces** and must not share a
  name on one node: it reads as one thing and behaves as two.

Full reference: `docs/ports-and-edges.md`.

---

## 8. Compile target

> **"Name the LangGraph construct this becomes."**

Acceptable answers are things `StateGraph` actually has: a node, a conditional
edge, a `Send` fan-out, a subgraph, a compiled agent dropped in as a node, a
middleware slot, a graph-assembly parameter.

**The redirect, and it is the most valuable one in the interview:** if the
honest answer is *nothing new*, this is not a node type. It is one of:

- **configuration** on a node that already exists;
- a **template** — a scaffold that creates a workflow and then stops existing;
- a **package** to mount — the reusable definition, by reference;
- a **middleware slot** contributed by name.

The recorded refusal: *"A Loop node would compile to nothing new."*
(`.scratch/production-ready/tickets/01-a-loop-template.md`, twice — once in the
original ticket and again in the amendment that corrected everything else about
it.) The amendment is worth reading, because it shows the refusal surviving a
correct pushback: "template" was the wrong *single* answer, and "not a node
type" was still right.

Vocabulary to keep straight while answering: **a package is a definition, a
template creates one, a mount instantiates one.** Change the original later and
every mount changes; a template severed the link at creation.

Two portability rules bind the answer:

- expressions are a **JSON AST**, never host-language code — a stored lambda
  kills portability and serialisability in one move;
- reducers are a **named enum**, not arbitrary functions.

---

## Grill technique

- **One question per turn.** Always.
- **Do not accept the first abstraction.** "Memory" is not an answer; "the
  previous step's output, visible to every run of this workflow, forever" is.
- **Read the answer back in the repository's own words** and ask if that is what
  they meant. Half the redirects are found here.
- **When they push back, check whether they are right.** The loop-template
  amendment exists because the owner pushed back and was correct about the
  framing while the refusal held. A grill that cannot be moved is not a grill.
- **Write the deferrals down.** "We are not doing X because Y" scores a point on
  the readiness card. "We didn't get to X" scores nothing.
- **Stop at the redirect.** If dimension 1 says tool or dimension 8 says
  configuration, the interview is finished and successful. A build that does not
  happen because the interview found the existing mechanism is the cheapest good
  outcome this skill produces.
