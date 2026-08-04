Type: research
Status: resolved
Blocked by: —

## Question

How do we make Pydantic the single source of truth and *generate* the TypeScript types, with no hand-mirroring?

Establish, from primary sources:
- The viable generation paths (e.g. `model_json_schema()` → `json-schema-to-typescript`, vs `pydantic-to-typescript`, vs a bespoke emitter). Maintenance status and OSS licence of each.
- How **discriminated unions** survive the round trip — critical, because the entity hierarchy is a tagged union over `kind`/`type`.
- How **inheritance** maps: does a Pydantic subclass emit a TS `interface X extends Y`, or a flattened structure? This directly decides whether `IEntity → BaseNode → AgentNode` is expressible in the generated output.
- Whether Pydantic **generics** survive at all.
- Where codegen runs (build step / CI / pre-commit) and whether output is committed.
- How drift is *detected* (a CI check that regeneration produces no diff).

Answer must name specific packages with versions and licences, and state what is NOT expressible.

## Answer

Researched 2026-08-04. Every claim below was verified empirically by running the real toolchain
(pydantic 2.13.4 → `model_json_schema()` → json-schema-to-typescript 15.0.4 → `tsc --strict`),
not from documentation alone. Version/licence/maintenance data taken from PyPI, npm and the
GitHub API.

### Verdict up front

1. **Inheritance is FLATTENED.** Pydantic's `model_json_schema()` erases the class hierarchy
   entirely — a subclass schema inlines every inherited field and emits no `allOf`/`$ref` to its
   parent. No off-the-shelf tool can emit `interface AgentNode extends BaseNode`, because the
   information is already gone before any TS generator sees it. **This is not fatal** (TypeScript
   is structurally typed, so `AgentNode` remains assignable to `BaseNode` — verified), but the
   `extends` keyword is not recoverable without a custom schema post-processor.
2. **Discriminated unions survive cleanly and are fully narrowable.** This is the good news, and
   it is the property the domain model actually depends on.
3. **Generics do not survive** as generics — they are monomorphised into concrete per-instantiation
   types.

### 1. Viable generation paths

