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
  pointer.

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
