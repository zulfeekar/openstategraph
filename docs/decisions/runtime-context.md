# A workflow declares what its runs carry

**Status: step 1 of 7 built; the rest is prose.** `organisms-first-class/41`,
adopted from ticket 19's owner decision (2026-08-15). The build is split into
seven tickets, listed at the end, in the order they must land.

**Ticket 67 has landed** (2026-08-22). The *declaration* is real: a document
can say what its runs carry, an ill-formed declaration is refused by
`openstategraph validate` with a non-zero exit, and a declaration naming one of
the four run-identity keys is refused in any casing. Nothing consumes it — no
schema is minted, no value is supplied and nothing reads one — so a workflow
declaring run context today behaves exactly as it did yesterday. The sections
below are marked accordingly: **[BUILT]** for what 67 shipped, and everything
else is still a plan.

The code it shipped with is `backend/tests/test_runtime_context_facts.py`,
which pins the library facts it rests on, plus
`backend/openstategraph/compile/run_context.py`,
`backend/tests/test_run_context_declaration.py`,
`src/core/model/contracts/workflow.ts` and
`src/core/serialization/runContextDeclaration.test.ts`.

## Problem

A run carries three kinds of data and this platform has a home for two of them.
**Graph state** flows between nodes and is drawn on the canvas. **Environment**
is machine-level and identical for every run on the process. Between them sits
a third: values that are *per-run* and *static for the whole run* — which
tenant this is for, which case id, a caller-supplied locale, a support handle,
a feature flag. Today a workflow author has nowhere to put them. They end up as
part of the question, which puts them inside the model's context window where
they can be argued with, or as an environment variable, which makes them the
same for every run.

LangGraph has the channel: `StateGraph(state_schema, context_schema=…)`, a
value supplied as `invoke(..., context=…)` and read as `Runtime[Ctx].context`.
This platform passes it nowhere — still true after 67, which builds a
declaration and no runtime, and still pinned by
`TestNothingHereUsesItYet::test_no_compiler_path_declares_a_context_schema`,
which walks all 148 modules of `openstategraph/` for the string `context_schema=`
and today finds none. `generated_module_contract.py` already records the same
absence, and records that a published capability brief promised `ToolRuntime`
anyway.

## What already exists, measured first

| channel | who supplies it | who reads it | scope |
| --- | --- | --- | --- |
| `configurable.thread_id` / `session_id` / `user_email` / `workflow_slug` | the **server** (`principal.py`), or the library caller, never the client | `memory.py:135`, `memory.py:187`, `prebuilt_session._configurable`, `api/streaming.py:1037`, `api/threads.py` | every run, every door |
| `document.settings.*` — `model`, `recursionLimit`, `checkpointer`, `memory`, `injectionScreening`, `knowledgeCodeRoot`, `purpose` | the **author**, saved in `workflow.json` | the compiler, at build | the package |
| `RunRequest` — `question`, `model`, `recursion_limit`, `thread_id`, `session_id`, `workflow_slug` | the caller | `api/routes/runs.py` | one run |
| `ask(question, *, thread_id, user_email, session_id, recursion_limit)` | the library caller | `loader.py:238` | one run |

So: **nothing today passes a per-run value that is neither state nor
environment**, and `context=` collides with nothing — not an `ask()` parameter,
not a `RunRequest` field (which is `extra: "forbid"`, so adding one is purely
additive), not a `settings` key.

## What the library actually does — docs, then measurement

The docs (`docs-langchain`, `/oss/python/concepts/context`,
`/oss/python/langchain/runtime`, `/oss/python/deepagents/context-engineering`,
`/oss/python/deepagents/subagents`) say: define the shape with `context_schema`
— "a `dataclasses.dataclass` or `typing.TypedDict` class"; pass values as
`context=` to `invoke`; read them in a node as `Runtime[Ctx]`, in middleware as
`request.runtime.context`, in a tool as `ToolRuntime[Ctx]`; and runtime context
"**propagates to all subagents**".

Run against langgraph 1.2.10 / langchain 1.3.14 / deepagents 0.7.5, every one
of those is true. Three of them are true with a caveat the docs do not carry,
and the caveats are what shaped the design:

