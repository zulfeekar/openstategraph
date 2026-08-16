# The knowledge architecture — second brain, chunked, source-generic

**Status: accepted (owner + assistant brainstorm, 2026-08-09). Supersedes
nothing; extends `mount-overrides.md`-era conventions and the initial
knowledge feature.**

## The mental model (owner's, refined together)

Progressive disclosure as architecture — three tiers of context cost, each
purchased only on the path actually taken ("chunking"):

1. **Index line** — one sentence per topic, free to always afford.
   `topics()` returns `[{name, hint}]`; the hint IS the doc's first line, so
   the index is self-assembling and costs nothing extra to author.
2. **Topic doc** — one page, fetched via `knowledge_lookup(topic)` only when
   an agent commits to that direction. Never concatenated into a prompt.
3. **Drill** — a mounted child's own store, entered only by routing there.

**Hierarchy means pointers, not copies.** The root workflow's knowledge holds
one coarse doc per child ("chinook — music-store sales Q&A over SQLite; has
its own second brain — route there for depth"), never a child's table-level
detail. Copying detail upward recreates context bloat one level up and rots
when the child rebuilds.

## The trainer — generic over sources

The build button doesn't know about databases. It knows about **sources**,
and every source answers three questions:

| Question | Mechanism |
| --- | --- |
| What are you? | **Recognition from wiring** — the workflow's own canvas declares its sources (connection scheme on sql tools, OpenAPI spec path, MCP server config). Reading, never guessing. |
| What's inside you? | **Per-kind introspection adapters** — sqlite_master / INFORMATION_SCHEMA / pg catalogs per SQL dialect; OpenAPI endpoints; MCP `list_tools` (self-describing by protocol); tabular headers. Adding an engine is an adapter, never a new builder. |
| What must an agent know before touching you? | **One shared drafting call** per topic: entity meaning, field semantics, relationships (FK joins / call-ordering / tool-argument conventions), business rules, caveats — kind-specific content, one shape. |

**Escalation ladder, cheapest first:** recognized source → mechanical adapter
(deterministic coverage, N topics = N model calls). Unrecognized source → the
**instructed explorer**: a bounded deep agent that studies the source through
the workflow's OWN wired read-only tools (if the workflow can query it, the
trainer can study it), steered by an optional developer instruction ("focus
on billing; fiscal year starts April").

Intelligence is agentic only where discovery is genuinely hard:
- `SqlKnowledgeBuilder` — mechanical (tables are enumerable).
- `CodebaseKnowledgeBuilder` — deep-agent explorer (a repo's concept map is
  not enumerable), openwiki-SHAPED output, first-party — never
  openwiki-the-binary (personal gh billing credential, wiki-shaped output,
  runtime dependency).
- `RootKnowledgeBuilder` — mechanical (children are enumerable); docs written
  to route well: first line is a great index line, body ends with the drill
  pointer. **Which children**, precisely, is below — the original text said
  only "per child" and the code read that two different wrong ways.
- `ProjectKnowledgeBuilder` — mechanical (packages are enumerable); a
  *catalogue* rather than a routing table, for a workflow whose wiring says it
  can see the whole project. Sibling of the above under
  `AbstractWorkflowPointerBuilder`, which owns the one thing they share — what
  a brief *about another workflow* is — while each concrete owns the two things
  they differ on: which workflows are topics, and what genre the doc is. See
  "The project scope" below.

## Which children the root builder writes for (ticket 16, corrected)

**Topics are the children this document MOUNTS** — the distinct slugs named by
its own `workflow.subgraph` nodes, and nothing else. A
workflow that mounts nothing yields no topics.

This is a **difference from what the code did**, not a restatement of it. The
previous rule enumerated *every published, non-hidden workflow on the
platform* and used the mounts only as a yes/no gate on whether to fire at all
(plus a `slug == "concierge"` special case). It was inverted in both
directions, and both halves were found **on disk at HEAD**, not argued:

| At HEAD | Mounted by concierge? | Routing doc? | |
| --- | --- | --- | --- |
| `chinook-nl-to-sql` | yes | yes | correct |
| `page-analytics` | **no** | **yes** | a pointer to a workflow the gateway has no edge to |
| `chinook-metrics-team` | **no** | **yes** | same |
| `workflow-architect` | **yes** | **no** | mounted, and the gateway was left ignorant of it |

`workflow-architect` is `hidden: true`, and `WorkflowStore.list()` drops
hidden packages — so the gateway got no routing doc for a child it actually
mounts, while getting two for children it cannot reach.

**The mount is the routing fact.** `published` and `hidden` describe a
package's own visibility on the `/chat` surface; they say nothing about
whether a *parent* can invoke it, because a mount compiles the child as a
subgraph and `document_loader` consults neither flag. Ticket 04's
`published_only` gate was right for the question it was asked — *"may a
routing doc send a customer to a draft they cannot open?"* — and does not
apply once the destination is reached through a mount rather than by slug.
That gate is therefore **removed from this builder**, deliberately, and
replaced by the mount set.

A mounted slug whose package will not load is a **warning**, exactly like an
unopenable SQL source: reported, never a doc, never a crash. (The concierge
has one of those too, mid-collapse.)

## The project scope (ticket 14): the project is a **source**, not a scope

The owner's ask — *"add a knowledgebase [second brain] to the project"* — names
a scope this record never covered. It reasoned about a workflow's *sources* and
a root workflow's *children*; "the project" is neither. The map's open question
put it as a fork: **one root store, or per-package stores with a root index?**

**Answered by refusing the premise: there is no project-level store, and there
deliberately never will be.** A store is only worth writing where an agent is
bound to read it, and binding is per package — `build-time-affordances.md` pins
that as mechanics: one open document is one package is one `knowledge/`
directory, and `KnowledgeLookupTool` is constructed with that directory. A
directory at the workflows root would be Markdown no runtime reads, reachable
only by inventing a second binding scope, a second "which store?" question at
every seam, and a build-time home that is neither a node affordance nor a
panel action scoped to the open workflow.

So the project joins the escalation ladder the way every other source does:
**recognition from the wiring.** A `tool.sql-*` node's connection field means
*a database is a source here*. A mount means *a child is*. A **platform tool**
(`tool.platform-list-workflows`, `tool.platform-describe-workflow`) means **the
project is** — a workflow holding one can enumerate and describe every package
on the platform at run time, so the project is something it reads.
`ProjectKnowledgeBuilder` writes its topics into that workflow's own
`knowledge/`, reached by the `knowledge_lookup` it already has ambiently.

**The project's second brain is therefore the union of the per-package ones,
plus a catalogue held by whichever workflows can see the project.** Pointers all
the way down, copies nowhere — which is the standing rule, applied to the scope
that tempted us to break it.

### Topics: what the platform tools show, minus this package, minus the mounts

Both subtractions are read off a mechanism rather than chosen, because ticket
16's whole lesson is that a topic set which *restates* a rule drifts from it.

**The visibility gate is imported from the tools** —
`prebuilt_platform.visible_to_platform_tools`, which was `_visible` and is now
public for exactly this second reader. A catalogue doc can therefore never name
a package the same agent's own `platform_describe_workflow` would refuse to
describe.

That inverts `RootKnowledgeBuilder`'s answer, and the inversion is the point:

| | `root` | `project` |
| --- | --- | --- |
| Reaches the destination by | compiling it as a subgraph | calling a platform tool |
| Does that mechanism consult `published`/`hidden`? | **no** — `document_loader` reads neither | **yes** — both, `hidden` trumping |
| Therefore a hidden/draft package | still gets a routing doc | gets **no** catalogue doc |

One rule — *the gate belongs to the mechanism that reaches the destination* —
two opposite outcomes. Ticket 16 **removed** the publish gate here and this
ticket **keeps** it, and neither is a preference.

**Mounts are subtracted** because a mounted child earns the strictly better
routing doc. Partitioning the two topic sets by construction keeps invariant
5's collision machinery a backstop rather than something that fires on every
build of a gateway.

### Genre: a catalogue is not a routing table

A routing doc says *send the question there*. A catalogue doc says *this
exists, here is what it is for, and here is when it is the wrong answer* — and
it explicitly must not tell the reader to route into a workflow this document
has no edge to.

That last clause is what makes this knowledge rather than introspection, and
the objection deserves stating because it nearly sank the whole idea:
`platform_list_workflows` already answers *what exists*, live, and
`platform_describe_workflow` already answers *what its topology is*, live. A
generated copy of either would be a copy that rots — the failure this record
forbids one level up. Neither answers **when not to recommend it**, which is
judgment a model must otherwise re-derive from raw topology on every turn. The
project already made that bet for mounts: the concierge's own system prompt
says *"Look a workflow up before describing or recommending it"* — on an agent
that also holds `platform_describe_workflow`.

**Consequence worth naming: nothing shipped grows a topic from this.** The one
workflow wiring platform tools is `concierge`, and every package it can see it
also mounts, so its project topic set is correctly empty. The natural consumer
is `workflow-architect` — which authors workflows and should know what already
exists to reuse — and it wires no platform tool today. Wiring one is a
follow-up, not a silent part of this change.

## Generating a skill from knowledge: **no** (ticket 14)

The owner's other half — *"and generate a skill"* — is refused, and the refusal
is the useful part.

`skill-layer.md` defines a skill precisely: Markdown that extends or replaces a
node's **rules**, rendered *above* the inline prompt because it is the
deliberate, reviewed customisation that should win ties. Knowledge is the other
thing entirely: **reference**, fetched on demand. Turning one into the other
fails four ways, any one of which is disqualifying:

1. **It spends the budget the design exists to save.** This module's opening
   argument is that `skills/` loads everything into every agent's context, and
   that a store behind a tool costs an index line per topic on a miss and one
   page on a hit, paid only on the path taken. A skill distilled from Chinook's
   eleven docs is eleven pages in every prompt of every turn, whether or not a
   table comes up. That is the `skills/`-at-scale failure, re-entered
   voluntarily.
2. **It creates a second, lossy copy of an authority store.** Two spellings of
   one fact, one of them stale the moment `knowledge build` runs again — and
   the stale one is the copy sitting in the prompt, which wins.
3. **It launders authorship.** A skill outranks the inline prompt *because a
   human chose it*. A generated skill carries that priority without the
   authorship: model output in the highest-priority editable layer, indexed by
   nothing.
4. **It is the one generated artifact that would not be fetched on demand.**
   Every builder writes into a store a tool reads at run time. A generated
   skill writes into the prompt — the one destination invariant "never
   concatenated into a system prompt" rules out.

The genuine need underneath the request — *the agent should know the store is
there* — is already met and costs nothing: the index tier is self-assembling,
and an unknown-topic miss answers with the whole menu. If an agent still does
not consult it, the fix is one sentence in that node's rules ("look the table
up before you query it"), authored by a person, not a generated file.

**What would change this answer.** A builder that discovers a genuinely
*rules-shaped* fact — an imperative that must hold on every turn regardless of
topic, e.g. "this connection is read-only; never emit INSERT" — has something a
lookup cannot deliver, because by then the model has already decided. That is a
different feature (a builder that emits an imperative, not a summariser that
compresses reference), it is per-package, and it is not this one.

## Where the build button lives, and how many stores a workflow has

Settled in `build-time-affordances.md`, which generalises it beyond this
feature. In short: the **Knowledge atom is a run-time node hosting a
build-time affordance** — it compiles to the `knowledge_lookup` tool, and the
button beside it is not part of the compile at all, so invariant 3 below is
structural rather than conventional. The atom declares `maxInstances: 1`, and
that already counts the right thing: one open document is one package is one
`knowledge/` directory. A mounted child is a *different* document, so a root
and a team may each hold one — the owner's collision question, answered
mechanically.

## What a developer does when the source is not a database

The button does not ask. It runs the whole ladder and reports what each rung
found, so "my source is not SQL" is never a dead end — but knowing which rung
you landed on is how you know what to fix:

1. **Recognised and enumerable** — a SQL tool's connection string. The
   mechanical builder writes one topic per table. Nothing to do.
2. **Recognised, unavailable** — a `postgres://` ref with no driver
   installed. Reported in `warnings`, never a crash: install the driver and
   press the button again.
3. **Not enumerable** — a codebase, a scraped site, anything whose concept
   map is not a list. The bounded explorer studies it **through the
   workflow's own wired read-only tools**: if the workflow can read it, the
   trainer can study it. Steer it with the optional instruction field
   (`--instruction` on the CLI, `instruction` on the build request) — *"focus
   on billing; the fiscal year starts in April"*. It reports what it did
   **not** cover rather than pretending completeness.
4. **Nothing recognised at all** — the honest answer is to write the docs by
   hand. `knowledge/<topic>.md` with no generated marker is yours, forever;
   the store, the index tier and the lookup tool do not care who wrote a
   file. Authoring the doc authors the index, so a hand-written doc gets its
   index line for free by starting with one sentence.

Adding a *new* enumerable kind is an adapter or a registered builder
(`docs/building-an-atom.md`, the `openstategraph.knowledge_builders` entry
point) — never an edit to the endpoint.

### Which of those two, for MCP and OpenAPI (register RC-06)

The build order below says "MCP and OpenAPI adapters after", and the word
**adapter** there is wrong in a way worth fixing before someone implements it.
An adapter of *what*? `IEngineAdapter` is not a generic source contract — it is
a SQL contract, and its three abstract members say so: `list_tables`,
`table_schema`, `sample`. MCP has tools, not tables; OpenAPI has operations
grouped under tags, not tables. Neither has a "sample five rows".

So the answer to "does the existing ladder fit a non-SQL source" is **no, and
it must not be made to.** Forcing `list_tools` into `list_tables` is the
Interface Segregation failure CLAUDE.md's **I** rule names, and widening
`IEngineAdapter` until three unlike sources fit is how it becomes the god
interface the **no god classes** rule forbids. The rung that generalises is the
one above it:

| Layer | Generic over sources? | Why |
| --- | --- | --- |
| `BaseKnowledgeBuilder` | **yes, already** | `source_kind` + `discover() -> Discovery`; prompt composition, the model call, the marker, the hash and the write are declared once and inherited by every source family |
| `SqlKnowledgeBuilder` | no — one family | *composes* the engine adapters; the SQL-shaped vocabulary lives here and stops here |
| `IEngineAdapter` | no — SQL dialects | `list_tables` / `table_schema` / `sample` are what a *database* is |

Therefore: **a sibling adapter ladder per source family, each composed by its
own `BaseKnowledgeBuilder` concrete** — `I*` / `Abstract*` / `Base*` /
concrete, in that family's own vocabulary. `McpKnowledgeBuilder` composes an
`IMcpServerAdapter` (`list_tools`); `OpenApiKnowledgeBuilder` composes an
`IOpenApiSpecAdapter` (`list_operations`, `operation_detail`). They meet, as
they should, at `BUILDERS` and at the shared recognition-from-wiring step —
which is composition across families, exactly as the boundary rule requires,
and not a shared ancestor. Nothing about the build endpoint changes: it still
runs the ladder and reports which rung found what.

**Scope, against the gap rather than around it.** The two are not equally
ready, and pretending otherwise is what would produce a half-built family:

- **MCP was blocked, and not on anything in this document.** An MCP knowledge
  adapter needs an MCP *client*, and this section recorded that we had none.
  *Amended 2026-08-16:* we do — `tool.mcp` binds every tool an MCP server
  offers onto an agent, over `prebuilt_mcp.py`'s `MultiServerMCPClient`. The
  original worry was that building a client inside the knowledge feature would
  put the product's first MCP integration where nobody would look for it; that
  cannot happen now, because the first one already shipped somewhere visible.
  What remains is ordinary work: an adapter that reads a server's `list_tools`
  as a knowledge source.
- **OpenAPI is unblocked but is not small.** Recognition from wiring means a
  spec path must be *declared on the canvas*, and no node type declares one
  today — so it is a new node type in the TypeScript catalogue (plus a
  `port_specs.json` regeneration) before any of the Python exists. That is a
  feature, sized and scheduled on its own, not an adapter drop-in.

The build order's third rung stands; this section is what it means.

## Ambient seeking (business rule, owner amendment 2026-08-09)

Knowledge-seeking is **ambient, not opt-in** — exactly mirroring how the
memory tools auto-attach when the runtime's Store is present ("capability by
configuration"): when the current workflow's `knowledge/` directory is
non-empty, every agent and worker in that workflow automatically gets the
`knowledge_lookup` tool, no Knowledge atom wiring required. The atom remains
the visible canvas declaration and the Build-second-brain button's home;
wiring it explicitly does not double-bind (deduped by tool name). Subgraph
children each seek their OWN package's knowledge, never the parent's — the
same isolation skills earned after the ticket-67 lesson.

## Curation contract (the UI half)

Builder generates → developer owns every word:
- **Auto-claim on edit**: the first UI keystroke removes the generated
  marker. Human touch = human ownership, no ceremony to forget — this is the
  defense against the silent-overwrite trap.
- **Stale badges apply to claimed docs too**: never overwrite a claimed doc,
  but compare the source content-hash stamped in the marker (and recorded for
  claimed docs at claim time) and badge "the source behind this doc changed".
  You keep the pen; you lose the ignorance.
- **Provenance footer**: what the builder actually looked at (files, tables,
  endpoints) — a wrong claim must be auditable to its source, because prose
  in `knowledge/` is not a hallucination anymore, it is the reference.
- Explicit save, lands in git, diffable. No autosave into an authority store.

**And the terminal half (ticket 14).** Ownership and staleness were recorded
from the first build and surfaced *only* by the editor's curation panel — the
wrong place for the one question a developer verifying a store actually asks,
which is "is any of this out of date?". `openstategraph knowledge list` now
prints the same three facts the panel shows: the index hint, the owner
(`[yours]` / `[generated: <builder>]`) and `STALE`. Nothing new was recorded to
make that work; the machinery was already on disk and merely unreachable
without a browser. The procedure that uses it — including how to tell a stale
doc from a wrong one, which have opposite fixes — is
[`../second-brain.md`](../second-brain.md).

## Invariants (violating any of these kills the feature's authority)

1. **Write-seam only.** Every builder — mechanical or agentic — writes solely
   through the store's `write_topic` seam (jail, slug rule, marker policy,
   never-overwrite-claimed). An explorer's "write capability" is this seam,
   never the filesystem.
