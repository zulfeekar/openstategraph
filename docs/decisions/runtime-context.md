# A workflow declares what its runs carry

**Status: steps 1 to 5 of 7 built; the rest is prose.** `organisms-first-class/41`,
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

**Ticket 68 has landed** (2026-08-22) and changed no behaviour at all. The four
run-identity keys are now spelled in one module,
`backend/openstategraph/run_identity.py`, and every reader of them goes through
its `run_identity()` accessor;
`backend/tests/test_one_accessor_reads_run_identity.py` is the census that
fails when a fifth reader hand-rolls `configurable`, the sibling of `ac870f6`'s
census of writers.

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
This platform passed it nowhere until ticket 69, which mints the class and
hands it to `StateGraph`. The census that used to assert *nobody* declares one
now asserts *exactly one place does*
(`TestOnlyTheCompilerDeclaresAContextSchema`), because the fact worth holding
was always **where** rather than how many. Nothing supplies a value yet (70)
and nothing reads one (71), so a workflow declaring run context today still
behaves as it did — it simply now compiles to a graph that would accept one.
`generated_module_contract.py` still records the read side's absence, and
records that a published capability brief promised `ToolRuntime` anyway; 73 is
what corrects it.

## What already exists, measured first

| channel | who supplies it | who reads it | scope |
| --- | --- | --- | --- |
| `configurable.thread_id` / `session_id` / `user_email` / `workflow_slug` | the **server** (`principal.py`), or the library caller, never the client | `run_identity.run_identity()` — the one accessor since ticket 68; `memory.py`, `prebuilt_session.py` and `api/streaming.py` call it, and `api/threads.py` reads a *stored* checkpoint rather than the run | every run, every door |
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

### A run supplies values by three routes, all JSON — **[BUILT, ticket 70]**

| route | shape |
| --- | --- |
| HTTP | `RunRequest.context: dict[str, str \| int \| float \| bool] \| None` |
| CLI | `openstategraph run --context tenant=acme --context caseId=C-1` (repeatable; typed by the declaration, never guessed from the literal) |
| library | `wf.ask(question, context={"tenant": "acme"})` |

All three land in one validator, and the validator is **ours**, because
measurement 1 above says the library's is unusable and measurement 2 says there
isn't one at the door. **Ticket 70 has landed** (2026-08-22):
`validate_run_context` in `compile/run_context.py` is that validator, called by
`CompiledWorkflow.ask`, by `POST /api/runs` and `POST /api/runs/stream`, and by
`openstategraph run` — before the graph is invoked at any of them, so the raw
`TypeError` is unreachable from all three. It refuses an undeclared key, a missing required key
with no default, and a value of the wrong declared type — each naming the key
and the workflow, not a synthesised Python class. `RunRequest` keeps
`extra: "forbid"` at the top level; `context` is validated against the posted
document's own declaration, which is the only place the truth lives.

**Four decisions 70 had to make.**

**A flag carries strings, so the type comes from the document.** `--context
key=value` is typed by the declaration and never guessed from the literal —
guessing would make `caseId=00123` a number for one workflow and a string for
the next, and `dryRun=false` a non-empty and therefore true string for
everybody. A `boolean` field accepts `true` and `false` in any casing and
**nothing else**: `1`, `0`, `yes`, `no`, `on` and `off` are refused by name in
the message. That narrowness is the safety, and it is `CLAUDE.md`'s law about
not promising what is not possible — a flag that quietly makes `false` mean
true breaks it in the direction nobody checks. A `number` field takes what
`float()` takes and then refuses what is not finite, because `inf` and `nan`
are literals `float()` accepts and values JSON cannot carry. A key the document
does **not** declare has no type to be read as, so it is left the string it
arrived as and refused by the validator with the undeclared-key sentence: one
refusal per fact, whichever door the value came in by.

**The two CLI failures are two exit codes, deliberately.** A pair with no `=`
is a mistyped command line and gets `EXIT_USAGE` (2), the code argparse itself
gives for every other flag; a value the *declaration* refuses is a run that
cannot start and gets `EXIT_FAILURE` (1). Exit codes are this CLI's API, and a
script must be able to tell "you typed it wrong" from "the workflow refused
it". Both are exercised as a real `cli.main` return and the second as a real
process.

**A refusal names the slug, or the document's name, or *this workflow*.** The
slug is the identity and is what a package is addressed by — but `POST
/api/runs` posts a canvas that may have none, and a refusal naming an empty
string is worse than one naming nothing. `workflow_label` is the one place that
falls back.

**Defaults are not copied into the mapping.** The minted dataclass carries them
(69) and that is the one place they live; filling them in here would be a
second spelling of the author's intent, and the two would drift. `required`
still yields to a default at the door, exactly as it does at the mint.

