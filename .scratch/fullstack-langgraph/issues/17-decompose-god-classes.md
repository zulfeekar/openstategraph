Type: grilling
Status: resolved — controller and model both done
Blocked by: 11

## Question

Decompose the two god classes, with tests in place first.

Measured, not asserted:
- `WorkflowController` — 38 public members, 540 lines, mixing node ops, edge ops, clipboard, grouping, selection, history and document I/O. Seven reasons to change.
- `WorkflowModel` — 41 public members, 451 lines, mixing node CRUD, edge CRUD, adjacency queries, topology, geometry and transactions.

CLAUDE.md now sets a ceiling of ~10 public members and one reason to change.

Decisions:
- The split for `WorkflowController`. Candidate seams: node ops, edge/connection ops, clipboard, grouping, history — with the controller reduced to a thin façade that *delegates* rather than implements. Is a façade even wanted, or should the view depend on the collaborators directly? A façade that only forwards is still a god class by another name.
- The split for `WorkflowModel`. The aggregate root legitimately owns node and edge mutation; the query surface (`topologicalOrder`, `bounds`, `descendantsOf`, `predecessorsOf`) arguably belongs in separate query objects. Decide whether the model keeps queries or exposes a read model.
- Ordering. This is a refactor of load-bearing code with no tests today, so it is blocked by 11 and must be done behind the regression tests named there.
- Whether the entity hierarchy (08) changes these shapes enough that this should wait for it.

Note: `PaperController` (11 members) and `ExecutionEngine` (6) are within budget and are not in scope.

---

## Answer — part 1: `WorkflowController`, done

**41 public members → 11.** One reason to change: which collaborators exist.

| Collaborator | Members | Owns |
| --- | --- | --- |
| `NodeEditor` | 9 | create, delete, move, resize, field edits |
| `EdgeEditor` | 4 | connect, disconnect, label; the replace-on-full-input transaction |
| `GroupingController` | 4 | containment, explicit and geometric |
| `ClipboardController` | 4 | copy, cut, paste, duplicate |
| `HistoryController` | 6 | undo, redo, availability, `transact` |
| `DocumentController` | 5 | validate, import, export, clear, rename |
| `SelectionActions` | 5 | gestures whose subject is the selection |

**The façade question, answered: no façade.** The ticket's own warning decided
it — a class forwarding 41 methods is the same god class with an extra layer, and
it would leave every consumer still depending on everything. Call sites now name
what they use: `controller.nodes.add(...)`, `controller.history.undo()`. A
consumer that only pastes imports `IClipboardController`.

**Two leaks closed as a side effect**, both found by making the surface explicit:

- `AutoLayout` reached through `controller.commands.transact(...)` — a canvas
  feature holding the entire command stack, including `execute` and `clear`, in
  order to group a batch of moves. Now `history.transact`.
- `useHistoryState` subscribed to the stack's `changed` event directly, so the
  toolbar re-rendered on every model change to learn something that only changes
  at an undo boundary. Now `history.onChange`, which is the narrow signal.

`registry` and the `ClipboardService` instance turned out to have **no external
consumers at all** and became private. That is the kind of thing a 41-member
class hides.

**Dependency arrows run one way** — `grouping <- nodes <- selectionActions <-
clipboard` — so construction order is forced and there are no cycles. Two
concerns stayed on the root because they genuinely span every collaborator:
pruning the selection when ids vanish, and the aggregate `onChange`.

**No `Abstract*`/`Base*` tier.** Each contract has one implementation and they
share no behaviour, so a ladder would be depth for its own sake. CLAUDE.md's
ladder is for entity *families* — node types, tools, providers — where subclasses
share behaviour. Controllers are collaborators, not a family. Recorded in
`contracts.ts` so it is not "fixed" later.

Verified: `tsc` clean, 101 tests green **through the new API** (the suites were
rewritten, not adapted with shims), and the app exercised in the browser —
selection via a real click populates the inspector.

Commit `2f0bf8e`.

## Answer — part 2: `WorkflowModel`, design settled, work outstanding

Deliberately **not** attempted in the same pass, and the reason is the blast
radius rather than the difficulty.