1. **"The shape of that data" is not validation, and how much of it is enforced
   depends on which kind of class you pick.** A **dataclass** schema is
   *constructed* from whatever mapping the caller passed, so an undeclared key
   and a missing required key are both refused — as
   `TypeError: Ctx.__init__() got an unexpected keyword argument 'zzz'`, naming
   a class the workflow author never wrote and cannot see. A **TypedDict**
   schema is not constructed at all and checks nothing: `{"tenant": …,
   "undeclared": 1}` rides straight through. **Neither checks a value's type** —
   `{"tenant": 123}` against `tenant: str` is accepted and delivered as an
   `int`.
2. **A run that supplies no context at all is not refused.** `runtime.context`
   is `None`, and the failure is an `AttributeError` at whichever node touched
   it first, naming neither the key nor the run.
3. **A dict is accepted where a dataclass was declared** — and coerced into it.
   So callers never need to import a Python type, which is the whole reason the
   three supply routes below can be JSON.

The deepagents claim is true and it is the one worth stating carefully. A
parent agent invoked with `context=Ctx(...)` and a subagent whose only tool
records what it can see: the subagent's tool saw the parent's context,
unchanged.

## Decision

### The declaration is data, in `settings` — **[BUILT, ticket 67]**

A workflow declares its context in `document.settings.context`, an **ordered
list** of field descriptors:

```json
"settings": {
  "context": [
    {
      "key": "tenant",
      "type": "string",
      "label": "Tenant",
      "description": "Which customer this run is for.",
      "required": true
    },
    { "key": "caseId", "type": "string", "label": "Case id", "required": false },
    { "key": "maxRefunds", "type": "number", "label": "Refund ceiling", "default": 3 }
  ]
}
```

- **A list, not an object map.** Order is the substance: this is the order the
  generated prompt section renders in and the order the inspector lists, and
  JSON object key order is not a contract. Port descriptors are a list for the
  same reason.
- **`type` is a named enum** — `"string" | "number" | "boolean"`. Not
  `"object"` or `"array"` in v1: a nested value cannot be rendered into a
  prompt section honestly, cannot be typed on a CLI flag without inventing a
  parser, and every one of those is a portability guardrail asking to be
  broken. A workflow needing structure passes a string and parses it in a tool
  it owns.
- **`default` absent means unset**, and `required` defaults to `false`. There
  is no sentinel and no non-finite number anywhere in this block — the same
  rule `maxConnections` is the worked example of.
- **No expressions.** A default is a JSON scalar. A default that could be
  computed would be host-language code in a serialised field, which is
  portability guardrail 1.
- **Declared once, derived everywhere.** This descriptor list is the field
  schema; the inspector row, the CLI flag list, the `RunRequest` validation and
  the generated prompt section all read it. That is the DRY rule as stated, and
  `13fa2d7` already made `document.setSetting(key, value)` generic in the key
  precisely so a sibling of `recursionLimit` lands without a second place
  settings get written.

### A run supplies values by three routes, all JSON — *not built (70)*

| route | shape |
| --- | --- |
| HTTP | `RunRequest.context: dict[str, str \| int \| float \| bool] \| None` |
| CLI | `openstategraph run --context tenant=acme --context caseId=C-1` (repeatable; typed by the declaration, never guessed from the literal) |
| library | `wf.ask(question, context={"tenant": "acme"})` |

All three land in one validator, and the validator is **ours**, because
measurement 1 above says the library's is unusable and measurement 2 says there
isn't one at the door. It refuses an undeclared key, a missing required key
with no default, and a value of the wrong declared type — each naming the key
and the workflow, not a synthesised Python class. `RunRequest` keeps
`extra: "forbid"` at the top level; `context` is validated against the posted
document's own declaration, which is the only place the truth lives.

### The compiler mints a dataclass — *not built (69)*

`WorkflowCompiler` turns the descriptor list into a `dataclass` at build time
and passes it as `StateGraph(..., context_schema=…)`. A dataclass rather than a
TypedDict for the reason measured: it enforces key names and required keys as a
second line of defence behind our own validator, where a TypedDict enforces
nothing. Nothing reads the minted class back into the model — the compile seam
stays one-directional, and the class is an artefact of the build, exactly like
the compiled graph.

### The read side is three doors, all of which already work — *not built (71–73)*

- **A node** takes `Runtime[Ctx]` as its second parameter.
- **A prompt** receives it as the **Context** section — generated, placed
  before the Rules, never editable, following `bc58fc1`'s `held_tools_context`
  as the precedent for a generated block that declares itself authoritative.
  It is composed by a middleware reading `request.runtime.context`, which is
  the single place context becomes prompt text, exactly as `resolveMiddleware`
  is for middleware. **Only declared keys marked for the prompt are rendered**:
  a context field is a place to put an API handle, and a handle must be able to
  reach a tool without reaching the model.
