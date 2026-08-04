Type: grilling
Status: claimed
Blocked by: 01, 02

## Question

Define the test strategy. There are currently **zero tests** — the largest single production-readiness gap.

Decisions:
- Runners: Vitest for TS, pytest for Python — confirm, and whether a single command runs both.
- Test boundaries. `core/` is pure TypeScript with no React or JointJS imports, so it is unit-testable directly. Decide what is unit, what is integration, and how much of the canvas is worth testing (jsdom? or model-layer only, treating the canvas as a projection?).
- **Contract tests across the generated boundary**: how do we prove the TS types still match the Pydantic models? (depends on 02)
- What must be true before a change is allowed to land — coverage floor, or named critical paths?
- Which existing behaviours get regression tests first. Candidates from phase 1: connection rule chain, command stack undo/redo + coalescing, topological scheduler, serializer round-trip and migration.

Consult `/tdd`.

---

## Performance budget — proposed, veto if wrong

"Memory efficient and performant" is not testable as stated. Proposed concrete budget so it becomes a failing test rather than an adjective:

| Target | Budget |
| --- | --- |
| Nodes on one canvas | **500** |
| Edges | 800 |
| Pan / zoom | 60fps sustained |
| Single node edit (keystroke → paint) | < 16ms |
| Full graph load → interactive | < 1s |
| Heap growth over 100 add/delete/undo cycles | ~0 after GC — no monotonic climb |

Notes on why these and not others:
- The **500-node pan test is the one that matters most**, because it exercises the untested risk: `foreignObject` + React portal render cost at scale. Everything else in the engine is already O(degree) or O(V+E).
- The heap test is the honest version of "garbage collection handled perfectly". Neither TS nor Python lets you control collection; what is testable is that nothing is *retained*. `DisposableStore` exists for this — the test proves it works.
- Write these as failing tests **before** optimising anything. If 500 nodes already passes, do not optimise.
