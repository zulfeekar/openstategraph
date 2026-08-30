# OpenStateGraph — architecture principles

Visual AI workflow builder. TypeScript editor (JointJS core) + Python LangGraph runtime.

**Before planning anything, read the maps under `.scratch/`** — each is a multi-session plan with its own tickets, and there are several live at once (`production-ready/` is the current one; `fullstack-langgraph/`, `ship-it/` and `memory-hardening/` are others). Resolve one ticket per session (research excepted).

**A resolved ticket is recorded in two places, and the commit is the one that
survives.** `.scratch/` is gitignored, so a resolution written only into a
ticket file leaves no diff, and a concurrent session's revert can take it with
no trace — which is how twenty tickets, including a data-loss blocker, came to
read `Status: open` for work that had shipped, CI-verified (production-ready
57). So: write the resolution in the ticket **and** put a trailer on the commit
that carries the work.

```
Ticket: production-ready/46
```

The map name is part of the id — every map numbers from 01. A commit may carry
several. `python3 scripts/ticket_ledger.py` reports where the ledger and git
disagree: a trailer whose ticket still says open, a ticket whose file carries a
resolution its header does not, a header citing a commit this repository does
not have. Run it before trusting any statement about what is left.

**A trailer says a commit's work belongs to that ticket — never that the ticket
is finished.** The header word for the difference is `partially`, and it covers
both shapes: half the fix shipped, *and* a different defect found on the way
shipped while the reported symptom survives (`every-workflow-green` 26 and 31,
swept 2026-08-20). Anything else is a drift row on every future run, which
teaches the two dishonest moves — mark it resolved, or leave the trailer off.

**The session that resolves a ticket has a fixed shape, and it is written down
in `skills/ticket-loop/`** — orient from the newest `.scratch/HANDOFF-<date>.md`
and the ledger, reproduce in the browser, TDD, reproduce again, commit with the
trailer, close the ticket in header *and* body, update the docs, and **write
today's handoff**. The last step is the one that gets dropped: a ticket closed
without it is a ticket the next session does not know is closed. Its date rule
matters too — the handoff is `.scratch/HANDOFF-<YYYY-MM-DD>.md` for *today*, so
when the date has rolled over you write a new file and carry the live parts
forward rather than editing yesterday's.

**Before reading source, query the code graph.** `graphify explain "X"`, `graphify path "A" "B"`. Rebuild with `graphify update .` after structural changes. The codebase is large enough that reading files to orient is a waste of context — several modules run past a thousand lines each, and `backend/tests/test_module_size_ceiling.py` records which and how big. (This sentence used to size `compile/node_runtime.py` at "over 2,000 lines"; the families were extracted and it is a third of that, so the *reason* given for a standing instruction had become false while the instruction stayed right — `docs-and-gaps/25`.)

**Before building a new module — a tool atom, a node family, a guard, a memory
construct, a function, or infrastructure such as a connector — run
`skills/atom-forge/`.** It is the agent-agnostic repo skill (plain markdown, no
Claude-specific tooling). It **routes first** (*is this on the canvas, or does
something on the canvas use it?*), then interviews across nine dimensions,
**verifies** each answer against this installation rather than taking it on
trust, **recommends** a shape, runs both honesty-gate sets, scores the readiness
card for the route taken, and only then builds through the pipeline in
`docs/building-an-atom.md`.

An interview that ends *"this platform cannot do that yet — here is the
ticket"* is a **correct outcome**, not a failed one. The law is *do not promise
which is not possible*, and it binds the interview as hard as it binds the
build.

The counts in that paragraph are pinned by `backend/tests/test_atom_forge_is_watertight.py`
rather than asserted here, for the reason this file records twice already: a
number in prose has no way to fail.

---

## Non-negotiables

### No god classes

A class with many public members is a design failure, not a convenience. If it can be described only with "and", split it.

**Ceiling: ~10 public members, one reason to change.**

`WorkflowController` (ticket 17) is fixed: **11 public members** — nine
collaborators (`controller.nodes`, `controller.edges`, `controller.history`,
...) plus `onChange` and `dispose`. Extend it by adding a collaborator, never
a method.

(Until 2026-08-15 this line said ten, and had said so since ticket 17 while the
class carried eleven. `model` is the eleventh: the one collaborator
re-exported rather than owned. Nobody added a method — the number in prose
simply had no way to fail. It is pinned now, in
`src/publicSurfaceCeiling.test.ts` alongside every other class over the
ceiling, so the next drift is a red test rather than a paragraph. The same
census runs on the Python side in `backend/tests/test_public_surface_ceiling.py`:
a class that passes ten fails until somebody records the number **and** the
argument for it.)

`WorkflowModel` is a **deliberate, recorded exception**, not a violation
still awaiting decomposition. Its internals *are* split — `AdjacencyIndex`
and `GraphQueries` hold the real implementations, independently unit-tested
— but its own public method count (`addNode`, `edgesOf`,
`topologicalOrder`, ...) was kept flat on purpose. Ticket 17's own
analysis concluded that collapsing those onto `model.queries.xxx()` /
`model.adjacency.xxx()` (the same move that fixed `WorkflowController`) is
a 100+-call-site rename across canvas, execution, and validation code for
a smaller public surface rather than a clearer design, and recommended
against forcing it. Do not re-litigate this without new evidence; do not
add new *behavior* directly onto `WorkflowModel` either way — a new query
belongs on `GraphQueries`, a new index on `AdjacencyIndex`, surfaced
through a thin pass-through only if genuinely needed.

The exception is **recorded in `src/publicSurfaceCeiling.test.ts`**, which
holds the count and this argument beside it. It was the most carefully
argued exception in this file and the least defended — an argument with no
way to fail is a story. One more member is a red test, which is exactly
what "do not add new behavior onto `WorkflowModel`" was always asking for.

The number itself is deliberately **not** restated here. It was 43 when this
paragraph was written, the pin retired two members that had no caller at all
(`install-experience` 21) and reads 41, and the sentence went on claiming 43
— a second copy of a pinned fact, which is the defect this whole section is
about, committed by the section stating it (`docs-and-gaps/25`).

### The sentence above has two clauses, and only one of them counts members