### The compiler mints a dataclass — **[BUILT, ticket 69]**

`WorkflowCompiler` turns the descriptor list into a `dataclass` at build time
and passes it as `StateGraph(..., context_schema=…)`. A dataclass rather than a
TypedDict for the reason measured: it enforces key names and required keys as a
second line of defence behind our own validator, where a TypedDict enforces
nothing. Nothing reads the minted class back into the model — the compile seam
stays one-directional, and the class is an artefact of the build, exactly like
the compiled graph.

**Ticket 69 has landed** (2026-08-22) and made three decisions this document
had left open.

**Keyword-only fields, and that is what makes order survivable.** A dataclass
whose fields carry defaults cannot be followed by one that does not —
`make_dataclass` raises *non-default argument follows default argument*. So a
document that declares an optional field before a required one would have
turned the author's chosen order into a build failure, in a list whose order is
the substance (it is the render order of the prompt section 72 builds).
`kw_only=True` removes the ordering rule entirely, and `dataclasses.fields()`
then reports the document's order verbatim. Values arrive as a mapping anyway,
so nothing is given up.

**`required` yields to a default.** A field flagged `required` that also
carries a default is *not* required of the caller — the caller may omit it and
get what the author wrote down. The alternative, a field the caller must always
name even though an answer already exists, makes the default unreachable.

**The class is called `RunContext`, and the name is all we control.** Measured
here: an undeclared key fails as
`TypeError: RunContext.__init__() got an unexpected keyword argument 'zzz'`.
The `.__init__()` half is generated by `dataclasses` and cannot be replaced —
assigning `__qualname__` afterwards does not touch it, because the generated
`__init__` baked its name in at class-creation time. A non-identifier class
name (`"the run context this workflow declared"`) *does* render in that
message, was tried, and was rejected: the class is a real Python type that a
`repr`, a traceback and `Runtime[...]` all print, and a type named with a
sentence lies about what it is everywhere except the one message. So the first
half is the lexicon word instead, and **the message is not the fix** — ticket
70's validator at the door is, which is why that ticket is next.

**And a key that cannot be a field name is a `plan.warnings` problem.** 67
accepts any non-empty string key; `case-id` and `2x` are legal JSON keys and
illegal field names, and `make_dataclass` would have raised out of the
compiler, blaming the compiler for a document defect. The compiler reports it,
withholds the *whole* schema rather than half of it, and builds. Whether 67's
declaration validator should refuse it earlier — in both mirrors, so the editor
says so while you type — is `organisms-first-class/74`.

### The read side is three doors — door one built (71), the other two prose (72–73)

- **A node** reads it through **`run_context()`**, the sibling of
  `run_identity()` — **[BUILT, ticket 71]**, and *not* through a second
  parameter, which is the one thing this section had wrong. See below.
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

**Ticket 71 has landed** (2026-08-22) and corrected the sentence above.

**A second parameter is not available to this compiler.** `Runtime[Ctx]` as a
node's second argument is how the library documents the read, and it is what
`test_runtime_context_facts.py::TestTheThreeReadDoors` pins — but LangGraph's
injection reads the *signature it is handed*, and this runtime hands it wrapped
closures (`recording_attempts` wraps a node factory's callable in
`(*args, **kwargs)`). 69 had already met this and used `get_runtime()` in its
own test harness for exactly that reason. So the read is
**`langgraph.runtime.get_runtime()`**, which was measured to work from an
ordinary `(state)` node, and the consequence is the good one: **no node family
grows a parameter, so reading context never becomes a family capability some
families carry and others do not.** It is graph assembly on the write side and
an ambient accessor on the read side, which is the cross-family boundary rule
satisfied rather than argued around.

**`run_context()` returns values, never the class.** A plain
`dict[str, Any]`, built from `dataclasses.fields()` — so the minted class stays
an artefact of the build, nothing reads a runtime type back into the model, and
a reader holds JSON rather than a LangGraph-shaped object. `{}` is the answer
to all three of *no runnable context*, *the workflow declares nothing* and
*the caller supplied nothing*, because a node can do nothing different about
any of them; that is the reader's half of measurement 2 above, which 70 closed
only at the supply doors.

**An author names the field they want by writing `{{key}}` in their own text.**
The naming lives in the field schema the node already has — `input.text`'s
`prompt`, `input.markdown` / `input.skill`'s `content`/`instruction` — so no
new node configuration was declared, which is the DRY rule as stated. A
placeholder is a **name reference and not an expression** (no operators, no
calls, no paths): guardrail 1 obeyed rather than skirted.