- **A tool** reads it through an accessor on `BaseTool`, not a third argument.
  `BaseTool.run` validates `**kwargs` into `Args` and calls `_execute(args)`;
  there is no third parameter and adding one changes every tool in the
  platform. The accessor mirrors `prebuilt_session._configurable()`, which
  already solved this exact problem for the identity keys, and it fixes the
  false clause `generated_module_contract.py` records — *"it reads state,
  context and memory through `ToolRuntime`"* — by making a true version of it
  available.

### How this relates to the four identity keys — the rule that keeps them apart — **[refusal BUILT, ticket 67; the `run_identity` accessor is still 68]**

They do not merge, and a declaration may not name one.

> **`configurable` is who the run is *for*. `context` is what the workflow
> *asked its caller for*.**

`thread_id`, `session_id`, `user_email` and `workflow_slug` are
**server-determined and unforgeable** — `RunRequest` deliberately has no
`user_email` field, because that value keys a per-person memory namespace and a
client that could name the person could read that person's memories (memory
ticket 01). `settings.context` is the opposite by construction: the *author*
declares it and the *caller* fills it. Moving identity into a channel any
caller may write would hand back exactly what ticket 01 took away.

So: **a `settings.context` entry whose `key` is `threadId`, `sessionId`,
`userEmail` or `workflowSlug` (in any casing) is a compile-time refusal**, and
the reserved list is read from the same one place `memory.py` and
`prebuilt_session.py` read, never restated. That is also how the
`memory.py:135` / `memory.py:187` drift this ticket was asked to settle gets
settled: **one `run_identity` accessor**, public, with the four keys named in
it, read by `memory.py` (both sites), `prebuilt_session.py` and
`api/streaming.py`. Three hand-rolled `get_config().get("configurable")` reads
are three chances for one of them to learn a normalisation the others do not —
which is the argument `_workflow_scope` already makes in its own docstring
about itself, applied one level up. `ac870f6`'s census of *writers* gains a
sibling census of *readers*.

### The subagent sentence, in full

> **Subagents are isolated from the parent's messages and graph state. They are
> not isolated from runtime context.** Measured in deepagents 0.7.5: a parent
> invoked with `context=` had those exact values reach a tool running inside a
> subagent, unchanged. So a declared context field is visible to every
> subagent of every agent in the workflow, and must be treated as
> workflow-wide. It is the right channel for a tenant id, which every part of
> the run legitimately needs; it is the wrong place for a value one node should
> hold and another should not, because there is no boundary here to hold it
> at.

`CLAUDE.md`'s "state flows down; subagents do not receive it" stays true and
unamended — this is a third channel it did not mention, and this paragraph is
the amendment.

### The lexicon row — the fourth collision

*Context* is now this repository's fourth word meaning several things at once,
after *loop*, *template* and *eval*. Settled the same way:

| User-facing word | Means | Must never mean |
| --- | --- | --- |
| **Run context** | the values a workflow **declares** in `settings.context` and a caller supplies per run — static for the whole run, read by nodes and tools | the **Context** section of a prompt, the context window, or graph state |
| **Context** (prompt part) | the generated, non-editable section of a system prompt — branch list, table schema, held tools, and now the rendered run-context fields | the run context itself; the section is one *consumer* of it |
| *(internal only)* `Runtime.context` | LangGraph's channel | anything in UI copy, and nothing in `workflow.json` |

## The hardest guardrail, and how this satisfies it

Guardrail 4 — **our own runtime vocabulary; do not leak LangGraph type names
into `workflow.json` or into `core/`**. A `context_schema` *is* a Python type,
and this feature's entire purpose is to let a document declare one. That is the
tension, and it is resolved by never storing the type:

- `workflow.json` stores a **list of JSON field descriptors** — key, a named
  type from a three-value enum, a label, a scalar default. No Python, no import
  path, no class name, nothing to resolve at load time. A document declaring
  run context is readable by a runtime that has never heard of LangGraph.
- The dataclass is **minted by the compiler and discarded with it**. It exists
  only inside the build, on the far side of the one-directional seam.
- `core/` sees field descriptors and nothing else. `Runtime`, `ToolRuntime` and
  `context_schema` appear in `compile/` and in the pinning test, and nowhere a
  document or the editor can reach.