**Ceiling: ~10 public members, one reason to change.** The censuses named above
measure the first clause. Until 2026-08-30 nothing measured the second, and the
bill is on the record: `NodeRuntime` held **twenty node families as private
methods across 5,331 lines** while presenting **nine public members**, so every
session that added a family ran the census, saw green, and added one more
reason for the class to change. Nobody disobeyed. Each commit was small,
justified and correct on its own, and the only thing that could have said "this
class now has twenty reasons to change" did not exist.

The second clause now has an instrument, and it is deliberately narrow:
`backend/tests/test_a_dispatch_table_does_not_hold_its_targets.py` counts the
**distinct implementations a module registers into its own registry**, ceiling
zero, exceptions recorded with their argument in the same file. That is
`CLAUDE.md`'s own **O** turned into a test — *extend by registering, never by
editing the engine* — because twenty families behind one `builder_for` is that
pattern with every body left in the engine. The historical `node_runtime.py`
scores sixteen on it; today's scores zero.

**Module length does not cover this, and the number that settles it is 465.**
`src/view/topbar/TopBar.tsx` is the other instance the ticket named — 777
physical lines of hardcoded JSX in a codebase carrying twelve `Registry<T>`
sites — and it measures 465 code lines, under the module ceiling of 500. Length
and reasons-to-change are correlated, not the same thing.

**And here is the part nothing measures.** The dispatch census sees a registry
whose bodies were left beside it. It cannot see the *absence* of a registry —
`TopBar.tsx`'s real defect — because an absence has no signature: a hardcoded
row of five buttons that should be an extension point and a hardcoded row of
five buttons that is genuinely five buttons are the same text. There is no
TypeScript mirror of the census either, and that is stated rather than implied:
the TypeScript registration idiom takes a single object argument
(`register(new AnthropicProvider())`, `register({ id, body })`), so there is no
key-and-target pair to compare, and a literal wrapping an imported value reads
exactly like one inlining an implementation. Three broader proxies were priced
and rejected for producing false failures — the reasoning is in the test's
docstring, since a proxy that fails wrongly gets suppressed and then measures
nothing. Recorded here the way the canvas-features gap two sections down is:
as a gap, not as a list.

### And a module has one, measured in code lines

A class had a ceiling and a module had none, which is an asymmetry a reader
trips on: an eleven-member class needs a recorded exception, and
`compile/node_runtime.py` — **5,331 physical lines** when this ceiling was
written — needed nothing. It passed every rule stated in words above:
one-sentence description, one reason to change (it is the node builders), and
`NodeRuntime` the class under the class ceiling at nine members, the count
`backend/tests/test_public_surface_ceiling.py` asserts today. Passing all of that at that size is evidence the rules
were incomplete, not evidence that length is fine.

**Ceiling: 500 code lines.** A *code line* is a physical line carrying at least
one token that is not a comment and not a docstring. Physical lines are the
wrong measure **here specifically**: this repository writes long argued
docstrings on purpose — this file is one — and a physical-line ceiling would tax
the practice the rules most want and reward deleting the reasoning. Sixty-two
percent of the `node_runtime.py` this ceiling was written against was prose and
blank space and none of it was charged for: 5,331 physical lines, **2,039 code
lines**. Both figures are historical — the census in
`backend/tests/test_module_size_ceiling.py` carries today's, and the whole
descent, which is where to read it rather than here. A multi-line string that is *not* a docstring
does count, because a prompt is content somebody has to read.

**The recorded number is exact, which makes it a ratchet as well as a ceiling,
and the two are one mechanism.** The ceiling decides which modules must be
argued for; the exact number fires when one grows. No file is asked to shrink to
500. A bare ceiling would be red on day one for ten files, which is how a pin
acquires a suppression and dies; a bare ratchet would put a number on every
module in the repository, which is a config file nobody reads. The escape hatch — bump the
recorded number — is one keystroke, and that is stated rather than dressed up:
what stops it being a formality is that the number sits in the same table as the
argument, so raising it lands in review beside a paragraph that has to still be
true.

Eight Python modules and two TypeScript ones are over it today, each carrying
its number and its argument in
`backend/tests/test_module_size_ceiling.py` and `src/moduleSizeCeiling.test.ts`
— derived censuses, not hand-picked lists, for the reason the class censuses
learned: pins chosen by hand cover the files somebody already worried about,
which are the ones least likely to drift.

Splitting `node_runtime.py` is **not** what this ceiling asks for and is not
settled by it. That is `docs-and-gaps/03`, open and `partially` resolved, with a
recommended order already written. What the ceiling adds is that the next
fifteen hundred lines cannot arrive unannounced, which is exactly how they
arrived last time: the ticket was charted at 1,639, found *"stale by 2.5x"* at
4,127 when somebody finally looked, split down to 3,751, and was back over 5,300
within the week — because nothing was watching the number. Or, in the sentence
`test_public_surface_ceiling.py` opens with and this section is an application
of: **a ceiling nobody measures is a preference.**

### Interface → Abstract → Base → Concrete

Every entity family declares this ladder, and every layer earns its place:

- **`I*` interface** — the contract consumers depend on. Consumers import the interface, never the class.
- **`Abstract*`** — shared behaviour with genuinely abstract members subclasses must supply.
- **`Base*`** — a usable default implementation.
- **Concrete** — one node type, one tool, one provider.

This applies to **every** concept — node, edge, tool, provider, workflow — not only agents. Mirrored in Python and TypeScript.

Inheritance must earn itself. Where a hierarchy exists only to share two fields, use composition and say so. Depth is not a virtue.

### Shared concerns live on the base — but inherit the *capability*, not the *composition*

Anything used by every member of a family — middleware, model resolution, token accounting, retry, error handling, logging — is declared **once** on the abstract base. Never re-declared per concrete type. That is the anti-duplication rule and it is not negotiable.

The precise form matters, because LangChain middleware is a **list whose order is significant**:

- **The base owns the schema and the resolution.** `AbstractAgentNode` declares the shared config fields once and implements `resolveMiddleware(config) -> list`, the single place config becomes middleware.
- **The base does not own a hardcoded middleware list.** A base that instantiates middleware directly is a fragile base class: adding one silently changes every subclass, and a subclass has no clean way to insert its own middleware anywhere but the end.

So: **inherit the capability to compose; do not inherit the composition.**

### A prompt is composed, and the machinery is not editable

Applies to **every** node that drives a model, not just agents. Split the system prompt in two and keep them apart:

