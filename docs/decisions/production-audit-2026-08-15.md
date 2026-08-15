# Production audit — 2026-08-15

The owner's final sweep before 10/10 (install-experience ticket 05): memory
leaks, data structures and algorithms, architecture principles, extendability.
Baseline: `docs/decisions/architecture-audit-2026-08.md` (2026-08-09, commit
`6139a6c`) and its pins in `backend/tests/test_architecture_audit_2026_08.py`.

**Scope: 185 commits, 803 files** — `6139a6c..HEAD`. The ticket said "~40"; the
real number is what git reports. The gallery, guardrail, orchestrator, route-
split, UX and install-story work all landed inside it, as did two sweeps of the
same family (`781c672` "Thirty verdicts", `b54231b` "NodeRuntime was
twenty-six public members"), whose conclusions this audit re-measures rather
than repeats.

**Method, per the ticket: nothing here is asserted from reading alone.** Every
leak claim carries a reproduction or an execution trace; every complexity claim
carries a doubling series; the extendability claim is a *walk* that now lives in
the test suite. Where a finding could only be established by reading — because
the harness to run it does not exist in this repository — that is said in the
finding itself, not glossed. The one framework claim made below
(`RunControl.request_drain()`'s stopping boundary) was verified against the
docs-langchain MCP server on the audit date.

New pins: `backend/tests/test_production_audit_2026_08_15.py`,
`src/core/extendability.test.ts`.

---

## What was measured and found sound

These are negative results, and they are the reason the findings list is as
short as it is. Each was produced by running something, not by reading it.

### Compiling a package repeatedly leaks nothing

100 × `load_workflow()` on `workflows/workflow-architect`, after a 3-cycle
warm-up to pay every lazy import, with a stub chat model:

| arm | fds | net objects | heap |
| --- | --- | --- | --- |
| `.close()` called | +0 | −1 | +37.8 KiB total, flat from cycle 20 |
| handle dropped | +0 | −2 | +38.3 KiB total, flat from cycle 20 |

The second arm matters more than the first: `load_workflow` opens a real
`SqliteSaver` every call (verified — `langgraph.checkpoint.sqlite.SqliteSaver`,
with `.openstategraph/checkpoints.sqlite{,-shm,-wal}` created under the root),
so a forgotten `.close()` *looks* like a descriptor leak and is not — the
connection is released on collection. The fd counter was itself validated
(opening 20 files moved it from 4 to 24), because a leak probe that cannot
count is worse than no probe. Frozen as a pin.

### The compile and validation seams are linear in document size

Synthetic documents, agents in a chain with a bound tool every tenth, timed
best-of-3:

| nodes | `WorkflowCompiler.plan()` | `validate_document()` |
| --- | --- | --- |
| 57 | 0.058 ms | 0.237 ms |
| 112 | 0.111 ms | 0.418 ms |
| 222 | 0.206 ms | 0.843 ms |
| 442 | 0.395 ms | 1.744 ms |
| 882 | 0.808 ms | 3.418 ms |

Doubling ratios 1.85–2.05 throughout — linear, on both. `plan()` builds an id
map first and touches each edge once; the only nested loop in it
(`keys.count(k)` over one orchestrator's workers, `workflow_compiler.py:574`)
is quadratic in the *worker* count, which the canvas bounds at a handful.

### `AdjacencyIndex` is used everywhere it should be

The ticket asked directly. A repo-wide search for the shape it exists to
replace — `model.edges().filter/find/some`, or a `for` over all edges — returns
**zero** hits outside `AdjacencyIndex`/`GraphQueries` themselves and their
tests. Every neighbour question in `src/core`, `src/controller`, `src/nodes`
and `src/view` goes through `edgesOf`, which is a set lookup. `GraphQueries`
(`src/core/model/GraphQueries.ts`) holds one full scan, `countOfType` at :102,
and it is called for naming a newly-created node — once per creation, not per
render.

### The SSE seam already survives a client walking away

`stop_when_client_leaves` (`backend/openstategraph/api/streaming.py:414`) races
an `http.disconnect` future against each frame and abandons the in-flight step
(`:443–449`); `GeneratorExit` is caught and re-raised at `:600`, `frames.close()`
runs in `finally` at `:651`, and the inner LangGraph stream is closed at
`:1088–1096`. Both stream routes are wrapped (`routes/runs.py:322`, `:418`) and
so is `/api/events` (`routes/system.py:135`). There is no unwrapped
`StreamingResponse` in the repo. Covered by `tests/test_stream_cancellation.py`,
including `test_a_disconnect_stops_the_run_instead_of_letting_it_finish`.

Its documented limit — cancellation lands on the superstep boundary, so a model
call already dispatched inside the current superstep still completes — is not a
gap we are choosing to carry over an available alternative. **MCP-verified on
the audit date:** LangGraph's own cooperative-shutdown API stops "an in-flight
graph run after the current superstep completes" (`RunControl.request_drain()`,
`langgraph>=1.2`, Graceful shutdown). Identical boundary. The in-code note at
`streaming.py:614` is accurate and nothing is being left on the table.

### `CatalogueBroadcaster`, background tasks, watchers

Unsubscription is structural — a `@contextmanager` whose `finally` discards the
subscriber and closes it (`api/catalogue_events.py:244–256`) — and the queue is
bounded at `SUBSCRIBER_BACKLOG_LIMIT = 32` (`:115`), so a slow client is dropped
rather than grown. Every `create_task`/`ensure_future` in the backend (four,
all in `streaming.py`) is held in a local and either awaited or cancelled. There
is no file watcher and no per-run registry to leak — cancellation rides the
generator's own lifetime, which is why there is nothing to evict.

---

## Findings

Ten, ticketed on the install-experience map as **06–15**.

### F1 — a run request names a file on disk. HIGH. Ticket 06

`RunRequest.workflow_slug` is `str | None` with no pattern
(`api/schemas.py:191`) and arrives in the request **body**. Both run endpoints
hand it, together with the caller's own document settings, to the per-workflow
saver:

```python
checkpointer=services.checkpointer_for(document.get("settings"), request.workflow_slug)
```
— `api/routes/runs.py:119–121` and `:289–291`, where `document` is
`normalize_document(request.workflow)` (`:82`, `:272`). `memory.py:828` then
interpolates it:

```python
state_dir(workflows_root_dir) / f"checkpoints-{slug or 'default'}.sqlite"
```

Executed, not reasoned about — a slug of `../../../../../../tmp/pwned` resolves
outside the state directory entirely:

```
'../../../../../../tmp/pwned' -> /private/var/folders/.../tmp/pwned.sqlite  | inside state_dir: False
```

Two consequences from one missing validation. A caller chooses where the process
creates a sqlite file, and a caller mints unbounded keys in
`WorkflowServices._workflow_checkpointers` (`api/services.py:105`), whose only
eviction is `close()` (`:182–184`) — one open descriptor each, against a soft
`RLIMIT_NOFILE` of 256 on macOS. Auth is opt-in (`api/auth.py:88`), so on the
default posture there is no gate in front of either.

This is the class `7754d13` ("A run request could tell the server where to send
its own key") closed on one field; it survives on a second. `loader.py` already
owns the right answer — it refuses a package directory that is not `slugify`'d,
with a comment explaining that a slug the store cannot address degrades
silently. The run path does not call it.

### F2 — closing the Ask panel orphans the run, and retires the button that could stop it. HIGH. Ticket 07

`AskPanel` is conditionally rendered — `{askOpen ? <AskPanel … /> : null}`
(`src/view/AppShell.tsx:306`) — so closing it is a real unmount, not a hide.
One `AbortController` is created per stream (`AskPanel.tsx:403–404`) and
`abort()` is reached from exactly one place, the Stop handler (`:897`). The only
unmount effect is:

```tsx
useEffect(() => () => runningChangeRef.current?.(false), []);   // :1050
```

which reports *not running* and aborts nothing. So closing the panel mid-run
leaves the `fetch` open and `RuntimeClient`'s reader looping — it keeps calling
`setTurns` and `controller.model.setNodeRuntime()` from a dead component — while
the toolbar's Stop disappears. The run becomes unstoppable from the UI and bills
tokens to nobody, which is precisely the failure `streaming.py`'s disconnect
handling was written to end on the server side; the client half re-opens it.

The reader itself is not at fault: `RuntimeClient.streamFrom`
(`src/core/runtime/RuntimeClient.ts:648–824`) cancels correctly on abort
(`:795–799`), on mid-stream error (`:809`) and needs no cancel on normal
completion (`:782–784`). It only ever reacts to `options.signal`, and nothing
aborts that signal on unmount. Ownership above it is the defect.

**Established by reading the three call sites, not by a running reproduction —
and that is itself a finding.** This repository has no DOM test environment:
`vite.config.ts:30` sets `environment: 'node'` and `include:
['src/**/*.test.ts']`, and neither jsdom nor a testing library is a dependency,
so no React component in `src/view/**` can be mounted and unmounted by a unit
test. The class of bug that only appears on unmount is therefore structurally
untestable here. Recorded in ticket 07 as the reason the fix needs an e2e or a
DOM environment, not just a patch.

### F3 — `SelectionFeature` leaks one listener per canvas rebuild. MEDIUM. Ticket 09

**Reproduced.** A DOM-free counting `EventTarget` stood in for the container;
install/dispose was run N times with `PanZoomFeature` as the control:

| cycles | `SelectionFeature` residual | added / removed | `PanZoomFeature` residual |
| --- | --- | --- | --- |
| 1 | 1 | 5 / 4 | 0 |
| 10 | 10 | 50 / 40 | 0 |
| 100 | **100** | 500 / 400 | 0 |

Exactly one per cycle, and the control is flat, so this is one line rather than
a pattern. It is `SelectionFeature.ts:48`:

```ts
container.addEventListener('pointerdown', (event: PointerEvent) => {
```

the only raw `addEventListener` in the feature layer. The same file uses the
base class's tracking helper for the same element four more times (`:96`, `:133`,
`:134`, `:135`), and `PaperFeature.onDom` (`IPaperFeature.ts:72–75`) is what
pushes the matching `removeEventListener` onto `teardown`. Line 48 bypasses it,
so `dispose()` cannot undo it — against the interface's own stated invariant at
`IPaperFeature.ts:31`: "Every feature must undo everything it installed on
`dispose`."

It genuinely outlives the feature: the container is the React-owned stage div,
which `PaperController` deliberately leaves intact (`PaperController.ts:229–231`),
and the orphaned closure retains `controller`, `viewport` and `paper` — the whole
disposed canvas. Introduced by `3451689` ("Clicking a field now selects its
node", 2026-08-14). The fix is `this.onDom(container, …)`.

### F4 — the acyclic rule is quadratic, and it runs on every edit. MEDIUM. Ticket 10

**Measured**, on a chain whose head is a 3-node cycle, so Kahn's leftover set is
the whole graph — the worst case, and the shape a revision loop near the entry
produces:

| nodes | `acyclicGraphRule.check` | full `validate()` (cycle) | full `validate()` (clean) |
| --- | --- | --- | --- |
| 50 | 0.55 ms | 0.19 ms | 0.084 ms |
| 100 | 0.83 ms | 0.70 ms | 0.155 ms |
| 200 | 2.76 ms | 2.62 ms | 0.310 ms |
| 400 | 11.83 ms | 11.19 ms | 0.521 ms |
| 800 | **48.03 ms** | **48.74 ms** | 0.924 ms |

Ratios ×3.6 → ×4.4 with a cycle present; ×1.7 → ×1.8 without. The clean column
is the proof that the rest of the validator is fine and this one rule is the
whole cost.

`WorkflowValidator.ts:195` runs `canReachSelf` (`:9–30`, a full DFS) once per
member of the blocked set, and the blocked set includes everything *downstream*
of the cycle, not only the cycle. That over-inclusion is deliberate and
correct — the comment at `:180–194` records why the naive membership test was
wrong — but it makes the filter O(V·(V+E)) exactly when a loop exists.

It is on the hot path: the class docstring says the rules run "continuously to
drive per-node status dots", and `Inspector.tsx:271–275` memoises diagnostics on
`useWorkflowVersion()`, which bumps on **any** model change. So on a 400-node
document containing a revision loop, every node drag pays ~12 ms of validation
inside a React render. Not blocking at the sizes anyone draws today (50 nodes:
0.19 ms), and the fix is standard — one Tarjan SCC pass over the blocked
subgraph instead of V DFS walks.

### F5 — the server never closes the services it opened. MEDIUM. Ticket 11

`single_server_lifespan(services)` takes the object and never touches it:
its `finally` releases only the single-server lock (`api/main.py:186`). There is
no `on_event("shutdown")` anywhere, and the only `services.close()` calls in the
backend are `cli.py:440` and `:470`, both in thread-query subcommands — never in
`serve`. For the server itself this is mostly a matter of principle, since the
process exits; for embedders and for the test suite it is real, because
`create_app()` eagerly resolves the checkpointer at `main.py:225` and there are
**104 `create_app(` call sites under `backend/tests/`** with no autouse teardown.
The `close()` machinery `services.py:163–172` already implements is simply not
reachable from the one path that matters. One line in the existing `finally`.

### F6 — the compiler's node table is not a registry. MEDIUM. Ticket 08

CLAUDE.md's **O**: "extend by **registering**, never by editing the engine.
Every extension point is a `Registry<T>`: node types, executors, providers …"

**The editor half holds; the compiler half does not.** `NodeRuntime._builders`
(`compile/node_runtime.py:928`) is a private dict literal inside `__init__`.
`builder_for` (`:981`) is total, and two conventions escape the table —
`function.*` and `workflow.subgraph` — but a new node *family* does not. Run:

```
builder_for('analyse.sentiment') -> _passthrough
builder_for('tool.weather')      -> _passthrough
builder_for('function.my_fn')    -> _discovered_function
```

`backend/openstategraph/extensions.py` confirms the same shape from the plugin
side: three entry-point groups — `openstategraph.tools`, `…knowledge_builders`,
`…providers` (`:77`, `:82`, `:87`) — and none for node types.

So a plugin-supplied node family compiles, runs, and does nothing. The one thing
standing between that and total silence is `validate_document` naming the type
(verified: `unknown node type 'analyse.sentiment' on 's1'`), and by design the
HTTP run path does **not** gate on it (`validation.py:16–21` — a canvas mid-edit
is invalid most of the time). Pinned in the new backend test so the gap can
never degrade from *reported* to *silent* while the ticket is open.

### F7 — `store` means eight things, and two of them meet in one class. MEDIUM. Ticket 12

Handed over from ticket 02's resolution, and the audit found it worse than
described. In `WorkflowServices` the constructor *keyword* and the *attribute*
are different objects, 16 lines apart:

```python
def __init__(self, workflows_root=None, *, store: BaseStore | None = None, …)   # :59
    self.store = WorkflowStore(root=workflows_root)                              # :69
    self.memory_store = store if store is not None else build_store()            # :85
```

`WorkflowServices(root, store=X)` does not set `.store`. Eight distinct meanings
of the bare identifier exist in the backend (filesystem `WorkflowStore`; LangGraph
`BaseStore`; the `WorkflowServices` kwarg; the `load_workflow` kwarg;
`RuntimeServices.store`; `WorkflowCompiler.build(store=)`; LangGraph's own
`compile(store=)`; and `postgres.store(url)`, a function). `store = services.store`
appears verbatim at `node_runtime.py:817` (memory) and `mcp_server.py:547`
(filesystem) — same nine characters, opposite objects.

The type wall stops where the two meanings meet: `RuntimeServices.store: Any`
(`node_runtime.py:629`), `NodeRuntime.__init__(store: Any)` (`:801`),
`WorkflowCompiler.build(store: Any)` (`workflow_compiler.py:596`). And
`runtime_for` puts both spellings in one function body — `store = self.store`
(`services.py:310`, filesystem) and `store=self.memory_store` (`:327`, memory) —
17 lines apart, where changing one to the other is a one-token edit mypy
accepts. The downstream guard is a bare `is not None` (`node_runtime.py:1271`),
so a `WorkflowStore` would pass it and bind the memory tools to every agent;
failure would surface as an `AttributeError` inside LangGraph at run time.
`load_workflow`'s own `store=` is correctly typed and commented (`loader.py:339–341`)
for exactly this reason — the discipline exists, it just stops one layer in.

### F8 — the ceiling pin cannot see the member it should be watching. LOW. Ticket 13

`test_public_surface_ceiling.py:72` asserts `NodeRuntime`'s public surface is
exactly six names, measured with `vars()` on `NodeRuntime(model=None)` — a
*fresh* instance. But `self.last_bound_tools` is assigned inside a method
(`node_runtime.py:1286`), not `__init__`, so the pin cannot see it. A runtime
that has built one agent has **seven**, and `last_bound_tools` is not obscure:
eight assertions across `test_node_runtime.py`, `test_memory.py`,
`test_knowledge.py` and `test_chinook_demo_file.py` depend on it.

The test measures an instance where it means to measure a class. This is the
same defect `ebdc888` ("Nine tests that could not fail") swept for, in the file
whose own docstring says "the count is the part that regrows".

### F9 — CLAUDE.md says ten; the count is eleven. LOW. Ticket 13

"`WorkflowController` (ticket 17) is **fixed: 10 public members**". Counted by
the repository's own rule (`src/publicSurfaceCeiling.test.ts`), it is **11** —
nine `readonly` collaborators (`WorkflowController.ts:61–71`) plus `onChange`
(`:139`) and `dispose` (`:147`). One over, unpinned, and asserted in prose as
settled. The wider problem is coverage: `publicSurfaceCeiling.test.ts` pins
three classes and `test_public_surface_ceiling.py` two, against **19** classes
over the ceiling — including `WorkflowModel` at 43, the recorded exception
CLAUDE.md spends the most words on and which no test guards at all. Full census
in the ticket.

### F10 — three view caches that only grow. LOW. Ticket 14

`CompositionBody.tsx:298` (`CACHE`, a full workflow document per slug), `:343`
(`PEEKS`, compiled Mermaid SVG per slug) and `SqlSchemaBody.tsx:146` (`CACHE`)
delete entries only on *failure*; successful entries are never evicted and
neither module has a `clear()`. The comment at `CompositionBody.tsx:295` claims
failures are cached "only until the next slug change", and no slug-change
eviction exists. Bounded by distinct slugs visited in one session, so this is
slow growth rather than a runaway — but these hold the heaviest payloads in the
app.

### F11 — the wheel-freshness gate counts files the wheel never ships. LOW. Ticket 15

Found by running the suite rather than by looking for it.
`test_the_wheel_ships_a_current_editor.py:98` fails on this working tree with
"dist/ is older than src/", and the file responsible is
`src/nodes/guard/GuardrailNode.test.ts` — a test, which never enters the bundle.
`editor_is_stale` (`backend/hatch_build.py:106-109`) walks `src.rglob("*")` and
accepts any `.ts`/`.tsx`, so a test file, a fixture or a `.probe` scratch file
demands a rebuild of an editor it cannot have changed.

Its own docstring makes the argument this violates: false negatives "cost one
needless rebuild", false positives "would ship the defect this exists to
catch — the asymmetry that decides the method". A `.test.ts` produces a false
*positive*, which is the side the docstring says is acceptable to pay for, so
this is not a correctness hole — but it is a gate that cries wolf, and a gate
people learn to silence with `npm run build` stops being a gate. Pre-existing:
it fails at `HEAD` before any of this audit's files were added.

---

## Blockers for 10/10

Two. Everything else above is a ticket, not a gate.

1. **F1 (ticket 06) — a request body names a file on disk.** `workflow_slug`
   is unvalidated, reaches `f"checkpoints-{slug}.sqlite"`, and a traversal slug
   was demonstrated writing outside the state directory. Auth is opt-in, so on
   the default posture nothing gates it. The same request also mints unbounded
   entries in a cache whose only eviction is `close()`, each holding a
   descriptor. This must not ship to a public beta.

2. **F2 (ticket 07) — closing the Ask panel starts a run nobody can stop.**
   The `AbortController` is never aborted on unmount, the reader keeps writing
   into a dead component, and the same unmount reports "not running" so the
   toolbar retires Stop. A user-visible correctness bug on the product's main
   surface, in a product whose "Stop stops work" claim is otherwise carefully
   engineered end to end.

Neither is a design flaw; both are one missing call on a path nobody walked.