Guardrail 1 is the one that constrains the *shape*: because expressions are
data and never code, a default cannot be computed and a type cannot be a
predicate — which is why the enum has three values rather than a validator
grammar. Guardrail 3 is satisfied by construction and guardrail 2 is not
engaged, since nothing here reduces.

## What is pinned, and what is prose

`backend/tests/test_runtime_context_facts.py` — 11 tests, executable, all
against the installed libraries:

- a node, a middleware and a tool each read the value (the three read doors);
- a dataclass schema coerces a plain dict, refuses an undeclared key and a
  missing required key, and says so as a Python `TypeError`;
- no schema checks a value's type;
- a TypedDict schema enforces nothing;
- a run supplying no context fails at the reader, not at the door;
- `context` and `configurable` coexist on one run, neither shadowing the other;
- **a parent's context reaches a tool inside a deepagents subagent**;
- no module in `openstategraph/` declares a `context_schema` — the measurement
  that dates this document, and the test that will announce the first build
  ticket landing.

`backend/tests/test_run_context_declaration.py` (47 tests) and
`src/core/serialization/runContextDeclaration.test.ts` (23) pin what 67 built:
the descriptor shape and its three-value enum; that a bad `type`, a duplicate
key, a non-finite default, a default of the wrong declared type, an unknown
property and a mapping-instead-of-a-list are each refused with the key named;
that every reserved key is refused in **every** casing while `threading`,
`slug` and `user_email_address` are left alone; that the refusal reaches
`plan.warnings` and `openstategraph validate` exits 1 on it; and the inverses —
a document without the key round-trips byte-identically through the store and
through the editor, an empty list is preserved and means what absence means,
and order is the rendering contract.

**Two decisions 67 made that this document had left open.** An **empty list is
preserved rather than dropped**, and means exactly what absence means: both say
*this workflow asks its caller for nothing*, and a serializer that helpfully
rewrites a file nobody edited is a loss this repository has already paid for
twice. And a bad declaration is a **`plan.warnings` problem, not a
`Finding`** — a `Finding` names a capability a compiled graph lost, where this
is a malformed document, the same class of thing as `plan`'s own "dropped an
edge with an unknown endpoint". That puts it on the channel `validate` turns
into PROBLEMS FOUND and a non-zero exit, which is the honest answer to that
command's one question.

The reserved list is read from `prebuilt_session.RUN_IDENTITY_FIELDS` — 67
promoted that tuple from `_FIELDS` to a public name so there is one place the
four keys are spelled. Ticket 68 moves it onto a `run_identity` accessor; until
then this is that place. The TypeScript half is a hand-mirror (`core/` cannot
import Python) and is pinned against the Python one by a drift test in
`test_run_context_declaration.py::TestTheTypeScriptMirrorDoesNotDrift`, the
same instrument `RuntimeClient.ts` is held to.

**Prose, unpinned, because it describes a thing that does not exist yet:** the
three supply routes, the compiler's minted schema, the prompt-section placement
and the tool accessor. Each is a build ticket below and each carries its own
test when it lands.

## The build, in the order it must land

| # | ticket | why here |
| --- | --- | --- |
| ~~67~~ | ~~`settings.context` is a declared field schema~~ | **Landed 2026-08-22.** TS `core/` contract + Pydantic mirror + both serializer round trips + the reserved-key refusal. Builds no runtime, as designed. |
| 68 | One `run_identity` accessor for the four keys | Settles the `memory.py` drift, and 69's reserved-key refusal needs one list to read. Pure refactor, no behaviour. |
| 69 | The compiler mints a `context_schema` | Needs 67's schema and 68's reserved list. Ends with `TestNothingHereUsesItYet` updated rather than deleted. |
| 70 | One validator, three supply routes | `ask(context=)`, `RunRequest.context`, `run --context`. Needs 69, or there is nothing to supply *to*. |
| 71 | Nodes read it | The first read door, and the cheapest to verify end to end. |
| 72 | The generated prompt **Context** section, and per-field opt-in | Needs 71 working, and needs the opt-in or a handle reaches a model. |
| 73 | `BaseTool` context accessor, and the generated-module contract clause | Last because it corrects a *published* false clause, which should be corrected against a working mechanism rather than a planned one. |

The editor's inspector surface is deliberately not in this list: it derives
from 67's field schema and can land beside any of 69–72, but it cannot land
before 67 and it is not on the critical path for a workflow that supplies
context over HTTP.