**Only the three text families render, and the choice is the point.** Those
are the families whose entire output *is* author-written text and which have
nowhere else to put a per-run value. The prompted families — `agent.llm`,
`route.classifier`, `route.grader`, `orchestrate.supervisor`,
`orchestrate.worker` — deliberately do **not**: their context arrives as 72's
generated **Context** section with its per-field opt-in, and a second mechanism
writing the same prompt would both duplicate the knowledge and defeat the
opt-in that keeps an API handle away from a model.
`TestThePromptedFamiliesAreNotRenderedHere` is what says so out loud. `function.*`
does not, because its contract is `fn(text: str) -> str` and ticket 35 withheld
run state from referenced code on purpose. Tools are 73.

**Unresolved is left byte-identical, never blanked.** An undeclared key, a
declared key this run has no value for, and a `{{` that was never a
placeholder are all passed through exactly as written. Substituting an empty
string would silently delete an author's text on surfaces — Markdown, skills,
prompts — that legitimately contain braces.

**One value, one spelling, whichever door it came by.** `true`/`false` rather
than Python's `True`/`False`, because that is what `--context dryRun=false`
accepts and what JSON carries; and an integral `number` renders `3` rather than
`3.0`, because the CLI's `float()` must not be visible in an answer that the
same value supplied over HTTP would spell differently.

**Found on the way, and fixed the next session:
`organisms-first-class/76`.** A mount is a closure over the child's
`invoke()`, and LangGraph carried the parent's runtime down it — so a mounted
child saw the **parent's** context object even when it declared its own, and
its own defaults never materialised. Invisible until something read a value.
The section below is what was decided.

### At a mount: inherit, then narrow — **[BUILT, ticket 76]**

> **A run-context key crosses a mount only when both documents declare it.**
> The run supplies; the child's own document decides. Everything the child
> declared and the run did not carry comes from the child's own defaults,
> minted from its own declaration exactly as for a direct run.

That is `582e098`'s rule for the step budget, pointed at a different channel:
the caller's run is the ceiling, the child's own drawing is the aperture. It
holds at every level, so a middle document that declares nothing passes nothing
on — a package cannot hand down a key it never asked its own caller for — which
is what makes a package's behaviour a function of its own document and its
immediate caller's, at any depth.

Two consequences worth stating plainly, because they are the two failures the
whole chain exists to remove:

- **A child cannot read a field it never declared**, at any depth. Its
  `{{tenant}}` stays byte-identical inside a run that has a live `tenant`,
  exactly as an unresolved placeholder does anywhere else (71).
- **A field a child declared is never silently `None`.** What the run cannot
  honour — a required key with no default that the parent's declaration does
  not name, or a value the parent typed differently — is refused before
  `invoke`, by 70's own validator, in our words naming the key and the child.
  It reaches a developer as a failure marker rather than as a raised exception,
  because that is what every node failure does here (`_error_handler_for`), and
  the child's nodes do not run at all.

**The library fact the mechanism rests on**, measured against langgraph 1.2.10:
a graph compiled with **no** `context_schema` is not isolated from its caller's
context — it inherits it, and `context=None`, `context={}` and passing nothing
are all the same to it. So `mint_context_schema` takes `sealed=`, and a mounted
child that declares nothing is given an **empty** schema rather than none.
`context_schema=` still has exactly one call site; a workflow run **directly**
is never sealed, so 69's promise that a document declaring nothing builds
exactly the graph it built before is kept where it was made.

**What was rejected.** *Inherit whole*, today's behaviour made deliberate: a
package would read a caller's field it never asked for, and would answer
differently depending on which parent happened to declare a key of the same
name — `3f688e5` refused exactly that. *Isolate completely*, the child seeing
only what its parent explicitly hands it: the honest end state, and it costs a
**new serialised field on the mount**, which is an owner's decision rather than
a thing to add while fixing a read path. It is `organisms-first-class/78`,
filed with the two questions its design must answer; until it lands, a package
whose declaration asks for a key its parent does not also declare is not
mountable, and says so.

**And the mount sentence beside the subagent one below**: a *subagent* is not
isolated from run context and cannot be, because there is no boundary there to
hold a value at. A *mount* is exactly such a boundary — a second document, with
its own declaration — so it is the one place in this platform where run context
narrows.

### How this relates to the four identity keys — the rule that keeps them apart — **[BUILT, tickets 67 and 68]**

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
about itself, applied one level up. `ac870f6`'s census of *writers* gained its
sibling census of *readers* in
`backend/tests/test_one_accessor_reads_run_identity.py`: every module naming
one of the four keys is classified as accessor, writer, transport or checkpoint
lookup, and no module but the accessor may take one out of a `configurable`
mapping — whether it called `get_config()` or was handed the config, which is
the half a `get_config()`-only check misses.

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
- **exactly one** module of `openstategraph/` declares a `context_schema` —
  `compile/workflow_compiler.py`, the graph-assembly seam — and no file in
  `src/core/` names one at all. This was `TestNothingHereUsesItYet`, asserting
  zero, until 69 landed; it was updated rather than deleted because the fact
  worth pinning was never *zero* but **where**, and a second declaration
  anywhere is either a node family growing a graph-assembly concern or a
  LangGraph type name walking towards `workflow.json`.

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

