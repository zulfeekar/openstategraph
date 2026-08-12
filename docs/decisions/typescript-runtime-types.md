# Pydantic → TypeScript: what is actually enforced across the run/stream seam

**Status: in force from 2026-08-12.** Resolves ship-it ticket 02(B).

## The claim, and why it could not be cited

`CLAUDE.md` § *DRY — but not by accident* stated, as a hard rule:

> Pydantic is the **single source of truth**; TypeScript types are
> **generated**. Never hand-mirror a type across the boundary.

Two facts made that unciteable in a review:

1. **There is no pydantic → TypeScript generator in this repository.** Not a
   stale one, not a broken one — none.
2. **`src/core/runtime/RuntimeClient.ts` hand-mirrors the whole run and stream
   schema.** `RunRequest`, `RunResult`, `DeveloperChannel`, `RunInterrupted`,
   `RunCancelled`, `RunOutcome`, `RunStreamEvent`, `ResumeRequest`, `PastRun`,
   `PastRunStep`, `PastRunHistory`, `PastRunQuery` are all hand-written
   TypeScript over Pydantic models in `backend/openstategraph/api/schemas.py`.

A rule the tree openly breaks is worse than no rule: a reviewer who cites it
is immediately shown the counter-example, and the next hand-mirror is waved
through on precedent.

## The decision

**Narrow the rule to what is true, and gate the boundary with a drift test
rather than a generator.** Concretely:

- `docs/openapi.json` is the **published contract** for the run/stream seam.
  It is generated from the FastAPI app and already double-gated
  (`backend/tests/test_openapi_contract.py` plus CI's `generated-openapi`
  job), so it cannot drift from Pydantic.
- `RuntimeClient.ts` stays hand-written, and a **contract test** pins it
  against that document — the same shape as
  `backend/tests/test_data_key_contract.py`, which pins the compiler's `data`
  reads against the editor's declared field keys, and of
  `src/nodes/portSpecs.test.ts`, which pins the committed port table against
  the built catalogue. The pattern is established in both languages; this is
  one more instance of it.

### Why not generate (option 1 from the ticket)

`npx openapi-typescript docs/openapi.json` is genuinely one line, and it is
what `docs/api.md` already recommends **to consumers**. It was still rejected
for the editor's own client, for three reasons:

1. **The generated shape is not the shape `core/` wants.** `openapi-typescript`
   emits a `paths`/`components` tree, so every use site becomes
   `components['schemas']['RunResult']`. Either `RuntimeClient.ts` grows a
   hand-written alias layer over it — a mirror with extra steps — or the alias
   names leak the OpenAPI document's structure into `core/`, which is the
   layer that is supposed to import nothing.
2. **OpenAPI cannot express half of the seam.** `RunStreamEvent` is a
   discriminated union of SSE frames. SSE frames are not response bodies, so
   they are not in the OpenAPI document at all — `docs/api.md` carries that
   half in prose, deliberately. A generator would cover the easy half and
   leave the half where drift actually hurts uncovered, while *appearing* to
   have solved the problem.
3. **It adds a build-order dependency for a benefit a test already gives.**
   The failure mode we care about is "Python changed and TypeScript did not".
   A test detects that; generation prevents it only for the subset in (2), at
   the cost of a `npm run generate:*` step, a committed artifact, and a fourth
   CI drift job.

### What the contract test should assert

Proposed as `src/core/runtime/runtimeContract.test.ts` (Vitest, reads
`docs/openapi.json` from disk — no server, no network, so it runs in
`npm run verify` like `portSpecs.test.ts` does):

- Every property of `components.schemas.RunRequest`, `RunResponse`,
  `DeveloperChannelResponse`, `ResumeRequest`, `ThreadSummary`, `ThreadStep`,
  `ThreadListResponse` and `ThreadHistoryResponse` has a counterpart in the
  corresponding `RuntimeClient.ts` interface, and vice versa. Missing on
  either side fails, naming the field. (Those eight are exactly the schemas
  `RuntimeClient.ts` mirrors; a ninth appearing in the document without a
  mirror is not a failure, an unmirrored *field* on these eight is.)
- `required` in the schema matches non-optional in TypeScript.
- Primitive kinds match (`string`/`number`/`boolean`/array/object).
- The **SSE half is explicitly out of scope** and says so in the test's
  docstring, pointing at `docs/api.md` § the frame vocabulary and at
  `backend/tests/test_stream_frames.py` as its Python-side gate.

That test is **not written yet** — this document is the decision, not the
implementation. Until it lands, the boundary is review-only, and
`CONTRIBUTING.md`'s non-negotiables table says so rather than implying a gate
that does not exist.

## The amendment to `CLAUDE.md`

The rule now reads:

> Pydantic is the **single source of truth** for the run/stream seam, and
> `docs/openapi.json` is its generated, committed publication. TypeScript is
> not generated from it: `src/core/runtime/RuntimeClient.ts` is a hand-written
> client, pinned to the published contract by a drift test rather than by
> codegen — see `docs/decisions/typescript-runtime-types.md`. A new
> hand-mirror without that pin is what the rule forbids.

Which is narrower, and true.