| Part | Owner | Editable? |
| --- | --- | --- |
| **Preamble** — what this node *is* | the base | **no** |
| **Context** — branch list, table schema, rubric | generated | no |
| **Rules** — the domain logic | the developer | **yes, and only this** |
| **Output contract** — the shape of the answer | the base | **no** |

`resolvePrompt()` on the base is the single place config becomes a prompt, exactly as `resolveMiddleware()` is for middleware. A developer supplies a sentence of rules and inherits a working node; a new kind of router is *configuration*, never a new class.

**Order is the substance: the output contract goes last.** Prompts are order-sensitive the way middleware is — later instructions win ties. If developer text came last, a rule like "explain your reasoning" would countermand the output format and every parse would fail. Their rules shape the *decision*; the base keeps the *shape of the answer*.

**Never ship the contract as a pre-filled editable field.** That was the original `RouterNode` bug: one `instruction` textarea pre-filled with the output contract, so clearing it — the first thing anyone does when writing their own rules — produced a router whose answer could not be parsed. Surface the locked sections **read-only** beside the editable one, so a developer can see what the machinery already says instead of duplicating or contradicting it.

**But prompt composition is a collaborator, not a base class.** Router, Grader and Agent compile to *different graph constructs*, so they are different families, and the boundary rule below applies: a shared `AbstractPromptedNode` would begin the god base class, and would force a prompt onto `CustomGraphNode`, which has none. Each family *composes* a `SystemPrompt`; nothing inherits it.

### The boundary — where inheritance stops

Sharing has two axes, and only one of them is inheritance:

| Shared… | Mechanism |
| --- | --- |
| **within** a family (all agents need summarization config) | abstract base class |
| **across** families (an agent *and* a tool node both want retry) | composition — a shared middleware/registry, a mixin, a decorator |

Pushing cross-family concerns up into a common ancestor is how "OOP everywhere" becomes a **god base class** — which violates the no-god-classes rule above and forces members to carry capabilities they do not use (an Interface Segregation failure). When a concern is needed by two *different* families, it is a collaborator, not a superclass.

### SOLID, applied concretely here

- **S** — one reason to change. See the god-class table.
- **O** — extend by **registering**, never by editing the engine. Every extension point is a `Registry<T>`: node types, executors, providers, connection rules, validation rules, canvas features, card bodies. A new capability must not require touching `core/`.

  **A registry is owned by its own layer, not by the `Workbench`.** Four hang off the `Workbench` because they are model-level; canvas features are a `Registry<IPaperFeature>` on `PaperController`, and card bodies are a `Registry<NodeBodyEntry>` in `view/`, because a `IPaperFeature` is JointJS and a card body is a React component and the `Workbench` is framework-free. What the rule asks for is the *behaviour* — a duplicate id throws, `upsert` is how you say you meant it, `list()` enumerates, and a fresh one is constructible so registrations do not leak between tests — never a common address. (Until 2026-08-16 card bodies were a bare `Map` with a setter, the only one of the seven that was not a registry; the hatch had never been used, so its shape had never cost anybody anything. Framework-packaging ticket 12. Six of the seven are walked: `src/core/extendability.test.ts`, `src/core/extendabilityRegistries.test.ts`, `src/view/nodes/nodeBodyRegistry.test.ts`. Canvas features are the one that is not, because a walk needs JointJS and a DOM — that is a gap, recorded here rather than implied by a list of six.)
- **L** — a subclass must be substitutable for its base. If an override throws or no-ops, the hierarchy is wrong.
- **I** — narrow interfaces. `INodeExecutor` and `IToolExecutor` are separate so a node opts into being a tool without carrying unused methods. Keep doing that.
- **D** — depend on abstractions. `core/` imports **neither React nor JointJS**. Never break that.

### DRY — but not by accident

Duplication of *knowledge* is the defect; duplication of *shape* is often fine. Two things that look alike but change for different reasons should stay apart.

Hard rules:
- Node configuration is declared **once** as a field schema; card, inspector, defaults and validation all derive from it.
- Pydantic is the **single source of truth** for the run/stream seam, and `docs/openapi.json` is its generated, committed publication. TypeScript is **not** generated from it: `src/core/runtime/RuntimeClient.ts` is a hand-written client, to be pinned to the published contract by a drift test rather than by codegen — the argument, and why a generator was rejected, is `docs/decisions/typescript-runtime-types.md`. A new hand-mirror **without** that pin is what this rule forbids. (Until 2026-08-12 this line claimed the types were generated. No generator has ever existed and `RuntimeClient.ts` mirrors twelve types by hand, so the claim was unciteable in review; it was narrowed to what is true rather than left aspirational.)
- One binding table drives both the keyboard dispatcher and the shortcuts drawer.

### Cardinality belongs to the port, not the node

A node has ports with different cardinalities at the same time — an agent's `prompt` takes exactly one link, its `tools` bus takes many, its `result` fans out to many. So there is no node-level "multiple edges" flag. Cardinality is `maxConnections` on the **port descriptor** (default: in = 1, out = unlimited), enforced by `capacityRule`.

Two distinct mechanisms, kept distinct:
- **A port that accepts many links** (a bus) → `maxConnections` on that port.
- **A node whose *number* of ports varies with config** → `ports: (data) => IPortDescriptor[]`.

Prefer varying the number of ports over toggling one port's cardinality. If a port sometimes carries a scalar and sometimes a list, its *type* changes at runtime and the executor must branch — which is what typed ports exist to prevent.

### Read a model's answer tolerantly; trust it strictly

**A protocol that only works when the model formats its reply perfectly is a
protocol that fails in production.** Four defects on one map, all the same
shape, all found by running the thing rather than by a test:

- `validate_workflow` typed its argument `str` — the document as a JSON string.
  The agent sent the document as an object, which is the obvious move for a
  field named `document`. Every retry re-appended the whole document until the
  provider answered 500 and the run died with a bare reference id
  (`every-workflow-green` 13).