| Package | Version | Licence | Maintenance (checked via GitHub API / PyPI) | Verdict |
|---|---|---|---|---|
| [`pydantic`](https://pypi.org/pypi/pydantic/json) | 2.13.4 | MIT | Active | Source of truth |
| [`json-schema-to-typescript`](https://github.com/bcherny/json-schema-to-typescript) | 15.0.4 | MIT | **Active** — last push 2026-08-04, 3.3k stars | **Recommended emitter** |
| [`pydantic-to-typescript`](https://github.com/phillipdupuis/pydantic-to-typescript) (CLI `pydantic2ts`) | 2.0.0 (released 2024-11-22) | MIT | **Dormant** — last commit 2024-11-22 (~20 months stale), 34 open issues, not archived. [Snyk classifies it "Inactive"](https://snyk.io/advisor/python/pydantic-to-typescript) (assessed 2026-01-07) | Usable but **thin wrapper — vendor it** |
| [`quicktype`](https://github.com/glideapps/quicktype) | 26.0.0 | Apache-2.0 | Active | **DISQUALIFIED — see below** |
| [`openapi-typescript`](https://www.npmjs.com/package/openapi-typescript) | 7.13.0 | MIT | Active | Viable alternative if types are already exposed via a FastAPI OpenAPI document; same flattening limits (FastAPI derives schemas from `model_json_schema()`) |
| [`datamodel-code-generator`](https://github.com/koxudaxi/datamodel-code-generator) | — | MIT | Active | **Wrong direction** (JSON Schema → Python). Not applicable. |

**quicktype is disqualified.** It does not preserve tagged unions — it *merges* union members into a
single interface. Verified on the exact domain shape:

```ts
// quicktype 26.0.0 output — AgentNode and ToolNode have been MERGED and destroyed
export interface Node {
    id: string;  kind: Kind;  model?: string;  x: number;  y: number;  tool_name?: string;
}
export type Kind = "agent" | "tool";
```

The `kind` discriminant collapses to a plain enum and every variant-specific field becomes
optional — losing all narrowing and all exhaustiveness checking. Do not use quicktype for a
discriminated-union domain model.

### 2. Inheritance: FLATTENED (the decisive finding)

Given exactly the ticket's hierarchy (`IEntity → BaseNode → AgentNode`), `AgentNode.model_json_schema()`
emits:

```json
{
  "title": "AgentNode", "type": "object",
  "properties": { "id": {...}, "x": {...}, "y": {...}, "kind": {"const": "agent"}, "model": {...} },
  "required": ["id", "x", "y", "kind", "model"]
}
```

There is **no `allOf`, no `$ref`, and `IEntity`/`BaseNode` do not appear in `$defs` at all.** The
hierarchy is erased at the Pydantic layer. This is known, intentional current behaviour; the
request to change it is [pydantic#12071 "Add option to use `allOf` in JSON Schema when a common
base is used"](https://github.com/pydantic/pydantic/issues/12071), **open since 2025-07-18 and
still unresolved**. There is no `model_config` flag to turn it on.

Consequently `pydantic2ts` produces flat, standalone interfaces — verified end-to-end:

```ts
// pydantic-to-typescript 2.0.0 actual output
export interface AgentNode { id: string; x: number; y: number; kind: "agent"; model: string; }
export interface BaseNode  { id: string; x: number; y: number; }
export interface IEntity   { id: string; }
```

`BaseNode` and `IEntity` *are* emitted (pydantic2ts exports every module-level model), but there is
**no structural link declared** — the fields are duplicated into each descendant.

**Mitigating fact (important):** because TypeScript is structurally typed, the flattening does not
cost type safety. This compiles cleanly under `--strict` (verified, tsc 7.0.2, exit 0):

```ts
export function up(n: AgentNode): [BaseNode, IEntity] { return [n, n]; }
export function allBases(g: Graph): IEntity[] { return g.nodes; }
```

So "is the hierarchy expressible?" splits in two:
- *Assignability semantics* (treat an `AgentNode` as a `BaseNode`): **yes, works out of the box.**
- *A literal `extends` declaration / DRY emitted output*: **no, not without custom work.**

**If a real hierarchy in the output is required**, it is achievable with a ~30-line post-processor
that walks `model.__mro__` / `model_fields` and rewrites each `$def` into
`allOf: [{$ref: parent}, {own props only}]`. Verified this works — json-schema-to-typescript then emits
**intersection types, not `extends`**:

```ts
export type AgentNode = BaseNode & { kind: "agent"; model: string; };
export type BaseNode  = IEntity  & { x: number; y: number; };
export interface IEntity { id: string; }
```

This is DRY, transitive, and preserves the named chain. Narrowing and exhaustiveness still work
(verified, tsc exit 0). Note that `json-schema-to-typescript` maps
[`allOf` → intersection and `oneOf` → union](https://github.com/bcherny/json-schema-to-typescript#readme);
it has **no option to emit `interface X extends Y`** at all. Intersections are the ceiling for
any JSON-Schema-based path. Only a bespoke emitter reading Pydantic classes directly could produce
true `extends`, and that is not worth the maintenance burden given intersections are semantically
equivalent for this use case.

### 3. Discriminated unions: survive cleanly ✅

`Annotated[Union[AgentNode, ToolNode], Field(discriminator="kind")]` emits proper JSON Schema
with an OpenAPI-style discriminator:

```json
{ "oneOf": [{"$ref": "#/$defs/AgentNode"}, {"$ref": "#/$defs/ToolNode"}],
  "discriminator": { "propertyName": "kind", "mapping": { "agent": "...", "tool": "..." } } }
```

`json-schema-to-typescript` ignores the `discriminator` annotation but doesn't need it — it maps
`oneOf` to a union, and each member's `kind` is a `const`, which becomes a **string-literal type**.
That is exactly what TS discriminated-union narrowing requires. Output: `nodes: (AgentNode | ToolNode)[]`.
Confirmed with `tsc --strict --noEmit` (exit 0) that `switch (n.kind)` narrows correctly **and**
`assertNever(n)` in the `default` branch compiles — i.e. **exhaustiveness checking works**, so adding
a new Pydantic variant produces a compile error in the frontend. This is the single most valuable
property of the whole pipeline.

**Two gotchas that must be handled or narrowing silently degrades:**

1. **Do not give the discriminant a default.** `kind: Literal["agent"] = "agent"` makes the field
   non-required, emitting `kind?: "agent"` — the discriminant becomes `"agent" | undefined`, which
   weakens narrowing and lets you construct a variant with no tag. Declare it as
   `kind: Literal["agent"]` (required, no default).
2. **`additionalProperties` must be forbidden.** By default Pydantic omits `additionalProperties`,
   and json-schema-to-typescript then adds `[k: string]: unknown` to every interface, which kills
   excess-property checking. Fix with `model_config = ConfigDict(extra="forbid")` on a shared base,
   or pass `--additionalProperties false`. (`pydantic2ts` already does this for you by temporarily
   forcing `extra="forbid"`.)

A third cosmetic issue: Pydantic emits a `title` for every field, which makes json-schema-to-typescript
generate a junk type alias per field (`export type Id = string; export type X1 = number; ...`).
`pydantic2ts` already strips these; a bespoke pipeline should suppress them via a
`GenerateJsonSchema` subclass overriding `field_title_should_be_set() -> False`.

### 4. Generics: do NOT survive ❌

Pydantic generics are **monomorphised**, not preserved. `Page[AgentNode]` produces a `$def` named
`Page_AgentNode_` (title `Page[AgentNode]`) and generates:

```ts
export interface PageAgentNode { items: AgentNode[]; total: number; }
```

There is **no `Page<T>`** in the output. Consequences:
- Every instantiation you actually reference emits a separate concrete interface. `Page[AgentNode]`
  and `Page[ToolNode]` become two unrelated types with no shared `Page<T>` parent.
- An **unparameterised** generic degrades to `items: unknown[]` (the `T` becomes an empty schema) —
  so never reference the bare generic in an exposed model.
- Only instantiations reachable from an exported model appear at all.
- Observed wart: the `extra="forbid"` config override does **not** propagate to parametrised generic
  subclasses, so `PageAgentNode` came back with a stray `[k: string]: unknown` even under
  `pydantic2ts`. Pass `--additionalProperties false` to be safe.

**Recommendation:** keep generics out of the wire contract. Use them freely for internal Python
plumbing, but define explicit concrete models for anything crossing to TypeScript. If a generic
container is genuinely needed frontend-side, hand-write the *one* `Page<T>` helper in a small
non-generated `.ts` file and have generated concrete types satisfy it — that is a helper, not a
mirrored domain type, so it doesn't violate single-source-of-truth.

### 5. Recommended toolchain

Pin these:

- **`pydantic == 2.13.x`** (MIT) — source of truth.
- **`json-schema-to-typescript == 15.0.4`** (MIT, actively maintained) — the emitter, as a
  `devDependency`.
- A **~50-line project-owned Python script** that: imports the model registry → calls
  `model_json_schema(schema_generator=NoTitles)` on a root model → optionally applies the `allOf`
  inheritance rewrite → writes `schema.json` → shells out to `json2ts --additionalProperties false`.

**Do not depend on `pydantic-to-typescript` in the long term.** It is MIT-licensed and its logic is
sound and worth copying (master-model aggregation, `extra="forbid"` override, title-stripping), but
it has had no commits since 2024-11-22, has 34 open issues, and is externally rated inactive. It is
a thin wrapper around `json2ts` — roughly 200 lines. Vendoring its approach removes a dormant
dependency from the critical path and is what makes the `allOf` inheritance rewrite possible at all
(the CLI gives you no hook for it). Use `pydantic2ts` for a fast spike; own the script for
production.

Also add `model_config = ConfigDict(extra="forbid")` to the shared `IEntity` base and declare all
`kind` discriminants as required `Literal`s with no default.

### 6. Where codegen runs, and drift detection

- **Do commit the generated `.ts`.** The frontend must typecheck without a Python interpreter
  present, editors need types on checkout, and a committed artifact makes contract changes visible
  in code review — a schema diff that silently changes 40 frontend types is exactly what you want a
  reviewer to see.
- **Codegen runs as an explicit script** (`make types` / `npm run codegen`), invoked manually and in
  CI. Do **not** wire it into the frontend dev-server build: that creates a hard Python dependency
  for every frontend task and makes the build non-hermetic.
- **Pre-commit hook: optional, and prefer verify-only.** A regenerating hook that rewrites files
  mid-commit is a common source of confusion. A `--check` hook that *fails* and tells the developer
  to run `make types` is better behaved.
- **CI drift gate — the load-bearing check.** Standard, tool-agnostic pattern:

  ```yaml
  - run: make types                    # regenerate in place
  - run: git diff --exit-code -- frontend/src/types/generated.ts
  ```

  `git diff --exit-code` returns non-zero if regeneration changed anything, so CI fails when the
  committed types are stale. Run this as its own job, before/parallel to the frontend typecheck, so
  the failure message is unambiguous ("types are stale" vs "frontend has a type error").
  Two details that matter: pin the `json-schema-to-typescript` version exactly (a minor bump can
  reformat output and produce phantom drift), and pin Prettier config/version since json2ts formats
  its output with Prettier. There is also a
  [`phillipdupuis/pydantic-to-typescript@v2.0.0` GitHub Action](https://github.com/marketplace/actions/pydantic-to-typescript)
  advertising an in-sync check, but given the project's dormancy the two-line `git diff` gate is
  preferable and has no extra dependency.

### 7. What is NOT expressible — limitations and tradeoffs

**Lost at the Pydantic → JSON Schema boundary:**
- **The inheritance hierarchy** (flattened; `allOf` requires custom post-processing —
  [pydantic#12071](https://github.com/pydantic/pydantic/issues/12071) still open).
- **Generics as generics** (monomorphised; unparameterised generics degrade to `unknown[]`).
- **All validators.** `@field_validator` / `@model_validator` logic is invisible to JSON Schema and
  therefore to TypeScript. The frontend cannot know a field is validated; the backend remains the
  only enforcement point. This is inherent, not a tool defect.
- **`computed_field`** appears only in serialization schemas; use
  `model_json_schema(mode="serialization")` if the frontend consumes computed values, and note that
  validation-mode and serialization-mode schemas can differ (aliases, computed fields), so you may
  need to emit both.

**Lost at the JSON Schema → TypeScript boundary** (TS simply cannot express these — per
json-schema-to-typescript's own documented list): `pattern` (regex), `minimum`/`maximum`,
`minProperties`/`maxProperties`, `multipleOf`/`divisibleBy`, `uniqueItems`, `format` (so
`EmailStr`, `AnyUrl`, `UUID`, `datetime` all arrive as plain `string`), `not`/`disallow`, and
`dependencies`. Branded types would need hand-written helpers.

**Tradeoffs accepted:**
- A Node toolchain is required in the Python-side codegen step (json2ts is npm-only). Acceptable in
  a full-stack repo that already has Node.
- Output is committed, so it can go stale — mitigated entirely by the CI `git diff` gate.
- Choosing the `allOf` rewrite buys DRY, hierarchical output at the cost of owning ~30 lines of
  schema-munging, and yields **intersections rather than `extends`**. Skipping it yields flat but
  correct and fully type-safe output. Either is defensible; flat-first then add the rewrite if
  duplication becomes painful.
- `oneOf` is treated as `anyOf` by json-schema-to-typescript, so genuinely *exclusive* unions are
  not enforced — irrelevant here since the `kind` literals make the variants mutually exclusive anyway.

### Sources

- [pydantic on PyPI (JSON API)](https://pypi.org/pypi/pydantic/json) — version 2.13.4
- [Pydantic — JSON Schema docs](https://docs.pydantic.dev/latest/concepts/json_schema/)
- [Pydantic — Models docs](https://docs.pydantic.dev/latest/concepts/models/)
- [pydantic#12071 — "Add option to use `allOf` in JSON Schema when a common base is used"](https://github.com/pydantic/pydantic/issues/12071) (open, 2025-07-18)
- [pydantic-to-typescript on GitHub](https://github.com/phillipdupuis/pydantic-to-typescript) (MIT, last commit 2024-11-22)
- [pydantic-to-typescript on PyPI (JSON API)](https://pypi.org/pypi/pydantic-to-typescript/json) — 2.0.0, MIT
- [pydantic2ts CLI source (`cli/script.py`)](https://raw.githubusercontent.com/phillipdupuis/pydantic-to-typescript/master/pydantic2ts/cli/script.py) — master-model aggregation, `extra="forbid"` override, title stripping
- [pydantic-to-typescript GitHub Action](https://github.com/marketplace/actions/pydantic-to-typescript)
- [Snyk Advisor: pydantic-to-typescript](https://snyk.io/advisor/python/pydantic-to-typescript) — "Inactive", assessed 2026-01-07
- [json-schema-to-typescript on GitHub](https://github.com/bcherny/json-schema-to-typescript) (MIT, active) — README documents options, `allOf`→intersection / `oneOf`→union, and the "not expressible in TypeScript" list
- [json-schema-to-typescript on npm registry](https://registry.npmjs.org/json-schema-to-typescript) — 15.0.4, MIT
- [quicktype on GitHub](https://github.com/glideapps/quicktype) (Apache-2.0) — v26.0.0 tested, collapses unions
- [openapi-typescript on npm](https://www.npmjs.com/package/openapi-typescript) — 7.13.0, MIT
- [datamodel-code-generator on GitHub](https://github.com/koxudaxi/datamodel-code-generator) (MIT) — opposite direction
- [TypeScript handbook — Discriminated unions](https://www.typescriptlang.org/docs/handbook/2/narrowing.html#discriminated-unions)
