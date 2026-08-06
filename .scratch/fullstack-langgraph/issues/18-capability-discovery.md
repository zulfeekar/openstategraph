Type: grilling
Status: resolved for tool capabilities (2026-08-06) — backend discovery, the frontend consumer, tool node-type registration, and hot-reload (polling, not SSE — same user-visible outcome, no new backend wiring) are all built and verified live. True node-*class* discovery beyond the `BaseTool`/tool ladder (a hand-written `Final*` node type of a kind that isn't a tool) remains unbuilt — a genuinely separate, larger question this ticket's own design section flagged. See map.md's "Implement ticket 18's node-type discovery" and "Close ticket 18's hot-reload gap" entries, `src/nodes/tools/DiscoveredToolNode.ts`, `src/app/workflowFileWatch.ts`.
Blocked by: 08, 16

## Question

Decide how hand-written code becomes an available node in the editor — the `code → canvas` channel.

The requirement: a developer defines a function (say, one that calls an API) inside a workflow's `functions/` folder, and the frontend surfaces it as a usable object. Same for `tools/`, and for skills or whatever else earns a folder. These are scoped to that one workflow and usable by any node within it.

This maps onto the existing `Registry<T>` seam: a discovered function is a **registration arriving at runtime from the filesystem** rather than at boot from a module. The palette already renders from the registry and the field schema already drives the card, so if the descriptor is right, no editor changes are needed. Confirm that holds.

Decisions:
- **What marks a callable as exposed?** An explicit decorator (`@dyflow.function`), LangChain's `@tool`, or convention (any public function with type hints)? Convention makes every private helper an accidental node — argue it out and pick.
- **Schema derivation.** LangChain `@tool` already yields a Pydantic `args_schema`; plain functions can go through `TypeAdapter` / `create_model` from the signature. Confirm Pydantic stays the single source of truth here too, consistent with ticket 02.
- **Which folders exist and what each means.** The user named `tools/`, `functions/`, `tests/`. Is `functions/` vs `tools/` a real distinction (a tool is model-callable with a description; a function is deterministic and called by an edge) or one concept with two names? Do skills get a folder?
- **Import executes code.** Discovery requires importing user modules, which runs module-level code in the backend. Same trust model as pytest collecting `conftest.py` — acceptable for a local dev tool, a real problem when hosted. Record the decision and its boundary explicitly.
- **Scoping and shadowing.** Workflow-local is the stated requirement, but shared capabilities across workflows will be wanted quickly. Decide the resolution order now (does workflow-local shadow shared?) rather than retrofitting.
- **Referential integrity.** A node references `functions.fetch_schema`; the developer renames or deletes it. What diagnostic fires, and where does it surface? Fold into `WorkflowValidator`. Note that ticket 04/05 established node names are identity, so renames can break an interrupted thread.
- **Hot reload.** Save a file, palette updates — depends on the watcher in ticket 16. What is the failure mode when a file has a syntax error?

---

## Discovering node *types*, not just callables

Clarified requirement: a developer writes `IX / BaseX / FinalX` and **`FinalX` appears in the UI**. So discovery has two distinct targets:

1. **Capabilities** — a function or tool inside a workflow, surfaced as something an existing node can *use*.
2. **Node types** — a new `Final*` class, surfaced as a new entry in the *palette*.

**The discovery predicate is folder scope AND base-class inheritance — both, not either.** Ticket 08 settled that convention is by location (`nodes/`, `functions/`, `tools/` hold concretes; `_abstract/` holds `I*` and `Base*`). Folder alone is too loose: a developer will legitimately put a helper class or a re-export in `nodes/`. So:

- **Folder** scopes *where* to look.
- **Subclass of a known base** decides *what counts*.

Together that is precise and needs no naming rules. Also settle: skip `_`-prefixed modules (Python's own private convention), and dedupe by class identity so `__init__.py` re-exports don't register a type twice.

Settle whether the two discovery targets (capabilities vs node types) share one mechanism or need two.

### The cross-process contract — this is *not* an in-process event bus

The instinct behind reaching for PureMVC was a notification bus so a new `FinalX` could "talk to frontend and backend". **PureMVC's bus is in-process only** — it would not have crossed the boundary at all. The actual need is a *wire contract plus a schema*, which decomposes into three pieces we already have decisions for:

| Need | Mechanism | Decided in |
| --- | --- | --- |
| Backend announces the node-type catalogue | a manifest endpoint returning JSON Schema per `Final*` | 07 |
| Backend pushes "catalogue changed" | SSE event on the existing stream | 07 |
| Frontend absorbs it at runtime | `NodeTypeRegistry.upsert()` → palette re-renders | already built |

So the design is: watcher fires → re-introspect `Final*` classes → emit a `registry:changed` SSE event → frontend re-fetches the manifest → `upsert` → palette updates. No new bus, and the schema stays typed end to end rather than becoming an untyped notification body.

### Hot reload: `uvicorn --reload` for dev, and that is enough

Corrected from an earlier draft that reached for a subprocess-discovery scheme. **`uvicorn --reload` is the answer for development** — it restarts the process on file change, so re-import is clean and there are no stale class objects. Vite gives the frontend the same. Nothing exotic required.

The one caveat, and it is smaller than it looks: a restart drops in-flight runs. But **runs are checkpointed to Postgres** (ticket 04), so a dropped run is *resumable from its last checkpoint* rather than lost. That is precisely what the checkpointer is for, and it turns the objection into a recoverable interruption.

What must still be settled:
- **Do NOT use `importlib.reload`.** Re-importing a module yields *new class objects* that fail `isinstance` against previously-imported bases, which would silently break subclass-based discovery. Process restart avoids this entirely; `reload` reintroduces it.
- Whether a restart should attempt to auto-resume interrupted threads, or leave that to the user.
- What the frontend shows during the restart window (a brief disconnect on the SSE stream).
- Reload is a **dev-only** facility. Production adds a node type by deploying, not by watching files — confirm that boundary so nobody ships `--reload`.

### Node type identity must be qualified, not just a class name

A concrete hazard from folder-scoped discovery: two workflows can each define `nodes/summarizer.py` with a class `Summarizer`. If `workflow.json` records the bare class name, references are ambiguous across workflows and break when a file is renamed.

Decide the qualified id — something like `text-to-sql/nodes.Summarizer` — and confirm it satisfies the stability rule from ticket 04/05 (node names are identity; renaming breaks an interrupted thread). Specifically: does renaming the *file* or the *class* change the type id, and what diagnostic fires for a workflow referencing a type that no longer exists?

## Partly resolved (2026-08-05) — capabilities built; node-type discovery is not

Built `backend/dyflow/api/capability_discovery.py` +
`GET /api/workflows/{slug}/capabilities`, answering the ticket's stated
requirement directly: a `BaseTool` subclass dropped into
`workflows/<slug>/tools/*.py` is discovered by importing it and checking
`issubclass(obj, BaseTool)` — the ticket's own "folder scopes where, subclass
decides what counts" predicate, using the `ITool -> BaseTool` ladder that
already existed rather than inventing a new marker. `functions/*.py` uses the
looser convention the ticket also named (any top-level, non-underscore
function), since there is no class to subclass a bare callable against.

Settled, as decisions:
- **What marks a callable as exposed**: folder + subclass for tools (no
  decorator needed); folder + naming convention for functions.
- **Schema derivation**: `Args.model_json_schema()` — Pydantic stays the
  single source of truth, consistent with ticket 02.
- **Qualified ids**: `<slug>/tools.<ClassName>` / `<slug>/functions.<name>`.
  Verified two workflows with an identically-named `tools/greet.py` do not
  collide, and a class re-exported through `__init__.py` is not
  double-counted (checked via `__module__`).
- **Import executes code**: confirmed and accepted, same trust model as
  `pytest` collecting `conftest.py` — no sandboxing exists or is proposed for
  local dev use.

Verified live against the **real** `chinook-nl-to-sql` workflow (not just
test fixtures): all three of its actual `BaseTool` subclasses
(`ListTablesTool`, `GetTableSchemaTool`, `ExecuteSqlTool`) were discovered
correctly through the running HTTP endpoint, schemas and all.

**Left open, honestly — this is the half of the ticket not built:**
- **Node-type discovery** (a hand-written `Final*` class appearing as a new
  palette entry) — the ticket's own harder target. The SSE-broadcast +
  `NodeTypeRegistry.upsert()` design it sketches is unbuilt; there is no
  manifest-changed event, no frontend consumer.
- **The frontend never calls this endpoint.** The palette does not yet show
  a workflow's discovered tools as usable nodes — this session built the
  discovery mechanism and its HTTP surface, not the palette integration.
- **Hot reload / referential integrity / `WorkflowValidator` diagnostics**
  for a renamed or deleted capability a node still references — none of this
  exists. `uvicorn --reload` during development is the answer the ticket
  itself settled on; not verified here.