2. **Read-only exploration, bounded budget** (recursion limit, topic cap;
   report what was NOT covered rather than pretend completeness).
3. **Build-time only.** Trainers run on the button, never during a customer
   run. The knowledge an answer relies on predates the question.
4. **Knowledge ≠ memory.** Memory (Store) is learned at runtime from
   conversations; knowledge is built from artifacts by builders. Runtime
   agents never write knowledge; promoting a runtime learning to knowledge is
   a human act.
5. **Ownership partitions rebuilds.** Markers record the owning builder;
   `owns()` gates regeneration; topic-name collisions across builders are
   refused and reported, never last-write-wins.

## Failure modes considered (each with its defense above)

Silent overwrite of tweaks (auto-claim) · staleness inversion of hand-edited
docs (stale badges) · laundered hallucination (provenance + curation)
· injection during exploration (read-only tools + write seam + marker review)
· unbounded exploration (budget) · a second browser write path (explicit
save, git).

## Build order

1. `topics()` hints (index tier) — store contract change.
2. Generic trainer core: recognition from wiring + engine adapters
   (SQLite exists; Postgres/MSSQL next; MCP and OpenAPI adapters after).
3. `RootKnowledgeBuilder` + concierge wiring.
4. Explorer fallback (bounded deep agent through workflow tools).
5. `CodebaseKnowledgeBuilder`.
6. Curation UI (edit-in-place, auto-claim, stale badges, provenance).