**The split, settled:**

```
core/model/
  WorkflowModel.ts     aggregate root — node + edge mutation, events, transactions
  AdjacencyIndex.ts    the incremental incident/children index the model maintains
  GraphQueries.ts      derived reads — predecessors, successors, descendants, bounds
  topology.ts          pure Kahn sort over (nodes, edges)
```

Two things this gets right that a naive split would not:

- **The index cannot simply move out.** `removeNode` maintains it and
  `setNodeParent` consults `descendantsOf` for its own cycle check, so the index
  is *written* by mutation and *read* by queries. It becomes a collaborator the
  model owns and mutates, with the derived queries composed on top — not a
  free-floating query object that recomputes.
- **`topologicalOrder` and `bounds` are pure functions** over nodes and edges,
  with no reason to be methods at all. `topology.test.ts` already exists under
  that name, which is a hint the seam was always there.

**Honest limit, stated rather than glossed:** even after this, the aggregate root
keeps roughly 25 members — twelve primitive mutators plus lookups, events and
transactions. That is above CLAUDE.md's ~10, and it is **one reason to change**:
the graph's consistency invariant. Getting to ten would mean splitting mutation
into `NodeCollection`/`EdgeCollection`, which is a coherent pattern but a rename
across 100-plus call sites (`model.node()`, `model.nodes()`, `model.hasNode()`
are used everywhere) in exchange for a smaller number rather than a clearer
design. Recommend against it unless the count is treated as a hard rule; the
binding test in CLAUDE.md is "one reason to change", and the root passes it while
the old controller did not.

**Why it is a separate commit:** it is a mechanical rename over a hundred call
sites in code with no view-layer tests, so it needs its own verification pass —
including the reload smoke check from ticket 26 — rather than being appended to
an already-large refactor.

## Answer — part 2 continued: `WorkflowModel`, done (2026-08-06)

Built exactly the split settled above, no deviation:

```
core/model/
  WorkflowModel.ts     475 → 350 lines. Node + edge mutation, events, transactions.
  AdjacencyIndex.ts    incident/children bookkeeping, incrementally maintained.
  GraphQueries.ts      edgesOf/Into/From, children/descendants/predecessors/
                       successors, countOfType, isAncestorOf — delegates
                       topologicalOrder/bounds to topology.ts.
  topology.ts          pure topologicalOrder(nodes, edges) and bounds(nodes) —
                        exactly the file `topology.test.ts` was already named for.
```

Confirmed the two things this was called out as needing to get right: the
index is still *written* by `WorkflowModel`'s mutators
(`adjacency.registerNode/registerEdge/linkChild`, ...) and *read* by
`GraphQueries` and `setNodeParent`'s cycle check
(`queries.isAncestorOf`) — never a free-floating object recomputed per
query. And `topologicalOrder`/`bounds` are genuinely pure functions with no
reason to be methods, now living where they were always going to.

**The honest limit stands, unchanged, and is not "fixed" here**:
`WorkflowModel`'s own public method count is untouched — still every
`addNode`/`edgesOf`/`topologicalOrder`/etc. a caller already depends on —
because this ticket's own prior analysis already concluded that collapsing
those into `NodeCollection`/`EdgeCollection` is a hundred-plus-call-site
rename for a smaller number rather than a clearer design, and recommended
against it. What changed is where the *implementation* of each concern
lives, verified by two new, independently-tested collaborators (22 tests:
`AdjacencyIndex.test.ts`, `GraphQueries.test.ts`) plus 5 direct unit tests
of the pure topology functions (`topology.pure.test.ts`) — none of which
need a `WorkflowModel`, a registry, or a controller to run. 235 Vitest
passing, zero regressions, `tsc` clean.

## Found while verifying: ticket 26

Browser verification surfaced a **pre-existing** defect — the canvas renders no
cells after a page reload, silently, with the model fully populated and no
console error. Confirmed pre-existing by stashing this refactor and reproducing
it on `6c52505`. Filed as ticket 26; see it for the evidence table.

Worth noting what caught it: not a test, but *looking at the running app*. The
101 tests pass in both states, because the model is correct in both.