The reserved list is read from `run_identity.RUN_IDENTITY_KEYS` — 67 promoted
the tuple from `prebuilt_session._FIELDS` to a public name, and 68 moved it to
the accessor's own module, which is now the one place the four keys are
spelled. The TypeScript half is a hand-mirror (`core/` cannot
import Python) and is pinned against the Python one by a drift test in
`test_run_context_declaration.py::TestTheTypeScriptMirrorDoesNotDrift`, the
same instrument `RuntimeClient.ts` is held to.

`backend/tests/test_compiler_mints_context_schema.py` (14 tests) pins what 69
built: a compiled graph carries a dataclass whose fields are the document's, in
the document's order even when an optional field is declared first; a supplied
value reaches a node that actually ran; a declared default is what an omitting
caller gets; a missing required key and an undeclared key are each refused, the
second with its message asserted verbatim; a document declaring nothing, an
empty list, a malformed declaration or an unmintable key mints nothing and — for
the first of those — **passes no `context_schema` argument at all**, asserted on
the `StateGraph` call rather than on its result, because `None` and absent are
not guaranteed to be the same thing to a library we do not own; and the
one-directional seam holds — building writes no type into the document, the plan
holds no Python type, and two builds of one document mint two classes.

`backend/tests/test_a_run_supplies_context.py` (61 tests) pins what 70 built:
the raw `TypeError` still being what `graph.invoke` says, and being unreachable
from all three doors; each of the four refusals driven once per door and
asserted **verbatim**; the flag's typing and everything it refuses; every exit
code as a real return and one as a real process; and the inverses — a workflow
declaring nothing runs at all three doors exactly as before and is passed **no
`context` argument at all**, a correct context reaches `invoke` unchanged,
`configurable` still carries its four keys and only those, and `RunRequest` is
still `extra: "forbid"` with a nested value refused by the model itself.

`backend/tests/test_a_node_reads_the_run_context.py` (21 tests) pins what 71
built: a supplied value reaching a real compiled graph's answer, two callers
getting two answers from one workflow, a declared default reaching a node, and
a skill node rendering through the *other* builder; and the inverses — a
workflow declaring nothing gets its text back byte-identical and its accessor
returns `{}`, the caller's question is never rendered, an undeclared key and a
valueless declared key are left exactly as written, an unmintable key stays
prose, an agent's instruction is untouched, and the two channels stay separate
inside one run.

**Prose, unpinned, because it describes a thing that does not exist yet:** the
prompt-section placement and the tool accessor. Each is a build ticket below and each carries its own
test when it lands.

## The build, in the order it must land

| # | ticket | why here |
| --- | --- | --- |
| ~~67~~ | ~~`settings.context` is a declared field schema~~ | **Landed 2026-08-22.** TS `core/` contract + Pydantic mirror + both serializer round trips + the reserved-key refusal. Builds no runtime, as designed. |
| ~~68~~ | ~~One `run_identity` accessor for the four keys~~ | **Landed 2026-08-22.** `openstategraph/run_identity.py`, four readers repointed, the reserved list moved onto it, and a census of readers beside `ac870f6`'s census of writers. Pure refactor, as designed. |
| ~~69~~ | ~~The compiler mints a `context_schema`~~ | **Landed 2026-08-22.** `mint_context_schema` in `compile/run_context.py`, one `StateGraph(..., context_schema=…)` in the compiler, and the sentinel updated into a census of one. Supplies and reads nothing, as designed. |
| ~~70~~ | ~~One validator, three supply routes~~ | **Landed 2026-08-22.** `validate_run_context` and `coerce_context_flags` in `compile/run_context.py`, `RunContextError` (Tier 1), `ask(context=)`, `RunRequest.context`, `run --context KEY=VALUE`. Reads nothing, as designed. |
| ~~71~~ | ~~Nodes read it~~ | **Landed 2026-08-22.** `run_context()` and `render_run_context()` in `compile/run_context.py`, read by `_input` and `_static_text`. `get_runtime()` rather than a second parameter; the prompted families deliberately untouched. |
| 72 | The generated prompt **Context** section, and per-field opt-in | Needs 71 working, and needs the opt-in or a handle reaches a model. |
| 73 | `BaseTool` context accessor, and the generated-module contract clause | Last because it corrects a *published* false clause, which should be corrected against a working mechanism rather than a planned one. |

The editor's inspector surface is deliberately not in this list: it derives
from 67's field schema and can land beside any of 69–72, but it cannot land
before 67 and it is not on the critical path for a workflow that supplies
context over HTTP.