- The capability-suggestion splitter required a ```suggestion fence. The model
  emitted the object bare, so the raw `{"nodeType": …}` was published to the
  customer and the developer lost the card — breaking a promise the function's
  own docstring makes (15).
- The orchestrator's labelling prompt renders its roster as `key: name`, so the
  model answered `writer: draft_agenda`. The parse required a bare key, every
  subtask fell to the default worker, and a wired Writer never ran once (17).
- `Grader.normalise` is the one that got it right first, and says why: a grader
  that raises on an unexpected shape turns a recoverable judgement into a dead
  run.

Note the third: **the prompt taught the model a format the parser could not
read.** When these disagree, suspect the parser.

The rule has two halves and both are load-bearing:

- **Tolerant in reading.** Accept the shapes a model actually produces — the
  object as well as the string, the line with a `key:` prefix, the reply with
  no fence, the numbered list. Try the whole thing, then its head.
- **Strict in trusting.** Every candidate is still resolved against a known
  set. An invented archetype still falls to the default worker; an unfenced
  object is taken only when it carries the keys that make it a suggestion and
  nothing else. Tolerance is never permission to act on something unrecognised
  — that is how a subtask reaches a tool-less worker on a model's say-so.

The narrowness is the safety, and it is the part that regresses. This product
prints JSON as prose constantly — SQL rows, and `workflow-architect` answers
*with an entire workflow document* — so every widening needs the test that
proves ordinary content is still left alone.

### Never put a non-finite number in a serialisable field

`Infinity` and `NaN` are not representable in JSON, and Pydantic/JSON Schema cannot express them. Use `int | None` with `None` meaning unbounded.

`maxConnections` is the worked example, and it is **fixed** — `number | null`, with the reasoning recorded at the field itself (`core/model/contracts/ports.ts`): `JSON.stringify(Infinity)` is `"null"`, so the value would not survive its own round trip and nothing would report the loss. (Until 2026-08-13 this line said `maxConnections` "currently violates this"; it had been corrected and the rule document had not caught up — the same stale-claim defect this file warns about two sections down.)

### Small, named packages

Directory = bounded context, with an explicit public surface. No `utils/` dumping grounds. If a module has no one-sentence description, it has no reason to exist.

---

## Layering — the rule that holds it together

```
gesture → Controller → ICommand → Model → event → Adapter → canvas
```

The canvas is a **one-way projection** of the model. No gesture writes to the graph and hopes the model catches up. Consequences: undo is generic, the graph is disposable, and the two cannot drift.

`core/` is framework-free TypeScript. `canvas/` owns JointJS. `view/` owns React. `design/` owns tokens and primitives and contains no app logic.

**Both halves of that sentence are gated, and they are gated by different
instruments on purpose.** A package restriction is by **name** — `react`,
`@joint/*` — and a name has one spelling, so it is `no-restricted-imports` in
`eslint.config.js`, firing on the keystroke. A layer restriction is by
**path**, and a path in this repository has at least two spellings:
`../view/AppShell` and `@view/AppShell` are the same file, and only the first
looks like a path. So the sideways rule is `src/layerBoundaries.test.ts`, which
**reads `tsconfig.app.json`'s alias table** and asks which file an import lands
on rather than how it was written.

Until 2026-08-30 the sideways rule was a third ESLint group matching
`'**/view/**'` and three siblings. It had never once fired: the codebase writes
`@view/`, which has no path segment called `view`, and `core/testing/fixtures.ts`
had walked through it. Adding the four aliases to the group was the obvious
repair and was rejected — the gate and the alias table would have stayed two
descriptions of one directory set, which is this file's named recurring defect,
so the eighth alias would have re-opened it in silence. **Never restate the
alias table. Resolve through it.** The table the gate does own is one row per
layer (`core` → `core`, `design`; `design` → `design`), and a row is a sentence
a reader can check.

Test code is exempt, declared rather than assumed: a test is not shipped and
cannot carry a framework into a worker, and `src/core/extendability.test.ts` —
the walk that proves "extend by registering" — needs a real `Workbench` to
walk. `src/core/testing/` spends that same exemption on a module that is not
itself a test, and it is the one exception; it costs a second assertion that no
shipped module imports from that directory, so the claim the exemption rests on
is a claim that can fail.

**PureMVC the framework is rejected** — layering kept, framework not adopted. Reasoning: `.scratch/fullstack-langgraph/decisions/puremvc.md`. Do not reintroduce it.

---

## LangGraph

All LangGraph and LangChain facts come from the **`docs-langchain` MCP server**. Never from memory, never invented.

Settled vocabulary:
- **Graph** = `StateGraph` — nodes, conditional edges, shared state, `Send` fan-out, subgraphs.
- **Loop** = `create_agent` (ReAct). It returns a compiled LangGraph, so it drops into a `StateGraph` as a node.
- Therefore **canvas = StateGraph, Agent node = the loop, workflow composition = subgraphs.**

#### "Loop" means two things, and only one of them may reach a user

The vocabulary above is **internal**. `Loop` there is the ReAct tool-calling
loop *inside one agent*. A user arriving from the "loop engineering vs graph
engineering" discourse means something else entirely: the **feedback cycle
across nodes** — run a step, check it, run it again with the errors included.

Both are real and both exist here. The collision lands exactly where a user
reads, so the user-facing words are fixed:

| User-facing word | Means | Must never mean |
| --- | --- | --- |
| **Revision loop** | grader `revise` → agent `feedback`; ends when the grader passes or the step budget runs out | the agent's internal tool-calling |
| **Step budget** | `recursion_limit` — **supersteps** | "iterations" or "max turns"; one lap with fan-out costs several supersteps |
| **Workflow node** | another workflow run as one isolated step — task in, answer out | inline expansion, shared state |
| **Template** | a starting document; it produces a workflow and stops existing | a node type; a reusable definition |
| **Package** | the reusable definition — `workflows/<slug>/`, the thing a mount points at | a PyPI distribution, in user-facing copy |
| **Instance** | one mount of a package, carrying its own `data.overrides` | a copy of the package |
| **Slug** | a package's folder name — `workflows/<slug>/`, `?w=<slug>`, and what a mount field asks for. **Minted by the backend at first save and frozen**, because a slug that moves renames a directory | a title, a display name, or anything a user chooses or edits |
| **Replay** | reading a recording back — a **profiler**, not a re-execution. Offsets are the server's own `elapsedMs` from stream open; the playhead spends nothing and produces no new run | a re-run; LangGraph's own *replay*, which **re-executes nodes** and fires the model calls again (`/oss/python/langgraph/use-time-travel`, confirmed 2026-08-29). The two words collide exactly where a reader following those docs lands |
| **Re-run** | forking a run from a checkpoint and executing it again — costs model calls, and produces a *different* run. Not built here; if it is ever offered it is a different button, in a different place, with a cost-and-consequences confirmation | a second mode of the play button, or anything the transport does |
| **Eval** | grading a workflow **offline** against a committed dataset of questions whose answers are known — `openstategraph eval`, `<package>/evals/*.eval.json` | the grader node's in-run judgement, which routes rather than scores |
| *(internal only)* the loop | `create_agent` / ReAct | anything in UI copy |

#### "Template" also meant two things, and this settles it

The same collision as *loop*, found the same way — a reader used "template" for
the **reusable definition** a mount points at, while `templates/index.json` uses
it for the **scaffold**. Both senses were live in this repository's own
documents, so this was a naming decision rather than a tidy-up.

**Settled: "template" is the scaffold sense only.** It is already the CLI flag
(`--template`) and the editor's *Start from* picker, so the word is spent. The
reusable-definition sense is **package**, which is what the filesystem, the
docs and `mount-overrides.md` already call it.

That gives three words and three jobs, with no overlap:

> **A package is a definition. A template creates one. A mount instantiates one.**

The test that separates them, and the one a user actually cares about — *if I
change the original later, does this change too?*

| | Mechanism | Change the original later |
| --- | --- | --- |
| Mount a package | by **reference** | every instance changes |
| Start from a template | by **copy** | nothing changes; the link was severed |

#### And a slug is a name a user never chose

`say-it-on-the-surface` 03. The word was on **five** surfaces — the mount
field's label, every Packages palette row's description, the Workflows panel,
the create toast, and `?w=` — and defined on exactly one, inside a panel a user
may never open. So a required field asked for a machine name nobody had
introduced.

The behaviour was never the problem and did not change. What changed is where
the word appears: it survives where it genuinely *is* the identity — the folder
path, the URL, and the create toast that names the one thing a user could not
have predicted — and the mount field is labelled **Workflow**, with the hint
explaining the identifier. The Packages section introduces it once, beside the
rows that print it.

Pinned by `src/nodes/compose/slugIsExplained.test.ts`, including the clause
that must **not** appear: nothing may imply the list is exhaustive, because the
field is a combobox and not a listbox on purpose — mounting a package you have
not built yet is a real way to work.

`docs/on-the-canvas.md` is written to this lexicon and is where a user meets it.

**A loop is a cycle in the graph, not a wrapper around one.** That is the
substantive difference from the popular framing, which treats loop and graph as
two techniques you compose. Here they are one substrate — which is why the
answer to "how do I add a feedback loop" is two edges rather than a different
tool. The genuine *outer* loop of that framing — retry and stopping policy
around the whole thing — is `retry_policy` / `timeout` / `set_node_defaults`,
graph-assembly parameters that live on the workflow (see below), never a node.

**Eval is not a third axis.** Graph and loop are two shapes of one substrate —
both are drawn, and both compile into the `StateGraph`. An eval is neither
drawn nor compiled: it is the same judgement machinery pointed at a dataset
instead of at a run. A grader's verdict is an **edge** (`pass`/`revise`,
consumed by the graph); an eval's verdict is a **destination** (a scorecard,
consumed by a human or a CI gate). Same judge, different consumer, different
clock. So there is no eval node, and there should not be one — the dataset is a
package file, and if the editor ever surfaces an eval it is a panel, not a node.
`docs/evaluation.md` §"Grading during a run vs grading a dataset" carries the
long version, including the third thing that is neither: a package's `tests/`,
which asserts the *document* and calls no model at all.

### Agent type is a developer choice, and it mirrors the library's own layering

LangChain publishes three tiers — *framework, runtime, harness*. A developer picks which one an Agent node is:

| Tier | Construct | Node type |
| --- | --- | --- |
| LangGraph (runtime) | hand-written `StateGraph` node | `CustomGraphNode` |
| LangChain (framework) | `create_agent` — minimal configurable harness | `ReactAgentNode` |
| Deep Agents (harness) | `create_deep_agent` — batteries-included | `DeepAgentNode` |

`create_deep_agent` **pre-assembles a middleware stack on top of `create_agent`** — but read that precisely: it is `create_agent` **plus a fixed slot assembly, not plus subclassing**. The library expresses the relationship as *data*, so `DeepAgentNode` is a **sibling** of `ReactAgentNode` under `AbstractAgentNode`, differing only by which middleware preset it declares. (An earlier draft here said `DeepAgentNode extends ReactAgentNode`; that was wrong and is superseded — it broke leaf semantics for no gain once the stack is data.)

### Middleware order is a slot table, never a list position

Because list position means **three different things at once**:

| Hook | Order |
| --- | --- |
| `before_*` | first to last |
| `after_*` | **last to first (reverse)** |
| `wrap_*` | nested — the first middleware wraps all others |

So `super().resolveMiddleware() + [mine]` does *not* mean "mine runs last". It means: my `before_*` runs last, my `after_*` runs **first**, and I am the innermost wrapper. **Any scheme expressing position as one number — append, prepend, or a priority integer — is expressing something that does not exist.**

Therefore `resolveMiddleware()` returns an **ordered, name-keyed slot table**; the base owns the canonical slot order, a subclass or plugin contributes by *naming a slot*, and replacement is by slot name. The compiler flattens to a list last. This mirrors `create_deep_agent`, whose 12-slot order encodes documented semantic constraints (Skills before Filesystem so skill metadata precedes file tools; Memory after prompt caching so injected memory does not invalidate the cache prefix). Never expose a raw ordering number to a user — it would let them express an invalid order silently.

### Retry, timeout and caching are graph-assembly parameters, not node concerns

`retry_policy`, `timeout`, `error_handler` and `cache_policy` are parameters of **`StateGraph.add_node`**, available to every node of every family, and `StateGraph.set_node_defaults(...)` applies them graph-wide with per-node override. So they live on the **workflow** and compile to graph assembly — never on an agent base, a tool base, or a shared ancestor.

This is the cross-family boundary rule confirmed by the runtime: putting `retry` on an agent base would force a duplicate onto the tool base and then two spellings of one feature. Token accounting and logging stay deliberately **not** unified — middleware for agents, callbacks/tracing elsewhere — because unifying them would invent an abstraction LangGraph does not have.

### Ollama means Ollama **cloud**, never a local model

Standing instruction, with direct evidence. `llama3.1:8b` running locally could not
hold `response_format` at all, took minutes per run, and answered a Chinook database
question from parametric knowledge — confidently, about global music revenue, having
queried nothing. The same workflow on `gpt-oss:120b-cloud` wrote a correct two-join
`GROUP BY` and answered in 23 seconds.

So: a bare `ollama:` fallback resolves to `OLLAMA_CLOUD_MODEL`, the model picker sorts
`-cloud` models first and labels local ones as local, and a local model must be named
explicitly to be used. Never benchmark, demo or debug against a local model and treat
the result as representative — a weak model turns a wiring bug and a capability gap
into the same symptom.

**The cloud is reached by `OLLAMA_API_KEY` plus an endpoint default, not by an
ambient daemon.** Until providers-and-credentials ticket 02 this rule was stated
and not enforced: Ollama's `ProviderSpec` declared `env_vars=()` — presented as
"keyless" — while nothing passed an endpoint at all, so `ollama.Client` dialled
`127.0.0.1:11434` and the cloud was reached, when it was reached, through a local
daemon signing with `~/.ollama/id_ed25519`. That credential never passes through
the environment and cannot be seen, moved or revoked from one, and on a machine
with no daemon running `/api/health` still reported `model_configured: true`. The
rule was being broken by omission rather than by decision.

It now declares `env_vars=("OLLAMA_API_KEY", "OLLAMA_HOST")` and
`endpoint_env=("OLLAMA_HOST", "OLLAMA_ENDPOINT")` with `default_endpoint =
"https://ollama.com"`. Because `is_configured` takes **any** of `env_vars`, two
setups coexist and both are supported: the key alone is the cloud; `OLLAMA_HOST`
alone is a daemon you run, which needs no key of ours because it owns its own
auth. Endpoint precedence is tuple order — your host, else `OLLAMA_ENDPOINT`,
else the cloud. Never restore a spec that reaches a vendor without naming a
variable someone can set, see and revoke.

### Never send a user's graph to a third party

`draw_mermaid_png()` defaults to posting the graph to the **Mermaid.Ink API**. Use **`draw_mermaid()`**, which returns Mermaid text with no network call and no extra dependency, and render it in the frontend. Compiled-graph previews come from `draw_mermaid()` on the compiled graph, so a preview shows what the compiler actually produced rather than a hand-drawn approximation that can drift.

**LangGraph's `xray` expands nothing here, and never will — so a composition is drawn by us.** `xray=True` opens a *LangGraph subgraph*, and this compiler emits none: an agent is built lazily inside its node's closure, and a mount is a closure over the child's `invoke()`. A function is opaque, so this is not a flag anyone can turn on. `backend/tests/test_behind_the_scenes.py` still pins that fact about LangGraph, and fails on the day a node type compiles to a real subgraph.

What it is **not** is a reason for a composition to render as one featureless box, which is what it was until `workflow-gallery` 28: `nested-mounts` — three documents, three levels, six nodes below the top — drew three boxes and nothing about the nesting survived. **`CompiledWorkflow.mermaid(xray=True)` now opens every mount to any depth**, from what the compiler recorded while it built the child (`NodeRuntime.mounted_graphs` → `compile/composition.py`), splicing with LangGraph's own drawable `Graph.extend` so the output is ordinary `subgraph` blocks. `mermaid(xray=False)` still draws what LangGraph itself holds — one box per mount — and that is the honest picture when a mount is the suspect. An agent stays one box either way: it has no second document to show.

Two sentences of this paragraph have now been wrong in opposite directions — before 2026-08-16 it claimed the expansion happened; after it, the correction read as a statement about the *preview* rather than about LangGraph. That is why the behaviour is pinned in `backend/tests/test_mount_composition_preview.py` against a package that actually mounts, rather than described here.

**The editor's preview endpoint now opens mounts too, in both audiences**
(`api/routes/workflows.py`, `workflow-gallery` 56). The obstacle that held it
back was real and was solved rather than routed around: the customer-audience
relabelling read node ids out of the *parent* document, and a spliced child's
ids are not in it, so a nested diagram would have kept the compiler's own
vocabulary for every node below the top. The route therefore **loads the child
documents** — the compiler says which package each mount runs, the package's
document says what its author called the nodes inside it — and titles are
scoped by mount path, because `in1` exists in all three of `nested-mounts`'
documents. A block carries the title the parent's author gave the mount. A
child that will not load costs the labels below it and nothing else.

**`mcp_server.py`'s `compile_workflow` stays flat, and that is the honest
answer there.** That path is stateless and holds no workflow library, so a
mount resolves to nothing and there is no child graph to splice; its docstrings
say so, and its `warnings` already name the capability that did not resolve.
`run_workflow` on the same server is the other case — it *ran* the children, so
it can draw them, and does.

**The run surfaces draw exactly what the preview draws** (`workflow-gallery`
62). `RunResponse.mermaid`, the terminal SSE `done` frame and `run_workflow`
each called `get_graph().draw_mermaid()` and so made neither of the two calls
above: a caller who had asked for the customer channel received `__start__`,
`__default_error_handler__` and `safe_name`d ids beside its answer, with every
mount as one box. They are one seam now — `api/diagram.py`'s
`workflow_mermaid`, which the preview route calls too — because four call
sites that must each remember two calls is a defect with a fifth instance
waiting. A run answers "what just ran" and a preview answers "what did the
compiler build", but about the same compiled graph, and two shapes for one
workflow is a worse answer to both.

`backend/tests/test_a_runs_diagram_opens_its_mounts.py` fails the day a fifth
surface draws its own, by parsing every module under `openstategraph/` for a
bare `draw_mermaid()` call.

### Cycles are gated by port *type*, and the step budget is not an iteration count

A loop is drawable only where a node declares a typed feedback input (`GraderNode.revise: feedback` → `AgentNode.feedback`). The type system stays the gate, so an *accidental* cycle remains inexpressible while the evaluator-optimizer pattern is two clicks. A cycle must contain at least one conditional edge — an all-static cycle can never terminate.

`recursion_limit` is a **standalone `config` key, not inside `configurable`**, and overrunning it raises `GraphRecursionError`. **Ours is 50**, and that is the number actually in force — `DEFAULT_STEP_BUDGET` in `backend/openstategraph/step_budget.py`, `STEP_BUDGET_DEFAULT` in `src/view/workflow/stepBudget.ts`, both pinned by tests. **LangGraph's own default is deliberately not quoted here, and that is a rule rather than an omission** (`docs-and-gaps/17`): it is `getenv("LANGGRAPH_DEFAULT_RECURSION_LIMIT", ...)` evaluated at import time, so it is a property of the machine as much as of the release, and no literal written down stays true. This sentence has now been wrong twice in opposite directions — once naming only the library's numbers so a reader looking for the budget in force found the wrong one, then again by carrying a library number that had moved by more than tenfold — which is the whole case for stating ours and deriving theirs. `backend/tests/test_a_library_default_is_never_literalised.py` fails on the next attempt to put a number back, and records the other library facts this file states beside it. It counts **supersteps, not iterations** — with fan-out, one lap of a loop can cost several supersteps — so never label it "max iterations" in the UI. Prefer generating a `RemainingSteps` guard so a runaway loop routes to `END` instead of crashing.

### State flows down; subagents do not receive it

Two distinct mechanisms, easy to conflate and important not to:

- **Graph state** flows to *nodes* through the shared state schema and reducers.
- **Subagents are isolated.** A subagent is invoked as a *tool*; its result comes back as a `ToolMessage` (JSON when `response_format` is set, otherwise its last message text). It never sees the parent's message history or graph state — it receives a task and reports a result.

Never build UI or state plumbing that implies a subagent shares the parent's context.

### A state key more than one node type can write needs a named reducer

A bare scalar field (`answer: str`) is only safe for state exactly one node
type ever produces. The moment two node kinds can legitimately write the same
key, use `Annotated[T, reducer]` — never a plain `LastValue` field. This was
found live, not hypothetically: a real graph combining a router, `Send`
fan-out, and multiple tool-using workers scheduled two `answer`-writing nodes
in the same superstep, and LangGraph raised `InvalidUpdateError` on a field
every scripted, single-writer-at-a-time test had exercised without incident.
`decisions`/`outputs`/`subtasks`/`worker_results` already followed this rule;
`answer` did not, and the gap was invisible until a real fan-out/join subgraph
ran. Applies to every future compiled workflow state schema.

### Portability guardrails

We go **deep on LangGraph** deliberately — no `IOrchestrator` abstraction, because no competing framework accepts a serialisable graph, so such an interface is unbindable rather than merely leaky. Portability is preserved instead by keeping `workflow.json` the vendor-neutral layer and obeying four rules that cost nothing now and are expensive to retrofit:

1. **Expressions are a JSON AST, never host-language code.** A router predicate is serialisable data — never a Python or JavaScript lambda. Storing a function kills portability *and* serialisability in one move.
2. **Reducers are a named enum**, not arbitrary functions.
3. **The compile seam is one-directional**: `workflow.json` → runtime. Nothing reads runtime objects back into the model.
4. **Our own runtime vocabulary.** Do not leak LangGraph type names into `workflow.json` or into `core/`.

**There is a third direction, and rule 3 was silent about it.** `code → canvas`
is real, sanctioned and load-bearing: `api/capability_discovery.py` imports a
package's `tools/*.py`, and `src/app/capabilityRefresh.ts` →
`src/nodes/workflowScoped.ts` → `src/nodes/tools/DiscoveredToolNode.ts` mints a
node **type** whose id is the Python qualified name
(`<slug>/tools.QueryTool`) — placeable, and therefore writable into a document
as `"type": "chinook-assistant/tools.QueryTool"`. A reader checking rule 3
against the code found a channel the rule does not mention, which is how a
guardrail stops being one (production-ready 46, item 2).

It does not breach rule 3 — that rule is about the *compile* seam, and this is
neither of its directions: nothing reads a runtime object back into the model.
Two properties keep it safe, and they are the boundary:

- **The type id is data.** A string in `workflow.json`, exactly like every
  built-in type id. No Python object, no import path to resolve at load time,
  nothing host-language about it.
- **The type travels with the package.** `tools/` sits beside `workflow.json`,
  so a document naming one of these types is portable to anywhere that carries
  the package — which is the same promise a built-in type makes about the
  runtime.

The cost, stated so nobody rediscovers it as a bug: a document can name a type
absent from `port_specs.json`, resolvable only by importing the package's
Python. The editor already handles that case as an unknown node type, preserved
exactly as saved.

**And there is a fourth channel, which is the third one's shape without its
second property** (`rules-that-can-fail/02`). `src/app/pluginNodes.ts` mints an
**app-scoped** node type per tool an installed **pip distribution** contributes
through `[project.entry-points."openstategraph.tools"]`, so a document can hold
`"type": "tool.acme-ping"` for a type that lives in somebody's virtualenv. It
does not travel with the package, and no field in `workflow.json` names the
wheel it needs.

Measured before it was ruled on, which changed the ruling: **"travels with the
package" is the wrong test, and it always was.** A built-in type does not
travel with the package either — it travels with the runtime, and nothing
thought that unsafe. What actually does the work in both cases is that the id
is **data that is resolved against a known set, and named when it resolves to
nothing**. So all four channels are safe on two properties, and the second one
is restated:

| Channel | Type id | Where the implementation lives |
| --- | --- | --- |
| built-in | data | the runtime |
| `code → canvas`, package `tools/` | data | beside `workflow.json` |
| `code → canvas`, entry-point plugin | data | an installed distribution |
| *(none)* | — | never a host-language object in the document |

- **The type id is data**, in every one of them.
- **An id nothing resolves is reported by name, and an id two sources both
  claim is reported with both names.** The first was already true — a document
  naming `tool.acme-ping` with no such distribution runs, is not refused, and
  says `No implementation for tool "tool.acme-ping"` on the developer channel.
  The second was true of two of the three places a tool type can be claimed
  twice and silent in the third; making it true was this ticket's work.
  `backend/tests/test_a_plugin_node_type_says_which_one_ran.py` is the
  instrument, one class per case.

The plugin channel therefore carries **one cost the other three do not**, and
it is recorded rather than fixed: a package cannot declare the distributions
its document depends on. `workflow.json` is the vendor-neutral layer (rule 4)
and a Python wheel is not vendor-neutral, so the field would be a portability
claim the format cannot keep — but omitting it does not make the document more
portable, only quieter about it. `OPENSTATEGRAPH_DISABLE_PLUGINS=1` is the
reproducibility answer that exists today and is documented in
`docs/building-an-atom.md`.

Adding a second runtime later is roughly an engineer-quarter, and permanently multiplies the cost of every new node type. Do not pay it speculatively.

### We are a compiler, not a runtime

Three distinct approaches exist. Know which one this is:

| Approach | Who executes | Examples |
| --- | --- | --- |
| Own your executor | you write the engine | n8n, Dify, Langflow, Flowise |
| Multi-runtime compiler | abstract over several | Oracle Agent Spec (the only one) |
| **Single-target compiler** | someone else's | **this project → LangGraph** |

**Never write an execution engine.** We compile `workflow.json` to a LangGraph `StateGraph` and inherit its checkpointing, time-travel, `interrupt()`, `Send` fan-out, reducer merging and streaming. Any proposal to "just interpret the graph ourselves" is a proposal to reimplement all of that — reject it.

The consequence worth protecting: those four tools are closed systems, where a workflow runs inside their platform or not at all. Our output is a standard Python object that runs anywhere Python runs — importable from a script, testable with pytest, deployable without this editor. **The compiler is not portable; the output is.** That is what makes `functions/`, `tools/` and `tests/` real code rather than decoration.

---

## Tests

TDD. Tests before implementation. `core/` is pure TypeScript and directly unit-testable — there is no excuse for untested logic there.

Never refactor a god class without tests in place first.

## Worktree economy

A git worktree of this repo must NOT install its own dependencies — each
copy costs ~420M (`node_modules` 183M + a venv 235M) for nothing. Instead:

```bash
ln -s "$(dirname "$(git rev-parse --git-common-dir)")/node_modules" node_modules
```

**Derived rather than typed**, because the absolute path written here was a
directory that did not exist — the checkout moved and this line did not, so
copy-pasting it made a dangling symlink, the build failed obscurely, and the
obvious recovery was the `npm install` this section exists to prevent
(`docs-and-gaps/25`). `git rev-parse --git-common-dir` answers with the *main*
checkout's `.git` from inside any worktree, so its parent is the main checkout
wherever it lives.

and use the system `python3` (the backend's deps are installed user-level;
`python3 -m pytest` works with no venv). Never run `npm install` or create
a `.venv` inside a worktree unless a dependency actually changed — and if
one did, do it on the main checkout and re-link.

<!-- OPENWIKI:START -->

## OpenWiki

This repository uses OpenWiki for recurring code documentation. Start with `openwiki/quickstart.md`, then follow its links to architecture, workflows, domain concepts, operations, integrations, testing guidance, and source maps.

The scheduled OpenWiki GitHub Actions workflow refreshes the repository wiki. Do not hand-edit generated OpenWiki pages unless explicitly asked; prefer updating source code/docs and letting OpenWiki regenerate.

<!-- OPENWIKI:END -->

Everything between the OPENWIKI markers above is stamped verbatim by
`openwiki code --update` on every run — a hand-edit inside the markers does
not survive the next run, which is why this correction lives outside them.
The stamped claim that the scheduled workflow "refreshes the repository wiki"
describes intent, not observed behaviour:

> **This workflow has now run, once, and failed** (2026-08-17, scheduled, run
> `32004530549`, 41s): *"OPENAI_API_KEY is required for non-interactive runs.
> Run openwiki in an interactive terminal to save credentials."* No model key
> is configured in the repository's secrets, so the scheduled job cannot
> produce a page and will fail identically every night until one is. Until
> 2026-08-17 this line said the workflow had never run at all, and that is the
> correction: it is no longer "never executed", it is **executing and failing**,
> which is a different fact with a different fix (add the secret, or retire the
> schedule).
>
> Either way the practical instruction is unchanged: "let OpenWiki regenerate"
> means *a human runs it locally*, and a generated page you leave stale stays
> stale.
>
> **The blanket version of this warning is itself now stale, and that is the
> point.** Until 2026-08-16 this block said the repository had "zero git
> remotes, so nothing in `.github/` has ever executed — not this, not the type
> gate, not the drift gates, not `clean-install`". A remote (`beta`) exists,
> and **CI does run and does pass** — 25 green runs including `clean-install`
> and the generated-artifact drift gates, alongside 24 Release runs. Corrected
> rather than deleted, because a rule document asserting the gates are theatre
> is more dangerous than one asserting they are real.
>
> One exception survives and is worth knowing by name: `pages.yml` has run
> four times and **failed four times** — see
> `.scratch/production-ready/tickets/28-the-gallery-nobody-could-see.md`.
> `openwiki-update.yml` is the paragraph above: it *has* run, once, and
> failed — this line said "never" beside that dated account for as long as
> both stood, and the dated one carries a run id (`docs-and-gaps/25`).
>
> **`docs-freshness` is no longer PR-only**, and this line said it was for
> four hours short of a day after `df8ce54` removed the `if:`. It runs on a
> push to `main` too, comparing `github.event.before` to `github.sha`; it
> exits 0 rather than skipping when there is no range to compare. Four
> documents carried the old sentence and one commit changed the yaml, which
> is why the claim is now derived from `ci.yml` by
> `backend/tests/test_no_document_repeats_a_retracted_claim.py` instead of
> being repeated in prose (`docs-and-gaps/28`).

**A generated page now says which commit it came from** (`docs-and-gaps/27`).
Staleness under the paragraph above is structural rather than careless, and
the defect was never the staleness — it was that no `openwiki/**` page carried
a date, so a contributor had nothing distinguishing a current page from a
nine-day-old one. `scripts/stamp_wiki_freshness.py` copies the commit and date
out of `openwiki/.last-update.json` onto the pages themselves, above the first
heading.

The stamp **does not survive a refresh**, for the reason this section is
already about: the generator writes each page whole, and we do not own the
generator. That is why it is a script and a test rather than a hand-edit — a
refresh deletes every stamp at exactly the moment every stamp has gone wrong
anyway, and `backend/tests/test_a_generated_wiki_page_says_when_it_was_generated.py`
turns the deletion into a red test naming each unstamped page instead of a
silence. Run the script after `openwiki code --update`. Nothing in the stamp
counts days or commits behind: it names the commit and hands the reader
`git log <sha>..HEAD`, because a number in prose has no way to fail.
