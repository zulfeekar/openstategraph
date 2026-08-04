Type: grilling
Status: resolved
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

---

## Answer

**Runners.** Vitest for TS, pytest for Python, no shared runner. Vitest runs with
`environment: 'node'`, not jsdom — `core/` imports neither React nor JointJS, so
a DOM environment would only mask an accidental dependency on one. That config
choice is load-bearing: it makes the layering rule enforced by the test setup
rather than by discipline. `resolve: { tsconfigPaths: true }` (Vite native) so
aliases resolve identically in tests and app; a harness test asserts this.

**Boundaries — three tiers, and the canvas is deliberately not one of them.**

| Tier | Scope | Runner env |
| --- | --- | --- |
| Unit | `core/` — model, commands, validation, serialization, kernel | node |
| Integration | controller -> model -> event, through the public controller API | node |
| Contract | Pydantic <-> generated TS (ticket 02) | pytest + `tsc` |

The canvas is **not** tested. It is a one-way projection of the model, so a
correct model plus a correct adapter is the whole of correctness, and a jsdom
test of JointJS would mostly assert facts about JointJS. What *is* worth testing
is the adapter's translation, against a fake paper — deferred, and named as a
known gap rather than quietly skipped. Phase 1's own bugs support the call: every
canvas defect (`var()` unresolved in SVG presentation attributes,
`paper.remove()` deleting React's node under StrictMode, the measurement
feedback loop) was a real-browser/real-JointJS behaviour that jsdom would have
reproduced incorrectly or not at all.

Tests go through `WorkflowController`, not through command classes directly. The
controller is what the UI calls; testing commands in isolation would verify a
path nothing uses.

**Gate: named critical paths, not a coverage percentage.** A global floor is
gameable and rewards testing the easy surface — providers and node definitions
are largely declarative and would inflate the number without adding safety. The
gate is: *the paths below have tests, and the suite is green*. A floor on
`core/**` exists only to catch regression, not as a target.

Measured after this ticket (`vitest run --coverage`, 101 tests, % lines):

| Area | Lines | Note |
| --- | --- | --- |
| `core/model` | 77% | the critical path |
| `core/commands` | 69% | undo/redo, coalescing, transactions |
| `core/validation` | 59% | `acyclicRule` is unreachable — see ticket 09 |
| `core/kernel` | 53% | |
| `controller` | 34% | reached transitively; not directly targeted |
| `core/execution` | 10% | **known gap** — needs a fake provider |
| `core/providers` | 17% | **known gap** |

Floor: `core/model` and `core/commands` must not drop below 65% lines. Execution
and providers are a stated gap, not an oversight — they are the layer most
likely to be replaced by tickets 07 and 15, so testing them now would be testing
code scheduled for deletion.

**Regression order — done. 101 tests, red-first wherever a defect existed.**

| Suite | Tests | Outcome |
| --- | --- | --- |
| `core/testing/harness.test.ts` | 5 | proves aliases, DOM-free workbench, full catalogue |
| `core/validation/ConnectionValidator.test.ts` | 19 | **found `acyclicRule` is dead code** -> ticket 09 |
| `core/commands/CommandStack.test.ts` | 19 | green |
| `core/model/topology.test.ts` | 15 | green |
| `core/serialization/WorkflowSerializer.test.ts` | 19 | **2 red -> fixed**, ticket 19 |
| `core/kernel/ordering.test.ts` | 11 | new module |
| `core/model/contracts/ports.test.ts` | 13 | **5 red -> fixed**, the `Infinity` defect |

They earned their cost through what they *found*, not the regressions they will
prevent. Serializer non-determinism and `Infinity` in a serialisable field were
both invisible until a test asserted the property, and both would have surfaced
later as silent data corruption rather than as a failure. `acyclicRule` being
unreachable is a third, and it changed the shape of ticket 09.

**Fixtures over mocks.** `core/testing/fixtures.ts` exposes `makeWorkbench()`,
`addNode()`, `connect()` and `TYPE`. Two notes for whoever extends it:

- `makeWorkbench()` constructs `new Workbench()` directly, **not**
  `createWorkbench()` — the latter calls `applyLayoutTokens()`, which touches
  `document` and would drag the DOM into a node-environment suite.
- `registerLoopableType()` exists because **no cycle is expressible with the
  shipped catalogue** — the only input accepting a `result` is on the output
  node, which has no output port. Exercising cycle behaviour needs a synthetic
  symmetric-port type. This is how the dead-rule finding surfaced.

**Contract tests across the generated boundary** — deferred to ticket 02, whose
answer already fixes the mechanism: generated output is committed and CI runs
`git diff --exit-code` after regeneration, so drift fails the build without a
bespoke test. Add to it a round-trip assertion that a serialised `workflow.json`
validates against the Pydantic model in both directions.

**Performance budget: stands as proposed, unvetoed.** Treated as ratified by
default so it stops blocking. The numbers are cheap to change and nothing built
so far depends on them. Not implemented here — the 500-node pan test needs the
canvas harness this ticket deliberately deferred, so it belongs with that work.
Recorded so it is not silently dropped.
